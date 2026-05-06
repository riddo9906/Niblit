#!/usr/bin/env python3
"""
nibblebots/system_interface_layer.py — Phase 16 Adaptive System Interface Engine

Implements "mirror + resonance" for system-to-system intelligence:

Mirror      → Niblit understands and reflects another system's structure,
              signals, and decision intent.

Resonance   → Niblit aligns and adapts its own behaviour to interact
              effectively with that system — without losing its own objective
              alignment.

Core concepts
-------------
ExternalSystemProfile
    A structural model of an external system, built from observed signals and
    response patterns.  Persisted across runs so Niblit's understanding of a
    partner system deepens over time.

mirror_system(system_id, external_data)
    Analyse incoming external data and construct (or update) an
    ExternalSystemProfile.  Extracts signal types, maps confidence patterns,
    and detects the external system's decision structure.

    Output example:
        "This system uses event-based signals with implicit confidence weighting"

establish_resonance(profile)
    Translate a mirrored profile into concrete parameter adjustments for
    Niblit's own strategy engine:
        - signal_weight_adj:      how much to trust signals from this system
        - explore_rate_adj:       delta to Niblit's exploration rate
        - decision_threshold_adj: adjustment to Niblit's action-gate thresholds

ObjectiveAlignmentGuard
    Enforces the constraint "without losing its own objective alignment".
    When an external signal's intent contradicts Niblit's current objective,
    its effective weight is down-scaled rather than blocked outright —
    preventing drift without brittleness.

    if external_signal_conflicts_with_objective:
        downweight_signal()

State
-----
system_interface_state.json  — active profiles + resonance history
system_interface_log.jsonl   — audit trail of mirror/resonance events

Constants (overridable via env vars)
-------------------------------------
SIL_MAX_PROFILES           : int   (env: SIL_MAX_PROFILES,            default 20)
SIL_RESONANCE_LR           : float (env: SIL_RESONANCE_LR,            default 0.10)
SIL_OBJECTIVE_PENALTY      : float (env: SIL_OBJECTIVE_PENALTY,       default 0.40)
SIL_MIN_SIGNAL_TRUST       : float (env: SIL_MIN_SIGNAL_TRUST,        default 0.10)
SIL_EMA_DECAY              : float (env: SIL_EMA_DECAY,               default 0.90)
                             Exponential moving average factor for both latency
                             and confidence model blending.
SIL_EXPLORE_RATIO_THRESHOLD: float (env: SIL_EXPLORE_RATIO_THRESHOLD, default 0.60)
                             Fraction of exploration signals above which Niblit
                             boosts its own exploration rate.
SIL_EXPLORE_BOOST          : float (env: SIL_EXPLORE_BOOST,           default 0.05)
                             Exploration rate delta applied when external signals
                             indicate uncertainty.
SIL_EXPLORE_REDUCTION      : float (env: SIL_EXPLORE_REDUCTION,       default 0.03)
                             Exploration rate delta applied when external signals
                             indicate stability.
SIL_ENABLED                : bool  (env: SIL_ENABLED,                 default "1" → True)
"""

from __future__ import annotations

import json
import logging
import os
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("NiblitSIL")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SIL_MAX_PROFILES: int = int(os.environ.get("SIL_MAX_PROFILES", "20"))
SIL_RESONANCE_LR: float = float(os.environ.get("SIL_RESONANCE_LR", "0.10"))
SIL_OBJECTIVE_PENALTY: float = float(os.environ.get("SIL_OBJECTIVE_PENALTY", "0.40"))
SIL_MIN_SIGNAL_TRUST: float = float(os.environ.get("SIL_MIN_SIGNAL_TRUST", "0.10"))
# EMA decay factor for confidence model and latency smoothing (renamed from
# SIL_LATENCY_DECAY for clarity; the env var SIL_LATENCY_DECAY is preserved
# for backward compatibility via the alias below).
SIL_EMA_DECAY: float = float(
    os.environ.get("SIL_EMA_DECAY", os.environ.get("SIL_LATENCY_DECAY", "0.90"))
)
# Exploration-rate adjustments applied by establish_resonance()
SIL_EXPLORE_RATIO_THRESHOLD: float = float(
    os.environ.get("SIL_EXPLORE_RATIO_THRESHOLD", "0.60")
)
SIL_EXPLORE_BOOST: float = float(os.environ.get("SIL_EXPLORE_BOOST", "0.05"))
SIL_EXPLORE_REDUCTION: float = float(os.environ.get("SIL_EXPLORE_REDUCTION", "0.03"))
SIL_ENABLED: bool = (
    os.environ.get("SIL_ENABLED", "1").lower() not in ("0", "false", "no")
)

