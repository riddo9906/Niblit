#!/usr/bin/env python3
"""
nibblebots/rollback_guard.py — Phase 4 Rollback Guard

Detects when a recent evolution commit caused a regression and emits a
``git revert`` command so the workflow can undo the change automatically.

How it works
------------
1. After a commit is pushed, ``check(fix_types, current_run_id)`` compares
   the latest CI outcome to a rolling window of recent runs.
2. If the new failure count exceeds the rolling average by more than
   ``ROLLBACK_THRESHOLD`` (default: 2 new failures), the guard sets a flag
   and writes a revert command to a well-known temp file.
3. The workflow reads that file and executes ``git revert`` if present.
4. The reverted fix type is marked ``risk_flag: true`` in impact_weights.json
   so the impact engine avoids it next run.

Constants
---------
ROLLBACK_THRESHOLD       : int   (env: EVOLUTION_ROLLBACK_THRESHOLD, default 2)
ROLLING_WINDOW           : int   (number of past runs to average, default 5)
REVERT_CMD_FILE          : Path  (/tmp/niblit_revert_cmd.txt)
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROLLBACK_THRESHOLD: int = int(os.environ.get("EVOLUTION_ROLLBACK_THRESHOLD", "2"))
ROLLING_WINDOW: int = int(os.environ.get("EVOLUTION_ROLLING_WINDOW", "5"))

REVERT_CMD_FILE = Path("/tmp/niblit_revert_cmd.txt")
_RISK_FLAG_KEY = "risk_flag"

# GitHub API (mirrors feedback_learner.py pattern)
_API_BASE = "https://api.github.com"
_TOKEN = os.environ.get("GITHUB_TOKEN", "")
_REPO = os.environ.get("GITHUB_REPOSITORY", "")

# Impact weights file (same as impact_engine.py)
_WEIGHTS_FILE = Path(__file__).parent / "impact_weights.json"


# ---------------------------------------------------------------------------
# GitHub API helper (minimal — avoids cross-module import)
# ---------------------------------------------------------------------------

def _gh_get(path: str) -> Any:
    url = f"{_API_BASE}{path}" if not path.startswith("http") else path
    if not url.startswith(_API_BASE):
        return None
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Niblit-Evolution-Agent/4.0",
    }
    if _TOKEN:
        headers["Authorization"] = f"Bearer {_TOKEN}"
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=15) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
    except (URLError, OSError, json.JSONDecodeError) as exc:
        print(f"  ⚠ RollbackGuard API error: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Rolling history of CI outcomes
# ---------------------------------------------------------------------------

def _fetch_recent_runs(n: int = ROLLING_WINDOW + 1) -> List[Dict[str, Any]]:
    """Return the n most recent completed workflow runs (newest first)."""
    if not _TOKEN or not _REPO:
        return []
    data = _gh_get(
        f"/repos/{_REPO}/actions/runs?status=completed&per_page={max(n, 10)}"
    )
    if not data:
        return []
    return data.get("workflow_runs", [])[:n]


def _failure_count(runs: List[Dict[str, Any]]) -> int:
    """Count the number of runs with conclusion != 'success'."""
    return sum(1 for r in runs if r.get("conclusion") != "success")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check(
    fix_types: List[str],
    commit_sha: str = "",
    pre_run_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Check whether the latest evolution commit caused a regression.

    Parameters
    ----------
    fix_types   : fix types that were applied in this evolution commit
    commit_sha  : SHA of the evolution commit (for the revert command)
    pre_run_id  : run ID of the workflow run that existed before the commit

    Returns a dict::

        {
          "regression": bool,
          "new_failures": int,     # failures in latest run
          "rolling_avg": float,    # average failures over previous window
          "action": str,           # "none" | "revert"
          "revert_cmd": str | None # "git revert <sha>" or None
        }
    """
    result: Dict[str, Any] = {
        "regression": False,
        "new_failures": 0,
        "rolling_avg": 0.0,
        "action": "none",
        "revert_cmd": None,
    }

    runs = _fetch_recent_runs(ROLLING_WINDOW + 1)
    if len(runs) < 2:
        result["action"] = "insufficient_history"
        return result

    # Latest = after the commit; window = previous ROLLING_WINDOW runs
    latest_run = runs[0]
    window_runs = runs[1: ROLLING_WINDOW + 1]

    latest_failed = int(latest_run.get("conclusion") != "success")
    window_failed = _failure_count(window_runs)
    rolling_avg = window_failed / max(len(window_runs), 1)

    new_failures = latest_failed - rolling_avg
    result["new_failures"] = latest_failed
    result["rolling_avg"] = round(rolling_avg, 3)

    if new_failures >= ROLLBACK_THRESHOLD:
        result["regression"] = True
        result["action"] = "revert"

        if commit_sha:
            revert_cmd = f"git revert --no-edit {commit_sha}"
        else:
            revert_cmd = "git revert --no-edit HEAD"

        result["revert_cmd"] = revert_cmd

        # Write revert command for the workflow to pick up
        try:
            REVERT_CMD_FILE.write_text(revert_cmd + "\n", encoding="utf-8")
            print(
                f"  🔄 RollbackGuard: regression detected "
                f"(new_failures={latest_failed}, rolling_avg={rolling_avg:.2f}) — "
                f"writing revert command to {REVERT_CMD_FILE}",
                file=sys.stderr,
            )
        except OSError as exc:
            print(f"  ⚠ RollbackGuard: could not write revert file: {exc}", file=sys.stderr)

        # Mark the offending fix types as risk_flag in impact_weights.json
        _flag_risk_types(fix_types)

    return result


def _flag_risk_types(fix_types: List[str]) -> None:
    """Set risk_flag: true for *fix_types* in impact_weights.json."""
    if not _WEIGHTS_FILE.exists():
        return
    try:
        weights: Dict[str, Any] = json.loads(
            _WEIGHTS_FILE.read_text(encoding="utf-8")
        )
        for ft in fix_types:
            if ft in weights:
                weights[ft][_RISK_FLAG_KEY] = True
            else:
                weights[ft] = {_RISK_FLAG_KEY: True}
        _WEIGHTS_FILE.write_text(
            json.dumps(weights, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(
            f"  🚩 RollbackGuard: flagged risk_flag=true for {fix_types}",
            file=sys.stderr,
        )
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  ⚠ RollbackGuard: could not update weights: {exc}", file=sys.stderr)


def is_risk_flagged(fix_type: str) -> bool:
    """Return True if *fix_type* has been flagged as risky by the rollback guard."""
    if not _WEIGHTS_FILE.exists():
        return False
    try:
        weights: Dict[str, Any] = json.loads(
            _WEIGHTS_FILE.read_text(encoding="utf-8")
        )
        return bool(weights.get(fix_type, {}).get(_RISK_FLAG_KEY, False))
    except (OSError, json.JSONDecodeError):
        return False
