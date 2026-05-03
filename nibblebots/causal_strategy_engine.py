#!/usr/bin/env python3
"""
nibblebots/causal_strategy_engine.py — Phase 10 Causal Strategy Learning

Moves the system from mode→outcome tracking to condition→outcome rule
formation.  Instead of "exploration worked", the system learns:

    exploration worked WHEN signal_conf > 0.6, subsystem = error_handling,
    CI volatility low

This is the final barrier before causal blindness is eliminated.

How it works
------------
1. Every cycle: ``record_episode()`` stores the full context vector with
   the outcome score, bucketing continuous values into named bands.

2. Periodically: ``derive_rules()`` groups episodes by their condition
   tuple (mode × confidence_band × signal_band × variance_band) and for
   each sufficiently-sampled group computes a recency-weighted,
   variance-penalised trust score — the same statistical formula as
   Phase 9.5b's ``get_mode_score()``.

3. Per cycle: ``query_strategy()`` matches current conditions against
   derived rules and returns a ``StrategyAdvice`` with concrete parameter
   adjustments (exploration_rate_delta, recommended_batch_size, etc.).

Decision matrix
---------------
Matched rule type               → Action
──────────────────────────────────────────────────────────────
High mean + low variance + N≥5  → Exploit (reduce explore, increase batch)
High mean + high variance       → Mixed (maintain rate, gather more data)
Low mean (≤ 0.5) + any          → Penalise (increase explore, shrink batch)
No rule match (unknown zone)    → Explore (max explore, batch = 1)

The "unknown zone" path directly solves the Phase 9.5b gap: when
``get_mode_score()`` would have returned ``0.0`` (no matching history),
this engine signals maximum uncertainty, triggering aggressive exploration
rather than treating absence of evidence as evidence of neutrality.

Constants (overridable via env vars)
-------------------------------------
CSE_MIN_RULE_SAMPLES    : int   (env: CSE_MIN_RULE_SAMPLES,   default 5)
CSE_RULE_WINDOW         : int   (env: CSE_RULE_WINDOW,        default 100)
CSE_RECENCY_DECAY       : float (env: CSE_RECENCY_DECAY,      default 30.0)
CSE_VARIANCE_THRESHOLD  : float (env: CSE_VARIANCE_THRESHOLD, default 0.15)
CSE_DERIVE_INTERVAL     : int   (env: CSE_DERIVE_INTERVAL,    default 10)
"""

from __future__ import annotations

import json
import math
import os
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CSE_MIN_RULE_SAMPLES: int = int(os.environ.get("CSE_MIN_RULE_SAMPLES", "5"))
CSE_RULE_WINDOW: int = int(os.environ.get("CSE_RULE_WINDOW", "100"))
CSE_RECENCY_DECAY: float = float(os.environ.get("CSE_RECENCY_DECAY", "30.0"))
CSE_VARIANCE_THRESHOLD: float = float(os.environ.get("CSE_VARIANCE_THRESHOLD", "0.15"))
CSE_DERIVE_INTERVAL: int = int(os.environ.get("CSE_DERIVE_INTERVAL", "10"))

# Confidence (and signal) bands: (lower_inclusive, upper_exclusive, label)
# The last band uses 1.01 so that value == 1.0 is captured as "high".
CSE_CONFIDENCE_BANDS: List[Tuple[float, float, str]] = [
    (0.0,  0.4,  "low"),
    (0.4,  0.7,  "medium"),
    (0.7,  1.01, "high"),
]

# Total episode cap — prevents unbounded state growth
_CSE_MAX_EPISODES: int = CSE_RULE_WINDOW * 10  # 1 000