_STATE_FILE = Path(__file__).parent / "system_interface_state.json"
_LOG_FILE = Path(__file__).parent / "system_interface_log.jsonl"

# ---------------------------------------------------------------------------
# Signal classification constants
# ---------------------------------------------------------------------------

# Signal key fragments that indicate "stability / risk-off" intent.
_STABILITY_SIGNAL_KEYS = frozenset({
    "low_volatility", "stable", "confidence_high", "risk_off",
    "pass", "success", "healthy", "green", "safe",
})

# Signal key fragments that indicate "exploration / uncertainty" intent.
_EXPLORATION_SIGNAL_KEYS = frozenset({
    "anomaly", "unknown", "low_confidence", "new_pattern",
    "fail", "error", "warning", "yellow", "orange", "spike", "oversold",
    "volatile", "volatile_", "instability",
})


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ExternalSystemProfile:
    """Structural model of an external system built from observed signals.

    Fields
    ------
    system_id          : Unique string identifier for the external system.
    signals            : Dict mapping signal_key → latest observed float value.
    response_patterns  : Dict mapping pattern_key → frequency count.
    confidence_model   : Dict mapping signal_key → estimated reliability [0,1].
    latency_profile    : Rolling-average response latency (seconds).
    trust_weight       : Niblit's overall trust in this system's signals [0,1].
    signal_types       : Inferred category per signal key.
    decision_structure : Human-readable summary of the system's decision style.
    last_mirrored      : ISO-8601 timestamp of the last mirror_system() call.
    resonance_outcomes : History of outcome scores recorded after resonance.
    """

    system_id: str
    signals: Dict[str, float] = field(default_factory=dict)
    response_patterns: Dict[str, int] = field(default_factory=dict)
    confidence_model: Dict[str, float] = field(default_factory=dict)
    latency_profile: float = 0.0
    trust_weight: float = 0.5
    signal_types: Dict[str, str] = field(default_factory=dict)
    decision_structure: str = ""
    last_mirrored: str = ""
    resonance_outcomes: List[float] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "system_id": self.system_id,
            "signals": self.signals,
            "response_patterns": self.response_patterns,
            "confidence_model": self.confidence_model,
            "latency_profile": round(self.latency_profile, 4),
            "trust_weight": round(self.trust_weight, 4),
            "signal_types": self.signal_types,
            "decision_structure": self.decision_structure,
            "last_mirrored": self.last_mirrored,
            "resonance_outcomes": [
                round(o, 4) for o in self.resonance_outcomes[-20:]
            ],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ExternalSystemProfile":
        return cls(
            system_id=d.get("system_id", "unknown"),
            signals=d.get("signals", {}),
            response_patterns=d.get("response_patterns", {}),
            confidence_model=d.get("confidence_model", {}),
            latency_profile=float(d.get("latency_profile", 0.0)),
            trust_weight=float(d.get("trust_weight", 0.5)),
            signal_types=d.get("signal_types", {}),
            decision_structure=d.get("decision_structure", ""),
            last_mirrored=d.get("last_mirrored", ""),
            resonance_outcomes=[
                float(o) for o in d.get("resonance_outcomes", [])
            ],
        )


@dataclass
class ResonanceConfig:
    """Concrete parameter adjustments derived from an ExternalSystemProfile.

    Applied by causal_strategy_engine.query_strategy() and niblit_brain.think()
    to align Niblit's behaviour with the external system while preserving its
    own objective direction.

    Fields
    ------
    signal_weight_adj       : Multiplicative trust factor for external signals
                              [SIL_MIN_SIGNAL_TRUST, 1.0].
    explore_rate_adj        : Signed delta applied to EXPLORATION_RATE.
    decision_threshold_adj  : Signed delta applied to action-gate thresholds.
    rationale               : Human-readable explanation for audit trails.
    objective_conflict      : True when the external system's signals partially
                              conflict with Niblit's current objective.
    """

    signal_weight_adj: float = 1.0
    explore_rate_adj: float = 0.0
    decision_threshold_adj: float = 0.0
    rationale: str = ""
    objective_conflict: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_weight_adj": round(self.signal_weight_adj, 4),
            "explore_rate_adj": round(self.explore_rate_adj, 4),
            "decision_threshold_adj": round(self.decision_threshold_adj, 4),
            "rationale": self.rationale,
            "objective_conflict": self.objective_conflict,
        }


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def _load_state() -> Dict[str, Any]:
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    return {"profiles": {}}


