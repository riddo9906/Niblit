#!/usr/bin/env python3
"""
os/userland/niblit_tool/niblit_entry.py
─────────────────────────────────────────────────────────────────────────────
NiblitOS userspace entry point for the Niblit AI tool.

Two modes of operation:

1. **Single-shot mode** (default): Called once by niblit_runner when a kernel
   request arrives.  Request parameters are delivered via environment
   variables:

     NIBLIT_REQUEST_ID   — numeric request ID
     NIBLIT_REQUEST_TYPE — "query" | "tool"
     NIBLIT_TOOL         — tool name (only for type=tool)
     NIBLIT_QUERY        — natural-language query or JSON arguments

   The result is printed as a JSON envelope on stdout and the process exits.

2. **Daemon mode** (--daemon): Runs a persistent UNIX socket server at
   NIBLIT_SOCKET_PATH (default: /tmp/niblit.sock).  The C runner sends
   requests via the socket and receives JSON responses.  This avoids the
   Python startup overhead for every kernel request.

Usage:
  # Single-shot (called by niblit_runner)
  NIBLIT_REQUEST_TYPE=query NIBLIT_QUERY="What is 2+2?" python3 niblit_entry.py

  # Daemon mode
  python3 niblit_entry.py --daemon

  # Status check
  python3 niblit_entry.py --status
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import threading
import traceback

# ── Path setup — ensure the Niblit repo root is on sys.path ──────────────────
# niblit_entry.py lives at  os/userland/niblit_tool/niblit_entry.py
# Niblit repo root is 3 levels up.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT  = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

_DEFAULT_SOCKET = os.environ.get("NIBLIT_SOCKET_PATH", "/tmp/niblit.sock")

log = logging.getLogger("niblit_entry")


# ── NiblitCore lazy singleton ─────────────────────────────────────────────────
_core_lock = threading.Lock()
_core_instance = None


def _get_core():
    global _core_instance
    if _core_instance is None:
        with _core_lock:
            if _core_instance is None:
                try:
                    from niblit_core import NiblitCore  # type: ignore[import]
                    _core_instance = NiblitCore()
                except Exception:  # noqa: BLE001
                    pass
    return _core_instance


# ── Request handlers ──────────────────────────────────────────────────────────

def _handle_query(query: str) -> str:
    """Process a natural-language query through NiblitCore."""
    core = _get_core()
    if core is None:
        return "ERROR: NiblitCore unavailable — failed to import"
    try:
        result = core.process(query)
        return str(result) if result else "(no response)"
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: NiblitCore.process() raised — {exc}"


def _handle_tool_call(tool_name: str, args_json: str) -> str:
    """Invoke a registered Niblit tool by name with JSON arguments."""
    try:
        from niblit_tools.tool_registry import get_registry  # type: ignore[import]
        registry = get_registry()
        try:
            kwargs = json.loads(args_json) if args_json else {}
        except json.JSONDecodeError:
            kwargs = {}
        result = registry.run(tool_name, kwargs)
        return json.dumps(result, default=str)
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: tool '{tool_name}' failed — {exc}"


def _handle_shutdown() -> str:
    """Gracefully shut down the Niblit daemon."""
    log.info("Shutdown requested via IPC.")
    return "OK: shutting down"


def dispatch(request: dict) -> dict:
    """Dispatch a request dict and return a response dict."""
    req_id   = int(request.get("request_id", 0))
    req_type = str(request.get("type", "query")).lower()
    tool     = str(request.get("tool", ""))
    query    = str(request.get("query", ""))

    try:
        if req_type == "shutdown":
            result = _handle_shutdown()
        elif req_type == "tool" and tool:
            result = _handle_tool_call(tool, query)
        else:
            result = _handle_query(query)
    except Exception:  # noqa: BLE001
        result = f"ERROR: unhandled exception\n{traceback.format_exc()}"

    result = str(result)
    return {
        "request_id": req_id,
        "status": "ok" if not result.startswith("ERROR:") else "error",
        "result": result,
    }


# ── Single-shot mode ──────────────────────────────────────────────────────────

def run_single_shot() -> None:
    """Read request from environment variables, print JSON response to stdout."""
    request = {
        "request_id": int(os.environ.get("NIBLIT_REQUEST_ID", "0")),
        "type":       os.environ.get("NIBLIT_REQUEST_TYPE", "query").lower(),
        "tool":       os.environ.get("NIBLIT_TOOL", ""),
        "query":      os.environ.get("NIBLIT_QUERY", ""),
    }
    response = dispatch(request)
    print(json.dumps(response), end="", flush=True)


# ── Daemon mode ───────────────────────────────────────────────────────────────

def _handle_connection(conn: socket.socket, addr: object) -> None:
    """Handle one client connection (one request / response pair)."""
    try:
        data = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break
        if not data:
            return
        request = json.loads(data.decode("utf-8", errors="replace").strip())
        response = dispatch(request)
        conn.sendall((json.dumps(response) + "\n").encode("utf-8"))

        if request.get("type", "").lower() == "shutdown":
            os._exit(0)  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        log.warning("Connection error from %s: %s", addr, exc)
    finally:
        conn.close()


def run_daemon(socket_path: str = _DEFAULT_SOCKET) -> None:
    """Run as a persistent UNIX socket server."""
    # Remove stale socket
    try:
        os.unlink(socket_path)
    except FileNotFoundError:
        pass

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(socket_path)
    os.chmod(socket_path, 0o600)
    server.listen(8)

    log.info("Niblit daemon listening on %s", socket_path)

    # Warm up NiblitCore in background so first request is fast
    threading.Thread(target=_get_core, daemon=True).start()

    try:
        while True:
            conn, addr = server.accept()
            t = threading.Thread(target=_handle_connection, args=(conn, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        log.info("Daemon interrupted — shutting down.")
    finally:
        server.close()
        try:
            os.unlink(socket_path)
        except OSError:
            pass


def run_status(socket_path: str = _DEFAULT_SOCKET) -> None:
    """Ping the daemon and print its status."""
    try:
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.settimeout(2.0)
        c.connect(socket_path)
        req = json.dumps({"request_id": 0, "type": "query", "query": "status"}) + "\n"
        c.sendall(req.encode())
        data = b""
        while True:
            chunk = c.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break
        c.close()
        resp = json.loads(data.decode())
        print("Daemon status: RUNNING")
        print(json.dumps(resp, indent=2))
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        print("Daemon status: NOT RUNNING")


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(prog="niblit_entry")
    parser.add_argument("--daemon",  action="store_true", help="Run as persistent socket daemon")
    parser.add_argument("--status",  action="store_true", help="Check daemon status")
    parser.add_argument("--socket",  default=_DEFAULT_SOCKET, help="UNIX socket path")
    parser.add_argument("--debug",   action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [niblit] %(levelname)s %(message)s",
    )

    if args.status:
        run_status(args.socket)
    elif args.daemon:
        run_daemon(args.socket)
    else:
        run_single_shot()


if __name__ == "__main__":
    main()
