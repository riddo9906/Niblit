#!/usr/bin/env python3
"""
nibblebots/stability_controller.py — Phase 9.5b Stability Controller

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
Five complementary mechanisms:

1. **Mode locking** (minimum duration)
   Once a mode is entered, it cannot be exited until
   ``MODE_MIN_DURATION`` cycles have elapsed.

2. **Asymmetric hysteresis thresholds**
   Entering "stability" mode requires confidence to drop below
   ``CONFIDENCE_ENTER_STABILITY`` (0.45 by default).
   Exiting requires confidence to rise above
   ``CONFIDENCE_EXIT_STABILITY`` (0.65 by default).
   This creates a "dead zone" that prevents flip-flopping.

3. **Switch penalty** (capped at 0.25)
   Recent mode switches accumulate a penalty that reduces the
   effective score of *any* new switch, making them progressively
   harder to trigger the more recent ones there were.  The cap of 0.25
   prevents the system from becoming permanently "stuck mode".

4. **Context-aware mode memory** (Phase 9.5)
   Every cycle is recorded with its *conditions* (confidence,
   intent_alignment, signal_reliability) alongside the outcome score.
   ``get_mode_score()`` looks up similar past conditions and returns
   a *statistically-grounded* score for a given mode.

   Phase 9.5b upgrades the raw-average lookup with three filters that
   prevent false-pattern reinforcement from noisy or sparse data:

   a. **Recency weighting** — outcomes are weighted by
      ``exp(-age / CONTEXT_RECENCY_DECAY)`` so recent evidence counts
      more than stale data.

   b. **Sample-confidence scaling** — if fewer than
      ``CONTEXT_MEMORY_MIN_SAMPLES`` similar records exist the score is
      scaled down proportionally, preventing a single lucky run from
      dominating the decision.

   c. **Variance penalty** — high variance across similar-condition
      outcomes reduces the returned score via
      ``1 / (1 + population_variance)``, discounting inconsistent modes.

   ``resolve_mode()`` uses these scores to favour exploration when
   history *reliably* shows exploration outperforms stability.

5. **Exploration epsilon** (Phase 9.5b)
   With probability ``CONTEXT_EXPLORATION_EPSILON`` (default 0.05) the
   controller overrides a settled non-exploration mode and forces
   "explore" for one cycle.  This prevents the system from getting stuck
   in a local optimum when memory consistently but incorrectly discourages
   exploration.

Public API
----------
``resolve_mode(proposed_mode, confidence, momentum, signal_conf, intent_score)``
    The primary entry point.  Given a proposed mode and current signals,
    returns the mode the system should actually use this cycle.

``record_cycle(mode, outcome_score, confidence, intent_alignment, signal_reliability)``
    Record the outcome of a completed cycle with its conditions so the
    controller can learn mode effectiveness per condition.

``get_mode_score(mode, confidence, signal_conf)``
    Return the recency-weighted, confidence-scaled, variance-penalised
    outcome score for ``mode`` under conditions similar to the provided
    values.  Returns 0.0 when no similar history exists.

``status()``
    Returns a dict summarising current controller state for logging.

Constants (overridable via env vars)
-------------------------------------
MODE_MIN_DURATION           : int    (env: SC_MODE_MIN_DURATION, default 5)
                              Minimum cycles before a mode can be changed.
CONFIDENCE_ENTER_STABILITY  : float  (env: SC_CONF_ENTER_STAB, default 0.45)
                              confidence below this triggers stability mode.
CONFIDENCE_EXIT_STABILITY   : float  (env: SC_CONF_EXIT_STAB, default 0.65)
                              confidence must exceed this to leave stability.
SWITCH_PENALTY_DECAY        : float  (env: SC_SWITCH_DECAY, default 0.05)
                              Penalty added per recent switch.
SWITCH_PENALTY_MAX          : float  (env: SC_SWITCH_PENALTY_MAX, default 0.25)
                              Hard cap on switch penalty (prevents stuck-mode).
SWITCH_WINDOW               : int    (env: SC_SWITCH_WINDOW, default 10)
                              Number of recent cycles tracked for switch penalty.
CONTEXT_MEMORY_MAX          : int    (env: SC_CTX_MEMORY_MAX, default 200)
                              Maximum number of contextual cycle records kept.
CONTEXT_SIMILARITY_BAND     : float  (env: SC_CTX_BAND, default 0.1)
                              Tolerance for matching conditions in get_mode_score.
CONTEXT_MEMORY_MIN_SAMPLES  : int    (env: SC_CTX_MIN_SAMPLES, default 5)
                              Minimum similar records needed for full trust.
                              Below this the score is scaled down proportionally.
CONTEXT_RECENCY_DECAY       : float  (env: SC_CTX_RECENCY_DECAY, default 50)
                              Exponential decay half-life (in cycles) for
                              recency weighting in get_mode_score.
EXPLORATION_BIAS_THRESHOLD  : float  (env: SC_EXPLORE_BIAS, default 0.05)
                              Margin by which exploration_score must exceed
                              stability_score to favour exploration.
CONTEXT_EXPLORATION_EPSILON : float  (env: SC_CTX_EXPLORE_EPSILON, default 0.05)
                              Probability of a forced exploration probe each
                              cycle to prevent long-term stagnation.
"""

