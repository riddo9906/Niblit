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
SIL_TRUST_DECAY_FACTOR     : float (env: SIL_TRUST_DECAY_FACTOR,      default 604800)
                             Time constant (seconds) for trust decay.  Default is
                             7 days.  A profile that has not been revalidated for
                             one full decay constant retains ≈37 % of its trust.
                             Set to 0 to disable decay.
SIL_ATTRIBUTION_LR         : float (env: SIL_ATTRIBUTION_LR,          default 0.15)
                             Learning rate for attribution-based TD trust updates.
                             Separate from SIL_RESONANCE_LR so causal validation
                             signals can be weighted more aggressively than simple
                             correlation-based updates.
SIL_ENABLED                : bool  (env: SIL_ENABLED,                 default "1" → True)
"""

from __future__ import annotations

import json
import logging
import math
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
# Trust decay time constant (seconds).  Default 7 days.  Set to 0 to disable.
SIL_TRUST_DECAY_FACTOR: float = float(os.environ.get("SIL_TRUST_DECAY_FACTOR", "604800"))
# Attribution learning rate — used by record_resonance_attribution() for
# causal validation-based trust updates (separate from simple TD rate).
SIL_ATTRIBUTION_LR: float = float(os.environ.get("SIL_ATTRIBUTION_LR", "0.15"))
SIL_SATURATION_THRESHOLD: float = float(
    os.environ.get("SIL_SATURATION_THRESHOLD", "0.45")
)
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

_AUTHORITY_DOMAIN_ORDER = (
    "rollback",
    "risk",
    "market_signals",
    "exploration",
    "general",
)

_AUTHORITY_DOMAIN_KEYWORDS = {
    "rollback": frozenset({
        "rollback", "revert", "undo", "restore", "recover",
    }),
    "risk": frozenset({
        "risk", "stable", "stability", "safe", "guard", "health",
        "monitor", "ci", "test", "failure", "healthy", "pass", "success",
        "regression",
    }),
    "market_signals": frozenset({
        "ticker", "market", "trade", "trading", "price", "volume",
        "profit", "rsi", "swing", "signal", "exchange",
    }),
    "exploration": frozenset({
        "explore", "exploration", "learn", "learning", "discover",
        "research", "creative", "llm", "agent", "novel", "unknown",
        "anomaly", "spike", "warning", "error",
    }),
}


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
    authority_domains: List[str] = field(default_factory=list)
    # Phase 16.5: causal attribution records
    attribution_history: List[Dict[str, Any]] = field(default_factory=list)

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
            "authority_domains": self.authority_domains,
            "attribution_history": self.attribution_history[-30:],
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
            authority_domains=[
                str(domain) for domain in d.get("authority_domains", [])
            ],
            attribution_history=d.get("attribution_history", []),
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


def _normalize_authority_domains(domains: List[str]) -> List[str]:
    """Return ordered, deduplicated authority domains."""
    cleaned = {
        str(domain).strip().lower()
        for domain in domains
        if str(domain).strip()
    }
    if not cleaned:
        return ["general"]
    ordered = [domain for domain in _AUTHORITY_DOMAIN_ORDER if domain in cleaned]
    unordered = sorted(cleaned - set(_AUTHORITY_DOMAIN_ORDER))
    return ordered + unordered


def _infer_authority_domains(
    system_id: str,
    external_data: Dict[str, Any],
    current_objective: str,
) -> List[str]:
    """Infer governance domains from the system identity and observed signals."""
    tokens = " ".join(
        [system_id.lower(), current_objective.lower()]
        + [str(key).lower() for key in external_data]
    )
    domains = [
        domain
        for domain, keywords in _AUTHORITY_DOMAIN_KEYWORDS.items()
        if any(keyword in tokens for keyword in keywords)
    ]
    if not domains:
        domains = ["general"]
    return _normalize_authority_domains(domains)


def _objective_requires_safety(current_objective: str) -> bool:
    objective_lower = current_objective.lower()
    return any(
        word in objective_lower
        for word in ("stability", "safe", "risk", "rollback", "regression")
    )


def _authority_priority_score(domains: List[str], objective: str) -> float:
    """Return an objective-aware governance priority multiplier."""
    domain_set = set(domains)
    if _objective_requires_safety(objective):
        if domain_set & {"risk", "rollback"}:
            return 1.25
        if "market_signals" in domain_set:
            return 0.8
        if "exploration" in domain_set:
            return 0.35
    objective_lower = objective.lower()
    if any(word in objective_lower for word in ("explore", "learn", "discover")):
        if "exploration" in domain_set:
            return 1.15
        if domain_set & {"risk", "rollback"}:
            return 0.9
    return 1.0


def _apply_authority_scope(
    profile: ExternalSystemProfile,
    current_objective: str,
    explore_rate_adj: float,
    decision_threshold_adj: float,
) -> Tuple[float, float, List[str]]:
    """Clamp adjustments that fall outside a system's authority domains."""
    domains = set(profile.authority_domains or ["general"])
    governance_notes: List[str] = []

    if explore_rate_adj != 0.0 and "exploration" not in domains:
        explore_rate_adj = 0.0
        governance_notes.append("AUTHORITY_DENIED(exploration)")

    if decision_threshold_adj > 0.0 and not (domains & {"risk", "rollback"}):
        decision_threshold_adj = 0.0
        governance_notes.append("AUTHORITY_DENIED(risk)")

    if decision_threshold_adj < 0.0 and "market_signals" not in domains:
        decision_threshold_adj = 0.0
        governance_notes.append("AUTHORITY_DENIED(market_signals)")

    if (
        _objective_requires_safety(current_objective)
        and explore_rate_adj > 0.0
        and not (domains & {"risk", "rollback"})
    ):
        explore_rate_adj = 0.0
        governance_notes.append("SAFETY_OVERRIDE(exploration)")

    if (
        _objective_requires_safety(current_objective)
        and decision_threshold_adj < 0.0
        and not (domains & {"risk", "rollback"})
    ):
        decision_threshold_adj = 0.0
        governance_notes.append("SAFETY_OVERRIDE(threshold)")

    return explore_rate_adj, decision_threshold_adj, governance_notes


