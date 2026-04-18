"""modules/niblit_sidecar.py — Niblit Sidecar Socket Server

Provides a lightweight UNIX socket server that runs as a background thread
inside the main Niblit process.  Any tool -- a separate terminal session,
a script, or niblit_ctl.py -- can connect and issue *any* Niblit command
while the main process is:

  * Loading the Qwen/llama-server model (slow on Android)
  * Running the Phase-1 deferred init (60-300 s on first boot)
  * Processing a long ALE / research cycle in the background
  * Blocked waiting for user input (the normal interactive shell)

Protocol (line-delimited JSON)
-------------------------------
Request (client → server)::

    {"id": 1, "cmd": "brain status"}\\n

Response (server → client)::

    {"id": 1, "status": "ok", "result": "Brain: ..."}\\n

Or, for streaming status during init::

    {"id": 0, "status": "init", "message": "Loading KnowledgeDB..."}\\n

Special ``cmd`` values
~~~~~~~~~~~~~~~~~~~~~~
``__ping__``    — instant reply: ``{"status": "pong"}``
``__status__``  — reply: ``{"status":"ok","init_done": bool, "uptime_s": float}``
``__shutdown__``— gracefully close the sidecar (does NOT stop Niblit itself)

Socket path
-----------
Default: ``/tmp/niblit-ctl.sock``
Override: env ``NIBLIT_CTL_SOCKET``

Usage from Python (e.g. in main.py)::

    from modules.niblit_sidecar import NiblitSidecar
    sidecar = NiblitSidecar(core_getter=lambda: core)
    sidecar.start()         # starts background thread; non-blocking

    # Later, when init is done:
    sidecar.mark_ready()    # notifies waiting clients
"""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from typing import Callable, Optional

log = logging.getLogger("Niblit.Sidecar")

# ── Configuration ─────────────────────────────────────────────────────────────

_DEFAULT_SOCKET = os.environ.get("NIBLIT_CTL_SOCKET", "/tmp/niblit-ctl.sock").strip()

# Max concurrent clients (usually one or two sidecar sessions)
_BACKLOG = 4

# Per-request timeout so a stuck client doesn't block the server thread
_CLIENT_TIMEOUT = 120.0


