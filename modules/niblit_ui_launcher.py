#!/usr/bin/env python3
"""Desktop UI Launcher for Niblit.

Responsibilities
---------------
1.  Inspect the Niblit trading-runtime manager and report its backend,
    state, mode and execution-enabled flag as real (non-"unknown") values.
2.  Ensure the Niblit Core API (``server.py``) is serving ``GET /health`` on
    the configured port (default **5000**).  If it is not already running the
    launcher starts it in a background daemon thread, then waits for readiness
    with retries (``NIBLIT_API_START_TIMEOUT``, default 45 s).
3.  Best-effort probe the Niblit Cloud inference server (port 8000).
4.  Launch the desktop UI (Tauri dev mode) as a tracked subprocess and return
    a :class:`UiLaunchResult` with a valid lifecycle handle.

The ``UiLaunchResult`` is a stable contract consumed by ``main.py``.  The
caller accesses ``result.success``, ``result.message``, ``result.wait()``,
and ``result.terminate()`` — which is why **every** code path in
:func:`launch_primary_ui` returns an :class:`UiLaunchResult` instance.
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

log = logging.getLogger("NiblitUiLauncher")

# ── Port / URL defaults ───────────────────────────────────────────────────────

#: Niblit Core API port (NOT the cloud inference server on 8000).
_NIBLIT_API_DEFAULT_PORT = 5000
_NIBLIT_CLOUD_DEFAULT_PORT = 8000

#: Health-check path on the Niblit Core API.
_API_HEALTH_PATH = "/health"

#: Health-check path on the Niblit Cloud inference server.
_CLOUD_HEALTH_PATH = "/healthz"

#: How long to wait for the API to become ready (seconds).
_API_READY_TIMEOUT = float(os.getenv("NIBLIT_API_START_TIMEOUT", "45"))

#: How long to wait for the UI process to stabilise after launch (seconds).
_UI_STABILIZATION_SECONDS = float(os.getenv("NIBLIT_UI_STABILIZATION_SECONDS", "5"))

#: Repo root resolved from this file's location.
_REPO_ROOT = Path(__file__).resolve().parent.parent


# ─────────────────────────────────────────────────────────────────────────────
# UiLaunchResult
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class UiLaunchResult:
    """Stable result object returned by :func:`launch_primary_ui`.

    Attributes
    ----------
    success:
        ``True`` when the desktop runtime launched successfully.
    mode:
        ``"active"`` | ``"degraded"`` | ``"disabled"``.
    api_url:
        The Niblit Core API base URL that was verified or started.
    cloud_url:
        The Niblit Cloud inference base URL that was probed.
    ui_url:
        URL or label describing how the desktop UI was launched.
    message:
        Human-readable status / failure reason.
    readiness:
        Mapping of service-name → readiness state (``"ready"`` | ``"unavailable"``).
    """

    success: bool
    mode: str = "disabled"
    api_url: str = ""
    cloud_url: str = ""
    ui_url: str = ""
    message: str = ""
    readiness: Dict[str, str] = field(default_factory=dict)
    # Private lifecycle handles (excluded from repr)
    _ui_process: Optional[subprocess.Popen] = field(default=None, repr=False)
    _cloud_process: Optional[subprocess.Popen] = field(default=None, repr=False)
    _api_thread: Optional[threading.Thread] = field(default=None, repr=False)
    _owned_server: Any = field(default=None, repr=False)
    _launch_mode: str = field(default="unknown", repr=False)  # "attached" | "detached"
    _shutdown_event: Any = field(default=None, repr=False)
    _stop_event: threading.Event = field(default_factory=threading.Event, repr=False)

    # ── lifecycle helpers ─────────────────────────────────────────────────

    def wait(self) -> int:
        """Block until the UI process exits.

        For attached mode this blocks on the underlying ``Popen`` handle.
        For detached mode this waits on the core shutdown event so the
        caller stays alive while background services run.
        """
        if not self.success:
            return 1

        if self._launch_mode == "detached":
            try:
                while not self._stop_event.is_set():
                    if self._shutdown_event is not None and self._shutdown_event.is_set():
                        break
                    self._stop_event.wait(timeout=0.25)
                return 0
            except KeyboardInterrupt:
                self.terminate()
                return 130

        if self._ui_process is None:
            raise RuntimeError(
                "UI launch succeeded without an attached UI process. "
                "The launcher must attach a real long-lived process on success."
            )

        try:
            return self._ui_process.wait()
        except KeyboardInterrupt:
            self.terminate()
            return 130

    def terminate(self) -> None:
        """Cleanly terminate any processes / threads owned by this launch."""
        self._stop_event.set()
        for proc in (self._ui_process, self._cloud_process):
            if proc is None:
                continue
            try:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            except Exception:
                pass
        # Signal our owned uvicorn server to exit (graceful)
        server = self._owned_server
        if server is not None:
            try:
                server.should_exit = True  # type: ignore[attr-defined]
            except Exception:
                pass
        if self._api_thread is not None and self._api_thread.is_alive():
            try:
                self._api_thread.join(timeout=10)
            except Exception:
                pass
        self._ui_process = None
        self._cloud_process = None
        self._api_thread = None
        self._owned_server = None

    # ── ergonomic helpers ─────────────────────────────────────────────────

    def is_trading_enabled(self) -> bool:
        return self.mode in ("active", "live")


# ─────────────────────────────────────────────────────────────────────────────
# Compatibility helper
# ─────────────────────────────────────────────────────────────────────────────

def _coerce_ui_launch_result(value: Any) -> UiLaunchResult:
    """Coerce a legacy ``dict`` (or stray object) into a :class:`UiLaunchResult`.

    The previous launcher returned a bare ``dict`` with keys ``status``,
    ``errors`` and ``runtime_state``.  Older callers may still pass that dict
    back through this helper so they receive a proper object with
    ``.success``, ``.wait()`` and ``.terminate()``.

    Raises
    ------
    TypeError
        If *value* cannot be coerced (e.g. ``None`` or an unrelated type).
    """
    if isinstance(value, UiLaunchResult):
        return value
    if isinstance(value, dict):
        status = str(value.get("status", "")).lower()
        errors = value.get("errors", [])
        message = value.get("message", "") or (
            "; ".join(errors) if errors else "legacy launcher completed"
        )
        return UiLaunchResult(
            success=status == "ok",
            mode="active" if status == "ok" else "degraded",
            message=message,
            readiness=dict(value.get("readiness", {})),
        )
    if value is None:
        raise TypeError("cannot coerce None to UiLaunchResult")
    raise TypeError(f"cannot coerce {type(value).__name__} to UiLaunchResult")


# ─────────────────────────────────────────────────────────────────────────────
# Runtime state (shared between caller and tests)
# ─────────────────────────────────────────────────────────────────────────────

class RuntimeState:
    """Mutable runtime-state object shared between launcher sub-steps."""

    def __init__(self) -> None:
        self.lean_ready: bool = False
        self.api_ready: bool = False
        self.cloud_ready: bool = False
        self.ui_ready: bool = False


def get_runtime_state() -> RuntimeState:
    """Return the singleton :class:`RuntimeState` used across launcher helpers."""
    global _RUNTIME_STATE
    if _RUNTIME_STATE is None:
        _RUNTIME_STATE = RuntimeState()
    return _RUNTIME_STATE


_RUNTIME_STATE: Optional[RuntimeState] = None


def reset_runtime_state() -> None:
    """Reset the singleton RuntimeState (primarily for tests)."""
    global _RUNTIME_STATE
    _RUNTIME_STATE = None


def _status_emitter(
    io: Any, on_status: Optional[Callable[[str], None]]
) -> Callable[[str], None]:
    """Return a function that emits a status line to *io* and/or *on_status*.

    When *on_status* is provided it is the primary output path; *io* is only
    used as a fallback when *on_status* is absent.  This prevents duplicate
    status lines when both are wired (e.g. ``launch_primary_ui`` is called
    with ``on_status=lambda msg: io.out(...)``).
    """
    def _emit(msg: str) -> None:
        if on_status is not None:
            try:
                on_status(msg)
                return
            except Exception:
                pass
        if io is not None:
            out = getattr(io, "out", None)
            if callable(out):
                try:
                    out(msg)
                    return
                except Exception:
                    pass
            if hasattr(io, "append"):
                try:
                    io.append(msg)
                    return
                except Exception:
                    pass
        log.info(msg)
    return _emit


def ui_launch_supported() -> bool:
    """Return True when a desktop UI can be launched in this environment."""
    if os.getenv("NIBLIT_HEADLESS", "").strip().lower() in {"1", "true", "yes"}:
        return False
    if os.getenv("CI", "").strip().lower() in {"1", "true", "yes"}:
        return False
    if platform.system().lower() in {"windows", "darwin"}:
        return True
    return bool(os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"))


# ─────────────────────────────────────────────────────────────────────────────
# Trading-runtime inspection
# ─────────────────────────────────────────────────────────────────────────────

def _inspect_trading_runtime(manager: Any) -> Dict[str, Any]:
    """Safely extract trading-runtime status from *manager*.

    Returns a dict with keys ``found``, ``backend``, ``state``, ``mode``
    and ``execution_enabled``.  Every attribute access is guarded so a
    manager that lacks the expected properties still yields sensible
    defaults rather than raising.

    Unlike earlier versions, this no longer silently coerces missing
    backends to ``"paper"`` or missing modes to ``"observe"`` — those
    defaults made it impossible to distinguish "not configured" from
    "paper backend active".  Callers must now check ``found`` and
    ``state`` explicitly.
    """
    if manager is None:
        return {
            "found": False,
            "backend": "none",
            "state": "stopped",
            "mode": "disabled",
            "execution_enabled": False,
        }

    # Use explicit sentinels so we can detect "attribute missing" vs "set to paper".
    # Only fall back to "paper"/"observe" when the manager explicitly reports them,
    # not when the attributes are absent entirely.
    backend = (
        getattr(manager, "backend", None)
        or getattr(manager, "selected_backend_name", None)
    )
    state = (
        getattr(manager, "state", None)
        or getattr(manager, "state_name", None)
    )
    mode = getattr(manager, "trading_mode", None)
    execution_enabled = bool(getattr(manager, "execution_enabled", False))

    # Only apply paper/observe defaults when manager exists but attributes are None —
    # this preserves the ability to detect "unconfigured" vs "explicitly paper".
    if backend is None:
        backend = "paper" if state is not None else "unknown"
    if mode is None:
        mode = "observe" if state is not None else "unknown"

    return {
        "found": True,
        "backend": str(backend),
        "state": str(state) if state is not None else "unknown",
        "mode": str(mode),
        "execution_enabled": execution_enabled,
    }


# ─────────────────────────────────────────────────────────────────────────────
# HTTP readiness helpers
# ─────────────────────────────────────────────────────────────────────────────

def _wait_for_http_ready(
    url: str,
    *,
    timeout_seconds: float,
    interval_seconds: float = 0.25,
) -> bool:
    """Poll *url* until it returns HTTP 200 or *timeout_seconds* elapses."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=min(5, max(1, remaining))) as resp:
                if 200 <= resp.status < 300:
                    return True
        except Exception:
            pass
        time.sleep(min(interval_seconds, max(0.05, remaining)))


