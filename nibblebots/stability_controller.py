#!/usr/bin/env python3
"""
nibblebots/stability_controller.py — Phase 9 Stability Controller

Prevents the "self-oscillation" failure mode where the system thrashes
between stability and exploration modes faster than it can learn from
either.

Problem
-------
Without inertia in decision-making, a system that reacts quickly to
signal confidence changes can get stuck in a loop:

  low confidence  → switch to stability
  stability works → confidence rises
  confidence high → switch to exploration
  exploration adds noise → confidence drops
  back to stability …

The system never accumulates compounding improvements.

Solution
--------
Three complementary mechanisms:

1. **Mode locking** (minimum duration)
   Once a mode is entered, it cannot be exited until
   ``MODE_MIN_DURATION`` cycles have elapsed.

2. **Asymmetric hysteresis thresholds**
   Entering "stability" mode requires confidence to drop below
   ``CONFIDENCE_ENTER_STABILITY`` (0.45 by default).
   Exiting requires confidence to rise above
   ``CONFIDENCE_EXIT_STABILITY`` (0.65 by default).
   This creates a "dead zone" that prevents flip-flopping.

3. **Switch penalty**
   Recent mode switches accumulate a penalty that reduces the
   effective score of *any* new switch, making them progressively
   harder to trigger the more recent ones there were.

Public API
----------
``resolve_mode(proposed_mode, confidence, momentum)``
    The primary entry point.  Given a proposed mode ("exploit" /
    "explore" / "stability") and the current confidence + momentum
    values, returns the mode the system should actually use this cycle.

``record_cycle(mode, outcome_score)``
    Record the outcome of a completed cycle so the controller can
    track per-mode effectiveness and switch history.

``status()``
    Returns a dict summarising current controller state for logging.

Constants (overridable via env vars)
-------------------------------------
MODE_MIN_DURATION       : int    (env: SC_MODE_MIN_DURATION, default 5)
                          Minimum cycles before a mode can be changed.
CONFIDENCE_ENTER_STABILITY : float (env: SC_CONF_ENTER_STAB, default 0.45)
                          confidence below this triggers stability mode.
CONFIDENCE_EXIT_STABILITY  : float (env: SC_CONF_EXIT_STAB, default 0.65)
                          confidence must exceed this to leave stability mode.
SWITCH_PENALTY_DECAY    : float  (env: SC_SWITCH_DECAY, default 0.05)
                          Penalty added per recent switch.
SWITCH_WINDOW           : int    (env: SC_SWITCH_WINDOW, default 10)
                          Number of recent cycles tracked for switch penalty.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODE_MIN_DURATION: int = int(os.environ.get("SC_MODE_MIN_DURATION", "5"))
CONFIDENCE_ENTER_STABILITY: float = float(
    os.environ.get("SC_CONF_ENTER_STAB", "0.45")
)
CONFIDENCE_EXIT_STABILITY: float = float(
    os.environ.get("SC_CONF_EXIT_STAB", "0.65")
)
SWITCH_PENALTY_DECAY: float = float(os.environ.get("SC_SWITCH_DECAY", "0.05"))
SWITCH_WINDOW: int = int(os.environ.get("SC_SWITCH_WINDOW", "10"))

_STATE_FILE = Path(__file__).parent / "stability_controller_state.json"
_LOG_FILE = Path(__file__).parent / "stability_controller_log.jsonl"

# Valid mode names
_VALID_MODES = {"exploit", "explore", "stability"}


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def _load_state() -> Dict[str, Any]:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "current_mode": "exploit",
        "cycles_in_mode": 0,
        "switch_history": [],       # list of bool — True = mode changed this cycle
        "mode_outcome_history": [], # list of {"mode": str, "outcome": float}
        "previous_score": None,
    }


def _save_state(state: Dict[str, Any]) -> None:
    # Bound history lists
    state["switch_history"] = state.get("switch_history", [])[-SWITCH_WINDOW * 2:]
    state["mode_outcome_history"] = state.get("mode_outcome_history", [])[-50:]
    try:
        _STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        pass


def _log_event(event: str, details: Dict[str, Any]) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **details,
    }
    try:
        with _LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _switch_penalty(switch_history: List[bool]) -> float:
    """Compute a score penalty based on how many recent cycles had mode switches."""
    recent = switch_history[-SWITCH_WINDOW:]
    num_switches = sum(1 for s in recent if s)
    return min(0.50, num_switches * SWITCH_PENALTY_DECAY)


def _apply_confidence_gate(
    proposed_mode: str,
    current_mode: str,
    confidence: float,
) -> str:
    """Apply asymmetric hysteresis to confidence-driven mode proposals.

    If the system is currently in "stability" mode, it can only exit when
    confidence is high enough (>= CONFIDENCE_EXIT_STABILITY).

    If the system is NOT in "stability" and confidence falls below
    CONFIDENCE_ENTER_STABILITY, force "stability" regardless of proposal.
    """
    if proposed_mode == "stability":
        # Always allow entering stability (safety override)
        return "stability"

    if current_mode == "stability":
        # Only exit stability if confidence is high enough
        if confidence < CONFIDENCE_EXIT_STABILITY:
            return "stability"
        return proposed_mode

    # Not in stability — check if we need to enter it
    if confidence < CONFIDENCE_ENTER_STABILITY:
        return "stability"

    return proposed_mode


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_mode(
    proposed_mode: str,
    confidence: float = 1.0,
    momentum: float = 0.0,
) -> str:
    """Resolve the mode the system should use this cycle.

    Applies mode locking, asymmetric hysteresis, and switch penalty to
    stabilise decision-making across cycles.

    Parameters
    ----------
    proposed_mode : "exploit" | "explore" | "stability"
                    The mode the strategic_planner wants to use.
    confidence    : float [0, 1] — avg_confidence from signal_integrity_engine.
                    Lower values push toward stability.
    momentum      : float (current_score − previous_score).
                    Positive = improving; negative = declining.

    Returns
    -------
    str : the resolved mode to actually use.
    """
    if proposed_mode not in _VALID_MODES:
        proposed_mode = "exploit"

    state = _load_state()
    current_mode = state.get("current_mode", "exploit")
    cycles_in_mode: int = state.get("cycles_in_mode", 0)

    # Step 1: Apply confidence-based asymmetric hysteresis
    gated_mode = _apply_confidence_gate(proposed_mode, current_mode, confidence)

    # Step 2: Mode locking — block mode change until min duration elapsed.
    # Exception: confidence-forced "stability" is a safety override and
    # always bypasses the lock (we don't want the system stuck in explore
    # when signals are dangerously noisy).
    confidence_forced_stability = (
        gated_mode == "stability"
        and current_mode != "stability"
        and confidence < CONFIDENCE_ENTER_STABILITY
    )
    if gated_mode != current_mode:
        if cycles_in_mode < MODE_MIN_DURATION and not confidence_forced_stability:
            # Block the switch; stay in current mode
            resolved = current_mode
        else:
            resolved = gated_mode
    else:
        resolved = current_mode

    # Step 3: Compute switch penalty (informational — log only, does not block)
    switch_occurred = resolved != current_mode
    switch_history: List[bool] = state.get("switch_history", [])
    switch_history.append(switch_occurred)
    penalty = _switch_penalty(switch_history)

    # If the switch penalty is high and momentum is negative, suppress the switch
    if switch_occurred and penalty >= 0.15 and momentum < 0.0:
        resolved = current_mode
        switch_occurred = False
        _log_event("switch_suppressed", {
            "proposed": proposed_mode,
            "gated": gated_mode,
            "current": current_mode,
            "penalty": round(penalty, 3),
            "momentum": round(momentum, 4),
        })

    # Step 4: Update state
    if switch_occurred:
        _log_event("mode_change", {
            "old_mode": current_mode,
            "new_mode": resolved,
            "confidence": round(confidence, 3),
            "momentum": round(momentum, 4),
            "cycles_in_prior_mode": cycles_in_mode,
        })
        state["current_mode"] = resolved
        state["cycles_in_mode"] = 1
        # Emit event (best-effort)
        _emit_mode_locked_event(
            old_mode=current_mode,
            new_mode=resolved,
            confidence=confidence,
        )
    else:
        state["current_mode"] = current_mode
        state["cycles_in_mode"] = cycles_in_mode + 1

    state["switch_history"] = switch_history
    _save_state(state)

    return resolved


def record_cycle(mode: str, outcome_score: float) -> None:
    """Record the outcome of a completed cycle.

    Parameters
    ----------
    mode          : the mode used during this cycle
    outcome_score : a scalar [0, 1] representing how well the cycle went
                    (e.g. avg value_delta, pass_rate, net_score)
    """
    state = _load_state()
    history: List[Dict[str, Any]] = state.get("mode_outcome_history", [])
    history.append({"mode": mode, "outcome": float(outcome_score)})
    state["mode_outcome_history"] = history

    # Update momentum baseline
    prev = state.get("previous_score")
    state["previous_score"] = float(outcome_score)
    if prev is not None:
        momentum = float(outcome_score) - float(prev)
        if abs(momentum) > 0.05:
            _log_event("momentum_shift", {
                "mode": mode,
                "outcome": round(outcome_score, 4),
                "momentum": round(momentum, 4),
            })

    _save_state(state)


def get_momentum(current_score: Optional[float] = None) -> float:
    """Return the current momentum value (current_score − previous_score).

    Parameters
    ----------
    current_score : if provided, compute live momentum against the stored
                    previous_score; otherwise return 0.0.
    """
    if current_score is None:
        return 0.0
    state = _load_state()
    prev = state.get("previous_score")
    if prev is None:
        return 0.0
    return float(current_score) - float(prev)


def status() -> Dict[str, Any]:
    """Return a summary of the stability controller state."""
    state = _load_state()
    switch_history: List[bool] = state.get("switch_history", [])
    mode_outcomes: List[Dict[str, Any]] = state.get("mode_outcome_history", [])
    recent_switches = sum(1 for s in switch_history[-SWITCH_WINDOW:] if s)
    penalty = _switch_penalty(switch_history)

    per_mode_avg: Dict[str, float] = {}
    per_mode_counts: Dict[str, int] = {}
    for entry in mode_outcomes:
        m = entry.get("mode", "unknown")
        o = float(entry.get("outcome", 0.0))
        per_mode_counts[m] = per_mode_counts.get(m, 0) + 1
        per_mode_avg[m] = per_mode_avg.get(m, 0.0) + o
    for m in per_mode_avg:
        if per_mode_counts[m] > 0:
            per_mode_avg[m] = round(per_mode_avg[m] / per_mode_counts[m], 4)

    return {
        "current_mode": state.get("current_mode", "exploit"),
        "cycles_in_mode": state.get("cycles_in_mode", 0),
        "mode_min_duration": MODE_MIN_DURATION,
        "recent_switches": recent_switches,
        "switch_penalty": round(penalty, 3),
        "per_mode_avg_outcome": per_mode_avg,
        "confidence_enter_stability": CONFIDENCE_ENTER_STABILITY,
        "confidence_exit_stability": CONFIDENCE_EXIT_STABILITY,
    }


# ---------------------------------------------------------------------------
# EventBus integration (best-effort)
# ---------------------------------------------------------------------------

def _emit_mode_locked_event(
    old_mode: str,
    new_mode: str,
    confidence: float,
) -> None:
    """Emit EVENT_MODE_LOCKED on the runtime EventBus if available."""
    try:
        from modules.event_bus import get_event_bus, NiblitEvent, EVENT_MODE_LOCKED  # noqa: PLC0415
        bus = get_event_bus()
        bus.publish(NiblitEvent(
            type=EVENT_MODE_LOCKED,
            source="stability_controller",
            payload={
                "old_mode": old_mode,
                "new_mode": new_mode,
                "confidence": round(confidence, 3),
            },
        ))
    except Exception:  # noqa: BLE001
        pass
