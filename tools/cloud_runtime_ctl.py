#!/usr/bin/env python3
"""Cloud/local runtime control CLI with compatibility/federation diagnostics."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from tools.lib.runtime_client import RuntimeClient

_DEFAULT_URL = os.environ.get("NIBLIT_RUNTIME_URL", "http://127.0.0.1:8000")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cloud_runtime_ctl",
        description="Inspect Niblit runtime contract, federation readiness, and compatibility status.",
    )
    parser.add_argument("command", nargs="?", default="diagnostics", choices=[
        "diagnostics",
        "runtime",
        "cluster",
        "peers",
        "compatibility",
        "sync",
    ])
    parser.add_argument("--url", default=_DEFAULT_URL, help="Niblit runtime base URL")
    parser.add_argument("--timeout", type=float, default=10.0, help="Request timeout seconds")
    parser.add_argument("--json", action="store_true", help="JSON output")
    return parser.parse_args(argv)


def _emit(payload: dict, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    print(payload)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    client = RuntimeClient(base_url=args.url, timeout=args.timeout)

    if args.command == "runtime":
        res = client.runtime_contract()
        return _emit(res.data if res.ok else {"error": res.error}, args.json)

    if args.command == "cluster":
        res = client.cluster_status()
        return _emit(res.data if res.ok else {"error": res.error}, args.json)

    if args.command == "peers":
        res = client.federation_peers()
        return _emit(res.data if res.ok else {"error": res.error}, args.json)

    diag = client.diagnostics()

    if args.command == "compatibility":
        return _emit(
            {
                "compatibility": diag.get("compatibility", {}),
                "compatibility_check": diag.get("compatibility_check", {}),
            },
            args.json,
        )

    if args.command == "sync":
        runtime = diag.get("runtime", {})
        cluster = diag.get("cluster", {})
        return _emit(
            {
                "runtime_mode": ((runtime.get("runtime") or {}).get("mode") if isinstance(runtime.get("runtime"), dict) else runtime.get("runtime_mode", "unknown")),
                "governance_mode": ((runtime.get("governance") or {}).get("governance_mode") if isinstance(runtime.get("governance"), dict) else runtime.get("governance_mode", "unknown")),
                "epoch_id": ((runtime.get("temporal") or {}).get("epoch_id") if isinstance(runtime.get("temporal"), dict) else runtime.get("epoch_id", 0)),
                "coherence_score": ((runtime.get("temporal") or {}).get("coherence_score") if isinstance(runtime.get("temporal"), dict) else runtime.get("coherence_score", 0.0)),
                "cluster_status": cluster.get("status", "unknown"),
            },
            args.json,
        )

    return _emit(diag, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
