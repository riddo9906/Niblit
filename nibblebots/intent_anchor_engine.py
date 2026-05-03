#!/usr/bin/env python3
"""
nibblebots/intent_anchor_engine.py — Phase 8.5 Intent Anchor Engine

Prevents *slow-drift goal loss*: the failure mode where the system stays
contextually coherent step-by-step but gradually wanders away from its
original purpose.

Problem
-------
context_guard.py protects against *sudden* context misbinding (short-term).
But it cannot catch gradual drift where every individual step looks aligned
with the previous one yet the aggregate trajectory has moved far from the
original goal.

Example drift sequence (all steps look locally aligned):
  1. Goal: improve_trading_profitability
  2. Fixes: trading strategy  ✅
  3. Fixes: trading logging   ✅ (still trading)
  4. Fixes: generic logging   ⚠  (adjacent)
  5. Fixes: whitespace        ❌ (goal lost but no spike detected)

Solution
--------
The engine maintains a persistent *intent anchor* — a goal signature made up
of a primary goal string, target subsystems, and key vocabulary.  Every time
evolution_planner scores a potential fix it asks the anchor engine for an
*alignment score* [0, 1].  Low-alignment fixes are penalised (not blocked),
preserving the system's ability to do essential maintenance while discouraging
pointless drift.

Drift detection uses a rolling window of per-fix alignment scores; when the
window mean drops below ``_DRIFT_THRESHOLD`` the engine publishes
``EVENT_INTENT_DRIFT`` and reduces ``effective_max_fixes``.

Public API
----------
``set_anchor(goal, keywords, subsystems)``
    Define (or redefine) the current intent anchor.  Called at the start of
    each evolution cycle or when the objective engine updates the goal.

``score_alignment(fix_type, subsystem, context_hint)``
    Return [0, 1] alignment of a single proposed fix with the anchor.

``update(fix_type, subsystem, context_hint)``
    Record an alignment observation into the rolling window.  Call after
    scoring each fix in build_plan().

``check_drift() → Optional[str]``
    Return ``"intent_drift"`` if rolling mean < ``_DRIFT_THRESHOLD``, else None.

``get_rolling_score() → float``
    Current rolling mean alignment (for diagnostics).

``status() → dict``
    Diagnostic snapshot.

State
-----
intent_anchor_state.json  — persisted anchor and rolling window
intent_anchor_log.jsonl   — audit trail of drift events

Constants (overridable via env vars)
-------------------------------------
INTENT_DRIFT_WINDOW     : int   (env: INTENT_DRIFT_WINDOW, default 10)
                          Rolling window size for alignment tracking.
INTENT_DRIFT_THRESHOLD  : float (env: INTENT_DRIFT_THRESHOLD, default 0.40)
                          Rolling alignment below this → drift alarm.
INTENT_ALIGNMENT_PENALTY: float (env: INTENT_ALIGNMENT_PENALTY, default 0.25)
                          Confidence multiplier subtracted for low-alignment fixes.
"""

from __future__ import annotations

import json
import logging
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

INTENT_DRIFT_WINDOW: int = int(os.environ.get("INTENT_DRIFT_WINDOW", "10"))
INTENT_DRIFT_THRESHOLD: float = float(
    os.environ.get("INTENT_DRIFT_THRESHOLD", "0.40")
)
INTENT_ALIGNMENT_PENALTY: float = float(
    os.environ.get("INTENT_ALIGNMENT_PENALTY", "0.25")
)

_STATE_FILE = Path(__file__).parent / "intent_anchor_state.json"
_LOG_FILE = Path(__file__).parent / "intent_anchor_log.jsonl"

# Subsystem-to-goal affinity map: which subsystems are relevant for each goal
_GOAL_SUBSYSTEMS: Dict[str, List[str]] = {
    "stability":     ["testing", "ci", "error_handling", "logging"],
    "profitability": ["trading", "decision", "strategy", "risk"],
    "learning":      ["learning", "research", "knowledge", "meta"],
}

# Default keywords per goal (supplements user-supplied keywords)
_GOAL_KEYWORDS: Dict[str, List[str]] = {
    "stability":     ["test", "error", "exception", "fix", "stable", "reliable"],
    "profitability": ["trading", "profit", "win", "risk", "strategy", "signal"],
    "learning":      ["learn", "knowledge", "research", "train", "adapt"],
}

# Stop-words excluded from keyword matching (too generic to signal intent)
_STOP_WORDS = frozenset({
    "a", "an", "the", "in", "of", "to", "and", "or", "for",
    "is", "it", "on", "at", "by", "with", "as", "be", "was",
    "file", "line", "code", "python", "function", "class", "module",
})


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def _load_state() -> Dict[str, Any]:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "goal": "stability",
        "keywords": _GOAL_KEYWORDS.get("stability", []),
        "subsystems": _GOAL_SUBSYSTEMS.get("stability", []),
        "rolling_window": [],
        "drift_count": 0,
        "total_observations": 0,
    }


def _save_state(state: Dict[str, Any]) -> None:
    try:
        _STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        pass


def _log_event(event_type: str, payload: Dict[str, Any]) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        **payload,
    }
    try:
        with _LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Tokenisation helper (shared with context_guard pattern)
# ---------------------------------------------------------------------------

