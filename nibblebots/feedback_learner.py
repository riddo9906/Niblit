#!/usr/bin/env python3
"""
nibblebots/feedback_learner.py — Phase 3 Feedback Learning Loop

Records the outcome of each evolution commit and feeds the results back into
the impact_engine's weight model so future runs make better decisions.

This closes the loop:

    Fix applied → Commit pushed → CI runs → Outcome observed
                        ↓
              feedback_learner.record_outcome()
                        ↓
              impact_engine.update_weights()
                        ↓
               Better fix selection next run

Outcome journal
---------------
Every recorded outcome is appended to a JSON-lines file
(outcome_journal.jsonl, next to this script) so you can inspect the full
history of what the agent did and what happened.

Automatic outcome detection
----------------------------
``fetch_ci_outcome()`` queries the GitHub Actions API to compare the most
recent two completed workflow runs (before/after the evolution commit) and
derives a signal from:

  • test failure count
  • overall success/failure status

This is Phase 3's "impact validation" — the system checks whether its fix
actually improved things, not just whether it compiled.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

from nibblebots import impact_engine


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_JOURNAL_FILE = Path(__file__).parent / "outcome_journal.jsonl"

# ---------------------------------------------------------------------------
# GitHub API helpers (same pattern as autonomous_evolution_agent.py)
# ---------------------------------------------------------------------------

_API_BASE = "https://api.github.com"
_TOKEN = os.environ.get("GITHUB_TOKEN", "")
_REPO = os.environ.get("GITHUB_REPOSITORY", "")


def _gh_get(path: str) -> Any:
    """GET from GitHub REST API v3.  Returns parsed JSON or None."""
    url = f"{_API_BASE}{path}" if not path.startswith("http") else path
    if not url.startswith(_API_BASE):
        print(f"  ⚠ _gh_get: rejected non-GitHub URL: {url!r}", file=sys.stderr)
        return None
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Niblit-Evolution-Agent/3.0",
    }
    if _TOKEN:
        headers["Authorization"] = f"Bearer {_TOKEN}"
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=15) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
    except URLError as exc:
        print(f"  ⚠ GitHub API network error: {exc}", file=sys.stderr)
        return None
    except OSError as exc:
        print(f"  ⚠ GitHub API OS error: {exc}", file=sys.stderr)
        return None
    except json.JSONDecodeError as exc:
        print(f"  ⚠ GitHub API malformed JSON: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# CI outcome detection
# ---------------------------------------------------------------------------

def fetch_ci_outcome(
    fix_types: List[str],
    pre_run_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Query GitHub Actions to derive a post-commit outcome signal.

    Compares the two most recent completed runs of the test workflow.
    Returns an outcome dict compatible with impact_engine.update_weights().

    Parameters
    ----------
    fix_types   : list of fix types applied in this evolution commit
    pre_run_id  : workflow run ID that existed BEFORE the commit (optional);
                  when provided, we compare that run's result to the latest.
    """
    outcome: Dict[str, Any] = {
        "tests_passed": None,
        "error_count_change": 0,
        "ci_failure_change": 0,
        "runtime_stable": None,
        "source": "github_actions",
    }

    if not _TOKEN or not _REPO:
        outcome["source"] = "unavailable"
        return outcome

    data = _gh_get(
        f"/repos/{_REPO}/actions/runs"
        f"?status=completed&per_page=10"
    )
    if not data or "workflow_runs" not in data:
        outcome["source"] = "api_error"
        return outcome

    runs = data["workflow_runs"]
    if len(runs) < 2:
        outcome["source"] = "insufficient_history"
        return outcome

    # Latest run = after commit; previous run = before commit
    latest = runs[0]
    previous = runs[1] if pre_run_id is None else next(
        (r for r in runs if r["id"] == pre_run_id), runs[1]
    )

    latest_ok = latest.get("conclusion") == "success"
    previous_ok = previous.get("conclusion") == "success"

    outcome["tests_passed"] = latest_ok
    outcome["runtime_stable"] = latest_ok

    # ci_failure_change: negative means fewer failures (good)
    if latest_ok and not previous_ok:
        outcome["ci_failure_change"] = -1
    elif not latest_ok and previous_ok:
        outcome["ci_failure_change"] = +1
    else:
        outcome["ci_failure_change"] = 0

    return outcome


# ---------------------------------------------------------------------------
# Outcome recording
# ---------------------------------------------------------------------------

def record_outcome(
    fix_types: List[str],
    fixed_files: List[str],
    total_instances: int,
    commit_sha: str = "",
    outcome: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Record the outcome of an evolution commit and update impact weights.

    Parameters
    ----------
    fix_types        : list of fix types that were applied
    fixed_files      : list of relative file paths that were changed
    total_instances  : total number of instances fixed
    commit_sha       : git SHA of the evolution commit (if known)
    outcome          : pre-computed outcome dict; if None, fetched from CI API

    Returns the outcome dict that was recorded.
    """
    if outcome is None:
        print("  🔍 Fetching CI outcome from GitHub Actions...")
        outcome = fetch_ci_outcome(fix_types)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "commit_sha": commit_sha,
        "fix_types": fix_types,
        "fixed_files": fixed_files,
        "total_instances": total_instances,
        "outcome": outcome,
    }

    # Append to journal
    try:
        with _JOURNAL_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError as exc:
        print(f"  ⚠ Could not write outcome journal: {exc}", file=sys.stderr)

    # Update impact weights for each fix type
    for fix_type in fix_types:
        impact_engine.update_weights(fix_type, outcome)
        _status = "✅" if outcome.get("tests_passed") else "⚠"
        print(
            f"  {_status} Outcome recorded for {fix_type}: "
            f"tests={'pass' if outcome.get('tests_passed') else 'fail/unknown'}, "
            f"ci_delta={outcome.get('ci_failure_change', 0):+d}"
        )

    return outcome


# ---------------------------------------------------------------------------
# Journal reader (for inspection / meta-engine integration)
# ---------------------------------------------------------------------------

def read_journal(last_n: int = 20) -> List[Dict[str, Any]]:
    """Return the last *n* outcome journal entries."""
    if not _JOURNAL_FILE.exists():
        return []
    try:
        lines = _JOURNAL_FILE.read_text(encoding="utf-8").splitlines()
        entries = []
        for line in lines:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return entries[-last_n:]
    except OSError:
        return []


def journal_summary() -> Dict[str, Any]:
    """Return aggregate stats from the outcome journal."""
    entries = read_journal(last_n=100)
    if not entries:
        return {"total_commits": 0}

    total = len(entries)
    passed = sum(
        1 for e in entries
        if e.get("outcome", {}).get("tests_passed") is True
    )
    fix_type_counts: dict = {}
    for e in entries:
        for ft in e.get("fix_types", []):
            fix_type_counts[ft] = fix_type_counts.get(ft, 0) + 1

    return {
        "total_commits": total,
        "pass_rate": round(passed / total, 3) if total else 0.0,
        "fix_type_counts": fix_type_counts,
        "latest_timestamp": entries[-1].get("timestamp", ""),
    }