_STATE_FILE = Path(__file__).parent / "causal_strategy_state.json"
_RULES_LOG_FILE = Path(__file__).parent / "causal_strategy_rules.jsonl"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class StrategyAdvice:
    """Concrete parameter adjustments returned by ``query_strategy()``."""

    __slots__ = (
        "exploration_rate_delta",   # float: signed delta for EXPLORATION_RATE
        "force_stability",          # bool: strongly prefer stability mode
        "force_exploration",        # bool: strongly prefer exploration mode
        "recommended_batch_size",   # int: hint for evolution_planner max_fixes
        "confidence",               # float [0, 1]: trust score of matched rule
        "rationale",                # str: human-readable reason for audit log
    )

    def __init__(
        self,
        exploration_rate_delta: float = 0.0,
        force_stability: bool = False,
        force_exploration: bool = False,
        recommended_batch_size: int = 3,
        confidence: float = 0.0,
        rationale: str = "",
    ) -> None:
        self.exploration_rate_delta = float(exploration_rate_delta)
        self.force_stability = bool(force_stability)
        self.force_exploration = bool(force_exploration)
        self.recommended_batch_size = int(recommended_batch_size)
        self.confidence = float(confidence)
        self.rationale = str(rationale)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "exploration_rate_delta": self.exploration_rate_delta,
            "force_stability": self.force_stability,
            "force_exploration": self.force_exploration,
            "recommended_batch_size": self.recommended_batch_size,
            "confidence": round(self.confidence, 4),
            "rationale": self.rationale,
        }

    def __repr__(self) -> str:
        return (
            f"StrategyAdvice(explore_delta={self.exploration_rate_delta:+.3f}, "
            f"batch={self.recommended_batch_size}, "
            f"conf={self.confidence:.3f}, "
            f"rationale={self.rationale!r})"
        )


# ---------------------------------------------------------------------------
# Bucketing helpers
# ---------------------------------------------------------------------------

def _bucket(value: float, bands: List[Tuple[float, float, str]]) -> str:
    """Map a continuous value into a named band label."""
    for lo, hi, label in bands:
        if lo <= value < hi:
            return label
    # Fall through: return the last label (handles edge cases such as value == 1.0)
    return bands[-1][2]


def _bucket_confidence(v: float) -> str:
    return _bucket(v, CSE_CONFIDENCE_BANDS)


def _bucket_variance(v: float) -> str:
    return "low" if v < CSE_VARIANCE_THRESHOLD else "high"


def _episode_key(mode: str, conf_band: str, signal_band: str, var_band: str) -> str:
    """Canonical pipe-delimited key for an episode bucket."""
    return f"{mode}|{conf_band}|{signal_band}|{var_band}"


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def _load_state() -> Dict[str, Any]:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "episodes": [],
        "rules": [],
        "episode_count": 0,
        "last_derive_count": 0,
    }


def _save_state(state: Dict[str, Any]) -> None:
    state["episodes"] = state.get("episodes", [])[-_CSE_MAX_EPISODES:]
    try:
        _STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        pass