def _niblit_api_port() -> int:
    """Resolve the Niblit Core API port (default **5000**)."""
    raw = os.environ.get("NIBLIT_API_PORT", str(_NIBLIT_API_DEFAULT_PORT))
    try:
        port = int(raw)
        if 0 < port < 65536:
            return port
    except (TypeError, ValueError):
        pass
    return _NIBLIT_API_DEFAULT_PORT


def _cloud_url() -> str:
    """Resolve the Niblit Cloud inference base URL."""
    env_url = os.environ.get("NIBLIT_CLOUD_SERVER_URL", "").strip()
    if not env_url:
        port = os.environ.get(
            "NIBLIT_CLOUD_SERVER_PRIMARY_PORT", str(_NIBLIT_CLOUD_DEFAULT_PORT)
        )
        env_url = f"http://127.0.0.1:{port}"
    return env_url.rstrip("/")


def _start_api_server_thread(
    core: Any, port: int, emit: Callable[[str], None]
) -> Any:
    """Start the Niblit Core API (``server.py``) in a daemon thread.

    Binds the existing *core* via ``server.bind_core`` so that the API
    and the CLI share the same NiblitCore instance (no duplicate
    initialisation).

    Returns ``(server_obj, thread)`` or ``None`` on failure.
    """
    try:
        import server as server_module  # type: ignore[import-not-found]
    except Exception as exc:
        emit(f"Niblit API module (server.py) import failed: {exc}")
        return None

    try:
        server_module.bind_core(core)
    except Exception as exc:
        emit(f"bind_core failed: {exc}")
        return None

    try:
        import uvicorn  # type: ignore[import-not-found]
    except ImportError:
        emit("uvicorn not installed — cannot start Niblit API server")
        return None

    config = uvicorn.Config(
        server_module.app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
    )
    server_obj = uvicorn.Server(config)
    thread = threading.Thread(
        target=server_obj.run, name="NiblitApiServer", daemon=True
    )
    thread.start()
    emit(f"Niblit API server starting on port {port}")
    return server_obj, thread


