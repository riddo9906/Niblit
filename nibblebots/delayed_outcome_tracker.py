#!/usr/bin/env python3
"""
nibblebots/delayed_outcome_tracker.py — Phase 7 Delayed Outcome Tracking

Some code changes don't reveal their impact immediately.  A change that
introduces a subtle logical bug may pass the next CI run but accumulate
failures over 5 or 20 subsequent runs.  This module tracks the *delayed*
impact of every evolution commit across multiple time horizons and feeds
corrected outcome signals back into the regression model.

Tracking horizons
-----------------
Each commit is tracked at three horizons:

    H1  :  1 run  after the commit  (immediate signal — already in Phase 4)
    H5  :  5 runs after the commit  (short-term trend)
    H20 : 20 runs after the commit  (long-term stability)

For each horizon the tracker records:
    * CI pass/fail counts
    * cumulative failure delta relative to H0 (before commit)

Corrected regression signal
---------------------------
When a horizon record matures, ``get_corrected_entries()`` returns the
commit's full outcome history enriched with a ``delayed_delta`` field.
The impact engine's regression model uses this field (when present) in
preference to the immediate ``ci_failure_change`` to get a more accurate
picture of long-term impact.

Persistence
-----------
State is stored in ``delayed_outcomes.jsonl`` (one line per tracked commit)
next to this file.  On each ``record_run()`` call the tracker:
1. Appends the new run result to each open (un-matured) commit record
2. Marks horizon records as matured when enough runs have been observed
3. Rewrites the file (replacing matured horizons with their final values)

Constants
---------
HORIZONS          : tuple of ints  (default: (1, 5, 20))
MAX_TRACKED       : int  max open commit records (default: 50)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HORIZONS: Tuple[int, ...] = (1, 5, 20)
MAX_TRACKED: int = 50

_DELAYED_FILE = Path(__file__).parent / "delayed_outcomes.jsonl"


# ---------------------------------------------------------------------------
# Internal record structure (stored as a JSON dict per line)
# ---------------------------------------------------------------------------
# {
#   "commit_sha": str,
#   "fix_types": [str],
#   "impact_net_score": float | null,
#   "registered_at": iso-timestamp,
#   "h0_failures": int,            # failure count at registration time
#   "runs_since": int,             # runs observed since the commit
#   "run_results": [bool],         # True = passed, for each run observed
#   "horizons": {                  # keyed by str(horizon_n)
#     "1":  {"matured": bool, "pass_count": int, "fail_count": int, "delta": int | null},
#     "5":  {...},
#     "20": {...},
#   }
# }


def _new_record(
    commit_sha: str,
    fix_types: List[str],
    h0_failures: int = 0,
    impact_net_score: Optional[float] = None,
) -> Dict[str, Any]:
    return {
        "commit_sha": commit_sha,
        "fix_types": fix_types,
        "impact_net_score": impact_net_score,
        "registered_at": datetime.now(timezone.utc).isoformat(),
        "h0_failures": h0_failures,
        "runs_since": 0,
        "run_results": [],
        "horizons": {
            str(h): {"matured": False, "pass_count": 0, "fail_count": 0, "delta": None}
            for h in HORIZONS
        },
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _load_records() -> List[Dict[str, Any]]:
    if not _DELAYED_FILE.exists():
        return []
    records: List[Dict[str, Any]] = []
    try:
        for line in _DELAYED_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except OSError:
        pass
    return records


def _save_records(records: List[Dict[str, Any]]) -> None:
    # Keep only the most recent MAX_TRACKED records
    records = records[-MAX_TRACKED:]
    try:
        lines = [json.dumps(r) for r in records]
        _DELAYED_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Horizon updating
# ---------------------------------------------------------------------------

def _update_horizons(record: Dict[str, Any]) -> None:
    """Update horizon maturity for a single record based on runs_since."""
    runs: int = record["runs_since"]
    results: List[bool] = record["run_results"]
    h0: int = record.get("h0_failures", 0)

    for h in HORIZONS:
        h_key = str(h)
        horizon = record["horizons"][h_key]
        if horizon["matured"]:
            continue
        if runs < h:
            continue
        # Enough runs have elapsed — compute horizon statistics
        window = results[:h]
        pass_count = sum(1 for r in window if r)
        fail_count = sum(1 for r in window if not r)
        delta = fail_count - h0 * (h / max(len(results), 1))  # rough normalisation
        horizon["pass_count"] = pass_count
        horizon["fail_count"] = fail_count
        horizon["delta"] = round(delta, 2)
        horizon["matured"] = True


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def register_commit(
    commit_sha: str,
    fix_types: List[str],
    h0_failures: int = 0,
    impact_net_score: Optional[float] = None,
) -> None:
    """Register a new evolution commit for delayed outcome tracking.

    Parameters
    ----------
    commit_sha       : git SHA of the commit
    fix_types        : fix types applied
    h0_failures      : failure count at registration (before this commit)
    impact_net_score : planned net_score for regression correlation
    """
    records = _load_records()

    # Avoid duplicates
    if any(r.get("commit_sha") == commit_sha for r in records):
        return

    records.append(_new_record(commit_sha, fix_types, h0_failures, impact_net_score))
    _save_records(records)


def record_run(ci_passed: bool) -> None:
    """Record the result of one CI run across all open commit records.

    Call this once after each CI completion (in the workflow).  All
    commit records that have not yet matured all horizons are updated.

    Parameters
    ----------
    ci_passed : True if the run passed, False if it failed
    """
    records = _load_records()
    changed = False

    for record in records:
        # Skip fully matured records
        if all(h["matured"] for h in record["horizons"].values()):
            continue
        record["run_results"].append(ci_passed)
        record["runs_since"] = record.get("runs_since", 0) + 1
        _update_horizons(record)
        changed = True

    if changed:
        _save_records(records)


def get_corrected_entries(
    min_horizon: int = 5,
) -> List[Dict[str, Any]]:
    """Return matured commit records enriched with delayed outcome signals.

    Parameters
    ----------
    min_horizon : minimum horizon that must have matured for a record
                  to be included (default: 5)

    Returns a list of dicts suitable for use as regression training entries::

        {
          "commit_sha": str,
          "fix_types": [str],
          "impact_net_score": float | None,
          "delayed_delta": float,   # negative = improvement, positive = regression
          "horizon": int,           # the horizon at which delta was measured
        }
    """
    records = _load_records()
    corrected: List[Dict[str, Any]] = []

    for record in records:
        h_key = str(min_horizon)
        if h_key not in record["horizons"]:
            continue
        horizon_data = record["horizons"][h_key]
        if not horizon_data.get("matured"):
            continue
        delta = horizon_data.get("delta")
        if delta is None:
            continue
        corrected.append({
            "commit_sha": record.get("commit_sha", ""),
            "fix_types": record.get("fix_types", []),
            "impact_net_score": record.get("impact_net_score"),
            "delayed_delta": delta,
            "horizon": min_horizon,
        })

    return corrected


def pending_count() -> int:
    """Return the number of commits still waiting for horizon maturation."""
    records = _load_records()
    return sum(
        1 for r in records
        if not all(h.get("matured") for h in r.get("horizons", {}).values())
    )


def summary() -> Dict[str, Any]:
    """Return a human-readable summary of the delayed outcome tracker."""
    records = _load_records()
    total = len(records)
    pending = pending_count()
    matured_h5 = sum(
        1 for r in records
        if r.get("horizons", {}).get("5", {}).get("matured")
    )
    matured_h20 = sum(
        1 for r in records
        if r.get("horizons", {}).get("20", {}).get("matured")
    )
    return {
        "total_tracked": total,
        "pending_maturation": pending,
        "matured_h5": matured_h5,
        "matured_h20": matured_h20,
    }
