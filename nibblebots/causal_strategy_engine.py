#!/usr/bin/env python3
"""
nibblebots/causal_strategy_engine.py — Phase 10/11/12 Causal Strategy Learning

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

Validation (Phase 11)
----------------------
Four additional mechanisms to move from correlation to causation:

* **Paired counterfactual scoring** — when a counterfactual is issued,
  the expected outcome (blended_mean of matched rules) is stored in state.
  The next ``record_episode()`` call picks it up, computes
  ``counterfactual_delta = (actual − expected) × signal_conf`` (confidence-
  normalised so noisy environments cannot corrupt rule learning), and
  accumulates it on the rule via ``counterfactual_score`` in
  ``derive_rules()``.  Positive delta means the inverted strategy
  outperformed expectations; negative means the original strategy was
  genuinely better.

* **Rule-blending agreement factor** — when top-K rules are blended, the
  combined variance of their exploration-rate suggestions, batch-size
  suggestions, and subsystem alignment is computed.  High disagreement
  between rules reduces effective trust, preventing confidently blending
  contradictory rules across all strategy dimensions.

* **Dominance detection** — every query increments a per-rule usage
  counter.  Rules whose selection rate exceeds ``CSE_DOMINANCE_THRESHOLD``
  (70 %) receive a *dynamic* trust penalty proportional to the excess:
  ``penalty = (usage_rate − threshold) × CSE_DOMINANCE_SCALE``, discouraging
  strategy monoculture while avoiding both over- and under-reaction.

* **Directional advice** — ``StrategyAdvice`` now carries
  ``target_subsystem`` and ``priority_fix_type`` derived from impact-weighted
  episode evidence (``sum(outcome × signal_conf)`` per candidate), not mere
  frequency.  This aligns direction with impact rather than volume.

Generalisation & Transfer (Phase 12)
--------------------------------------
Three mechanisms to distinguish narrow hacks from robust strategies:

* **Cross-context generalisation score** — when a rule is applied to a
  context whose distance from the rule's training band is non-trivial
  (> ``CSE_GENERALIZATION_BAND``), the query stores a
  ``pending_generalization`` token in state.  The next ``record_episode()``
  call marks that episode with the rule key and context distance.
  ``derive_rules()`` aggregates these cross-context episodes into a
  ``generalization_score`` per rule:
  positive (good cross-context performance) means the rule is robust;
  negative means it is a narrow hack that should stay in its home band.

* **Value-weighted directional selection** — ``target_subsystem`` and
  ``priority_fix_type`` are now chosen by ``argmax(∑ outcome × signal_conf)``
  across episodes in the rule's bucket, aligning effort with impact rather
  than with frequency.

* **Multi-dimensional agreement factor** — the agreement penalty now covers
  exploration-delta variance, batch-size variance, and subsystem-alignment
  variance across the top-K blended rules, ensuring all strategy dimensions
  are internally consistent before high confidence is awarded.

Constants (overridable via env vars)
-------------------------------------
CSE_MIN_RULE_SAMPLES      : int   (env: CSE_MIN_RULE_SAMPLES,       default 5)
CSE_RULE_WINDOW           : int   (env: CSE_RULE_WINDOW,            default 100)
CSE_RECENCY_DECAY         : float (env: CSE_RECENCY_DECAY,          default 30.0)
CSE_VARIANCE_THRESHOLD    : float (env: CSE_VARIANCE_THRESHOLD,     default 0.15)
CSE_DERIVE_INTERVAL       : int   (env: CSE_DERIVE_INTERVAL,        default 10)
CSE_COUNTERFACTUAL_RATE   : float (env: CSE_COUNTERFACTUAL_RATE,    default 0.10)
CSE_RULE_DECAY            : float (env: CSE_RULE_DECAY,             default 100.0)
CSE_SOFT_MATCH_TOP_K      : int   (env: CSE_SOFT_MATCH_TOP_K,       default 3)
CSE_MAX_SAFE_BATCH        : int   (env: CSE_MAX_SAFE_BATCH,         default 5)
CSE_DOMINANCE_THRESHOLD   : float (env: CSE_DOMINANCE_THRESHOLD,    default 0.70)
CSE_DOMINANCE_SCALE       : float (env: CSE_DOMINANCE_SCALE,         default 0.50)
CSE_GENERALIZATION_BAND   : float (env: CSE_GENERALIZATION_BAND,     default 0.20)
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

# Dominance detection: rules selected more than this fraction of total
# queries receive a dynamic trust penalty to prevent strategy monoculture.
CSE_DOMINANCE_THRESHOLD: float = float(
    os.environ.get("CSE_DOMINANCE_THRESHOLD", "0.70")
)
# Phase 12: dynamic dominance penalty scale.
# penalty = (usage_rate − threshold) × CSE_DOMINANCE_SCALE
# This replaces the flat CSE_DOMINANCE_PENALTY with a proportional response.
CSE_DOMINANCE_SCALE: float = float(
    os.environ.get("CSE_DOMINANCE_SCALE", "0.50")
)

# Phase 12: minimum context distance for a rule application to be counted
# as a cross-context (generalisation) test rather than an in-band match.
CSE_GENERALIZATION_BAND: float = float(
    os.environ.get("CSE_GENERALIZATION_BAND", "0.20")
)

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
        "target_subsystem",         # str: subsystem to focus on (may be empty)
        "priority_fix_type",        # str: fix type to prioritise (may be empty)
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
        target_subsystem: str = "",
        priority_fix_type: str = "",
    ) -> None:
        self.exploration_rate_delta = float(exploration_rate_delta)
        self.force_stability = bool(force_stability)
        self.force_exploration = bool(force_exploration)
        self.recommended_batch_size = int(recommended_batch_size)
        self.confidence = float(confidence)
        self.rationale = str(rationale)
        self.is_counterfactual = bool(is_counterfactual)
        self.target_subsystem = str(target_subsystem)
        self.priority_fix_type = str(priority_fix_type)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "exploration_rate_delta": self.exploration_rate_delta,
            "force_stability": self.force_stability,
            "force_exploration": self.force_exploration,
            "recommended_batch_size": self.recommended_batch_size,
            "confidence": round(self.confidence, 4),
            "rationale": self.rationale,
            "is_counterfactual": self.is_counterfactual,
            "target_subsystem": self.target_subsystem,
            "priority_fix_type": self.priority_fix_type,
        }

    def __repr__(self) -> str:
        cf = " [COUNTERFACTUAL]" if self.is_counterfactual else ""
        direction = ""
        if self.target_subsystem:
            direction = f" subsystem={self.target_subsystem!r}"
        if self.priority_fix_type:
            direction += f" fix={self.priority_fix_type!r}"
        return (
            f"StrategyAdvice(explore_delta={self.exploration_rate_delta:+.3f}, "
            f"batch={self.recommended_batch_size}, "
            f"conf={self.confidence:.3f}, "
            f"rationale={self.rationale!r}{cf}{direction})"
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
        "query_count": 0,             # Phase 11: total query calls for dominance calc
        "rule_usage_counts": {},      # Phase 11: {rule_key: int} usage frequency
        "pending_counterfactual": None,  # Phase 11: {expected_outcome, rule_key} or None
        "pending_generalization": None,  # Phase 12: {rule_key, context_distance} or None
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

    Phase 11: if a counterfactual was previously dispatched
    (``pending_counterfactual`` set in state), this episode's
    ``counterfactual_delta`` is computed as ``outcome − expected_outcome``
    and stored so ``derive_rules()`` can aggregate it per-rule.
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

    # Phase 11: consume pending counterfactual — compute delta vs expected outcome.
    # Phase 12: normalize delta by signal_conf so noisy environments cannot
    # corrupt rule learning (high uncertainty → smaller weight on the delta).
    pending_cf = state.get("pending_counterfactual")
    if pending_cf is not None:
        expected = float(pending_cf.get("expected_outcome", outcome))
        raw_delta = float(outcome) - expected
        adjusted_delta = raw_delta * max(0.0, float(signal_conf))
        episode["counterfactual_delta"] = round(adjusted_delta, 4)
        episode["counterfactual_rule_key"] = pending_cf.get("rule_key", "")
        state["pending_counterfactual"] = None  # consumed

    # Phase 12: consume pending generalisation token — mark this episode so
    # derive_rules() can compute a cross-context generalisation score.
    pending_gen = state.get("pending_generalization")
    if pending_gen is not None:
        episode["gen_rule_key"] = pending_gen.get("rule_key", "")
        episode["gen_context_distance"] = float(pending_gen.get("context_distance", 0.0))
        state["pending_generalization"] = None  # consumed

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

    Phase 11 additions
    ------------------
    * ``target_subsystem`` — the most common subsystem across the group's
      episodes; guides the planner on *where* to focus.
    * ``priority_fix_type`` — the most common fix_type across the group's
      episodes; guides selection of which fix category to prioritise.
    * ``counterfactual_score`` — mean of ``counterfactual_delta`` values
      from episodes that were recorded immediately after a counterfactual
      dispatch for this rule.  Positive = inverted strategy beat expectations;
      negative = original strategy was genuinely better.

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

        # Phase 11/12: derive directional hints from impact-weighted episode evidence.
        # Phase 12 upgrade: use sum(outcome × signal_conf) instead of bare frequency,
        # so subsystems/fix_types that yield higher-impact outcomes rank higher.
        subsystem_scores: Dict[str, float] = {}
        fix_type_scores: Dict[str, float] = {}
        for ep in recent_eps:
            sub = ep.get("subsystem", "")
            ft = ep.get("fix_type", "")
            weight = float(ep.get("outcome", 0.0)) * max(0.0, float(ep.get("signal_conf", 0.5)))
            if sub:
                subsystem_scores[sub] = subsystem_scores.get(sub, 0.0) + weight
            if ft:
                fix_type_scores[ft] = fix_type_scores.get(ft, 0.0) + weight

        target_subsystem = (
            max(subsystem_scores, key=lambda k: subsystem_scores[k])
            if subsystem_scores else ""
        )
        priority_fix_type = (
            max(fix_type_scores, key=lambda k: fix_type_scores[k])
            if fix_type_scores else ""
        )

        # Phase 11: aggregate counterfactual scores for episodes attributed
        # to this rule key.
        cf_deltas = [
            float(ep["counterfactual_delta"])
            for ep in recent_eps
            if "counterfactual_delta" in ep
            and ep.get("counterfactual_rule_key", "") == key
        ]
        counterfactual_score = round(sum(cf_deltas) / len(cf_deltas), 4) if cf_deltas else 0.0

        # Phase 12: generalisation score — aggregated from episodes where this
        # rule was applied to a context outside its home band.  Positive means
        # the rule transfers well; negative means it is a narrow hack.
        gen_episodes = [
            ep for ep in recent_eps
            if ep.get("gen_rule_key", "") == key
            and float(ep.get("gen_context_distance", 0.0)) > CSE_GENERALIZATION_BAND
        ]
        if gen_episodes:
            # Weight each episode's contribution by (1 − distance/1.0) so
            # further-out applications are slightly discounted.
            gen_weighted = sum(
                float(ep.get("outcome", 0.0)) * max(0.0, 1.0 - float(ep.get("gen_context_distance", 0.0)))
                for ep in gen_episodes
            )
            gen_score = round(gen_weighted / len(gen_episodes) - 0.5, 4)  # centre on 0
        else:
            gen_score = 0.0

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
            "target_subsystem": target_subsystem,    # Phase 11/12
            "priority_fix_type": priority_fix_type,  # Phase 11/12
            "counterfactual_score": counterfactual_score,  # Phase 11
            "generalization_score": gen_score,             # Phase 12
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

    Phase 11 additions
    ------------------
    5. **Agreement factor** — the combined variance of explore-delta,
       batch-size, and subsystem-alignment values across top-K rules is used
       to compute a multi-dimensional agreement penalty.  High disagreement
       across any strategy dimension reduces effective trust.

    6. **Dominance detection** — tracks per-rule selection frequency; rules
       exceeding ``CSE_DOMINANCE_THRESHOLD`` receive a *dynamic* trust penalty
       proportional to the excess:
       ``penalty = (rate − threshold) × CSE_DOMINANCE_SCALE``.

    7. **Paired counterfactual scoring** — when issuing a counterfactual
       inversion, the expected outcome (blended_mean) is stored in state as
       ``pending_counterfactual``.  The next ``record_episode()`` call reads
       it, computes ``(actual − expected) × signal_conf``, and stores the
       normalised delta so ``derive_rules()`` can aggregate it as
       ``counterfactual_score``.

    8. **Directional advice** — ``StrategyAdvice.target_subsystem`` and
       ``priority_fix_type`` are populated from impact-weighted episode
       evidence (``argmax ∑ outcome × signal_conf``).

    Phase 12 additions
    ------------------
    9. **Cross-context generalisation tracking** — when the best rule is
       applied at a context distance > ``CSE_GENERALIZATION_BAND``, a
       ``pending_generalization`` token is stored in state so the next
       ``record_episode()`` can mark the outcome as a cross-context test.
       ``derive_rules()`` aggregates these into ``generalization_score``
       per rule.
    """
    state = _load_state()
    rules: List[Dict[str, Any]] = state.get("rules", [])
    episode_count: int = state.get("episode_count", 0)
    query_count: int = int(state.get("query_count", 0))
    rule_usage_counts: Dict[str, int] = state.get("rule_usage_counts", {})

    confidence = float(current_context.get("confidence", 0.5))
    signal_conf = float(current_context.get("signal_conf", 0.5))
    variance = float(current_context.get("variance", 0.0))
    mode = str(current_context.get("mode", ""))

    conf_band = _bucket_confidence(confidence)
    signal_band = _bucket_confidence(signal_conf)
    var_band = _bucket_variance(variance)

    # Increment global query counter (Phase 11 dominance tracking)
    query_count += 1
    state["query_count"] = query_count

    if not rules:
        # No rules derived yet — unknown zone
        _save_state(state)
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
        _save_state(state)
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
    explore_deltas: List[float] = []       # Phase 11/12: for multi-dim agreement
    batch_sizes_float: List[float] = []   # Phase 12: for batch-variance agreement
    top_subsystem = top_k[0][2].get("target_subsystem", "") if top_k else ""

    for _dist, dt, rule in top_k:
        w = dt / total_weight
        adj = rule.get("recommended_adjustments", {})
        stats = rule.get("outcome_stats", {})
        delta = float(adj.get("exploration_rate_delta", 0.0))
        batch_size = int(adj.get("batch_size", 2))
        blended_explore_delta += delta * w
        explore_deltas.append(delta)
        batch_votes.append(batch_size)
        batch_sizes_float.append(float(batch_size))
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
    # Phase 12: Multi-dimensional agreement factor — penalise blending of
    # contradictory rules across all strategy dimensions.
    # combined_var = var(explore_delta) + 0.1×var(batch_size) + 0.1×var(subsystem_alignment)
    # agreement = 1 / (1 + combined_var)
    # ------------------------------------------------------------------
    if len(explore_deltas) > 1:
        delta_variance = statistics.pvariance(explore_deltas)
        batch_variance = statistics.pvariance(batch_sizes_float)
        # Subsystem alignment: 0.0 if rule agrees with best rule's subsystem, 1.0 if not
        subsys_enc = [
            0.0 if rule.get("target_subsystem", "") == top_subsystem else 1.0
            for _, _, rule in top_k
        ]
        subsys_variance = statistics.pvariance(subsys_enc) if len(subsys_enc) > 1 else 0.0
        combined_var = delta_variance + 0.1 * batch_variance + 0.1 * subsys_variance
        agreement = 1.0 / (1.0 + combined_var)
        effective_trust *= agreement
    else:
        agreement = 1.0

    # ------------------------------------------------------------------
    # Phase 12: Dynamic dominance penalty — proportional to excess usage,
    # replacing the flat Phase 11 penalty.
    # penalty = (usage_rate − threshold) × CSE_DOMINANCE_SCALE
    # ------------------------------------------------------------------
    best_rule_key = top_k[0][2].get("key", "")
    if best_rule_key and query_count > 0:
        usage = int(rule_usage_counts.get(best_rule_key, 0))
        # Include the current selection in the rate for an accurate reading.
        usage_rate = (usage + 1) / query_count
        if usage_rate > CSE_DOMINANCE_THRESHOLD:
            excess = usage_rate - CSE_DOMINANCE_THRESHOLD
            penalty = excess * CSE_DOMINANCE_SCALE
            effective_trust = max(0.0, effective_trust - penalty)
    # Track usage of the top-1 selected rule
    if best_rule_key:
        rule_usage_counts[best_rule_key] = int(rule_usage_counts.get(best_rule_key, 0)) + 1
    state["rule_usage_counts"] = rule_usage_counts

    # ------------------------------------------------------------------
    # Phase 11.8 / 12: Directional advice — populate subsystem / fix_type
    # hints from the best-matched rule (already impact-weighted in derive_rules).
    # Phase 12: also store pending_generalization when applied cross-context.
    # ------------------------------------------------------------------
    best_rule = top_k[0][2]
    target_subsystem = str(best_rule.get("target_subsystem", ""))
    priority_fix_type = str(best_rule.get("priority_fix_type", ""))

    # Phase 12: if the rule was applied outside its home band, register a
    # pending_generalization token so the outcome can update generalization_score.
    if best_rule_key and best_dist > CSE_GENERALIZATION_BAND:
        state["pending_generalization"] = {
            "rule_key": best_rule_key,
            "context_distance": round(best_dist, 4),
        }

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
        f"trust={effective_trust:.3f} agree={agreement:.3f} dist={best_dist:.3f} "
        f"→ explore_delta={blended_explore_delta:+.3f} batch={blended_batch}"
    )

    # ------------------------------------------------------------------
    # 4. Counterfactual pressure: deliberately invert the strategy
    #    when the matched rule is highly trusted, to prevent lock-in.
    #    Phase 11: also persist expected outcome for paired scoring.
    # ------------------------------------------------------------------
    is_counterfactual = False
    if (
        effective_trust >= CSE_COUNTERFACTUAL_MIN_TRUST
        and random.random() < CSE_COUNTERFACTUAL_RATE
    ):
        is_counterfactual = True
        # Phase 11: store expected outcome so the next record_episode()
        # can compute counterfactual_delta = actual − expected.
        state["pending_counterfactual"] = {
            "expected_outcome": round(blended_mean, 4),
            "rule_key": best_rule_key,
        }
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

    _save_state(state)

    return StrategyAdvice(
        exploration_rate_delta=blended_explore_delta,
        force_stability=force_stability,
        force_exploration=force_exploration,
        recommended_batch_size=blended_batch,
        confidence=effective_trust,
        rationale=rationale,
        is_counterfactual=is_counterfactual,
        target_subsystem=target_subsystem,
        priority_fix_type=priority_fix_type,
    )