# ─────────────────────────────────────────────────────────────────────────────
# UI process launch
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_npm_executable(ui_path: str, emit: Callable[[str], None]) -> Optional[str]:
    """Resolve the npm executable path for Windows.

    Discovery order:
    1. ``NIBLIT_NPM_PATH`` environment variable
    2. ``shutil.which("npm.cmd")``
    3. ``shutil.which("npm")``

    Returns the resolved executable path, or ``None`` if npm cannot be found.
    """
    env_override = os.environ.get("NIBLIT_NPM_PATH", "").strip()
    candidates = []
    if env_override:
        candidates.append(env_override)
    candidates.extend(["npm.cmd", "npm"])

    for candidate in candidates:
        try:
            resolved = shutil.which(candidate)
        except Exception as exc:
            emit(f"[UI] shutil.which({candidate!r}) lookup failed: {exc}")
            continue
        if resolved:
            emit(f"[UI] Resolved npm executable: {resolved}")
            return resolved

    emit("[UI] npm not found in PATH — cannot launch Tauri dev UI")
    return None


def _validate_ui_repository(ui_path: str) -> Dict[str, Any]:
    """Validate the UI repository structure and return metadata.

    Returns a dict with keys:
    - ``valid`` (bool)
    - ``package_json`` (Path or None)
    - ``script_name`` (str or None)
    - ``error`` (str or None)
    """
    result: Dict[str, Any] = {
        "valid": False,
        "package_json": None,
        "script_name": None,
        "error": None,
    }

    if not ui_path or not os.path.isdir(ui_path):
        result["error"] = f"UI path missing or not a directory: {ui_path}"
        return result

    package_json = Path(ui_path) / "package.json"
    if not package_json.exists():
        result["error"] = f"package.json not found in {ui_path}"
        return result

    result["package_json"] = package_json

    try:
        import json as _json
        with package_json.open("r", encoding="utf-8") as fh:
            pkg = _json.load(fh)
    except Exception as exc:
        result["error"] = f"Failed to parse package.json: {exc}"
        return result

    scripts = pkg.get("scripts") or {}
    script_name = None
    for candidate in ("tauri:dev", "tauri dev", "tauri", "dev", "start"):
        if candidate in scripts:
            script_name = candidate
            break

    if script_name is None:
        result["error"] = (
            "No Tauri dev script found in package.json. "
            f"Available scripts: {', '.join(sorted(scripts.keys()))}"
        )
        return result

    result["valid"] = True
    result["script_name"] = script_name
    return result


