#!/usr/bin/env python3
"""
nibblebots/governance_evolution_engine.py — Phase 18 Governance Evolution Engine

Provides *adaptive governance* for the System Interface Layer (SIL) governance
rules introduced in Phase 17.  While Phase 17 made governance *static and
correct*, Phase 18 allows governance *to improve itself* — but only slowly,
and subject to immutable constitutional invariants.

Design philosophy
-----------------
Three adaptation time-scales exist in the Niblit architecture:

  strategy      — adapts every cycle (CSE, stability_controller)
  resonance     — adapts per-profile via trust updates (SIL)
  governance    — adapts only every GEE_ADAPT_INTERVAL cycles (this module)

That separation prevents governance from oscillating in response to short-term
outcome variance the way strategy does.

Metrics tracked
---------------
GovernanceSnapshot measures four signals over a rolling window:

  override_frequency           — fraction of resonance events that triggered a
                                 SAFETY_OVERRIDE (high → governance may be too
                                 aggressive).
  suppressed_exploration_rate  — fraction of resonance events where exploration
                                 was zeroed by AUTHORITY_DENIED or SAFETY_OVERRIDE
                                 (high → exploration may be over-constrained).
  conflict_resolution_success  — fraction of multi-system conflict resolutions
                                 that were NOT saturated (saturated = total
                                 adjustment magnitude exceeded threshold).
  stability_preservation_score — rolling mean outcome score recorded during
                                 cycles where a safety override fired (reflects
                                 whether overrides actually helped).

Adaptation rules (GEE_ADAPT_INTERVAL cadence)
----------------------------------------------
All rules respect constitutional floors (see IMMUTABLE_* constants) that can
never be violated regardless of the measured metrics.

  1. Over-aggressive overrides AND good preservation score
       → loosen SIL_OBJECTIVE_PENALTY slightly (overrides are warranted but
         too frequent — widen the allowable zone before they trigger)

  2. Over-aggressive overrides AND poor preservation score
       → tighten SIL_SATURATION_THRESHOLD (reduce combined influence allowed)

  3. Excessive exploration suppression
       → loosen SIL_SATURATION_THRESHOLD slightly (allow more influence
         through so exploration has room to operate)

  4. Low conflict resolution success (high saturation rate)
       → tighten SIL_SATURATION_THRESHOLD further

Adaptations are applied to the SIL module's runtime constants in-memory
(the env-var defaults remain unchanged so each restart gets a clean start).

State
-----
governance_state.json  — rolling metric windows + applied parameter adjustments
governance_log.jsonl   — audit trail of all adaptation events

Constants (all overridable via env vars)
----------------------------------------
GEE_ENABLED                         : bool  default True
GEE_ADAPT_INTERVAL                  : int   default 20 (adaptation check every N cycles)
GEE_WINDOW                          : int   default 50 (rolling metric window)
GEE_ADAPTATION_STEP                 : float default 0.02 (max param change per adaptation)
GEE_OVERRIDE_THRESHOLD              : float default 0.30 (max acceptable override_frequency)
GEE_SUPPRESSION_THRESHOLD           : float default 0.60 (max acceptable suppressed_exploration_rate)
GEE_CONFLICT_SUCCESS_MIN            : float default 0.50 (min acceptable conflict_resolution_success)
IMMUTABLE_OBJECTIVE_PENALTY_FLOOR   : float default 0.20 (SIL_OBJECTIVE_PENALTY lower bound)
IMMUTABLE_SATURATION_THRESHOLD_FLOOR: float default 0.10 (SIL_SATURATION_THRESHOLD lower bound)
"""

from __future__ import annotations

import json
import logging
import os
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("NiblitGEE")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GEE_ENABLED: bool = (
    os.environ.get("GEE_ENABLED", "1").lower() not in ("0", "false", "no")
)
GEE_ADAPT_INTERVAL: int = int(os.environ.get("GEE_ADAPT_INTERVAL", "20"))
GEE_WINDOW: int = int(os.environ.get("GEE_WINDOW", "50"))
GEE_ADAPTATION_STEP: float = float(os.environ.get("GEE_ADAPTATION_STEP", "0.02"))
GEE_OVERRIDE_THRESHOLD: float = float(os.environ.get("GEE_OVERRIDE_THRESHOLD", "0.30"))
GEE_SUPPRESSION_THRESHOLD: float = float(
    os.environ.get("GEE_SUPPRESSION_THRESHOLD", "0.60")
)
GEE_CONFLICT_SUCCESS_MIN: float = float(
    os.environ.get("GEE_CONFLICT_SUCCESS_MIN", "0.50")
)