def _save_state(state: Dict[str, Any]) -> None:
    try:
        _STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as exc:
        log.debug("[SIL] could not save state: %s", exc)


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
# Signal classification helpers
# ---------------------------------------------------------------------------

def _infer_signal_type(key: str, value: Any) -> str:
    """Infer the category of a signal from its key name and value type."""
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        v = float(value)
        if v in (0.0, 1.0):
            return "discrete"
        if 0.0 < v < 1.0:
            return "probabilistic"
        return "continuous"
    if isinstance(value, str):
        return "categorical"
    return "event"


def _extract_signal_types(
    external_data: Dict[str, Any],
) -> Dict[str, str]:
    """Map each signal key in external_data to a category label."""
    return {
        key: _infer_signal_type(key, val)
        for key, val in external_data.items()
        if key not in ("system_id", "latency_ms", "timestamp")
    }


def _map_confidence_patterns(
    external_data: Dict[str, Any],
) -> Dict[str, float]:
    """Estimate per-signal reliability from key naming and value type.

    Keys ending in ``_confidence`` or ``_conf`` are treated as explicit
    reliability annotations; all other keys receive heuristic baselines:
      - discrete / boolean  → 0.70
      - probabilistic       → 0.60
      - continuous          → 0.60
      - categorical / event → 0.50
    """
    explicit: Dict[str, float] = {}
    for key, val in external_data.items():
        if isinstance(val, (int, float)):
            if key.endswith("_confidence"):
                base = key[: -len("_confidence")]
                explicit[base] = max(0.0, min(1.0, float(val)))
            elif key.endswith("_conf"):
                base = key[: -len("_conf")]
                explicit[base] = max(0.0, min(1.0, float(val)))

    conf: Dict[str, float] = {}
    for key, val in external_data.items():
        if key in ("system_id", "latency_ms", "timestamp"):
            continue
        if key in explicit:
            conf[key] = explicit[key]
            continue
        stype = _infer_signal_type(key, val)
        if stype in ("boolean", "discrete"):
            conf[key] = 0.70
        elif stype in ("probabilistic", "continuous"):
            conf[key] = 0.60
        else:
            conf[key] = 0.50
    return conf


def _detect_decision_structure(
    signal_types: Dict[str, str],
    external_data: Dict[str, Any],
) -> str:
    """Produce a human-readable summary of the external system's decision style.

    Examples
    --------
    "This system uses event-based signals (3 discrete, 2 probabilistic)
     with implicit confidence weighting"
    """
    type_counts: Dict[str, int] = {}
    for stype in signal_types.values():
        type_counts[stype] = type_counts.get(stype, 0) + 1

    has_explicit_conf = any(
        k.endswith("_confidence") or k.endswith("_conf")
        for k in external_data
    )

    dominant = (
        max(type_counts, key=lambda k: type_counts[k])
        if type_counts else "unknown"
    )
    conf_style = (
        "explicit confidence annotation"
        if has_explicit_conf
        else "implicit confidence weighting"
    )
    count_summary = ", ".join(
        f"{v} {k}"
        for k, v in sorted(type_counts.items(), key=lambda x: -x[1])
    )
    return (
        f"This system uses {dominant}-based signals ({count_summary}) "
        f"with {conf_style}"
    )


# ---------------------------------------------------------------------------
# Objective alignment guard
# ---------------------------------------------------------------------------

def _check_objective_conflict(
    profile: ExternalSystemProfile,
    signal_dict: Dict[str, float],
    current_objective: str,
) -> Tuple[bool, float]:
    """Check whether external signals conflict with Niblit's current objective.

    Returns ``(conflict_detected, penalty_factor)`` where ``penalty_factor``
    is the fraction to subtract from the signal trust weight when a conflict
    is detected.  Returns ``(False, 0.0)`` when no conflict exists.

    Logic:
        - Count keys that contain stability-flavoured words vs exploration-
          flavoured words.
        - Compare to what the current objective desires.
        - When the signal tone opposes the objective, apply a proportional
          penalty (up to ``SIL_OBJECTIVE_PENALTY``).
    """
    if not current_objective:
        return False, 0.0

    stability_count = sum(
        1 for key in signal_dict
        if any(sk in key.lower() for sk in _STABILITY_SIGNAL_KEYS)
    )
    explore_count = sum(
        1 for key in signal_dict
        if any(ek in key.lower() for ek in _EXPLORATION_SIGNAL_KEYS)
    )
    total = stability_count + explore_count
    if total == 0:
        return False, 0.0

    objective_lower = current_objective.lower()
    wants_stability = any(
        word in objective_lower
        for word in ("stability", "stabilit", "conservative", "risk_off")
    )
    wants_exploration = any(
        word in objective_lower
        for word in ("explore", "learn", "improve_learning", "discover")
    )

    if wants_stability and explore_count > stability_count:
        conflict_ratio = explore_count / total
        return True, SIL_OBJECTIVE_PENALTY * conflict_ratio

    if wants_exploration and stability_count > explore_count:
        conflict_ratio = stability_count / total
        return True, SIL_OBJECTIVE_PENALTY * conflict_ratio

    return False, 0.0