def _adjustment_magnitude(config: "ResonanceConfig") -> float:
    """Measure total deviation away from the neutral resonance baseline."""
    return (
        abs(1.0 - config.signal_weight_adj)
        + abs(config.explore_rate_adj)
        + abs(config.decision_threshold_adj)
    )


# ---------------------------------------------------------------------------
# Core public API
# ---------------------------------------------------------------------------

def _apply_trust_decay(profile: ExternalSystemProfile) -> ExternalSystemProfile:
    """Apply time-based exponential trust decay to a profile (in-place).

    ``new_trust = old_trust × exp(−Δt / SIL_TRUST_DECAY_FACTOR)``

    where Δt is the number of seconds elapsed since ``profile.last_mirrored``.
    Decayed trust is clamped to ``[SIL_MIN_SIGNAL_TRUST, 0.95]`` so a profile
    never becomes completely inert and can always recover via revalidation.

    Set ``SIL_TRUST_DECAY_FACTOR = 0`` in the environment to disable decay.
    """
    if SIL_TRUST_DECAY_FACTOR <= 0.0 or not profile.last_mirrored:
        return profile
    try:
        last = datetime.fromisoformat(profile.last_mirrored)
        dt_seconds = max(0.0, (datetime.now(timezone.utc) - last).total_seconds())
        decay = math.exp(-dt_seconds / SIL_TRUST_DECAY_FACTOR)
        profile.trust_weight = max(
            SIL_MIN_SIGNAL_TRUST,
            min(0.95, round(profile.trust_weight * decay, 4)),
        )
    except Exception as _decay_err:  # noqa: BLE001
        log.debug("[SIL] trust decay failed for %s: %s", profile.system_id, _decay_err)
    return profile