def _build_child_env(ui_path: str) -> Dict[str, str]:
    """Build a child process environment that preserves PATH and adds Node/Cargo bins."""
    env = os.environ.copy()
    env.setdefault("NODE_ENV", "development")

    # Ensure Node.js and Cargo bin directories are on PATH for the child.
    path_entries = [entry for entry in env.get("PATH", "").split(os.pathsep) if entry]

    node_dir = os.environ.get("NIBLIT_NODE_DIR", "").strip()
    if node_dir:
        path_entries.insert(0, node_dir)

    cargo_dir = os.environ.get("NIBLIT_CARGO_DIR", "").strip()
    if cargo_dir:
        path_entries.insert(0, cargo_dir)

    # Common defaults when not explicitly configured
    if not node_dir:
        for candidate in (
            r"C:\Program Files\nodejs",
            r"C:\Program Files (x86)\odejs",
        ):
            if candidate not in path_entries and os.path.isdir(candidate):
                path_entries.insert(0, candidate)

    if not cargo_dir:
        cargo_default = os.path.join(os.environ.get("USERPROFILE", ""), ".cargo", "bin")
        if os.path.isdir(cargo_default) and cargo_default not in path_entries:
            path_entries.insert(0, cargo_default)

    env["PATH"] = os.pathsep.join(path_entries)
    return env