def _log_rules(rules: List[Dict[str, Any]], episode_count: int) -> None:
    """Append a snapshot of derived rules to the JSONL audit log."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "episode_count": episode_count,
        "rule_count": len(rules),
        "rules": rules,
    }
    try:
        with _RULES_LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Core: record_episode
# ---------------------------------------------------------------------------

def record_episode(
    mode: str,
    outcome: float,
    confidence: float = 0.5,
    signal_conf: float = 0.5,
    intent_score: float = 1.0,
    variance: float = 0.0,
    fix_type: str = "",
    subsystem: str = "",
) -> None:
    """Record one completed cycle for causal rule learning.

    Parameters
    ----------
    mode         : mode used this cycle ("exploit" | "explore" | "stability")
    outcome      : outcome score [0, 1]; higher = better
    confidence   : avg_confidence at cycle time
    signal_conf  : signal_reliability at cycle time
    intent_score : intent alignment score
    variance     : variance estimate of recent outcomes (0.0 if unavailable)
    fix_type     : dominant fix type applied this cycle
    subsystem    : dominant subsystem targeted this cycle
    """
    state = _load_state()
    episodes: List[Dict[str, Any]] = state.get("episodes", [])
    episode_count: int = state.get("episode_count", 0)

    conf_band = _bucket_confidence(confidence)
    signal_band = _bucket_confidence(signal_conf)
    var_band = _bucket_variance(variance)

    episode: Dict[str, Any] = {
        "mode": mode,
        "outcome": float(outcome),
        "confidence": float(confidence),
        "signal_conf": float(signal_conf),
        "intent_score": float(intent_score),
        "variance": float(variance),
        "fix_type": fix_type,
        "subsystem": subsystem,
        "conf_band": conf_band,
        "signal_band": signal_band,
        "var_band": var_band,
        "episode_index": episode_count,  # monotonic index for recency weighting
    }
    episodes.append(episode)
    episode_count += 1
    state["episodes"] = episodes
    state["episode_count"] = episode_count

    # Periodically re-derive rules
    last_derive: int = state.get("last_derive_count", 0)
    if episode_count - last_derive >= CSE_DERIVE_INTERVAL:
        _save_state(state)
        derive_rules()   # derive_rules saves state internally
        return

    _save_state(state)


# ---------------------------------------------------------------------------
# Core: derive_rules
# ---------------------------------------------------------------------------

def _compute_rule_stats(
    episodes: List[Dict[str, Any]],
    max_idx: int,
) -> Dict[str, Any]:
    """Compute recency-weighted mean, variance, and trust score for a group."""
    n = len(episodes)
    weighted_sum = 0.0
    total_weight = 0.0
    outcomes: List[float] = []

    for ep in episodes:
        age = max(0, max_idx - ep.get("episode_index", 0))
        w = math.exp(-age / max(1.0, CSE_RECENCY_DECAY))
        outcome = float(ep.get("outcome", 0.0))
        weighted_sum += outcome * w
        total_weight += w
        outcomes.append(outcome)

    if total_weight == 0.0:
        return {"mean": 0.0, "variance": 0.0, "count": n, "trust_score": 0.0}

    weighted_mean = weighted_sum / total_weight

    # Population variance over raw outcomes (same formula as Phase 9.5b)
    variance = statistics.pvariance(outcomes) if n > 1 else 0.0

    # Trust score = sample confidence × stability factor
    sample_confidence = min(1.0, n / max(1, CSE_MIN_RULE_SAMPLES))
    stability_factor = 1.0 / (1.0 + variance)
    trust_score = sample_confidence * stability_factor

    return {
        "mean": round(weighted_mean, 4),
        "variance": round(variance, 4),
        "count": n,
        "trust_score": round(trust_score, 4),
    }


def _derive_adjustments(mean: float, variance: float, count: int) -> Dict[str, Any]:
    """Derive recommended parameter adjustments from rule statistics."""
    if count < CSE_MIN_RULE_SAMPLES:
        return {"exploration_rate_delta": 0.0, "batch_size": 2}

    if mean > 0.5 and variance < CSE_VARIANCE_THRESHOLD:
        # High mean + low variance → exploit: reduce exploration, larger batches
        return {"exploration_rate_delta": -0.05, "batch_size": 4}
    elif mean > 0.5 and variance >= CSE_VARIANCE_THRESHOLD:
        # High mean + high variance → mixed: maintain rate, moderate batch
        return {"exploration_rate_delta": 0.0, "batch_size": 2}
    else:
        # Low mean → penalise: increase exploration, shrink batch
        return {"exploration_rate_delta": +0.05, "batch_size": 1}


def derive_rules() -> List[Dict[str, Any]]:
    """Scan episode log and crystallise recurring patterns into strategy rules.

    Rules are grouped by (mode × confidence_band × signal_band × variance_band).
    Only groups with at least ``CSE_MIN_RULE_SAMPLES`` episodes are promoted.

    Returns the list of derived rules (also persisted to state and audit log).
    """
    state = _load_state()
    episodes: List[Dict[str, Any]] = state.get("episodes", [])
    episode_count: int = state.get("episode_count", 0)

    if not episodes:
        return []

    max_idx = max(ep.get("episode_index", 0) for ep in episodes)

    # Group episodes by their condition key
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for ep in episodes:
        key = _episode_key(
            ep.get("mode", "exploit"),
            ep.get("conf_band", "medium"),
            ep.get("signal_band", "medium"),
            ep.get("var_band", "low"),
        )
        groups.setdefault(key, []).append(ep)

    rules: List[Dict[str, Any]] = []
    for key, group_eps in groups.items():
        n = len(group_eps)
        if n < CSE_MIN_RULE_SAMPLES:
            continue  # Insufficient evidence — wait for more data

        # Use the most recent CSE_RULE_WINDOW episodes per bucket
        group_sorted = sorted(group_eps, key=lambda e: e.get("episode_index", 0))
        recent_eps = group_sorted[-CSE_RULE_WINDOW:]

        stats = _compute_rule_stats(recent_eps, max_idx)
        adjustments = _derive_adjustments(
            stats["mean"], stats["variance"], stats["count"]
        )

        parts = key.split("|")
        mode, conf_band, signal_band, var_band = (
            parts[0], parts[1], parts[2], parts[3]
        )

        rule: Dict[str, Any] = {
            "key": key,
            "conditions": {
                "mode": mode,
                "confidence_band": conf_band,
                "signal_band": signal_band,
                "variance_band": var_band,
            },
            "outcome_stats": stats,
            "recommended_adjustments": adjustments,
            "trust_score": stats["trust_score"],
        }
        rules.append(rule)

    # Sort by trust_score descending so query_strategy always picks the best first
    rules.sort(key=lambda r: -r["trust_score"])

    state["rules"] = rules
    state["last_derive_count"] = episode_count
    _save_state(state)

    _log_rules(rules, episode_count)
    return rules


# ---------------------------------------------------------------------------
# Core: query_strategy
# ---------------------------------------------------------------------------

def query_strategy(current_context: Dict[str, Any]) -> StrategyAdvice:
    """Find the best matching strategy rule for the current context.

    Parameters
    ----------
    current_context : dict with keys:
        - confidence  : float [0, 1]
        - signal_conf : float [0, 1]
        - variance    : float (recent outcome variance, 0.0 if unknown)
        - mode        : str   (proposed mode, informational only)

    Returns
    -------
    StrategyAdvice with concrete adjustments and a confidence rating.
    An advice confidence of 0.0 signals "unknown zone — explore freely".
    """
    state = _load_state()
    rules: List[Dict[str, Any]] = state.get("rules", [])

    confidence = float(current_context.get("confidence", 0.5))
    signal_conf = float(current_context.get("signal_conf", 0.5))
    variance = float(current_context.get("variance", 0.0))

    conf_band = _bucket_confidence(confidence)
    signal_band = _bucket_confidence(signal_conf)
    var_band = _bucket_variance(variance)

    # Mode-agnostic matching: find all rules for the current condition bands
    matching = [
        r for r in rules
        if (
            r.get("conditions", {}).get("confidence_band") == conf_band
            and r.get("conditions", {}).get("signal_band") == signal_band
            and r.get("conditions", {}).get("variance_band") == var_band
        )
    ]

    if not matching:
        # Unknown zone: no historical data for these conditions
        return StrategyAdvice(
            exploration_rate_delta=+0.10,
            force_exploration=True,
            recommended_batch_size=1,
            confidence=0.0,
            rationale=(
                f"unknown_zone: no rules for "
                f"conf={conf_band}/signal={signal_band}/var={var_band}"
                " — maximise exploration"
            ),
        )

    # Pick the highest-trust matching rule (list is pre-sorted by trust_score desc)
    best = matching[0]
    stats = best.get("outcome_stats", {})
    adjustments = best.get("recommended_adjustments", {})
    trust = float(best.get("trust_score", 0.0))

    mean = float(stats.get("mean", 0.0))
    rule_variance = float(stats.get("variance", 0.0))
    count = int(stats.get("count", 0))

    explore_delta = float(adjustments.get("exploration_rate_delta", 0.0))
    batch_size = int(adjustments.get("batch_size", 2))

    if mean > 0.5 and rule_variance < CSE_VARIANCE_THRESHOLD and count >= CSE_MIN_RULE_SAMPLES:
        rationale = (
            f"exploit_rule: mean={mean:.3f} var={rule_variance:.3f} "
            f"trust={trust:.3f} → reduce exploration, batch={batch_size}"
        )
        force_stability = False
        force_exploration = False
    elif mean > 0.5 and rule_variance >= CSE_VARIANCE_THRESHOLD:
        rationale = (
            f"mixed_rule: mean={mean:.3f} var={rule_variance:.3f} (high) "
            f"trust={trust:.3f} → gather more data"
        )
        force_stability = False
        force_exploration = False
    else:
        rationale = (
            f"penalise_rule: mean={mean:.3f} var={rule_variance:.3f} "
            f"trust={trust:.3f} → increase exploration"
        )
        force_stability = False
        force_exploration = explore_delta > 0

    return StrategyAdvice(
        exploration_rate_delta=explore_delta,
        force_stability=force_stability,
        force_exploration=force_exploration,
        recommended_batch_size=batch_size,
        confidence=trust,
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Inspection / status
# ---------------------------------------------------------------------------

def status() -> Dict[str, Any]:
    """Return a summary of the causal strategy engine state."""
    state = _load_state()
    rules = state.get("rules", [])
    return {
        "episode_count": state.get("episode_count", 0),
        "last_derive_count": state.get("last_derive_count", 0),
        "rule_count": len(rules),
        "top_rules": rules[:5],
        "cse_min_rule_samples": CSE_MIN_RULE_SAMPLES,
        "cse_variance_threshold": CSE_VARIANCE_THRESHOLD,
        "cse_recency_decay": CSE_RECENCY_DECAY,
        "cse_derive_interval": CSE_DERIVE_INTERVAL,
    }