# Constitutional invariants — governance cannot reduce these below their floors
IMMUTABLE_OBJECTIVE_PENALTY_FLOOR: float = float(
    os.environ.get("IMMUTABLE_OBJECTIVE_PENALTY_FLOOR", "0.20")
)
IMMUTABLE_SATURATION_THRESHOLD_FLOOR: float = float(
    os.environ.get("IMMUTABLE_SATURATION_THRESHOLD_FLOOR", "0.10")
)

_STATE_FILE = Path(__file__).parent / "governance_state.json"
_LOG_FILE = Path(__file__).parent / "governance_log.jsonl"

# ---------------------------------------------------------------------------
# Event types
# ---------------------------------------------------------------------------

EVT_SAFETY_OVERRIDE = "safety_override"
EVT_AUTHORITY_DENIED = "authority_denied"
EVT_CONFLICT_RESOLVED = "conflict_resolved"
EVT_CYCLE = "cycle_outcome"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GovernanceSnapshot:
    """Rolling governance health metrics over the last ``GEE_WINDOW`` events."""

    window_size: int = 0
    override_frequency: float = 0.0
    suppressed_exploration_rate: float = 0.0
    conflict_resolution_success: float = 1.0
    stability_preservation_score: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "window_size": self.window_size,
            "override_frequency": round(self.override_frequency, 4),
            "suppressed_exploration_rate": round(
                self.suppressed_exploration_rate, 4
            ),
            "conflict_resolution_success": round(
                self.conflict_resolution_success, 4
            ),
            "stability_preservation_score": round(
                self.stability_preservation_score, 4
            ),
        }


@dataclass
class GovernanceAdaptation:
    """Result of a single governance adaptation step."""

    timestamp: str = ""
    saturation_threshold_delta: float = 0.0
    objective_penalty_delta: float = 0.0
    rationale: str = ""
    was_clamped_to_invariants: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "saturation_threshold_delta": round(self.saturation_threshold_delta, 4),
            "objective_penalty_delta": round(self.objective_penalty_delta, 4),
            "rationale": self.rationale,
            "was_clamped_to_invariants": self.was_clamped_to_invariants,
        }


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _load_state() -> Dict[str, Any]:
    try:
        return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state: Dict[str, Any]) -> None:
    try:
        _STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as exc:
        log.debug("[GEE] could not save state: %s", exc)


def _log_event(event_type: str, payload: Dict[str, Any]) -> None:
    try:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            **payload,
        }
        with _LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Public API: event recording
# ---------------------------------------------------------------------------

def record_governance_event(
    event_type: str,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """Record a governance event for metric accumulation.

    Parameters
    ----------
    event_type : One of the ``EVT_*`` constants above or any free-form string.
                 The well-known types contribute to the GovernanceSnapshot metrics;
                 unknown types are stored for audit only.
    context    : Optional dict with event-specific details (stored for audit).
    """
    if not GEE_ENABLED:
        return

    state = _load_state()
    events: List[Dict[str, Any]] = state.get("events", [])

    record: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
    }
    if context:
        record.update({k: v for k, v in context.items() if k not in ("ts", "type")})
    events.append(record)

    # Trim to rolling window
    if len(events) > GEE_WINDOW * 2:
        events = events[-GEE_WINDOW * 2:]
    state["events"] = events
    state["cycle_count"] = state.get("cycle_count", 0) + (
        1 if event_type == EVT_CYCLE else 0
    )
    _save_state(state)

    log.debug("[GEE] event recorded: %s", event_type)


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------