def _launch_tauri_dev_process(
    ui_path: str,
    emit: Callable[[str], None],
) -> Optional[subprocess.Popen]:
    """Launch the Tauri dev UI as a long-lived subprocess.

    Returns the ``Popen`` handle for the npm process, or ``None`` on failure.
    """
    npm_executable = _resolve_npm_executable(ui_path, emit)
    if npm_executable is None:
        return None

    validation = _validate_ui_repository(ui_path)
    if not validation["valid"]:
        emit(f"[UI] Repository validation failed: {validation['error']}")
        return None

    script_name = validation["script_name"]
    cmd = [npm_executable, "run", script_name]
    cwd = ui_path
    env = _build_child_env(ui_path)

    kwargs: Dict[str, Any] = {
        "cwd": cwd,
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "bufsize": 1,
    }

    if platform.system().lower() == "windows":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    try:
        proc = subprocess.Popen(cmd, **kwargs)
        emit(f"[UI] Launch command: {' '.join(cmd)} (cwd={cwd})")
        emit(f"[UI] Process PID: {proc.pid}")
        return proc
    except Exception as exc:
        emit(f"[UI] Failed to launch UI process: {exc}")
        return None


def _wait_for_process_stabilisation(
    proc: subprocess.Popen,
    emit: Callable[[str], None],
    window_seconds: float = _UI_STABILIZATION_SECONDS,
) -> bool:
    """Wait *window_seconds* and verify the process is still alive.

    Also drains any immediate stderr lines to detect fatal startup errors.

    Returns True when the process survived the window, False otherwise.
    """
    if proc.poll() is not None:
        emit(f"UI process exited immediately with code {proc.returncode}")
        return False

    # Drain stderr in the background to detect fatal errors
    stderr_lines: list = []

    def _read_stderr() -> None:
        try:
            for line in proc.stderr or ():
                line = line.rstrip()
                if line:
                    stderr_lines.append(line)
        except Exception:
            pass

    stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
    stderr_thread.start()

    deadline = time.monotonic() + window_seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            emit(f"UI process exited during stabilisation with code {proc.returncode}")
            if stderr_lines:
                emit("UI stderr (tail): " + "; ".join(stderr_lines[-5:]))
            return False
        time.sleep(0.25)

    if stderr_lines:
        emit(f"UI stderr (last 3 lines): {'; '.join(stderr_lines[-3:])}")
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def launch_primary_ui(
    core: Any | None = None,
    io: Any | None = None,
    *,
    on_status: Optional[Callable[[str], None]] = None,
) -> UiLaunchResult:
    """Launch the Niblit desktop runtime.

    The correct startup order is:

    1.  Inspect the trading-runtime manager (backend / state / mode).
    2.  Ensure the Niblit Core API is ready at ``/health`` (start if owned).
    3.  Best-effort probe the Niblit Cloud inference server.
    4.  Launch the desktop UI (Tauri dev mode) and verify it stays alive.

    Returns a :class:`UiLaunchResult` on **every** code path.
    """
    # Reset shared runtime state for this launch attempt
    reset_runtime_state()
    state = get_runtime_state()
    emit = _status_emitter(io, on_status)
    readiness: Dict[str, str] = {}

    emit("Desktop runtime preflight")

    # ── 1. Trading-runtime inspection ─────────────────────────────────────
    manager: Any = None
    if core is not None:
        manager = (
            getattr(core, "trading_runtime_manager", None)
            or getattr(core, "lean_algo_manager", None)
        )
    trading = _inspect_trading_runtime(manager)

    if trading["found"]:
        state.lean_ready = True
        emit(
            f"Trading runtime found: backend={trading['backend']} "
            f"state={trading['state']}"
        )
        readiness["trading"] = trading["state"]
    else:
        emit("Trading runtime missing — trading features will be limited")
        readiness["trading"] = "missing"

    trading_required = os.environ.get(
        "NIBLIT_TRADING_REQUIRED", "1" if getattr(sys, "frozen", False) else ""
    ).strip().lower() in {"1", "true", "yes"}
    trading_ok = trading["found"] and trading["state"] in ("ready", "running")

    # ── 2. Niblit Core API (port 5000 /health) ──────────────────────────
    api_port = _niblit_api_port()
    api_url = f"http://127.0.0.1:{api_port}"
    health_url = f"{api_url}{_API_HEALTH_PATH}"

    # Quick check — is the API already serving?
    api_ready = _wait_for_http_ready(health_url, timeout_seconds=2.0, interval_seconds=0.1)

    api_thread: Optional[threading.Thread] = None
    owned: Any = None

    if not api_ready and core is not None:
        started = _start_api_server_thread(core, api_port, emit)
        if started is not None:
            _server_obj, api_thread = started
            owned = _server_obj
            # Wait for it to become ready
            api_ready = _wait_for_http_ready(
                health_url,
                timeout_seconds=_API_READY_TIMEOUT,
                interval_seconds=0.25,
            )

    if api_ready:
        state.api_ready = True
        emit(f"Niblit API ready at {api_url}")
        readiness["api"] = "ready"
    else:
        state.api_ready = False
        emit(f"Niblit API unavailable at {health_url}")
        readiness["api"] = "unavailable"

    # ── 3. Niblit Cloud inference (port 8000 /healthz + /v1/models) ──────
    c_url = _cloud_url()
    cloud_health_url = f"{c_url}{_CLOUD_HEALTH_PATH}"
    cloud_ready = _wait_for_http_ready(cloud_health_url, timeout_seconds=3.0)
    cloud_process: Optional[subprocess.Popen] = None
    if not cloud_ready:
        cloud_process = _maybe_start_cloud_server(c_url, emit)
        if cloud_process is not None:
            cloud_result = _wait_for_cloud_ready(c_url, timeout_seconds=120.0)
            cloud_ready = cloud_result["ready"]
            if not cloud_ready:
                emit(
                    f"[Cloud] Cloud unavailable at {c_url}: {cloud_result['error']}"
                )
            else:
                emit(f"[Cloud] Niblit Cloud ready at {c_url}")
        else:
            emit(f"[Cloud] Niblit Cloud unavailable at {c_url}")
    else:
        emit(f"[Cloud] Niblit Cloud ready at {c_url}")

    if cloud_ready:
        state.cloud_ready = True
        readiness["cloud"] = "ready"
    else:
        state.cloud_ready = False
        readiness["cloud"] = "unavailable"

    # ── 4. Determine whether we may proceed ─────────────────────────────
    # The Niblit Core API is required by the desktop UI for chat, memory
    # and file endpoints.  Without it the UI cannot function, so we must
    # NOT claim success.
    if not api_ready:
        return UiLaunchResult(
            success=False,
            mode="degraded",
            api_url=api_url,
            cloud_url=c_url,
            message=(
                f"Niblit API did not become ready at {health_url} "
                f"within {_API_READY_TIMEOUT}s"
            ),
            readiness=readiness,
            _api_thread=api_thread,
            _owned_server=owned,
        )

    if getattr(sys, "frozen", False) and not cloud_ready:
        return UiLaunchResult(
            success=False, mode="degraded", api_url=api_url, cloud_url=c_url,
            message="Packaged Cloud service is not ready; desktop startup blocked",
            readiness=readiness, _api_thread=api_thread, _owned_server=owned,
            _cloud_process=cloud_process,
        )

    # Packaged builds require Lean unless the user explicitly opts out.
    if trading_required and not trading_ok:
        return UiLaunchResult(
            success=False,
            mode="degraded",
            api_url=api_url,
            cloud_url=c_url,
            message=(
                "Trading runtime required (NIBLIT_TRADING_REQUIRED=true) but "
                f"manager reported state={trading['state']}"
            ),
            readiness=readiness,
            _api_thread=api_thread,
            _owned_server=owned,
        )

    # ── 5. Launch desktop UI ─────────────────────────────────────────────
    emit("Desktop UI launching")

    ui_path = os.environ.get("NIBLIT_UI_PATH", "").strip()
    if not ui_path:
        for candidate in (
            str(_REPO_ROOT / "niblit-ui"),
            str(_REPO_ROOT.parent / "niblit-ui"),
            "../niblit-ui",
            "./niblit-ui",
        ):
            if candidate and os.path.isdir(candidate):
                ui_path = candidate
                break

    ui_process: Optional[subprocess.Popen] = None
    launch_mode = "detached"
    ui_url = ""
    ui_failure_reason = ""

    if getattr(sys, "frozen", False):
        bundled_ui = Path(sys.executable).resolve().parent / "niblit-ui.exe"
        ui_url = str(bundled_ui)
        if bundled_ui.is_file():
            try:
                ui_process = subprocess.Popen(
                    [str(bundled_ui)], cwd=str(bundled_ui.parent),
                    env=_build_child_env(str(bundled_ui.parent)),
                )
                if not _wait_for_process_stabilisation(ui_process, emit):
                    ui_process.kill()
                    ui_process = None
                    ui_failure_reason = "Bundled UI process failed stabilisation check"
                else:
                    launch_mode = "attached"
                    state.ui_ready = True
                    readiness["ui"] = "ready"
                    emit(f"Desktop UI ready (PID={ui_process.pid})")
            except OSError as exc:
                ui_failure_reason = f"Bundled UI launch failed: {exc}"
        else:
            ui_failure_reason = f"Bundled UI executable missing: {bundled_ui}"
    elif ui_path and os.path.isdir(ui_path):
        ui_url = os.path.abspath(ui_path)
        ui_process = _launch_tauri_dev_process(ui_path, emit)
        if ui_process is not None:
            launch_mode = "attached"
            stable = _wait_for_process_stabilisation(ui_process, emit)
            if not stable:
                try:
                    ui_process.kill()
                except Exception:
                    pass
                ui_process = None
                launch_mode = "detached"
                ui_failure_reason = "UI process failed stabilisation check"
                emit("[UI] Process failed stabilisation — not reporting UI ready")
            else:
                emit(f"Desktop UI ready (PID={ui_process.pid})")
                state.ui_ready = True
                readiness["ui"] = "ready"
        else:
            ui_failure_reason = "UI process failed to launch"
            emit(f"[UI] Launch failed — not reporting UI ready: {ui_url}")
    else:
        emit("Desktop UI ready (headless / no bundled UI)")
        state.ui_ready = True
        readiness["ui"] = "ready"

    if ui_failure_reason and not state.ui_ready:
        return UiLaunchResult(
            success=False,
            mode="failed",
            api_url=api_url,
            cloud_url=c_url,
            message=ui_failure_reason,
            readiness=readiness,
            _api_thread=api_thread,
            _owned_server=owned,
        )

    # Mode determination
    # Distinguish three cases:
    #   1. trading is healthy AND execution is enabled AND mode is "live" → "live"
    #   2. trading is healthy but execution is disabled OR mode is observe → "active"
    #   3. trading is missing, stopped, or degraded → "degraded"
    if trading_ok and trading["execution_enabled"] and trading["mode"] == "live":
        mode = "live"
    elif trading_ok:
        mode = "active"
    else:
        mode = "degraded"

    # Determine operational status based on real service health
    if not api_ready:
        operational_status = "failed"
    elif not state.ui_ready:
        operational_status = "degraded"
    elif not cloud_ready:
        operational_status = "degraded"
    else:
        operational_status = mode

    result = UiLaunchResult(
        success=state.ui_ready,
        mode=operational_status,
        api_url=api_url,
        cloud_url=c_url,
        ui_url=ui_url,
        message="Niblit desktop runtime launched" if state.ui_ready else "Desktop UI failed to launch",
        readiness=readiness,
        _api_thread=api_thread,
        _owned_server=owned,
        _ui_process=ui_process,
        _launch_mode=launch_mode,
        _cloud_process=cloud_process,
        _shutdown_event=getattr(core, "_shutdown_event", None),
    )
    return result


