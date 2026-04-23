#!/usr/bin/env python3
"""tools/niblit_ctl.py — Niblit Control Terminal (Sidecar Client)

Connect to a running Niblit process from ANY terminal session and issue
commands in real-time — even while the model is loading or Niblit is busy.

Works with all three Termux deployment patterns:

  Pattern A — Model loading (same session)
  ─────────────────────────────────────────
  Session 1:  python main.py        ← Niblit + model loading here
  Session 2:  python tools/niblit_ctl.py  ← Control Niblit from here

  Pattern B — Two-session (model + Niblit separate)
  ────────────────────────────────────────────────────
  Session 1:  llama-server [model loads here]
  Session 2:  python main.py  (proot)
  Session 3:  python tools/niblit_ctl.py   ← Control from normal Termux

  Pattern C — Script / one-shot
  ───────────────────────────────
  python tools/niblit_ctl.py -c "brain status"
  python tools/niblit_ctl.py -c "recall python" --json

Usage
-----
  python tools/niblit_ctl.py                # interactive shell
  python tools/niblit_ctl.py -c "status"   # one-shot command, then exit
  python tools/niblit_ctl.py --wait        # block until Niblit is ready, then open shell
  python tools/niblit_ctl.py --ping        # check if Niblit sidecar is running
  python tools/niblit_ctl.py --json        # print raw JSON responses

Environment
-----------
  NIBLIT_CTL_SOCKET   Path to the sidecar UNIX socket
                      (default: /tmp/niblit-ctl.sock)
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time

# Add repo root to path so imports from modules/ work when run as a script.
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

_DEFAULT_SOCKET = os.environ.get("NIBLIT_CTL_SOCKET", "/tmp/niblit-ctl.sock").strip()

# ── Low-level socket helpers ──────────────────────────────────────────────────

def _connect(socket_path: str, timeout: float = 5.0) -> socket.socket:
    """Connect to the sidecar socket.  Raises OSError on failure."""
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(timeout)
    conn.connect(socket_path)
    return conn


def _send_recv(
    socket_path: str,
    payload: dict,
    timeout: float = 300.0,
) -> dict:
    """Send one JSON request; return the parsed JSON response."""
    conn = _connect(socket_path)
    try:
        conn.settimeout(timeout)
        conn.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        data = b""
        while b"\n" not in data:
            chunk = conn.recv(8192)
            if not chunk:
                break
            data += chunk
        # There may be multiple JSON lines (e.g. an "init" status followed by
        # the real result).  Collect all of them.
        lines = [l.strip() for l in data.decode("utf-8", errors="replace").splitlines() if l.strip()]
        if not lines:
            return {"status": "error", "result": "No response from Niblit sidecar."}
        # Return the LAST response (the actual result, after any "init" status)
        return json.loads(lines[-1])
    finally:
        conn.close()


def _send_recv_streaming(
    socket_path: str,
    payload: dict,
    timeout: float = 600.0,
    raw_json: bool = False,
) -> str:
    """Send request; print each JSON line as it arrives; return final result."""
    conn = _connect(socket_path)
    last_result = ""
    try:
        conn.settimeout(timeout)
        conn.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        buf = b""
        while True:
            try:
                chunk = conn.recv(8192)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                line = line.strip()
                if not line:
                    continue
                try:
                    resp = json.loads(line.decode("utf-8", errors="replace"))
                except json.JSONDecodeError:
                    continue

                status = resp.get("status", "")

                if raw_json:
                    print(json.dumps(resp))
                elif status == "init":
                    print(f"\033[33m⏳ {resp.get('message', 'Initialising...')}\033[0m", flush=True)
                elif status == "pong":
                    print("🟢 Niblit sidecar is running.")
                elif status in ("ok", "timeout", "error"):
                    result = resp.get("result", "")
                    last_result = result
                    return last_result

    except (OSError, socket.timeout) as exc:
        return f"[CONNECTION ERROR] {exc}"
    finally:
        conn.close()
    return last_result


# ── High-level helpers ────────────────────────────────────────────────────────

def ping(socket_path: str) -> bool:
    """Return True if the sidecar is reachable."""
    try:
        resp = _send_recv(socket_path, {"cmd": "__ping__"}, timeout=3.0)
        return resp.get("status") == "pong"
    except OSError:
        return False


def wait_for_ready(socket_path: str, poll_interval: float = 2.0, max_wait: float = 600.0) -> bool:
    """Block until the sidecar is up.  Return True if ready, False on timeout."""
    deadline = time.monotonic() + max_wait
    print("⏳ Waiting for Niblit sidecar to start...", flush=True)
    while time.monotonic() < deadline:
        try:
            resp = _send_recv(socket_path, {"cmd": "__status__"}, timeout=3.0)
            if resp.get("status") == "ok":
                init_done = resp.get("init_done", False)
                uptime = resp.get("uptime_s", "?")
                label = "READY" if init_done else "INIT (model loading)"
                print(f"🟢 Niblit sidecar UP — {label}  (uptime {uptime}s)")
                return True
        except OSError:
            pass
        time.sleep(poll_interval)
    print("🔴 Timed out waiting for Niblit sidecar.", file=sys.stderr)
    return False


# ── Interactive shell ─────────────────────────────────────────────────────────

_BANNER = """\033[1;36m
╔══════════════════════════════════════════════════════╗
║  Niblit Control Terminal  (niblit_ctl.py)             ║
║  Connected to: {socket:<36} ║
║  Type any Niblit command.  'exit' to quit.           ║
╚══════════════════════════════════════════════════════╝\033[0m
"""

_HELP = """\
Built-in niblit_ctl commands:
  exit / quit / Ctrl+C   — close this control terminal (does NOT stop Niblit)
  !ping                  — ping the sidecar
  !status                — show sidecar and init status
  !socket                — show socket path
  !help                  — this help text

Any other input is forwarded to Niblit as a normal command, e.g.:
  brain status
  recall python
  qwen ask What are my KB gaps?
  autonomous-learn status
  toggle-llm status
  help
"""


def run_interactive(socket_path: str, raw_json: bool = False) -> None:
    print(_BANNER.format(socket=socket_path))

    # Quick connectivity check
    if not ping(socket_path):
        print(
            f"🔴 Cannot reach Niblit sidecar at {socket_path}\n"
            "   Is Niblit (python main.py) running?\n"
            "   If Niblit just started, wait a few seconds and try again.\n"
            f"   Override socket path with: NIBLIT_CTL_SOCKET=/path python {__file__}",
            file=sys.stderr,
        )
        sys.exit(1)

    req_id = 1
    try:
        while True:
            try:
                line = input("\033[1;36mNiblit-ctl\033[0m > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nClosing control terminal.")
                break

            if not line:
                continue

            low = line.lower()

            if low in ("exit", "quit"):
                print("Closing control terminal.")
                break

            if line == "!help":
                print(_HELP)
                continue

            if line == "!ping":
                ok = ping(socket_path)
                print("🟢 PONG — sidecar is alive." if ok else "🔴 No response.")
                continue

            if line == "!status":
                try:
                    resp = _send_recv(socket_path, {"cmd": "__status__"}, timeout=5.0)
                    init_done = resp.get("init_done", False)
                    uptime = resp.get("uptime_s", "?")
                    print(
                        f"  Status   : {'READY' if init_done else 'INIT (model may still be loading)'}\n"
                        f"  Uptime   : {uptime}s\n"
                        f"  Socket   : {resp.get('socket', socket_path)}"
                    )
                except OSError as exc:
                    print(f"🔴 Cannot reach sidecar: {exc}")
                continue

            if line == "!socket":
                print(f"  Socket: {socket_path}")
                continue

            # Forward command to Niblit
            result = _send_recv_streaming(
                socket_path,
                {"id": req_id, "cmd": line},
                raw_json=raw_json,
            )
            req_id += 1
            if result:
                print(result)

    except KeyboardInterrupt:
        print("\nClosing control terminal.")


# ── CLI entry point ───────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="niblit_ctl",
        description="Niblit Control Terminal — issue commands to a running Niblit process.",
    )
    p.add_argument(
        "-c", "--command",
        metavar="CMD",
        default=None,
        help="Run a single command and exit (non-interactive)",
    )
    p.add_argument(
        "-s", "--socket",
        default=_DEFAULT_SOCKET,
        metavar="PATH",
        help=f"Path to the sidecar UNIX socket (default: {_DEFAULT_SOCKET})",
    )
    p.add_argument(
        "--wait",
        action="store_true",
        help="Wait until the sidecar is ready before opening the shell",
    )
    p.add_argument(
        "--ping",
        action="store_true",
        help="Check if the Niblit sidecar is running and exit",
    )
    p.add_argument(
        "--status",
        action="store_true",
        help="Print sidecar status and exit",
    )
    p.add_argument(
        "--json",
        action="store_true",
        dest="raw_json",
        help="Print raw JSON responses (useful for scripting)",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=300.0,
        metavar="SECS",
        help="Command timeout in seconds (default: 300)",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    socket_path = args.socket

    if args.ping:
        ok = ping(socket_path)
        if args.raw_json:
            print(json.dumps({"status": "pong" if ok else "unreachable", "socket": socket_path}))
        elif ok:
            print(f"🟢 Niblit sidecar is running  ({socket_path})")
        else:
            print(f"🔴 Niblit sidecar not found   ({socket_path})\n"
                  "   Start Niblit with: python main.py")
        sys.exit(0 if ok else 1)

    if args.status:
        try:
            resp = _send_recv(socket_path, {"cmd": "__status__"}, timeout=5.0)
            if args.raw_json:
                print(json.dumps(resp))
            else:
                init_done = resp.get("init_done", False)
                uptime = resp.get("uptime_s", "?")
                state = "READY" if init_done else "INIT (model loading)"
                print(f"Niblit sidecar: {state}  |  uptime={uptime}s  |  socket={socket_path}")
        except OSError as exc:
            print(f"🔴 Cannot reach sidecar at {socket_path}: {exc}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    if args.wait:
        if not wait_for_ready(socket_path):
            sys.exit(1)

    if args.command:
        # One-shot mode
        try:
            result = _send_recv_streaming(
                socket_path,
                {"id": 1, "cmd": args.command},
                timeout=args.timeout,
                raw_json=args.raw_json,
            )
            if result:
                print(result)
        except OSError as exc:
            print(f"[ERROR] Cannot reach Niblit sidecar at {socket_path}: {exc}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    # Interactive mode
    run_interactive(socket_path, raw_json=args.raw_json)


if __name__ == "__main__":
    main()