from __future__ import annotations

import json
import math
import os
import random
import statistics
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
SWITCH_PENALTY_MAX: float = float(os.environ.get("SC_SWITCH_PENALTY_MAX", "0.25"))
SWITCH_WINDOW: int = int(os.environ.get("SC_SWITCH_WINDOW", "10"))

# Phase 9.5: context-aware mode memory
CONTEXT_MEMORY_MAX: int = int(os.environ.get("SC_CTX_MEMORY_MAX", "200"))
CONTEXT_SIMILARITY_BAND: float = float(os.environ.get("SC_CTX_BAND", "0.1"))
EXPLORATION_BIAS_THRESHOLD: float = float(os.environ.get("SC_EXPLORE_BIAS", "0.05"))

# Phase 9.5b: statistically-grounded memory scoring
CONTEXT_MEMORY_MIN_SAMPLES: int = int(os.environ.get("SC_CTX_MIN_SAMPLES", "5"))
CONTEXT_RECENCY_DECAY: float = float(os.environ.get("SC_CTX_RECENCY_DECAY", "50"))
CONTEXT_EXPLORATION_EPSILON: float = float(
    os.environ.get("SC_CTX_EXPLORE_EPSILON", "0.05")
)

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
        "switch_history": [],         # list of bool — True = mode changed this cycle
        "mode_outcome_history": [],   # list of {"mode": str, "outcome": float}
        "context_history": [],        # list of Phase 9.5 contextual records
        "previous_score": None,
    }


def _save_state(state: Dict[str, Any]) -> None:
    # Bound history lists
    state["switch_history"] = state.get("switch_history", [])[-SWITCH_WINDOW * 2:]
    state["mode_outcome_history"] = state.get("mode_outcome_history", [])[-50:]
    state["context_history"] = state.get("context_history", [])[-CONTEXT_MEMORY_MAX:]
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
    """Compute a score penalty based on how many recent cycles had mode switches.

    Capped at ``SWITCH_PENALTY_MAX`` (default 0.25) to prevent the system
    from becoming permanently unable to switch modes.
    """
    recent = switch_history[-SWITCH_WINDOW:]
    num_switches = sum(1 for s in recent if s)
    raw_penalty = num_switches * SWITCH_PENALTY_DECAY
    return min(SWITCH_PENALTY_MAX, raw_penalty)


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
# Phase 9.5: context-aware mode memory helpers
# ---------------------------------------------------------------------------