def mirror_system(
    system_id: str,
    external_data: Dict[str, Any],
    latency_ms: Optional[float] = None,
    current_objective: str = "",
    authority_domains: Optional[List[str]] = None,
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
    authority_domains : Optional explicit governance domains for this system.

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
    inferred_domains = _infer_authority_domains(
        system_id,
        external_data,
        current_objective,
    )
    if authority_domains is not None:
        profile.authority_domains = _normalize_authority_domains(authority_domains)
    else:
        profile.authority_domains = _normalize_authority_domains(
            profile.authority_domains + inferred_domains
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
        "authority_domains": profile.authority_domains,
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
                "authority_domains": profile.authority_domains,
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

    # Phase 16.5: apply time-based trust decay before deriving adjustments so
    # that stale profiles automatically lose influence between validations.
    profile = _apply_trust_decay(profile)

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

    explore_rate_adj, decision_threshold_adj, governance_notes = _apply_authority_scope(
        profile,
        current_objective,
        explore_rate_adj,
        decision_threshold_adj,
    )

    rationale_parts = [
        f"SIL/resonance({profile.system_id})",
        f"trust={signal_weight_adj:.3f}",
        f"explore_adj={explore_rate_adj:+.4f}",
        f"gate_adj={decision_threshold_adj:+.4f}",
        f"authority={','.join(profile.authority_domains or ['general'])}",
    ]
    if conflict:
        rationale_parts.append(f"OBJECTIVE_CONFLICT(penalty={penalty:.2f})")
    rationale_parts.extend(governance_notes)

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
        "authority_domains": profile.authority_domains,
        "governance_notes": governance_notes,
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


def get_all_profile_ids() -> List[str]:
    """Return the list of all currently known external system IDs."""
    return list(_load_state().get("profiles", {}).keys())


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


# ---------------------------------------------------------------------------
# Phase 16.5: Resonance Attribution Layer
# ---------------------------------------------------------------------------

def record_resonance_attribution(
    system_id: str,
    baseline_outcome: float,
    post_resonance_outcome: float,
    adjustments_applied: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Record causal attribution of resonance to an observed outcome improvement.

    This separates *signal* from *noise* in the trust update:
        - ``record_resonance_outcome()`` updates trust via simple correlation
          (observed outcome → TD update).
        - ``record_resonance_attribution()`` updates trust via causal attribution
          (Δoutcome caused by resonance → attribution-weighted TD update).

    The attribution TD rule is:
        ``resonance_delta = post_resonance_outcome − baseline_outcome``
        ``new_trust = clamp(old_trust + SIL_ATTRIBUTION_LR × resonance_delta)``

    By tracking both ``baseline_outcome`` (what the system would have done
    without resonance) and ``post_resonance_outcome`` (what happened after
    resonance was applied), callers can estimate how much of the improvement
    was *caused* by resonance rather than by background system behaviour.

    Parameters
    ----------
    system_id               : The external system whose resonance is being
                              attributed.
    baseline_outcome        : Outcome score before resonance was applied [0,1]
                              (e.g. objective_engine score pre-cycle).
    post_resonance_outcome  : Outcome score after resonance was applied [0,1]
                              (e.g. objective_engine score post-cycle).
    adjustments_applied     : The ``ResonanceConfig.to_dict()`` dict that was
                              applied this cycle (for audit).

    Returns
    -------
    The attribution record dict (also appended to ``profile.attribution_history``
    and logged to ``system_interface_log.jsonl``).
    """
    state = _load_state()
    profiles_raw: Dict[str, Any] = state.get("profiles", {})

    resonance_delta = round(float(post_resonance_outcome) - float(baseline_outcome), 4)

    attribution: Dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "system_id": system_id,
        "resonance_applied": True,
        "adjustments": adjustments_applied or {},
        "baseline_outcome": round(float(baseline_outcome), 4),
        "post_resonance_outcome": round(float(post_resonance_outcome), 4),
        "delta": resonance_delta,
    }

    if system_id in profiles_raw:
        profile = ExternalSystemProfile.from_dict(profiles_raw[system_id])

        profile.attribution_history.append(attribution)
        if len(profile.attribution_history) > 30:
            profile.attribution_history = profile.attribution_history[-30:]

        # Causal attribution trust update — stronger learning signal than
        # simple correlation because it explicitly measures the delta.
        old_trust = profile.trust_weight
        new_trust = max(
            SIL_MIN_SIGNAL_TRUST,
            min(0.95, old_trust + SIL_ATTRIBUTION_LR * resonance_delta),
        )
        profile.trust_weight = round(new_trust, 4)
        profiles_raw[system_id] = profile.to_dict()
        state["profiles"] = profiles_raw
        _save_state(state)

    _log_event("attribution", attribution)
    log.debug(
        "[SIL] attribution %s: delta=%.4f baseline=%.4f post=%.4f",
        system_id, resonance_delta, baseline_outcome, post_resonance_outcome,
    )
    return attribution


# ---------------------------------------------------------------------------
# Phase 16.5: Multi-system conflict resolution
# ---------------------------------------------------------------------------

def resolve_conflict(objective: str = "") -> Optional[ResonanceConfig]:
    """Resolve multi-system conflicts into a single :class:`ResonanceConfig`.

    When multiple external systems are active and their signals potentially
    disagree (e.g. one is bullish / explore, another is bearish / stabilise),
    this function computes a composite weight per system:

        ``weight = trust_weight × avg_confidence × objective_alignment_score``

    where ``objective_alignment_score = 1.0 − conflict_penalty``.

    The final :class:`ResonanceConfig` is a weighted average of all systems'
    resonance configs.  This ensures that high-trust, well-aligned systems
    dominate while low-trust or misaligned ones contribute proportionally less.

    Direct signal conflicts (one system says explore, another says stabilise)
    are detected and surfaced in the ``rationale`` field so callers can log
    or act on the disagreement.

    Parameters
    ----------
    objective : Niblit's current goal string (alignment guard).

    Returns
    -------
    A conflict-resolved :class:`ResonanceConfig`, or ``None`` if SIL is
    disabled or no profiles exist.
    """
    if not SIL_ENABLED:
        return None

    profiles_raw = _load_state().get("profiles", {})
    if not profiles_raw:
        return None

    profiles = [ExternalSystemProfile.from_dict(r) for r in profiles_raw.values()]

    if len(profiles) == 1:
        return establish_resonance(_apply_trust_decay(profiles[0]), objective)

    # Compute per-profile composite weight and resonance config
    items: List[Tuple[float, ResonanceConfig, str]] = []
    for profile in profiles:
        profile = _apply_trust_decay(profile)  # noqa: PLW2901 — apply decay inline

        conf_values = list(profile.confidence_model.values())
        avg_conf = statistics.mean(conf_values) if conf_values else 0.5

        _, penalty = _check_objective_conflict(profile, profile.signals, objective)
        alignment_score = max(0.0, 1.0 - penalty)

        authority_score = _authority_priority_score(profile.authority_domains, objective)
        composite_weight = profile.trust_weight * avg_conf * alignment_score * authority_score
        config = establish_resonance(profile, objective)
        items.append((composite_weight, config, profile.system_id))

    total_weight = sum(w for w, _, _ in items) or 1.0

    blended_explore = (
        sum(w * c.explore_rate_adj for w, c, _ in items) / total_weight
    )
    blended_threshold = (
        sum(w * c.decision_threshold_adj for w, c, _ in items) / total_weight
    )
    blended_signal = (
        sum(w * c.signal_weight_adj for w, c, _ in items) / total_weight
    )
    any_conflict = any(c.objective_conflict for _, c, _ in items)
    total_adjustment_magnitude = sum(
        _adjustment_magnitude(c) for _, c, _ in items
    )
    damping_factor = 1.0
    if total_adjustment_magnitude > SIL_SATURATION_THRESHOLD:
        damping_factor = max(
            0.1,
            round(SIL_SATURATION_THRESHOLD / total_adjustment_magnitude, 4),
        )
        blended_signal = 1.0 - ((1.0 - blended_signal) * damping_factor)
        blended_explore *= damping_factor
        blended_threshold *= damping_factor

    # Detect direct exploration / stabilisation conflict
    explore_adjs = [c.explore_rate_adj for _, c, _ in items]
    signal_conflict = (
        any(a > 0.0 for a in explore_adjs) and any(a < 0.0 for a in explore_adjs)
    )

    system_ids = [sid for _, _, sid in items]
    rationale = (
        f"SIL/conflict_resolved({len(profiles)} systems: {', '.join(system_ids)}) "
        f"signal_conflict={'yes' if signal_conflict else 'no'}"
    )
    if damping_factor < 1.0:
        rationale += f" | SATURATED(scale={damping_factor:.3f})"

    _log_event("conflict_resolved", {
        "system_ids": system_ids,
        "signal_conflict": signal_conflict,
        "objective": objective,
        "blended_signal_weight": round(blended_signal, 4),
        "blended_explore_adj": round(blended_explore, 4),
        "total_adjustment_magnitude": round(total_adjustment_magnitude, 4),
        "saturation_threshold": SIL_SATURATION_THRESHOLD,
        "damping_factor": damping_factor,
    })

    return ResonanceConfig(
        signal_weight_adj=round(blended_signal, 4),
        explore_rate_adj=round(blended_explore, 4),
        decision_threshold_adj=round(blended_threshold, 4),
        rationale=rationale,
        objective_conflict=any_conflict,
    )


def get_active_resonance(objective: str = "") -> Optional[ResonanceConfig]:
    """Return a conflict-resolved :class:`ResonanceConfig` across all known profiles.

    When multiple profiles exist, delegates to :func:`resolve_conflict` which
    weights each system by ``trust × confidence × objective_alignment``.  Falls
    back to the single-profile path when only one profile is known.

    Returns ``None`` when SIL is disabled or no profiles exist.
    """
    if not SIL_ENABLED:
        return None

    profiles_raw = _load_state().get("profiles", {})
    if not profiles_raw:
        return None

    if len(profiles_raw) == 1:
        profile = ExternalSystemProfile.from_dict(next(iter(profiles_raw.values())))
        return establish_resonance(profile, objective)

    # Phase 16.5: use conflict-resolution for multi-system scenarios
    return resolve_conflict(objective)


def status() -> Dict[str, Any]:
    """Return a diagnostic snapshot of the System Interface Layer."""
    state = _load_state()
    profiles_raw = state.get("profiles", {})

    profile_summaries = []
    for sid, raw in profiles_raw.items():
        profile = ExternalSystemProfile.from_dict(raw)
        # Compute decayed trust for display (doesn't mutate state)
        decayed_profile = _apply_trust_decay(
            ExternalSystemProfile.from_dict(raw)
        )
        attrs = profile.attribution_history
        recent_attrs = attrs[-5:] if attrs else []
        mean_attr_delta = (
            round(statistics.mean(a["delta"] for a in attrs), 4)
            if attrs else None
        )
        profile_summaries.append({
            "system_id": sid,
            "trust_weight": profile.trust_weight,
            "trust_weight_decayed": decayed_profile.trust_weight,
            "signal_count": len(profile.signals),
            "last_mirrored": profile.last_mirrored,
            "decision_structure": profile.decision_structure,
            "authority_domains": profile.authority_domains,
            "attribution_samples": len(attrs),
            "mean_attribution_delta": mean_attr_delta,
            "recent_attributions": recent_attrs,
        })

    return {
        "sil_enabled": SIL_ENABLED,
        "active_profiles": len(profiles_raw),
        "max_profiles": SIL_MAX_PROFILES,
        "resonance_lr": SIL_RESONANCE_LR,
        "attribution_lr": SIL_ATTRIBUTION_LR,
        "saturation_threshold": SIL_SATURATION_THRESHOLD,
        "trust_decay_factor_seconds": SIL_TRUST_DECAY_FACTOR,
        "objective_penalty": SIL_OBJECTIVE_PENALTY,
        "min_signal_trust": SIL_MIN_SIGNAL_TRUST,
        "authority_matrix": {
            sid: ExternalSystemProfile.from_dict(raw).authority_domains
            for sid, raw in profiles_raw.items()
        },
        "profiles": profile_summaries,
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