# ---------------------------------------------------------------------------
# Core public API
# ---------------------------------------------------------------------------

def mirror_system(
    system_id: str,
    external_data: Dict[str, Any],
    latency_ms: Optional[float] = None,
    current_objective: str = "",
) -> ExternalSystemProfile:
    """Analyse external data and build or update an ExternalSystemProfile.

    Steps
    -----
    1. ``extract_signal_types()``    — classify each signal key.
    2. ``map_confidence_patterns()`` — estimate per-signal reliability.
    3. ``detect_decision_structure()`` — infer the external system's style.
    4. Persist updated profile to state.
    5. Emit ``EVENT_SYSTEM_MIRRORED`` via EventBus (best-effort).

    Parameters
    ----------
    system_id         : Unique name for the external system (e.g. "tickerbot").
    external_data     : Dict of ``signal_key → value`` observations.
    latency_ms        : Optional observed response latency in milliseconds.
    current_objective : Niblit's current goal string (for audit purposes).

    Returns
    -------
    The updated :class:`ExternalSystemProfile`.
    """
    if not SIL_ENABLED:
        return ExternalSystemProfile(system_id=system_id)

    state = _load_state()
    profiles_raw: Dict[str, Any] = state.get("profiles", {})

    profile = (
        ExternalSystemProfile.from_dict(profiles_raw[system_id])
        if system_id in profiles_raw
        else ExternalSystemProfile(system_id=system_id)
    )

    # Step 1: extract signal types
    new_signal_types = _extract_signal_types(external_data)
    profile.signal_types.update(new_signal_types)

    # Step 2: map confidence patterns (blend with exponential moving average)
    new_conf = _map_confidence_patterns(external_data)
    for key, new_val in new_conf.items():
        old_val = profile.confidence_model.get(key, new_val)
        profile.confidence_model[key] = round(
            SIL_EMA_DECAY * old_val + (1.0 - SIL_EMA_DECAY) * new_val, 4
        )

    # Step 3: detect decision structure
    profile.decision_structure = _detect_decision_structure(
        profile.signal_types, external_data
    )

    # Step 4: update signal observations (store latest numeric values)
    for key, val in external_data.items():
        if key in ("system_id", "latency_ms", "timestamp"):
            continue
        if isinstance(val, (int, float, bool)):
            profile.signals[key] = float(val)

    # Step 5: update latency profile
    if latency_ms is not None:
        profile.latency_profile = round(
            SIL_EMA_DECAY * profile.latency_profile
            + (1.0 - SIL_EMA_DECAY) * (latency_ms / 1000.0),
            4,
        )

    profile.last_mirrored = datetime.now(timezone.utc).isoformat()

    # Persist — cap total profile count
    profiles_raw[system_id] = profile.to_dict()
    if len(profiles_raw) > SIL_MAX_PROFILES:
        oldest = min(
            profiles_raw.keys(),
            key=lambda k: profiles_raw[k].get("last_mirrored", ""),
        )
        del profiles_raw[oldest]
    state["profiles"] = profiles_raw
    _save_state(state)

    _log_event("mirrored", {
        "system_id": system_id,
        "signal_count": len(new_signal_types),
        "decision_structure": profile.decision_structure,
        "objective": current_objective,
    })

    # Best-effort EventBus notification
    try:
        from modules.event_bus import (  # noqa: PLC0415
            get_event_bus, NiblitEvent, EVENT_SYSTEM_MIRRORED,
        )
        get_event_bus().publish(NiblitEvent(
            type=EVENT_SYSTEM_MIRRORED,
            source="system_interface_layer",
            payload={
                "system_id": system_id,
                "decision_structure": profile.decision_structure,
                "signal_count": len(new_signal_types),
            },
        ))
    except Exception:  # noqa: BLE001
        pass

    log.debug("[SIL] mirrored %s — %s", system_id, profile.decision_structure)
    return profile


