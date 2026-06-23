#!/usr/bin/env python3
"""
nibblebots/confidence_decay.py — Phase 7 Confidence Decay

Applies time-based decay to fix-type weights in impact_weights.json so that
knowledge about fix types that haven't been validated recently loses authority.
This prevents the impact engine from acting on stale priors when the codebase
has evolved.

Decay model
-----------
For each fix type, the engine tracks the last time that fix type appeared in a
successful outcome journal entry (``last_validated`` timestamp).  On each call
to ``apply_decay()``, dimensions whose last validation is older than
``DECAY_HALF_LIFE_DAYS`` are multiplied by a decay factor:

    factor = exp(-ln(2) * days_since_validation / DECAY_HALF_LIFE_DAYS)

This is a standard exponential half-life model.  A fix type that hasn't been
validated for exactly ``DECAY_HALF_LIFE_DAYS`` days retains 50% of its weight.

The ``risk_`` dimension weights decay in the opposite direction (they *increase*
when a fix type hasn't been validated recently — unknown territory is riskier).

The ``risk_flag`` key is never modified.

Constants (all overridable via environment variables)
-----------------------------------------------------
DECAY_HALF_LIFE_DAYS  : float  (env: EVOLUTION_DECAY_HALF_LIFE, default 14)
DECAY_MIN_FACTOR      : float  (env: EVOLUTION_DECAY_MIN, default 0.20)
                        Floor on how far any dimension can decay.
DECAY_MAX_RISK_FACTOR : float  (env: EVOLUTION_DECAY_MAX_RISK, default 2.0)
                        Ceiling on how far risk dimensions can inflate.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DECAY_HALF_LIFE_DAYS: float = float(
    os.environ.get("EVOLUTION_DECAY_HALF_LIFE", "14")
)
DECAY_MIN_FACTOR: float = float(os.environ.get("EVOLUTION_DECAY_MIN", "0.20"))
DECAY_MAX_RISK_FACTOR: float = float(
    os.environ.get("EVOLUTION_DECAY_MAX_RISK", "2.0")
)

_LN2: float = math.log(2.0)

_WEIGHTS_FILE = Path(__file__).parent / "impact_weights.json"
_DECAY_STATE_FILE = Path(__file__).parent / "confidence_decay_state.json"


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def _load_decay_state() -> Dict[str, Any]:
    """Load persisted decay state (last_validated timestamps per fix type)."""
    if _DECAY_STATE_FILE.exists():
        try:
            return json.loads(_DECAY_STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"last_validated": {}, "last_decay_applied": ""}


def _save_decay_state(state: Dict[str, Any]) -> None:
    try:
        _DECAY_STATE_FILE.write_text(
            json.dumps(state, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Decay factor computation
# ---------------------------------------------------------------------------

def _decay_factor(days_since: float) -> float:
    """Return exponential decay factor for a given age in days.

    factor = exp(-ln2 * days_since / half_life)
    Clamped to [DECAY_MIN_FACTOR, 1.0].
    """
    if days_since <= 0:
        return 1.0
    factor = math.exp(-_LN2 * days_since / DECAY_HALF_LIFE_DAYS)
    return max(DECAY_MIN_FACTOR, factor)


def _risk_inflate_factor(days_since: float) -> float:
    """Return risk-inflation factor for dimensions that haven't been validated.

    Older = riskier.  The factor grows from 1.0 towards DECAY_MAX_RISK_FACTOR
    over one half-life.
    """
    if days_since <= 0:
        return 1.0
    # Linear growth capped at DECAY_MAX_RISK_FACTOR
    raw = 1.0 + (days_since / DECAY_HALF_LIFE_DAYS)
    return min(DECAY_MAX_RISK_FACTOR, raw)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def mark_validated(fix_types: List[str]) -> None:
    """Record that *fix_types* were validated successfully right now.

    Call this in feedback_learner.record_outcome() when tests pass.

    Parameters
    ----------
    fix_types : list of fix type strings that were just validated
    """
    state = _load_decay_state()
    now_iso = datetime.now(timezone.utc).isoformat()
    for ft in fix_types:
        state["last_validated"][ft] = now_iso
    _save_decay_state(state)


def apply_decay(dry_run: bool = False) -> Dict[str, float]:
    """Apply time-based decay to impact_weights.json.

    Reads the current weights, computes the decay factor for each fix type
    based on how long ago it was last validated, then multiplies gain
    dimensions by the decay factor and inflates risk dimensions.

    Parameters
    ----------
    dry_run : when True, return the would-be factors without modifying files

    Returns a dict of fix_type → applied decay factor (for logging).
    """
    if not _WEIGHTS_FILE.exists():
        return {}

    try:
        weights: Dict[str, Any] = json.loads(
            _WEIGHTS_FILE.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return {}

    state = _load_decay_state()
    last_validated: Dict[str, str] = state.get("last_validated", {})
    now = datetime.now(timezone.utc)

    applied_factors: Dict[str, float] = {}

    for fix_type, dims in weights.items():
        if not isinstance(dims, dict):
            continue
        last_ts = last_validated.get(fix_type)
        if last_ts:
            try:
                last_dt = datetime.fromisoformat(last_ts)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                days_since = (now - last_dt).total_seconds() / 86_400
            except ValueError:
                days_since = DECAY_HALF_LIFE_DAYS  # unknown → apply half decay
        else:
            days_since = DECAY_HALF_LIFE_DAYS  # never validated → apply half decay

        gain_factor = _decay_factor(days_since)
        risk_factor = _risk_inflate_factor(days_since)
        applied_factors[fix_type] = round(gain_factor, 4)

        if dry_run:
            continue

        for dim in list(dims.keys()):
            if dim == "risk_flag":
                continue
            val = dims[dim]
            if not isinstance(val, (int, float)):
                continue
            if dim.startswith("risk_"):
                # Risk inflates when stale — but only up to the ceiling
                new_val = min(DECAY_MAX_RISK_FACTOR, val * risk_factor)
            else:
                # Gain decays when stale; floor is DECAY_MIN_FACTOR
                new_val = max(DECAY_MIN_FACTOR, val * gain_factor)
            dims[dim] = round(new_val, 4)

    if not dry_run:
        try:
            _WEIGHTS_FILE.write_text(
                json.dumps(weights, indent=2, sort_keys=True), encoding="utf-8"
            )
            state["last_decay_applied"] = now.isoformat()
            _save_decay_state(state)
        except OSError:
            pass

    return applied_factors


def get_staleness_report() -> Dict[str, Any]:
    """Return per-fix-type staleness (days since last validation).

    Useful for inspection / MetaEngine integration.
    """
    state = _load_decay_state()
    last_validated: Dict[str, str] = state.get("last_validated", {})
    now = datetime.now(timezone.utc)
    report: Dict[str, Any] = {}

    for fix_type, ts_str in last_validated.items():
        try:
            dt = datetime.fromisoformat(ts_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            days = (now - dt).total_seconds() / 86_400
        except ValueError:
            days = float("inf")
        factor = _decay_factor(days)
        report[fix_type] = {
            "days_since_validation": round(days, 1),
            "decay_factor": round(factor, 4),
            "stale": days > DECAY_HALF_LIFE_DAYS,
        }

    return report


if __name__ == "__main__":
    print('Running confidence_decay.py')
