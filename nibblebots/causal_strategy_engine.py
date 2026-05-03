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

Hardening (Phase 10 post-audit)
---------------------------------
Four defences against confident-but-wrong rule lock-in:

* **Soft matching** — rules are ranked by continuous-distance similarity
  rather than exact band equality, handling near-boundary conditions
  gracefully (``CSE_SOFT_MATCH_TOP_K`` best rules averaged).

* **Counterfactual pressure** — with probability
  ``CSE_COUNTERFACTUAL_RATE`` (10 %) the engine deliberately inverts the
  derived strategy for one cycle when trust > 0.7.  The outcome feeds back
  into the episode log, preventing premature exploitation lock-in.

* **Rule decay** — trust scores are attenuated by
  ``exp(-age / CSE_RULE_DECAY)`` where *age* is the number of episodes
  since the rule was derived, so stale rules lose influence over time.

* **Risk-adjusted batch size** — recommended batch is computed as
  ``round(base × trust × (1 − variance))`` and clamped to
  ``CSE_MAX_SAFE_BATCH``, limiting blast radius under high-variance rules.

Constants (overridable via env vars)
-------------------------------------
CSE_MIN_RULE_SAMPLES    : int   (env: CSE_MIN_RULE_SAMPLES,   default 5)
CSE_RULE_WINDOW         : int   (env: CSE_RULE_WINDOW,        default 100)
CSE_RECENCY_DECAY       : float (env: CSE_RECENCY_DECAY,      default 30.0)
CSE_VARIANCE_THRESHOLD  : float (env: CSE_VARIANCE_THRESHOLD, default 0.15)
CSE_DERIVE_INTERVAL     : int   (env: CSE_DERIVE_INTERVAL,    default 10)
CSE_COUNTERFACTUAL_RATE : float (env: CSE_COUNTERFACTUAL_RATE, default 0.10)
CSE_RULE_DECAY          : float (env: CSE_RULE_DECAY,          default 100.0)
CSE_SOFT_MATCH_TOP_K    : int   (env: CSE_SOFT_MATCH_TOP_K,    default 3)
CSE_MAX_SAFE_BATCH      : int   (env: CSE_MAX_SAFE_BATCH,       default 5)
"""

from __future__ import annotations

import json
import math
import os
import random
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

# Counterfactual pressure: probability of deliberately inverting a
# high-confidence rule to prevent exploitation lock-in.
CSE_COUNTERFACTUAL_RATE: float = float(
    os.environ.get("CSE_COUNTERFACTUAL_RATE", "0.10")
)
# Minimum trust score that triggers counterfactual challenges.
CSE_COUNTERFACTUAL_MIN_TRUST: float = float(
    os.environ.get("CSE_COUNTERFACTUAL_MIN_TRUST", "0.70")
)

# Rule age decay: trust is attenuated by exp(-age/CSE_RULE_DECAY) where
# age = current_episode_count - rule.derived_at_index.
CSE_RULE_DECAY: float = float(os.environ.get("CSE_RULE_DECAY", "100.0"))

# Soft matching: take top-k closest rules (by continuous distance) rather
# than requiring exact band equality.
CSE_SOFT_MATCH_TOP_K: int = int(os.environ.get("CSE_SOFT_MATCH_TOP_K", "3"))

# Blast-radius cap for recommended batch size under uncertainty.
CSE_MAX_SAFE_BATCH: int = int(os.environ.get("CSE_MAX_SAFE_BATCH", "5"))

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
        "is_counterfactual",        # bool: True when strategy was deliberately
                                    #       inverted for counterfactual testing
    )

    def __init__(
        self,
        exploration_rate_delta: float = 0.0,
        force_stability: bool = False,
        force_exploration: bool = False,
        recommended_batch_size: int = 3,
        confidence: float = 0.0,
        rationale: str = "",
        is_counterfactual: bool = False,
    ) -> None:
        self.exploration_rate_delta = float(exploration_rate_delta)
        self.force_stability = bool(force_stability)
        self.force_exploration = bool(force_exploration)
        self.recommended_batch_size = int(recommended_batch_size)
        self.confidence = float(confidence)
        self.rationale = str(rationale)
        self.is_counterfactual = bool(is_counterfactual)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "exploration_rate_delta": self.exploration_rate_delta,
            "force_stability": self.force_stability,
            "force_exploration": self.force_exploration,
            "recommended_batch_size": self.recommended_batch_size,
            "confidence": round(self.confidence, 4),
            "rationale": self.rationale,
            "is_counterfactual": self.is_counterfactual,
        }

    def __repr__(self) -> str:
        cf = " [COUNTERFACTUAL]" if self.is_counterfactual else ""
        return (
            f"StrategyAdvice(explore_delta={self.exploration_rate_delta:+.3f}, "
            f"batch={self.recommended_batch_size}, "
            f"conf={self.confidence:.3f}, "
            f"rationale={self.rationale!r}{cf})"
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
# Soft-matching helpers
# ---------------------------------------------------------------------------

# Representative midpoint values for each named band, used for continuous-
# distance calculation in soft rule matching.
_CONF_BAND_MIDPOINT: Dict[str, float] = {"low": 0.20, "medium": 0.55, "high": 0.85}
_VAR_BAND_MIDPOINT: Dict[str, float] = {"low": 0.075, "high": 0.25}
_MODE_MISMATCH_PENALTY: float = 0.50   # added to distance when modes differ

# Weights for the soft-distance formula:
#   distance = w_conf * |conf_diff| + w_signal * |signal_diff| + w_var * |var_diff|
# plus mode-mismatch penalty if applicable.
_W_CONF: float = 0.40
_W_SIGNAL: float = 0.35
_W_VAR: float = 0.25


def _rule_distance(
    rule: Dict[str, Any],
    confidence: float,
    signal_conf: float,
    variance: float,
    mode: str,
) -> float:
    """Compute a continuous distance between a rule's conditions and the
    current context.  Lower distance ⟹ better match."""
    conds = rule.get("conditions", {})
    r_conf = _CONF_BAND_MIDPOINT.get(conds.get("confidence_band", "medium"), 0.55)
    r_sig  = _CONF_BAND_MIDPOINT.get(conds.get("signal_band", "medium"), 0.55)
    r_var  = _VAR_BAND_MIDPOINT.get(conds.get("variance_band", "low"), 0.075)

    dist = (
        _W_CONF   * abs(confidence  - r_conf)
        + _W_SIGNAL * abs(signal_conf - r_sig)
        + _W_VAR    * abs(variance    - r_var)
    )
    if conds.get("mode") != mode:
        dist += _MODE_MISMATCH_PENALTY
    return dist


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


def _derive_adjustments(mean: float, variance: float, count: int, trust: float = 1.0) -> Dict[str, Any]:
    """Derive recommended parameter adjustments from rule statistics.

    Batch size is risk-adjusted: ``round(base × trust × (1 − variance))``,
    then clamped to [1, CSE_MAX_SAFE_BATCH].  This limits blast radius when
    the rule is uncertain (high variance) or has low trust.
    """
    if count < CSE_MIN_RULE_SAMPLES:
        return {"exploration_rate_delta": 0.0, "batch_size": 2}

    if mean > 0.5 and variance < CSE_VARIANCE_THRESHOLD:
        # High mean + low variance → exploit: reduce exploration, larger batches
        base_batch = 4
        explore_delta = -0.05
    elif mean > 0.5 and variance >= CSE_VARIANCE_THRESHOLD:
        # High mean + high variance → mixed: maintain rate, moderate batch
        base_batch = 2
        explore_delta = 0.0
    else:
        # Low mean → penalise: increase exploration, shrink batch
        base_batch = 1
        explore_delta = +0.05

    # Risk-adjusted batch: scale by trust and consistency
    risk_batch = max(1, round(base_batch * trust * (1.0 - variance)))
    capped_batch = min(risk_batch, CSE_MAX_SAFE_BATCH)
    return {"exploration_rate_delta": explore_delta, "batch_size": capped_batch}


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
            stats["mean"], stats["variance"], stats["count"], stats["trust_score"]
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
            "derived_at_index": episode_count,  # for age-based decay in query_strategy
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

    Hardening mechanisms applied here
    ----------------------------------
    1. **Soft matching** — all rules are ranked by continuous distance from
       the current context; the top ``CSE_SOFT_MATCH_TOP_K`` are blended by
       their (decayed) trust scores to produce the final advice.

    2. **Rule age decay** — each rule's effective trust is attenuated by
       ``exp(-age / CSE_RULE_DECAY)`` to prevent stale rules from dominating.

    3. **Counterfactual pressure** — when the winning rule has trust > 0.7,
       there is a ``CSE_COUNTERFACTUAL_RATE`` (10 %) probability of inverting
       the strategy for one cycle.  The inverted outcome feeds back into the
       episode log normally, providing a controlled challenge to the rule.

    4. **Risk-adjusted batch size** — batch is capped at
       ``CSE_MAX_SAFE_BATCH`` and scaled by trust × (1 − variance), already
       baked into ``recommended_adjustments`` during ``derive_rules()``.
    """
    state = _load_state()
    rules: List[Dict[str, Any]] = state.get("rules", [])
    episode_count: int = state.get("episode_count", 0)

    confidence = float(current_context.get("confidence", 0.5))
    signal_conf = float(current_context.get("signal_conf", 0.5))
    variance = float(current_context.get("variance", 0.0))
    mode = str(current_context.get("mode", ""))

    conf_band = _bucket_confidence(confidence)
    signal_band = _bucket_confidence(signal_conf)
    var_band = _bucket_variance(variance)

    if not rules:
        # No rules derived yet — unknown zone
        return StrategyAdvice(
            exploration_rate_delta=+0.10,
            force_exploration=True,
            recommended_batch_size=1,
            confidence=0.0,
            rationale=(
                f"unknown_zone: no rules derived yet "
                f"(conf={conf_band}/signal={signal_band}/var={var_band})"
                " — maximise exploration"
            ),
        )

    # ------------------------------------------------------------------
    # 1. Rank all rules by continuous distance from current context,
    #    then apply age-based decay to effective trust.
    # ------------------------------------------------------------------
    scored: List[Tuple[float, float, Dict[str, Any]]] = []  # (distance, decayed_trust, rule)
    for rule in rules:
        dist = _rule_distance(rule, confidence, signal_conf, variance, mode)
        raw_trust = float(rule.get("trust_score", 0.0))
        derived_at = int(rule.get("derived_at_index", 0))
        age = max(0, episode_count - derived_at)
        decayed_trust = raw_trust * math.exp(-age / max(1.0, CSE_RULE_DECAY))
        scored.append((dist, decayed_trust, rule))

    # Sort by distance ascending, break ties by decayed_trust descending
    scored.sort(key=lambda t: (t[0], -t[1]))

    # Keep top-k candidates
    top_k = scored[:max(1, CSE_SOFT_MATCH_TOP_K)]

    # Check whether the best match is a genuine near-miss or too far away.
    # A distance ≥ 1.0 means the closest rule is at least a full unit away
    # (e.g. mode mismatch + large numeric gap) — treat as unknown zone.
    best_dist = top_k[0][0]
    if best_dist >= 1.0:
        return StrategyAdvice(
            exploration_rate_delta=+0.10,
            force_exploration=True,
            recommended_batch_size=1,
            confidence=0.0,
            rationale=(
                f"unknown_zone: closest rule distance={best_dist:.3f} ≥ 1.0 "
                f"(conf={conf_band}/signal={signal_band}/var={var_band})"
                " — maximise exploration"
            ),
        )

    # ------------------------------------------------------------------
    # 2. Blend top-k rules weighted by decayed_trust (trust-weighted mean
    #    of explore_delta; majority-vote for batch size).
    # ------------------------------------------------------------------
    total_weight = sum(dt for _, dt, _ in top_k)
    if total_weight == 0.0:
        total_weight = 1.0  # guard against all-zero decay

    blended_explore_delta = 0.0
    batch_votes: List[int] = []
    blended_mean = 0.0
    blended_variance = 0.0

    for _dist, dt, rule in top_k:
        w = dt / total_weight
        adj = rule.get("recommended_adjustments", {})
        stats = rule.get("outcome_stats", {})
        blended_explore_delta += float(adj.get("exploration_rate_delta", 0.0)) * w
        batch_votes.append(int(adj.get("batch_size", 2)))
        blended_mean += float(stats.get("mean", 0.0)) * w
        blended_variance += float(stats.get("variance", 0.0)) * w

    # Majority-vote batch: use the median of top-k suggestions
    batch_votes.sort()
    mid = len(batch_votes) // 2
    blended_batch = batch_votes[mid]

    # Effective trust is the weighted-average decayed trust across top-k
    effective_trust = total_weight / len(top_k) if len(top_k) > 0 else 0.0
    # Normalise so it stays in [0, 1]
    effective_trust = min(1.0, effective_trust)

    # ------------------------------------------------------------------
    # 3. Determine force flags from blended statistics
    # ------------------------------------------------------------------
    if blended_mean > 0.5 and blended_variance < CSE_VARIANCE_THRESHOLD:
        force_stability = False
        force_exploration = False
        rule_type = "exploit"
    elif blended_mean > 0.5:
        force_stability = False
        force_exploration = False
        rule_type = "mixed"
    else:
        force_stability = False
        force_exploration = blended_explore_delta > 0
        rule_type = "penalise"

    rationale = (
        f"{rule_type}_blended(k={len(top_k)}): "
        f"mean={blended_mean:.3f} var={blended_variance:.3f} "
        f"trust={effective_trust:.3f} dist={best_dist:.3f} "
        f"→ explore_delta={blended_explore_delta:+.3f} batch={blended_batch}"
    )

    # ------------------------------------------------------------------
    # 4. Counterfactual pressure: deliberately invert the strategy
    #    when the matched rule is highly trusted, to prevent lock-in.
    # ------------------------------------------------------------------
    is_counterfactual = False
    if (
        effective_trust >= CSE_COUNTERFACTUAL_MIN_TRUST
        and random.random() < CSE_COUNTERFACTUAL_RATE
    ):
        is_counterfactual = True
        # Invert: flip exploration delta sign, shrink batch to 1 when
        # the rule recommended exploit, or increase it when it recommended
        # penalise.
        blended_explore_delta = -blended_explore_delta
        blended_batch = 1 if blended_batch > 1 else min(3, CSE_MAX_SAFE_BATCH)
        force_exploration = not force_exploration
        rationale = (
            f"COUNTERFACTUAL({rationale}): "
            f"inverted → explore_delta={blended_explore_delta:+.3f} batch={blended_batch}"
        )

    return StrategyAdvice(
        exploration_rate_delta=blended_explore_delta,
        force_stability=force_stability,
        force_exploration=force_exploration,
        recommended_batch_size=blended_batch,
        confidence=effective_trust,
        rationale=rationale,
        is_counterfactual=is_counterfactual,
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
        "cse_counterfactual_rate": CSE_COUNTERFACTUAL_RATE,
        "cse_counterfactual_min_trust": CSE_COUNTERFACTUAL_MIN_TRUST,
        "cse_rule_decay": CSE_RULE_DECAY,
        "cse_soft_match_top_k": CSE_SOFT_MATCH_TOP_K,
        "cse_max_safe_batch": CSE_MAX_SAFE_BATCH,
    }