def get_mode_score(
    mode: str,
    confidence: float,
    signal_conf: float,
) -> float:
    """Return a statistically-grounded outcome score for *mode* under similar
    past conditions.

    "Similar" is defined as records where both *confidence* and
    *signal_reliability* fall within ``CONTEXT_SIMILARITY_BAND`` of the
    provided values.

    Phase 9.5b upgrade — the raw average is replaced with three filters:

    1. **Recency weighting** — each record is weighted by
       ``exp(-age / CONTEXT_RECENCY_DECAY)`` where *age* is the number of
       records recorded since that entry.  Recent evidence counts more.

    2. **Sample-confidence scaling** — if fewer than
       ``CONTEXT_MEMORY_MIN_SAMPLES`` similar records are found, the score
       is scaled down linearly so a single lucky result cannot dominate
       the decision.

    3. **Variance penalty** — the weighted average is multiplied by
       ``1 / (1 + population_variance)`` of the similar-condition outcomes,
       reducing trust in modes that have produced inconsistent results.

    Parameters
    ----------
    mode        : the mode whose historical effectiveness to query
    confidence  : current avg_confidence value
    signal_conf : current signal_reliability / avg_confidence from SIE

    Returns
    -------
    float : adjusted outcome score in [0, 1], or 0.0 if no similar records exist.
    """
    state = _load_state()
    history: List[Dict[str, Any]] = state.get("context_history", [])

    similar = [
        r for r in history
        if r.get("mode") == mode
        and abs(r.get("confidence", 0.0) - confidence) < CONTEXT_SIMILARITY_BAND
        and abs(r.get("signal_reliability", 0.0) - signal_conf) < CONTEXT_SIMILARITY_BAND
    ]
    n = len(similar)
    if n == 0:
        return 0.0

    # Sample-confidence: scale down when evidence is sparse
    sample_confidence = min(1.0, n / max(1, CONTEXT_MEMORY_MIN_SAMPLES))

    # Recency weighting: newer records get higher weight
    # Use list position as proxy for cycle age (larger index = more recent)
    # The global history list grows monotonically; compute index-based age.
    max_idx = len(history) - 1
    weighted_sum = 0.0
    total_weight = 0.0
    for r in similar:
        # Prefer stored cycle_index; fall back to linear scan position
        record_idx = r.get("cycle_index", history.index(r) if r in history else 0)
        age = max(0, max_idx - record_idx)
        w = math.exp(-age / max(1.0, CONTEXT_RECENCY_DECAY))
        outcome = float(r.get("outcome", 0.0))
        weighted_sum += outcome * w
        total_weight += w

    if total_weight == 0.0:
        return 0.0

    weighted_avg = weighted_sum / total_weight

    # Variance penalty: inconsistent history is less trustworthy
    if n > 1:
        outcomes = [float(r.get("outcome", 0.0)) for r in similar]
        variance = statistics.pvariance(outcomes)
        stability_factor = 1.0 / (1.0 + variance)
    else:
        stability_factor = 1.0

    return weighted_avg * sample_confidence * stability_factor


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def resolve_mode(
    proposed_mode: str,
    confidence: float = 1.0,
    momentum: float = 0.0,
    signal_conf: float = 1.0,
    intent_score: float = 1.0,
) -> str:
    """Resolve the mode the system should use this cycle.

    Applies mode locking, asymmetric hysteresis, switch penalty, and
    Phase 9.5 context-aware bias to stabilise decision-making across cycles.

    Parameters
    ----------
    proposed_mode : "exploit" | "explore" | "stability"
                    The mode the strategic_planner wants to use.
    confidence    : float [0, 1] — avg_confidence from signal_integrity_engine.
                    Lower values push toward stability.
    momentum      : float (current_score − previous_score).
                    Positive = improving; negative = declining.
    signal_conf   : float [0, 1] — signal_reliability from the snapshot.
                    Used for contextual mode memory lookup (Phase 9.5).
    intent_score  : float [0, 1] — intent_alignment score.
                    Stored with context records for future analysis.

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

    # Step 1b (Phase 9.5): contextual bias — if exploration has historically
    # outperformed stability under the current conditions, favour exploration
    # when the gated result is "stability" (but not when it's a forced-safety).
    # This only applies when we are not already in exploration and the confidence
    # gate is suggesting stability for reasons other than a hard safety override.
    favor_exploration = False
    if gated_mode == "stability" and confidence >= CONFIDENCE_ENTER_STABILITY:
        exploration_score = get_mode_score("explore", confidence, signal_conf)
        stability_score = get_mode_score("stability", confidence, signal_conf)
        if exploration_score > stability_score + EXPLORATION_BIAS_THRESHOLD:
            favor_exploration = True
            gated_mode = "explore"
            _log_event("contextual_exploration_bias", {
                "exploration_score": round(exploration_score, 4),
                "stability_score": round(stability_score, 4),
                "confidence": round(confidence, 3),
                "signal_conf": round(signal_conf, 3),
            })

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

    # Step 3: Compute switch penalty (capped at SWITCH_PENALTY_MAX)
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
            "favor_exploration": favor_exploration,
        })

    # Step 3b (Phase 9.5b): Exploration epsilon safeguard
    # When the system has been settled in a non-exploration mode for at least
    # MODE_MIN_DURATION cycles, occasionally force one exploration cycle to
    # prevent long-term stagnation from over-confident memory.
    if (
        not switch_occurred
        and resolved != "explore"
        and cycles_in_mode >= MODE_MIN_DURATION
        and random.random() < CONTEXT_EXPLORATION_EPSILON
    ):
        resolved = "explore"
        switch_occurred = True
        switch_history[-1] = True  # Mark this cycle as a switch
        _log_event("exploration_epsilon_trigger", {
            "overridden_mode": current_mode,
            "cycles_in_mode": cycles_in_mode,
            "epsilon": CONTEXT_EXPLORATION_EPSILON,
        })

    # Step 4: Update state
    if switch_occurred:
        _log_event("mode_change", {
            "old_mode": current_mode,
            "new_mode": resolved,
            "confidence": round(confidence, 3),
            "momentum": round(momentum, 4),
            "cycles_in_prior_mode": cycles_in_mode,
            "favor_exploration": favor_exploration,
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


def record_cycle(
    mode: str,
    outcome_score: float,
    confidence: float = 0.5,
    intent_alignment: float = 1.0,
    signal_reliability: float = 1.0,
) -> None:
    """Record the outcome of a completed cycle with its conditions.

    Phase 9.5 upgrade: stores full context alongside each outcome so
    ``get_mode_score()`` can provide condition-aware effectiveness scores.

    Parameters
    ----------
    mode               : the mode used during this cycle
    outcome_score      : a scalar [0, 1] representing how well the cycle went
                         (e.g. avg value_delta, pass_rate, net_score)
    confidence         : avg_confidence at cycle time (from signal_integrity_engine)
    intent_alignment   : intent alignment score at cycle time (from intent_anchor_engine)
    signal_reliability : signal reliability / avg_confidence from the snapshot
    """
    state = _load_state()

    # Legacy per-mode outcome history (kept for backwards compat)
    history: List[Dict[str, Any]] = state.get("mode_outcome_history", [])
    history.append({"mode": mode, "outcome": float(outcome_score)})
    state["mode_outcome_history"] = history

    # Phase 9.5: contextual record
    ctx_history: List[Dict[str, Any]] = state.get("context_history", [])
    ctx_history.append({
        "mode": mode,
        "outcome": float(outcome_score),
        "confidence": float(confidence),
        "intent_alignment": float(intent_alignment),
        "signal_reliability": float(signal_reliability),
        "cycle_index": len(ctx_history),  # Phase 9.5b: monotonic index for recency weighting
    })
    state["context_history"] = ctx_history

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

    ctx_history: List[Dict[str, Any]] = state.get("context_history", [])

    return {
        "current_mode": state.get("current_mode", "exploit"),
        "cycles_in_mode": state.get("cycles_in_mode", 0),
        "mode_min_duration": MODE_MIN_DURATION,
        "recent_switches": recent_switches,
        "switch_penalty": round(penalty, 3),
        "switch_penalty_max": SWITCH_PENALTY_MAX,
        "per_mode_avg_outcome": per_mode_avg,
        "confidence_enter_stability": CONFIDENCE_ENTER_STABILITY,
        "confidence_exit_stability": CONFIDENCE_EXIT_STABILITY,
        "context_memory_size": len(ctx_history),
        "context_memory_max": CONTEXT_MEMORY_MAX,
        "context_memory_min_samples": CONTEXT_MEMORY_MIN_SAMPLES,
        "context_recency_decay": CONTEXT_RECENCY_DECAY,
        "exploration_bias_threshold": EXPLORATION_BIAS_THRESHOLD,
        "exploration_epsilon": CONTEXT_EXPLORATION_EPSILON,
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