def _wait_for_cloud_ready(
    url: str,
    *,
    timeout_seconds: float = 120.0,
    interval_seconds: float = 0.5,
) -> Dict[str, Any]:
    """Poll the Niblit Cloud inference server until it reports ready.

    Checks ``/health`` and ``/v1/models``. Returns a dict with keys:
    ``ready``, ``health_ok``, ``models_ok``, ``error``.
    """
    result: Dict[str, Any] = {
        "ready": False,
        "health_ok": False,
        "models_ok": False,
        "error": None,
    }
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        try:
            req = urllib.request.Request(
                f"{url.rstrip('/')}/health",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=min(5, max(1, remaining))) as resp:
                if 200 <= resp.status < 300:
                    result["health_ok"] = True
        except Exception:
            pass

        try:
            req = urllib.request.Request(
                f"{url.rstrip('/')}/v1/models",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=min(5, max(1, remaining))) as resp:
                if 200 <= resp.status < 300:
                    result["models_ok"] = True
        except Exception:
            pass

        if result["health_ok"] and result["models_ok"]:
            result["ready"] = True
            return result

        time.sleep(min(interval_seconds, max(0.05, remaining)))

    result["error"] = "Cloud server did not become ready within timeout"
    return result


def _find_cloud_server_root() -> Optional[Path]:
    """Locate the Niblit-cloud-server repository root."""
    candidates = [
        Path(os.environ.get("NIBLIT_CLOUD_SERVER_PATH", "")),
        _REPO_ROOT.parent / "Niblit-cloud-server",
        _REPO_ROOT / "Niblit-cloud-server",
        Path.cwd().parent / "Niblit-cloud-server",
        Path.cwd() / "Niblit-cloud-server",
    ]
    for candidate in candidates:
        # Skip empty/unset env overrides and non-directory entries.
        if not candidate or str(candidate) in {".", ""}:
            continue
        if candidate.is_dir():
            return candidate
    return None