# ---------------------------------------------------------------------------
# Inspection / status
# ---------------------------------------------------------------------------

def status() -> Dict[str, Any]:
    """Return a summary of the causal strategy engine state."""
    state = _load_state()
    rules = state.get("rules", [])
    query_count = int(state.get("query_count", 0))
    rule_usage_counts: Dict[str, int] = state.get("rule_usage_counts", {})

    # Compute dominance summary: rules whose usage_rate > threshold
    dominant_rules = []
    if query_count > 0:
        for r in rules:
            key = r.get("key", "")
            usage = int(rule_usage_counts.get(key, 0))
            rate = usage / query_count
            if rate > CSE_DOMINANCE_THRESHOLD:
                dominant_rules.append({"key": key, "usage_rate": round(rate, 3)})

    # Phase 12: generalisation summary — rules ranked by generalization_score
    generalization_summary = sorted(
        [
            {
                "key": r.get("key", ""),
                "generalization_score": r.get("generalization_score", 0.0),
                "trust_score": r.get("trust_score", 0.0),
            }
            for r in rules
            if r.get("generalization_score", 0.0) != 0.0
        ],
        key=lambda x: -x["generalization_score"],
    )[:5]

    return {
        "episode_count": state.get("episode_count", 0),
        "last_derive_count": state.get("last_derive_count", 0),
        "rule_count": len(rules),
        "query_count": query_count,
        "dominant_rules": dominant_rules,
        "top_rules": rules[:5],
        "generalization_summary": generalization_summary,
        "cse_min_rule_samples": CSE_MIN_RULE_SAMPLES,
        "cse_variance_threshold": CSE_VARIANCE_THRESHOLD,
        "cse_recency_decay": CSE_RECENCY_DECAY,
        "cse_derive_interval": CSE_DERIVE_INTERVAL,
        "cse_counterfactual_rate": CSE_COUNTERFACTUAL_RATE,
        "cse_counterfactual_min_trust": CSE_COUNTERFACTUAL_MIN_TRUST,
        "cse_rule_decay": CSE_RULE_DECAY,
        "cse_soft_match_top_k": CSE_SOFT_MATCH_TOP_K,
        "cse_max_safe_batch": CSE_MAX_SAFE_BATCH,
        "cse_dominance_threshold": CSE_DOMINANCE_THRESHOLD,
        "cse_dominance_scale": CSE_DOMINANCE_SCALE,
        "cse_generalization_band": CSE_GENERALIZATION_BAND,
    }