def _tokenise(text: str) -> List[str]:
    return [
        w.lower()
        for w in text.replace("_", " ").split()
        if w.lower() not in _STOP_WORDS and len(w) > 1
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def set_anchor(
    goal: str,
    keywords: Optional[List[str]] = None,
    subsystems: Optional[List[str]] = None,
) -> None:
    """Define (or redefine) the current intent anchor.

    Parameters
    ----------
    goal       : primary goal string (e.g. "stability", "profitability")
    keywords   : extra vocabulary that signals intent alignment
    subsystems : target subsystem names aligned with this goal
    """
    # Merge user-supplied with built-in defaults for the goal
    merged_kws = list(_GOAL_KEYWORDS.get(goal, []))
    if keywords:
        for kw in keywords:
            if kw not in merged_kws:
                merged_kws.append(kw)

    merged_subs = list(_GOAL_SUBSYSTEMS.get(goal, []))
    if subsystems:
        for sub in subsystems:
            if sub not in merged_subs:
                merged_subs.append(sub)

    state = _load_state()
    old_goal = state.get("goal", "stability")

    state["goal"] = goal
    state["keywords"] = merged_kws
    state["subsystems"] = merged_subs
    # Reset rolling window on explicit anchor change (clean slate)
    state["rolling_window"] = []

    _save_state(state)

    if old_goal != goal:
        _log_event("anchor_set", {"old_goal": old_goal, "new_goal": goal,
                                   "keywords": merged_kws,
                                   "subsystems": merged_subs})
        log.info("[intent_anchor] anchor updated: %s → %s", old_goal, goal)


def score_alignment(
    fix_type: str,
    subsystem: str,
    context_hint: str = "",
) -> float:
    """Return alignment score [0, 1] for a proposed fix vs the anchor.

    Scoring breakdown:
      • +0.50 if subsystem is in anchor subsystems
      • +0.50 keyword overlap between (fix_type + context_hint) and anchor keywords

    Parameters
    ----------
    fix_type     : fix_type from SemanticIssue (e.g. "bare_except")
    subsystem    : subsystem from SemanticIssue (e.g. "error_handling")
    context_hint : additional free-form description (e.g. module path)
    """
    state = _load_state()
    anchor_subs = set(state.get("subsystems", []))
    anchor_kws = set(_tokenise(" ".join(state.get("keywords", []))))

    score = 0.0

    # Subsystem component (50%)
    if subsystem in anchor_subs:
        score += 0.50
    else:
        # Partial credit for adjacent subsystems (prefix match)
        for s in anchor_subs:
            if s in subsystem or subsystem in s:
                score += 0.20
                break

    # Keyword component (50%)
    if anchor_kws:
        fix_tokens = set(_tokenise(f"{fix_type} {subsystem} {context_hint}"))
        overlap = len(fix_tokens & anchor_kws)
        # Jaccard-style: overlap / union
        union = len(fix_tokens | anchor_kws)
        kw_score = overlap / max(union, 1)
        # Scale to the [0, 0.5] range
        score += min(0.50, kw_score * 2.0)

    return round(min(1.0, max(0.0, score)), 4)


def update(
    fix_type: str,
    subsystem: str,
    context_hint: str = "",
) -> float:
    """Record an alignment observation and return the computed score.

    Called by evolution_planner for each issue considered in the plan.
    """
    alignment = score_alignment(fix_type, subsystem, context_hint)
    state = _load_state()
    window: List[float] = list(state.get("rolling_window", []))
    window.append(alignment)
    if len(window) > INTENT_DRIFT_WINDOW:
        window = window[-INTENT_DRIFT_WINDOW:]
    state["rolling_window"] = window
    state["total_observations"] = state.get("total_observations", 0) + 1
    _save_state(state)
    return alignment


def check_drift() -> Optional[str]:
    """Return ``"intent_drift"`` if the rolling alignment mean is below threshold.

    Publishes EVENT_INTENT_DRIFT on the event bus (best-effort).
    Returns None when alignment is acceptable.
    """
    state = _load_state()
    window: List[float] = state.get("rolling_window", [])
    if len(window) < max(3, INTENT_DRIFT_WINDOW // 2):
        return None   # not enough data to call drift

    rolling_mean = sum(window) / len(window)
    if rolling_mean >= INTENT_DRIFT_THRESHOLD:
        return None

    goal = state.get("goal", "stability")
    payload = {
        "rolling_alignment": round(rolling_mean, 4),
        "threshold": INTENT_DRIFT_THRESHOLD,
        "goal": goal,
        "window_size": len(window),
    }
    _log_event("intent_drift", payload)
    state["drift_count"] = state.get("drift_count", 0) + 1
    _save_state(state)

    # Publish on event bus (best-effort, no hard dependency)
    try:
        from modules.event_bus import get_event_bus, NiblitEvent, EVENT_INTENT_DRIFT  # noqa: PLC0415
        get_event_bus().publish(NiblitEvent(
            type=EVENT_INTENT_DRIFT,
            source="intent_anchor_engine",
            payload=payload,
        ))
    except Exception:  # noqa: BLE001
        pass

    log.warning(
        "[intent_anchor] drift detected: rolling_alignment=%.3f < %.3f (goal=%s)",
        rolling_mean, INTENT_DRIFT_THRESHOLD, goal,
    )
    return "intent_drift"


def get_rolling_score() -> float:
    """Return current rolling mean alignment score (0–1), or 1.0 when no data."""
    state = _load_state()
    window: List[float] = state.get("rolling_window", [])
    if not window:
        return 1.0
    return round(sum(window) / len(window), 4)


def status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the engine state."""
    state = _load_state()
    window: List[float] = state.get("rolling_window", [])
    rolling = round(sum(window) / len(window), 4) if window else 1.0
    return {
        "goal": state.get("goal", "stability"),
        "keywords": state.get("keywords", []),
        "subsystems": state.get("subsystems", []),
        "rolling_alignment": rolling,
        "drift_threshold": INTENT_DRIFT_THRESHOLD,
        "is_drifting": rolling < INTENT_DRIFT_THRESHOLD and len(window) >= 3,
        "drift_count": state.get("drift_count", 0),
        "total_observations": state.get("total_observations", 0),
        "window_size": len(window),
    }