def establish_resonance(
    profile: ExternalSystemProfile,
    current_objective: str = "",
) -> ResonanceConfig:
    """Translate a mirrored profile into concrete strategy adjustments.

    Steps
    -----
    1. ``align_signal_weights()``    — derive trust factor from confidence model.
    2. ``adjust_exploration_rate()`` — push toward exploration when external
       signals indicate volatility; nudge toward exploitation when they
       indicate stability.
    3. ``tune_decision_thresholds()`` — lower action gates for high-trust
       external systems; raise them for low-trust ones.
    4. Objective alignment guard — downweight conflicting signals so Niblit
       never loses its own objective direction.
    5. Emit ``EVENT_SYSTEM_RESONANCE`` via EventBus (best-effort).

    Parameters
    ----------
    profile           : :class:`ExternalSystemProfile` from :func:`mirror_system`.
    current_objective : Niblit's current goal string (alignment guard).

    Returns
    -------
    :class:`ResonanceConfig` with bounded, auditable adjustments.
    """
    if not SIL_ENABLED:
        return ResonanceConfig(rationale="SIL disabled")

    # Step 1: align signal weights
    conf_values = list(profile.confidence_model.values())
    avg_conf = statistics.mean(conf_values) if conf_values else 0.5
    base_weight = 0.5 * profile.trust_weight + 0.5 * avg_conf
    signal_weight_adj = max(SIL_MIN_SIGNAL_TRUST, min(1.0, round(base_weight, 4)))

    # Step 2: adjust exploration rate
    stability_signals = sum(
        1 for key in profile.signals
        if any(sk in key.lower() for sk in _STABILITY_SIGNAL_KEYS)
    )
    explore_signals = sum(
        1 for key in profile.signals
        if any(ek in key.lower() for ek in _EXPLORATION_SIGNAL_KEYS)
    )
    total_signals = max(1, stability_signals + explore_signals)
    stability_ratio = stability_signals / total_signals
    explore_ratio = explore_signals / total_signals

    if explore_ratio > SIL_EXPLORE_RATIO_THRESHOLD:
        # External system is signalling uncertainty → boost exploration
        explore_rate_adj = round(+SIL_EXPLORE_BOOST * signal_weight_adj, 4)
    elif stability_ratio > SIL_EXPLORE_RATIO_THRESHOLD:
        # External system is signalling stability → reduce exploration
        explore_rate_adj = round(-SIL_EXPLORE_REDUCTION * signal_weight_adj, 4)
    else:
        explore_rate_adj = 0.0

    # Step 3: tune decision thresholds
    if signal_weight_adj >= 0.75:
        decision_threshold_adj = -0.02   # high trust → act more readily
    elif signal_weight_adj <= 0.30:
        decision_threshold_adj = +0.03   # low trust → be more sceptical
    else:
        decision_threshold_adj = 0.0
    decision_threshold_adj = round(decision_threshold_adj, 4)

    # Step 4: objective alignment guard
    conflict, penalty = _check_objective_conflict(
        profile,
        profile.signals,
        current_objective,
    )
    if conflict:
        signal_weight_adj = max(
            SIL_MIN_SIGNAL_TRUST,
            round(signal_weight_adj - penalty, 4),
        )

    rationale_parts = [
        f"SIL/resonance({profile.system_id})",
        f"trust={signal_weight_adj:.3f}",
        f"explore_adj={explore_rate_adj:+.4f}",
        f"gate_adj={decision_threshold_adj:+.4f}",
    ]
    if conflict:
        rationale_parts.append(f"OBJECTIVE_CONFLICT(penalty={penalty:.2f})")

    config = ResonanceConfig(
        signal_weight_adj=signal_weight_adj,
        explore_rate_adj=explore_rate_adj,
        decision_threshold_adj=decision_threshold_adj,
        rationale=" | ".join(rationale_parts),
        objective_conflict=conflict,
    )

    _log_event("resonance", {
        "system_id": profile.system_id,
        "config": config.to_dict(),
        "objective": current_objective,
    })

    try:
        from modules.event_bus import (  # noqa: PLC0415
            get_event_bus, NiblitEvent, EVENT_SYSTEM_RESONANCE,
        )
        get_event_bus().publish(NiblitEvent(
            type=EVENT_SYSTEM_RESONANCE,
            source="system_interface_layer",
            payload={
                "system_id": profile.system_id,
                "resonance": config.to_dict(),
            },
        ))
    except Exception:  # noqa: BLE001
        pass

    log.debug("[SIL] resonance %s — %s", profile.system_id, config.rationale)
    return config