def _maybe_start_cloud_server(
    url: str,
    emit: Callable[[str], None],
) -> Optional[subprocess.Popen]:
    """Best-effort start the local Niblit-cloud-server if it is not already healthy."""
    frozen = getattr(sys, "frozen", False)
    cloud_root = (
        Path(sys.executable).resolve().parent / "cloud"
        if frozen else _find_cloud_server_root()
    )
    if cloud_root is None:
        emit("[Cloud] Niblit-cloud-server repository not found — skipping autostart")
        return None

    emit(f"[Cloud] Discovered Niblit-cloud-server at {cloud_root}")
    python_exe = sys.executable or shutil.which("python") or shutil.which("python3")
    if python_exe is None:
        emit("[Cloud] Python executable not found — cannot start cloud server")
        return None

    if frozen:
        packaged_cloud = cloud_root / ("niblit-cloud.exe" if os.name == "nt" else "niblit-cloud")
        if not packaged_cloud.is_file():
            emit(f"[Cloud] Bundled cloud executable missing: {packaged_cloud}")
            return None
        cmd = [str(packaged_cloud)]
    else:
        cmd = [python_exe, "main.py"]
    cwd = str(cloud_root)
    env = os.environ.copy()
    env.setdefault("NIBLIT_CLOUD_SERVER_URL", url.rstrip("/"))

    kwargs: Dict[str, Any] = {
        "cwd": cwd,
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "bufsize": 1,
    }
    if platform.system().lower() == "windows":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

    try:
        proc = subprocess.Popen(cmd, **kwargs)
        emit(f"[Cloud] Launch command: {' '.join(cmd)} (cwd={cwd})")
        emit(f"[Cloud] Process PID: {proc.pid}")
        return proc
    except Exception as exc:
        emit(f"[Cloud] Failed to start cloud server: {exc}")
        return None


def _open_primary_ui_url() -> Optional[str]:
    """Return the desktop UI base URL / path, or ``None`` when absent."""
    ui_path = os.environ.get("NIBLIT_UI_PATH", "").strip()
    if not ui_path:
        cwd = Path.cwd()
        for candidate in (cwd / "niblit-ui", cwd.parent / "niblit-ui"):
            if candidate.is_dir():
                ui_path = str(candidate)
                break
    if ui_path and os.path.isdir(ui_path):
        return os.path.abspath(ui_path)
    return None


if __name__ == "__main__":
    result = launch_primary_ui()
    print(f"success={result.success} mode={result.mode} message={result.message}")
