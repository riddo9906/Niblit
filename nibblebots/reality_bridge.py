#!/usr/bin/env python3
"""
nibblebots/reality_bridge.py — Phase 8 Reality Bridge

Connects the evolution engine to real-world performance signals.

The bridge aggregates metrics from three sources into a single
``RealitySnapshot`` dict that the ``ObjectiveEngine`` and ``ValueEngine``
can score:

1. **Trading signals** — pulled from the evolution outcome journal and the
   trade_kb_learner data file (``niblit_trade_knowledge.json``).
   Derives: ``profit_delta``, ``win_rate``, ``drawdown``.

2. **CI / test signals** — pulled from the outcome journal.
   Derives: ``pass_rate``, ``ci_failure_trend``.

3. **Runtime signals** — pulled from ``system_health_monitor`` snapshots
   stored in ``system_health_log.jsonl`` when that module writes them.
   Derives: ``runtime_score`` from error_rate, memory_pressure, response_quality.

When a signal source is unavailable the bridge uses a conservative default
so the objective scorer degrades gracefully rather than crashing.

State
-----
The most recent snapshot is cached in ``reality_snapshot_cache.json`` so the
value engine can compare before/after without requiring both snapshots to be
computed in the same process invocation.

Constants (overridable via env vars)
-------------------------------------
REALITY_JOURNAL_WINDOW  : int  (env: REALITY_JOURNAL_WINDOW, default 20)
                          Number of most-recent journal entries to aggregate.
REALITY_TRADE_WINDOW    : int  (env: REALITY_TRADE_WINDOW, default 50)
                          Number of trade KB entries to consider.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

REALITY_JOURNAL_WINDOW: int = int(os.environ.get("REALITY_JOURNAL_WINDOW", "20"))
REALITY_TRADE_WINDOW: int = int(os.environ.get("REALITY_TRADE_WINDOW", "50"))

_JOURNAL_FILE = Path(__file__).parent / "outcome_journal.jsonl"
_TRADE_KB_FILE = Path(__file__).parent.parent / "niblit_trade_knowledge.json"
_HEALTH_LOG = Path(__file__).parent / "system_health_log.jsonl"
_CACHE_FILE = Path(__file__).parent / "reality_snapshot_cache.json"


# ---------------------------------------------------------------------------
# RealitySnapshot keys (documentation)
# ---------------------------------------------------------------------------
# pass_rate         : float 0–1   fraction of recent CI runs that passed
# ci_failure_trend  : float -1–1  slope of pass_rate over time (positive = improving)
# runtime_score     : float 0–1   normalised runtime quality
# real_world_score  : float 0–1   trading / outcome quality
# win_rate          : float 0–1   trading win rate (None when unavailable)
# profit_delta      : float       normalised P&L delta (None when unavailable)
# drawdown          : float 0–1   max drawdown (0 = none, 1 = full loss)
# n_journal_entries : int         how many journal entries were used


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _read_journal(last_n: int = REALITY_JOURNAL_WINDOW) -> List[Dict[str, Any]]:
    if not _JOURNAL_FILE.exists():
        return []
    lines = []
    try:
        lines = [
            json.loads(ln)
            for ln in _JOURNAL_FILE.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
    except (OSError, json.JSONDecodeError):
        pass
    return lines[-last_n:]


def _read_trade_kb() -> List[Dict[str, Any]]:
    if not _TRADE_KB_FILE.exists():
        return []
    try:
        data = json.loads(_TRADE_KB_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data[-REALITY_TRADE_WINDOW:]
        if isinstance(data, dict):
            # Flatten dict values which may be lists of entries
            entries: List[Dict[str, Any]] = []
            for v in data.values():
                if isinstance(v, list):
                    entries.extend(v)
                elif isinstance(v, dict):
                    entries.append(v)
            return entries[-REALITY_TRADE_WINDOW:]
    except (OSError, json.JSONDecodeError):
        pass
    return []


def _read_health_log(last_n: int = 10) -> List[Dict[str, Any]]:
    if not _HEALTH_LOG.exists():
        return []
    try:
        lines = [
            json.loads(ln)
            for ln in _HEALTH_LOG.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        return lines[-last_n:]
    except (OSError, json.JSONDecodeError):
        return []


# ---------------------------------------------------------------------------
# CI / outcome signal derivation
# ---------------------------------------------------------------------------

def _ci_signals(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not entries:
        return {"pass_rate": 0.8, "ci_failure_trend": 0.0}

    passed = [
        1.0 if e.get("outcome", {}).get("tests_passed") else 0.0
        for e in entries
    ]
    pass_rate = sum(passed) / len(passed)

    # Trend: compare first half vs second half
    mid = max(1, len(passed) // 2)
    first_half = sum(passed[:mid]) / mid
    second_half = sum(passed[mid:]) / max(len(passed) - mid, 1)
    trend = round(second_half - first_half, 4)   # positive = improving

    return {"pass_rate": round(pass_rate, 4), "ci_failure_trend": trend}


# ---------------------------------------------------------------------------
# Trading signal derivation
# ---------------------------------------------------------------------------

def _trading_signals(trade_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not trade_entries:
        return {"win_rate": None, "profit_delta": None, "drawdown": 0.0,
                "real_world_score": 0.5}

    wins = 0
    total = 0
    profit_vals: List[float] = []
    drawdown_vals: List[float] = []

    for e in trade_entries:
        outcome = e.get("outcome", e.get("result", ""))
        if isinstance(outcome, str):
            if outcome.lower() in ("win", "profit", "long_win", "short_win"):
                wins += 1
                total += 1
            elif outcome.lower() in ("loss", "lose", "long_loss", "short_loss"):
                total += 1
        elif isinstance(outcome, (int, float)):
            total += 1
            if outcome > 0:
                wins += 1
            profit_vals.append(float(outcome))

        dd = e.get("drawdown", e.get("max_drawdown", 0.0))
        if isinstance(dd, (int, float)) and dd >= 0:
            drawdown_vals.append(float(dd))

        profit = e.get("profit", e.get("pnl", e.get("profit_loss")))
        if isinstance(profit, (int, float)):
            profit_vals.append(float(profit))

    win_rate = (wins / total) if total > 0 else None

    # Normalised profit delta: tanh so large swings don't dominate
    import math
    if profit_vals:
        mean_profit = sum(profit_vals) / len(profit_vals)
        # Map [-∞, +∞] → [0, 1] using tanh
        profit_delta = round((math.tanh(mean_profit) + 1.0) / 2.0, 4)
    else:
        profit_delta = None

    drawdown = round(min(1.0, max(0.0,
        sum(drawdown_vals) / len(drawdown_vals)
    )) if drawdown_vals else 0.0, 4)

    # Composite real-world score
    parts = []
    if win_rate is not None:
        parts.append(win_rate)
    if profit_delta is not None:
        parts.append(profit_delta)
    if drawdown_vals:
        parts.append(1.0 - drawdown)   # low drawdown is good

    real_world_score = round(sum(parts) / max(len(parts), 1), 4) if parts else 0.5

    return {
        "win_rate": round(win_rate, 4) if win_rate is not None else None,
        "profit_delta": profit_delta,
        "drawdown": drawdown,
        "real_world_score": real_world_score,
    }


# ---------------------------------------------------------------------------
# Runtime signal derivation
# ---------------------------------------------------------------------------

def _runtime_signals(health_entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not health_entries:
        return {"runtime_score": 0.7}

    scores = []
    for snap in health_entries:
        error_rate = float(snap.get("error_rate", 0.1))
        memory_pressure = float(snap.get("memory_pressure", 0.3))
        response_quality = float(snap.get("response_quality", 0.7))
        learning_velocity = float(snap.get("learning_velocity", 0.5))

        # Runtime score: high quality, low error, low memory pressure
        s = (
            response_quality * 0.40
            + (1.0 - min(1.0, error_rate)) * 0.30
            + (1.0 - min(1.0, memory_pressure)) * 0.15
            + learning_velocity * 0.15
        )
        scores.append(min(1.0, max(0.0, s)))

    return {"runtime_score": round(sum(scores) / len(scores), 4)}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def pull_snapshot() -> Dict[str, Any]:
    """Build and return a fresh RealitySnapshot.

    Reads from outcome journal, trade KB, and health log.  Any missing
    source degrades gracefully to conservative defaults.
    """
    journal_entries = _read_journal()
    trade_entries = _read_trade_kb()
    health_entries = _read_health_log()

    ci = _ci_signals(journal_entries)
    trading = _trading_signals(trade_entries)
    runtime = _runtime_signals(health_entries)

    snapshot: Dict[str, Any] = {
        **ci,
        **trading,
        **runtime,
        "n_journal_entries": len(journal_entries),
    }

    # Cache for before/after comparison
    _cache_snapshot(snapshot)
    return snapshot


def get_cached_snapshot() -> Optional[Dict[str, Any]]:
    """Return the most recently cached snapshot without recomputing."""
    if not _CACHE_FILE.exists():
        return None
    try:
        return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _cache_snapshot(snapshot: Dict[str, Any]) -> None:
    try:
        _CACHE_FILE.write_text(
            json.dumps(snapshot, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def inject_snapshot(snapshot: Dict[str, Any]) -> None:
    """Directly inject a snapshot (used in tests and by other subsystems)."""
    _cache_snapshot(snapshot)
