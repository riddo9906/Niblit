#!/usr/bin/env python3
"""Niblit runtime control terminal (thin wrapper around tools.lib.sidecar_client)."""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tools.lib.runtime_profiles import apply_profile, available_profiles
from tools.lib.sidecar_client import SidecarClient, SidecarTarget, format_response

_DEFAULT_SOCKET = os.environ.get("NIBLIT_CTL_SOCKET", "/tmp/niblit-ctl.sock").strip()
_DEFAULT_HOST = os.environ.get("NIBLIT_CTL_HOST", "").strip()
_DEFAULT_PORT = int(os.environ.get("NIBLIT_CTL_PORT", "7681") or 7681)

_GOVERNANCE_COMMANDS = {
    "runtime_status": "runtime status",
    "governance_snapshot": "governance snapshot",
    "coherence_state": "coherence state",
    "active_model_state": "active model state",
    "runtime_mode": "runtime mode",
    "attention_allocator_metrics": "attention allocator metrics",
}


def _output_mode(args: argparse.Namespace) -> str:
    if args.raw:
        return "raw"
    if args.json:
        return "json"
    return "pretty"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="niblit_ctl",
        description="Niblit runtime control client (UNIX socket or TCP).",
    )
    parser.add_argument("-c", "--command", default=None, help="Run one command and exit")
    parser.add_argument("--profile", default="niblit", choices=available_profiles() or ["niblit"], help="Runtime profile")

    parser.add_argument("--transport", choices=["unix", "tcp", "auto"], default="auto", help="Control transport")
    parser.add_argument("-s", "--socket", default=_DEFAULT_SOCKET, help="UNIX socket path")
    parser.add_argument("--host", default=_DEFAULT_HOST, help="TCP host")
    parser.add_argument("--port", type=int, default=_DEFAULT_PORT, help="TCP port")

    parser.add_argument("--wait", action="store_true", help="Wait for sidecar before interactive mode")
    parser.add_argument("--wait-timeout", type=float, default=600.0, help="Max wait seconds")
    parser.add_argument("--ping", action="store_true", help="Ping sidecar")
    parser.add_argument("--status", action="store_true", help="Get sidecar status (__status__) ")

    parser.add_argument("--runtime-status", action="store_true", help="Send 'runtime status'")
    parser.add_argument("--governance-snapshot", action="store_true", help="Send 'governance snapshot'")
    parser.add_argument("--coherence-state", action="store_true", help="Send 'coherence state'")
    parser.add_argument("--active-model-state", action="store_true", help="Send 'active model state'")
    parser.add_argument("--runtime-mode", action="store_true", help="Send 'runtime mode'")
    parser.add_argument("--attention-allocator-metrics", action="store_true", help="Send 'attention allocator metrics'")

    parser.add_argument("--json", action="store_true", help="Structured JSON output")
    parser.add_argument("--pretty", action="store_true", help="Human-readable output (default)")
    parser.add_argument("--raw", action="store_true", help="Raw payload output")
    parser.add_argument("--timeout", type=float, default=300.0, help="Command timeout (s)")
    return parser.parse_args(argv)


def _target_from_args(args: argparse.Namespace) -> SidecarTarget:
    transport = args.transport
    if transport == "auto":
        if args.host:
            transport = "tcp"
        else:
            transport = "unix"

    if transport == "tcp":
        host = args.host or "127.0.0.1"
        return SidecarTarget(transport="tcp", host=host, port=args.port)
    return SidecarTarget(transport="unix", socket_path=args.socket)


def _wait_for_ready(client: SidecarClient, timeout_s: float, mode: str) -> bool:
    print("⏳ Waiting for Niblit sidecar...", flush=True)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            resp = client.send_recv({"cmd": "__status__"}, timeout=3.0)
        except OSError:
            time.sleep(1.5)
            continue
        if resp.status == "ok":
            print(format_response(resp, mode=mode))
            return True
        time.sleep(1.5)
    return False


def _emit(client: SidecarClient, payload: dict, mode: str, timeout: float, stream: bool = False) -> int:
    try:
        if stream:
            results = client.stream_responses(payload, timeout=timeout)
            for item in results:
                print(format_response(item, mode=mode))
            return 0 if results and results[-1].status in {"ok", "pong", "init"} else 1

        resp = client.send_recv(payload, timeout=timeout)
        print(format_response(resp, mode=mode))
        return 0 if resp.status in {"ok", "pong"} else 1
    except OSError as exc:
        if mode == "json":
            import json as _json
            print(_json.dumps({"status": "error", "result": str(exc)}, ensure_ascii=False))
        else:
            print(f"[ERROR] {exc}", file=sys.stderr)
        return 1


def _interactive(client: SidecarClient, mode: str, timeout: float) -> int:
    print("Niblit Control Terminal (type 'exit' to quit)")
    req_id = 1
    while True:
        try:
            line = input("Niblit-ctl > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line.lower() in {"exit", "quit"}:
            return 0
        if line == "!ping":
            code = _emit(client, {"cmd": "__ping__"}, mode=mode, timeout=min(timeout, 5.0))
            continue
        if line == "!status":
            code = _emit(client, {"cmd": "__status__"}, mode=mode, timeout=min(timeout, 5.0))
            continue

        code = _emit(client, {"id": req_id, "cmd": line}, mode=mode, timeout=timeout, stream=True)
        req_id += 1
        if code != 0:
            print("⚠️ command returned non-ok status", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    apply_profile(args.profile)

    mode = _output_mode(args)
    target = _target_from_args(args)
    client = SidecarClient(target=target, timeout=args.timeout)

    if args.wait:
        if not _wait_for_ready(client, args.wait_timeout, mode):
            print("Timed out waiting for sidecar", file=sys.stderr)
            return 1

    if args.ping:
        return _emit(client, {"cmd": "__ping__"}, mode=mode, timeout=min(args.timeout, 5.0))
    if args.status:
        return _emit(client, {"cmd": "__status__"}, mode=mode, timeout=min(args.timeout, 5.0))

    governance_flags = {
        "runtime_status": args.runtime_status,
        "governance_snapshot": args.governance_snapshot,
        "coherence_state": args.coherence_state,
        "active_model_state": args.active_model_state,
        "runtime_mode": args.runtime_mode,
        "attention_allocator_metrics": args.attention_allocator_metrics,
    }
    for key, enabled in governance_flags.items():
        if enabled:
            return _emit(client, {"id": 1, "cmd": _GOVERNANCE_COMMANDS[key]}, mode=mode, timeout=args.timeout, stream=True)

    if args.command:
        return _emit(client, {"id": 1, "cmd": args.command}, mode=mode, timeout=args.timeout, stream=True)

    return _interactive(client, mode, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
