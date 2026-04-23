#!/usr/bin/env python3
"""
scripts/deploy_all_to_qc.py — Deploy all Niblit LEAN algorithms to QuantConnect Cloud.

Uses Niblit's LeanDeployEngine (modules/lean_deploy_engine.py) REST API client
to create projects on QuantConnect, upload algorithm code, and optionally run
an initial backtest to validate each algorithm.

Usage
-----
    # From the niblit-lean-algos directory:
    python scripts/deploy_all_to_qc.py

    # With options:
    python scripts/deploy_all_to_qc.py --dry-run          # Print only, don't deploy
    python scripts/deploy_all_to_qc.py --backtest         # Also launch backtests
    python scripts/deploy_all_to_qc.py --algo 01          # Deploy specific algo by prefix

Environment variables required:
    QC_USER_ID   — QuantConnect numeric user ID
    QC_API_CRED  — QuantConnect API token

Both can also be set in niblit_params.json in the Niblit root directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import urllib.request
import urllib.error
import base64

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

_SCRIPT_DIR  = Path(__file__).resolve().parent
_REPO_ROOT   = _SCRIPT_DIR.parent
_ALGOS_DIR   = _REPO_ROOT / "algorithms"
_NIBLIT_ROOT = _REPO_ROOT.parent  # sibling: .../Niblit/

_QC_API_BASE = "https://www.quantconnect.com/api/v2"

# ─────────────────────────────────────────────────────────────────────────────
# Credentials
# ─────────────────────────────────────────────────────────────────────────────

def _load_credentials() -> tuple[str, str]:
    """Return (user_id, api_token) from env or niblit_params.json."""
    user_id  = os.environ.get("QC_USER_ID", "").strip()
    api_cred = os.environ.get("QC_API_CRED", "").strip()

    if not user_id or not api_cred:
        params_file = _NIBLIT_ROOT / "niblit_params.json"
        if params_file.exists():
            try:
                params = json.loads(params_file.read_text())
                user_id  = user_id  or str(params.get("QC_USER_ID", "")).strip()
                api_cred = api_cred or str(params.get("QC_API_CRED", "")).strip()
            except Exception:
                pass

    return user_id, api_cred


def _auth_headers(user_id: str, api_cred: str) -> Dict[str, str]:
    """Build QuantConnect HMAC-SHA256 auth header."""
    ts = str(int(time.time()))
    digest_input = f"{ts}:{api_cred}".encode()
    hash_hex = hashlib.sha256(digest_input).hexdigest()
    raw = f"{user_id}:{hash_hex}"
    encoded = base64.b64encode(raw.encode()).decode()
    return {
        "Authorization": f"Basic {encoded}",
        "Timestamp": ts,
        "Content-Type": "application/json",
    }


# ─────────────────────────────────────────────────────────────────────────────
# API helpers
# ─────────────────────────────────────────────────────────────────────────────

def _api(
    method: str,
    endpoint: str,
    payload: Optional[Dict[str, Any]],
    user_id: str,
    api_cred: str,
) -> Dict[str, Any]:
    url = f"{_QC_API_BASE}/{endpoint.lstrip('/')}"
    headers = _auth_headers(user_id, api_cred)
    body = json.dumps(payload).encode() if payload else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code}: {exc.reason}"}
    except Exception as exc:
        return {"error": str(exc)}


def _create_project(name: str, user_id: str, api_cred: str) -> Optional[int]:
    data = _api("POST", "projects/create", {"name": name, "language": "Py"}, user_id, api_cred)
    if "error" in data:
        print(f"  ❌ Create project failed: {data['error']}")
        return None
    project_id = data.get("projects", [{}])[0].get("projectId")
    return project_id


def _upload_file(
    project_id: int,
    filename: str,
    content: str,
    user_id: str,
    api_cred: str,
) -> bool:
    data = _api(
        "POST",
        f"files/create",
        {"projectId": project_id, "name": filename, "content": content},
        user_id,
        api_cred,
    )
    if "error" in data:
        print(f"  ❌ Upload failed: {data['error']}")
        return False
    return True


def _compile_project(project_id: int, user_id: str, api_cred: str) -> Optional[str]:
    data = _api("POST", f"compile/create", {"projectId": project_id}, user_id, api_cred)
    if "error" in data:
        print(f"  ❌ Compile failed: {data['error']}")
        return None
    return data.get("compileId")


def _launch_backtest(project_id: int, compile_id: str, user_id: str, api_cred: str) -> Optional[str]:
    data = _api(
        "POST",
        "backtests/create",
        {"projectId": project_id, "compileId": compile_id, "backtestName": "niblit-initial"},
        user_id,
        api_cred,
    )
    if "error" in data:
        print(f"  ❌ Backtest launch failed: {data['error']}")
        return None
    return data.get("backtestId")


# ─────────────────────────────────────────────────────────────────────────────
# Main deployment logic
# ─────────────────────────────────────────────────────────────────────────────

def discover_algorithms(prefix_filter: Optional[str] = None) -> List[tuple[str, Path]]:
    """Return [(algo_name, main_py_path), ...] sorted by prefix number."""
    algos = []
    if not _ALGOS_DIR.exists():
        print(f"❌ Algorithms directory not found: {_ALGOS_DIR}")
        return algos
    for d in sorted(_ALGOS_DIR.iterdir()):
        if not d.is_dir():
            continue
        if prefix_filter and not d.name.startswith(prefix_filter):
            continue
        main_py = d / "main.py"
        if main_py.exists():
            algos.append((d.name, main_py))
    return algos


def deploy_algorithm(
    algo_name: str,
    main_py: Path,
    user_id: str,
    api_cred: str,
    dry_run: bool,
    run_backtest: bool,
) -> Dict[str, Any]:
    """Deploy a single algorithm. Returns a result dict."""
    qc_name = f"niblit-{algo_name}"
    content = main_py.read_text(encoding="utf-8")

    print(f"\n🚀 {algo_name}")
    print(f"   QC Project name: {qc_name}")
    print(f"   File size: {len(content)} bytes")

    if dry_run:
        print("   [DRY RUN — no changes made]")
        return {"algo": algo_name, "status": "dry_run"}

    # 1. Create project
    print("   Creating project…", end=" ", flush=True)
    project_id = _create_project(qc_name, user_id, api_cred)
    if project_id is None:
        return {"algo": algo_name, "status": "failed", "step": "create"}
    print(f"✅ projectId={project_id}")

    # 2. Upload main.py
    print("   Uploading main.py…", end=" ", flush=True)
    ok = _upload_file(project_id, "main.py", content, user_id, api_cred)
    if not ok:
        return {"algo": algo_name, "status": "failed", "step": "upload"}
    print("✅")

    # 3. Compile
    print("   Compiling…", end=" ", flush=True)
    compile_id = _compile_project(project_id, user_id, api_cred)
    if compile_id is None:
        return {"algo": algo_name, "status": "failed", "step": "compile"}
    print(f"✅ compileId={compile_id}")

    result = {
        "algo": algo_name,
        "status": "deployed",
        "project_id": project_id,
        "compile_id": compile_id,
        "qc_name": qc_name,
    }

    # 4. Optional backtest
    if run_backtest:
        print("   Launching backtest…", end=" ", flush=True)
        bt_id = _launch_backtest(project_id, compile_id, user_id, api_cred)
        if bt_id:
            print(f"✅ backtestId={bt_id}")
            result["backtest_id"] = bt_id
        # Small delay between backtests to avoid rate limits
        time.sleep(2)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy Niblit LEAN algorithms to QuantConnect Cloud")
    parser.add_argument("--dry-run",   action="store_true", help="Print plan without deploying")
    parser.add_argument("--backtest",  action="store_true", help="Launch initial backtest after deploy")
    parser.add_argument("--algo",      default=None, help="Deploy only algorithms starting with this prefix")
    parser.add_argument("--save-ids",  default="deployed_projects.json", help="Save project IDs to this file")
    args = parser.parse_args()

    user_id, api_cred = _load_credentials()
    if not user_id or not api_cred:
        print("❌ QC_USER_ID and QC_API_CRED must be set.")
        print("   Set as environment variables or in niblit_params.json.")
        sys.exit(1)
    print(f"✅ Credentials loaded (user_id={user_id[:4]}...)")

    algos = discover_algorithms(args.algo)
    if not algos:
        print(f"❌ No algorithms found in {_ALGOS_DIR}")
        sys.exit(1)

    print(f"\nFound {len(algos)} algorithm(s) to deploy:")
    for name, path in algos:
        print(f"  • {name}")

    results = []
    for algo_name, main_py in algos:
        r = deploy_algorithm(
            algo_name=algo_name,
            main_py=main_py,
            user_id=user_id,
            api_cred=api_cred,
            dry_run=args.dry_run,
            run_backtest=args.backtest,
        )
        results.append(r)
        # Rate-limit: 1 project per 3 seconds
        if not args.dry_run:
            time.sleep(3)

    # Summary
    deployed = [r for r in results if r["status"] == "deployed"]
    failed   = [r for r in results if r["status"] == "failed"]
    print(f"\n{'='*50}")
    print(f"Deployed: {len(deployed)}  Failed: {len(failed)}  Dry-run: {args.dry_run}")

    if deployed and not args.dry_run:
        out_file = _REPO_ROOT / args.save_ids
        out_file.write_text(json.dumps(results, indent=2))
        print(f"Project IDs saved to: {out_file}")
        print("\nTo start live practice trading, inside Niblit:")
        for r in deployed[:3]:
            print(f"  lean deploy live {r['project_id']} PaperBrokerage")
        print("  (use the project IDs above)")


if __name__ == "__main__":
    main()