def get_profile(system_id: str) -> Optional[ExternalSystemProfile]:
    """Return the persisted :class:`ExternalSystemProfile` for *system_id*, or None."""
    raw = _load_state().get("profiles", {}).get(system_id)
    return ExternalSystemProfile.from_dict(raw) if raw is not None else None


def record_resonance_outcome(system_id: str, outcome: float) -> None:
    """Record an outcome score [0, 1] after resonance was applied.

    Updates ``profile.trust_weight`` via a TD-style rule:
    ``new_trust = clamp(old_trust + SIL_RESONANCE_LR × (outcome − 0.5))``
    """
    state = _load_state()
    profiles_raw: Dict[str, Any] = state.get("profiles", {})
    if system_id not in profiles_raw:
        return

    profile = ExternalSystemProfile.from_dict(profiles_raw[system_id])
    profile.resonance_outcomes.append(float(outcome))
    if len(profile.resonance_outcomes) > 50:
        profile.resonance_outcomes = profile.resonance_outcomes[-50:]

    old_trust = profile.trust_weight
    new_trust = max(
        0.05, min(0.95, old_trust + SIL_RESONANCE_LR * (outcome - 0.5))
    )
    profile.trust_weight = round(new_trust, 4)
    profiles_raw[system_id] = profile.to_dict()
    state["profiles"] = profiles_raw
    _save_state(state)


def get_active_resonance(objective: str = "") -> Optional[ResonanceConfig]:
    """Return a blended :class:`ResonanceConfig` across all known profiles.

    When multiple profiles exist, their resonance configs are trust-weighted
    and averaged.  Returns ``None`` when SIL is disabled or no profiles exist.
    """
    if not SIL_ENABLED:
        return None

    profiles_raw = _load_state().get("profiles", {})
    if not profiles_raw:
        return None

    profiles = [ExternalSystemProfile.from_dict(r) for r in profiles_raw.values()]
    configs = [establish_resonance(p, objective) for p in profiles]

    if len(configs) == 1:
        return configs[0]

    total_weight = sum(c.signal_weight_adj for c in configs) or 1.0
    blended_explore = (
        sum(c.explore_rate_adj * c.signal_weight_adj for c in configs) / total_weight
    )
    blended_threshold = (
        sum(c.decision_threshold_adj * c.signal_weight_adj for c in configs)
        / total_weight
    )
    blended_weight = sum(c.signal_weight_adj for c in configs) / len(configs)
    any_conflict = any(c.objective_conflict for c in configs)

    return ResonanceConfig(
        signal_weight_adj=round(blended_weight, 4),
        explore_rate_adj=round(blended_explore, 4),
        decision_threshold_adj=round(blended_threshold, 4),
        rationale=f"SIL/blended({len(configs)} systems)",
        objective_conflict=any_conflict,
    )


def status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the System Interface Layer."""
    state = _load_state()
    profiles_raw = state.get("profiles", {})
    return {
        "sil_enabled": SIL_ENABLED,
        "active_profiles": len(profiles_raw),
        "max_profiles": SIL_MAX_PROFILES,
        "resonance_lr": SIL_RESONANCE_LR,
        "objective_penalty": SIL_OBJECTIVE_PENALTY,
        "min_signal_trust": SIL_MIN_SIGNAL_TRUST,
        "profiles": [
            {
                "system_id": sid,
                "trust_weight": profiles_raw[sid].get("trust_weight", 0.5),
                "signal_count": len(profiles_raw[sid].get("signals", {})),
                "last_mirrored": profiles_raw[sid].get("last_mirrored", ""),
                "decision_structure": profiles_raw[sid].get("decision_structure", ""),
            }
            for sid in profiles_raw
        ],
    }


if __name__ == "__main__":
    # Quick smoke test
    _profile = mirror_system(
        "tickerbot",
        {
            "rsi_oversold": 1.0,
            "volume_spike": 1.0,
            "price_confidence": 0.72,
        },
        latency_ms=120.0,
        current_objective="maximize_stability",
    )
    print("Profile:", _profile.to_dict())
    _cfg = establish_resonance(_profile, current_objective="maximize_stability")
    print("Resonance:", _cfg.to_dict())
    print("Status:", status())