class NiblitSidecar:
    """Background UNIX socket server that proxies commands to a live NiblitCore.

    Parameters
    ----------
    core_getter:
        A callable that returns the current ``NiblitCore`` instance (or
        ``None`` if init is still in progress).  Evaluated on every request
        so callers don't need to pass the core before it exists.
    socket_path:
        Path for the UNIX domain socket.  Defaults to the value of
        ``NIBLIT_CTL_SOCKET`` env var or ``/tmp/niblit-ctl.sock``.
    """

    def __init__(
        self,
        core_getter: Callable[[], Optional[object]],
        socket_path: str = _DEFAULT_SOCKET,
    ) -> None:
        self._core_getter = core_getter
        self.socket_path = socket_path
        self._boot_time = time.monotonic()
        self._ready = threading.Event()  # set by mark_ready()
        self._stop_event = threading.Event()
        self._server: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None

        # Pending-command queue: while core is not yet ready, commands are
        # buffered and their results sent back once the core is available.
        # Key: request id  Value: (cmd, result_event, result_holder)
        self._pending: dict[int, tuple[str, threading.Event, list[str]]] = {}
        self._pending_lock = threading.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the sidecar server thread.  Non-blocking."""
        self._thread = threading.Thread(
            target=self._serve,
            name="niblit-sidecar",
            daemon=True,
        )
        self._thread.start()
        log.info("Niblit sidecar listening on %s", self.socket_path)

    def mark_ready(self) -> None:
        """Signal that NiblitCore has finished Phase-1 init."""
        self._ready.set()
        log.info("Niblit sidecar: core is ready — queued commands can now execute.")

    def stop(self) -> None:
        """Signal the sidecar to stop accepting connections."""
        self._stop_event.set()
        if self._server:
            try:
                self._server.close()
            except OSError:
                pass
        try:
            os.unlink(self.socket_path)
        except OSError:
            pass

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Server loop ───────────────────────────────────────────────────────────

    def _serve(self) -> None:
        """Main server loop — runs in the sidecar background thread."""
        # Clean up any stale socket from a previous run
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass

        try:
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(self.socket_path)
            os.chmod(self.socket_path, 0o600)
            srv.listen(_BACKLOG)
            srv.settimeout(1.0)  # allows checking _stop_event
            self._server = srv
        except OSError as exc:
            log.error("Niblit sidecar: cannot bind socket %s: %s", self.socket_path, exc)
            return

        while not self._stop_event.is_set():
            try:
                conn, _addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            t = threading.Thread(
                target=self._handle,
                args=(conn,),
                name="niblit-sidecar-conn",
                daemon=True,
            )
            t.start()

        try:
            srv.close()
        except OSError:
            pass

    # ── Connection handler ────────────────────────────────────────────────────

    def _handle(self, conn: socket.socket) -> None:
        """Handle one client connection: read JSON request, send JSON response."""
        conn.settimeout(_CLIENT_TIMEOUT)
        try:
            # Read one newline-terminated JSON request
            data = b""
            while b"\n" not in data:
                chunk = conn.recv(8192)
                if not chunk:
                    return
                data += chunk
                if len(data) > 65536:
                    self._send(conn, {"status": "error", "result": "request too large"})
                    return

            line = data.decode("utf-8", errors="replace").strip()
            try:
                req = json.loads(line)
            except json.JSONDecodeError as exc:
                self._send(conn, {"status": "error", "result": f"bad JSON: {exc}"})
                return

            resp = self._dispatch(req, conn)
            if resp is not None:
                self._send(conn, resp)

        except (OSError, socket.timeout):
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _send(self, conn: socket.socket, payload: dict) -> None:
        try:
            conn.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        except OSError:
            pass

    # ── Command dispatcher ────────────────────────────────────────────────────

    def _dispatch(self, req: dict, conn: socket.socket) -> Optional[dict]:
        cmd = str(req.get("cmd") or req.get("input") or "").strip()
        req_id = req.get("id", 0)

        # ── Built-in sidecar control commands ────────────────────────────────
        if cmd == "__ping__":
            return {"id": req_id, "status": "pong"}

        if cmd == "__status__":
            return {
                "id": req_id,
                "status": "ok",
                "init_done": self._ready.is_set(),
                "uptime_s": round(time.monotonic() - self._boot_time, 1),
                "socket": self.socket_path,
            }

        if cmd == "__shutdown__":
            self._stop_event.set()
            return {"id": req_id, "status": "ok", "result": "Sidecar shutting down."}

        if not cmd:
            return {"id": req_id, "status": "error", "result": "Empty command."}

        # ── Wait for core to be available ─────────────────────────────────────
        if not self._ready.is_set():
            # Tell the client we're still initialising, then wait.
            self._send(conn, {
                "id": req_id,
                "status": "init",
                "message": "Niblit is still initialising — your command will run as soon as ready...",
            })
            # Wait up to 10 minutes for core to become ready
            self._ready.wait(timeout=600)
            if not self._ready.is_set():
                return {
                    "id": req_id,
                    "status": "timeout",
                    "result": "Niblit init timed out — try again.",
                }

        # ── Route the command through NiblitCore / NiblitRouter ───────────────
        core = self._core_getter()
        if core is None:
            return {"id": req_id, "status": "error", "result": "NiblitCore not yet available."}

        try:
            if hasattr(core, "router") and core.router is not None:
                result = core.router.process(cmd)
            else:
                result = core.handle(cmd)
        except Exception as exc:  # noqa: BLE001
            log.warning("Sidecar command error for %r: %s", cmd, exc)
            result = f"[ERROR] {exc}"

        return {"id": req_id, "status": "ok", "result": str(result) if result is not None else ""}

    # ── Status string ─────────────────────────────────────────────────────────

    def status_line(self) -> str:
        state = "READY" if self._ready.is_set() else "INIT"
        running = "UP" if self.is_running() else "DOWN"
        return f"Niblit sidecar [{running}|{state}] socket={self.socket_path}"


# ── Module-level singleton ────────────────────────────────────────────────────

_sidecar: Optional[NiblitSidecar] = None
_sidecar_lock = threading.Lock()


def get_sidecar() -> Optional[NiblitSidecar]:
    """Return the module-level NiblitSidecar singleton (or None if not started)."""
    return _sidecar


def start_sidecar(
    core_getter: Callable[[], Optional[object]],
    socket_path: str = _DEFAULT_SOCKET,
) -> NiblitSidecar:
    """Create and start the module-level sidecar singleton.

    Safe to call multiple times — returns the existing instance on subsequent
    calls.
    """
    global _sidecar
    with _sidecar_lock:
        if _sidecar is not None and _sidecar.is_running():
            return _sidecar
        _sidecar = NiblitSidecar(core_getter=core_getter, socket_path=socket_path)
        _sidecar.start()
        return _sidecar


def stop_sidecar() -> None:
    """Stop the module-level sidecar singleton."""
    global _sidecar
    with _sidecar_lock:
        if _sidecar is not None:
            _sidecar.stop()
            _sidecar = None