def snapshot() -> GovernanceSnapshot:
    """Compute current GovernanceSnapshot from the rolling event window."""
    state = _load_state()
    events: List[Dict[str, Any]] = state.get("events", [])[-GEE_WINDOW:]

    if not events:
        return GovernanceSnapshot()

    resonance_events = [
        e for e in events
        if e.get("type") in (EVT_SAFETY_OVERRIDE, EVT_AUTHORITY_DENIED)
    ]
    conflict_events = [e for e in events if e.get("type") == EVT_CONFLICT_RESOLVED]
    cycle_events = [e for e in events if e.get("type") == EVT_CYCLE]

    # override_frequency: fraction of resonance events that were SAFETY_OVERRIDE
    total_resonance = max(1, len(resonance_events))
    safety_overrides = [
        e for e in resonance_events if e.get("type") == EVT_SAFETY_OVERRIDE
    ]
    override_frequency = len(safety_overrides) / total_resonance

    # suppressed_exploration_rate: fraction of resonance events where
    # exploration was zeroed by governance (either type)
    suppressed = [
        e for e in resonance_events
        if e.get("explore_rate_adj_before", 1.0) != 0.0
        and e.get("explore_rate_adj_after", None) == 0.0
    ]
    suppressed_exploration_rate = len(suppressed) / total_resonance

    # conflict_resolution_success: fraction of conflict events NOT saturated
    if conflict_events:
        not_saturated = [e for e in conflict_events if not e.get("saturated", False)]
        conflict_resolution_success = len(not_saturated) / len(conflict_events)
    else:
        conflict_resolution_success = 1.0

    # stability_preservation_score: mean outcome during safety-override cycles
    override_outcomes = [
        float(e["outcome"])
        for e in cycle_events
        if "outcome" in e and e.get("had_safety_override", False)
    ]
    if override_outcomes:
        stability_preservation_score = statistics.mean(override_outcomes)
    elif cycle_events:
        outcomes = [float(e["outcome"]) for e in cycle_events if "outcome" in e]
        stability_preservation_score = statistics.mean(outcomes) if outcomes else 0.5
    else:
        stability_preservation_score = 0.5

    return GovernanceSnapshot(
        window_size=len(events),
        override_frequency=round(override_frequency, 4),
        suppressed_exploration_rate=round(suppressed_exploration_rate, 4),
        conflict_resolution_success=round(conflict_resolution_success, 4),
        stability_preservation_score=round(stability_preservation_score, 4),
    )


# ---------------------------------------------------------------------------
# Adaptation engine
# ---------------------------------------------------------------------------

def evaluate_and_adapt(outcome_score: Optional[float] = None) -> Optional[GovernanceAdaptation]:
    """Evaluate governance health and adapt SIL parameters if warranted.

    Called by ``feedback_learner._evaluate_real_world_value()`` on a slow
    cadence (every ``GEE_ADAPT_INTERVAL`` cycles).  Reads the rolling
    GovernanceSnapshot, applies adaptation rules, and mutates the SIL
    module's runtime constants.

    Constitutional invariants are enforced: no adaptation can drive
    ``SIL_OBJECTIVE_PENALTY`` below ``IMMUTABLE_OBJECTIVE_PENALTY_FLOOR`` or
    ``SIL_SATURATION_THRESHOLD`` below ``IMMUTABLE_SATURATION_THRESHOLD_FLOOR``.

    Parameters
    ----------
    outcome_score : Optional float in [0, 1] representing the current cycle's
                    real-world outcome.  When provided it is stored as a
                    ``EVT_CYCLE`` event so the stability_preservation_score
                    metric can track override effectiveness.

    Returns
    -------
    ``GovernanceAdaptation`` if an adaptation was applied, ``None`` if not yet
    due or if GEE is disabled.
    """
    if not GEE_ENABLED:
        return None

    state = _load_state()
    cycle_count = state.get("cycle_count", 0)

    # Store cycle outcome (best-effort, before adaptation check)
    if outcome_score is not None:
        events: List[Dict[str, Any]] = state.get("events", [])
        recent_overrides = [
            e for e in events[-5:]
            if e.get("type") in (EVT_SAFETY_OVERRIDE,)
        ]
        state["events"] = events + [{
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": EVT_CYCLE,
            "outcome": round(float(outcome_score), 4),
            "had_safety_override": len(recent_overrides) > 0,
        }]
        state["cycle_count"] = cycle_count + 1
        _save_state(state)

    # Only adapt every GEE_ADAPT_INTERVAL cycles
    if (cycle_count + 1) % GEE_ADAPT_INTERVAL != 0:
        return None

    gsnap = snapshot()
    sat_delta = 0.0
    penalty_delta = 0.0
    rationale_parts: List[str] = []
    clamped = False

    # Rule 1: overrides too frequent AND they were effective → loosen penalty
    if (
        gsnap.override_frequency > GEE_OVERRIDE_THRESHOLD
        and gsnap.stability_preservation_score > 0.55
    ):
        penalty_delta -= GEE_ADAPTATION_STEP
        rationale_parts.append(
            f"LOOSEN_PENALTY(override_freq={gsnap.override_frequency:.2f},"
            f" preservation={gsnap.stability_preservation_score:.2f})"
        )

    # Rule 2: overrides too frequent BUT they were ineffective → dampen more
    elif (
        gsnap.override_frequency > GEE_OVERRIDE_THRESHOLD
        and gsnap.stability_preservation_score <= 0.55
    ):
        sat_delta -= GEE_ADAPTATION_STEP
        rationale_parts.append(
            f"TIGHTEN_SATURATION(override_freq={gsnap.override_frequency:.2f},"
            f" preservation={gsnap.stability_preservation_score:.2f})"
        )

    # Rule 3: too much exploration suppression → loosen saturation
    if gsnap.suppressed_exploration_rate > GEE_SUPPRESSION_THRESHOLD:
        sat_delta += GEE_ADAPTATION_STEP
        rationale_parts.append(
            f"LOOSEN_SATURATION(suppression={gsnap.suppressed_exploration_rate:.2f})"
        )

    # Rule 4: poor conflict resolution success → tighten saturation
    if gsnap.conflict_resolution_success < GEE_CONFLICT_SUCCESS_MIN:
        sat_delta -= GEE_ADAPTATION_STEP
        rationale_parts.append(
            f"TIGHTEN_SATURATION(conflict_success={gsnap.conflict_resolution_success:.2f})"
        )

    # Nothing to adapt
    if not rationale_parts:
        return None

    # Apply constitutional floors
    try:
        import nibblebots.system_interface_layer as _sil  # noqa: PLC0415

        current_penalty = getattr(_sil, "SIL_OBJECTIVE_PENALTY", 0.40)
        new_penalty = round(current_penalty + penalty_delta, 4)
        if new_penalty < IMMUTABLE_OBJECTIVE_PENALTY_FLOOR:
            new_penalty = IMMUTABLE_OBJECTIVE_PENALTY_FLOOR
            clamped = True
        _sil.SIL_OBJECTIVE_PENALTY = new_penalty

        current_saturation = getattr(_sil, "SIL_SATURATION_THRESHOLD", 0.45)
        new_saturation = round(current_saturation + sat_delta, 4)
        if new_saturation < IMMUTABLE_SATURATION_THRESHOLD_FLOOR:
            new_saturation = IMMUTABLE_SATURATION_THRESHOLD_FLOOR
            clamped = True
        _sil.SIL_SATURATION_THRESHOLD = new_saturation

        # Compute effective deltas after clamping
        penalty_delta = round(new_penalty - current_penalty, 4)
        sat_delta = round(new_saturation - current_saturation, 4)
    except Exception as exc:  # noqa: BLE001
        log.debug("[GEE] could not apply SIL adaptation: %s", exc)
        return None

    rationale = " | ".join(rationale_parts)
    if clamped:
        rationale += " | CLAMPED_TO_CONSTITUTIONAL_FLOOR"

    adaptation = GovernanceAdaptation(
        timestamp=datetime.now(timezone.utc).isoformat(),
        saturation_threshold_delta=sat_delta,
        objective_penalty_delta=penalty_delta,
        rationale=rationale,
        was_clamped_to_invariants=clamped,
    )

    _log_event("governance_adapted", adaptation.to_dict())

    # Emit event bus notification (best-effort)
    try:
        from modules.event_bus import (  # noqa: PLC0415
            get_event_bus, NiblitEvent, EVENT_GOVERNANCE_ADAPTED,
        )
        get_event_bus().publish(NiblitEvent(
            type=EVENT_GOVERNANCE_ADAPTED,
            source="governance_evolution_engine",
            payload=adaptation.to_dict(),
        ))
    except Exception:  # noqa: BLE001
        pass

    log.info(
        "[GEE] governance adapted: sat_delta=%+.4f penalty_delta=%+.4f — %s",
        sat_delta, penalty_delta, rationale,
    )

    # Persist last adaptation for diagnostics
    state = _load_state()
    state["last_adaptation"] = adaptation.to_dict()
    _save_state(state)

    return adaptation


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the Governance Evolution Engine."""
    state = _load_state()
    gsnap = snapshot()
    return {
        "gee_enabled": GEE_ENABLED,
        "adapt_interval": GEE_ADAPT_INTERVAL,
        "window_size": GEE_WINDOW,
        "adaptation_step": GEE_ADAPTATION_STEP,
        "cycle_count": state.get("cycle_count", 0),
        "constitutional_invariants": {
            "objective_penalty_floor": IMMUTABLE_OBJECTIVE_PENALTY_FLOOR,
            "saturation_threshold_floor": IMMUTABLE_SATURATION_THRESHOLD_FLOOR,
        },
        "thresholds": {
            "override_threshold": GEE_OVERRIDE_THRESHOLD,
            "suppression_threshold": GEE_SUPPRESSION_THRESHOLD,
            "conflict_success_min": GEE_CONFLICT_SUCCESS_MIN,
        },
        "current_snapshot": gsnap.to_dict(),
        "last_adaptation": state.get("last_adaptation"),
        "total_events": len(state.get("events", [])),
    }
