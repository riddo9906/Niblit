#!/usr/bin/env python3
"""modules/policy_optimizer.py — Policy Learning Layer for Niblit.

The PolicyOptimizer is the control-system upgrade that replaces static
nudges with a learned, per-context-type decision policy.

It sits between the MetaEngine (diagnostics) and the DecisionEngine
(execution), and is responsible for:

1. **Context classification** — infers the task type from the user input
   (``"chat"``, ``"code"``, ``"trading"``, ``"research"``) so the system
   can apply task-appropriate advisor strengths.

2. **Advisor capability profiles** — each advisor has known strengths per
   task type.  These multipliers condition the base weights *before*
   competition begins, replacing the one-size-fits-all approach.

3. **Uncertainty tracking** — rolling variance of each advisor's confidence
   across recent episodes.  High-uncertainty advisors are explored first,
   making exploration *informed* rather than random.

4. **Decision trajectory logging** — records ``(context_type, advisor,
   confidences, reward)`` episodes so the system can learn which advisors
   perform best in each context over time.

5. **Incremental policy learning** — every ``_LEARN_EVERY`` episodes the
   optimizer recomputes per-context policy values
   (``exploration_rate``, ``risk_preference``, ``priority_mode``)
   from historical win-weighted quality, replacing static rule-based nudges.

Architecture position::

    DecisionEngine
         ↑
    MetaEngine   (pattern diagnostics)
         ↑
    PolicyOptimizer  ← THIS MODULE
         ↑
    CognitiveIdentity  (personality + persistence)

Public API
----------
``DecisionEpisode``
    Immutable snapshot of one decision cycle.

``PolicyOptimizer.record_episode(...)``
    Log a completed episode and trigger incremental learning.

``PolicyOptimizer.get_context_overrides(context_type) → Dict[str, float]``
    Per-advisor weight multipliers conditioned on the current task context.

``PolicyOptimizer.classify_context(user_input, state) → str``
    Infer task type without any external dependencies.

``PolicyOptimizer.get_exploration_candidates(signals) → List[str]``
    Return non-winning advisor names sorted by uncertainty (highest first).

``PolicyOptimizer.record_meta_insight(patterns, slope, avg_quality)``
    Let the optimizer learn from MetaEngine behavioral diagnostics.

``get_policy_optimizer(**kwargs) → PolicyOptimizer``
    Process-level singleton.

Configuration (environment variables)::

    NIBLIT_POLICY_LEARN_EVERY   — re-learn policy every N episodes (default 20)
    NIBLIT_POLICY_MAX_EPISODES  — rolling episode buffer size          (default 500)
    NIBLIT_POLICY_MIN_EXPLORE   — floor for exploration_rate           (default 0.02)
    NIBLIT_POLICY_MAX_EXPLORE   — ceiling for exploration_rate         (default 0.35)
"""

from __future__ import annotations

import logging
import math
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("PolicyOptimizer")

# ── Configuration ─────────────────────────────────────────────────────────────

_LEARN_EVERY    = int(float(os.environ.get("NIBLIT_POLICY_LEARN_EVERY",  "20")))
_MAX_EPISODES   = int(float(os.environ.get("NIBLIT_POLICY_MAX_EPISODES", "500")))
_MIN_EXPLORE    = float(os.environ.get("NIBLIT_POLICY_MIN_EXPLORE",      "0.02"))
_MAX_EXPLORE    = float(os.environ.get("NIBLIT_POLICY_MAX_EXPLORE",      "0.35"))

# ── Advisor capability profiles ────────────────────────────────────────────────
# Per-task-type multipliers applied to base advisor weights.
# Values >1.0 boost an advisor; <1.0 suppresses it.
# These reflect each advisor's *domain strengths*, not absolute quality.

_CAPABILITY_PROFILES: Dict[str, Dict[str, float]] = {
    "code": {
        "reasoning": 1.35,
        "memory":    1.10,
        "llm":       1.15,
        "goal":      0.90,
        "quality":   1.10,
    },
    "trading": {
        "memory":    1.40,
        "reasoning": 1.25,
        "llm":       0.80,
        "goal":      1.10,
        "quality":   1.25,
    },
    "research": {
        "memory":    1.30,
        "llm":       1.20,
        "reasoning": 1.20,
        "goal":      0.90,
        "quality":   1.10,
    },
    "chat": {
        "llm":       1.30,
        "memory":    1.00,
        "reasoning": 0.90,
        "goal":      1.00,
        "quality":   1.00,
    },
}

# Default "balanced" profile used when context is unknown.
_DEFAULT_CAPABILITY: Dict[str, float] = {
    "memory":    1.00,
    "reasoning": 1.00,
    "llm":       1.00,
    "goal":      1.00,
    "quality":   1.00,
}

# ── Context keyword sets ───────────────────────────────────────────────────────

_CODE_KEYWORDS     = re.compile(
    r"\b(code|function|class|method|bug|debug|error|python|script|"
    r"algorithm|compile|syntax|import|module|variable|loop|array|"
    r"json|api|endpoint|database|sql)\b",
    re.IGNORECASE,
)
_TRADING_KEYWORDS  = re.compile(
    r"\b(buy|sell|trade|trading|market|price|pnl|profit|loss|signal|"
    r"forex|crypto|stock|equity|indicator|candle|ohlcv|strategy|"
    r"portfolio|position|order)\b",
    re.IGNORECASE,
)
_RESEARCH_KEYWORDS = re.compile(
    r"\b(explain|research|learn|study|what\s+is|what\s+are|how\s+does|"
    r"why\s+does|define|describe|summary|overview|history|science|"
    r"paper|concept|theory|evidence|analyze|compare)\b",
    re.IGNORECASE,
)

# ── Optional event bus ─────────────────────────────────────────────────────────

try:
    from modules.event_bus import (
        get_event_bus as _get_event_bus,
        NiblitEvent as _NiblitEvent,
        EVENT_POLICY_OPTIMIZED,
    )
    _EVENT_BUS_AVAILABLE = True
except ImportError:
    _get_event_bus = None  # type: ignore[assignment]
    _NiblitEvent = None  # type: ignore[assignment,misc]
    EVENT_POLICY_OPTIMIZED = "policy.optimized"
    _EVENT_BUS_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# DecisionEpisode
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DecisionEpisode:
    """Immutable record of one decision cycle.

    Attributes
    ----------
    context_type:        Classified task type (``"chat"|"code"|"trading"|"research"``).
    advisor_chosen:      Name of the advisor whose output was selected.
    advisor_confidences: ``{advisor_name: confidence}`` for all advisors this cycle.
    outcome_score:       RewardModel quality score for the response [0, 1].
    reward:              Normalised reward signal derived from outcome_score.
    ts:                  UNIX timestamp.
    """

    context_type: str
    advisor_chosen: str
    advisor_confidences: Dict[str, float]
    outcome_score: float
    reward: float
    ts: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "context_type": self.context_type,
            "advisor_chosen": self.advisor_chosen,
            "outcome_score": round(self.outcome_score, 3),
            "reward": round(self.reward, 3),
            "ts": self.ts,
        }


# ─────────────────────────────────────────────────────────────────────────────
# PolicyOptimizer
# ─────────────────────────────────────────────────────────────────────────────

class PolicyOptimizer:
    """Policy learning layer — replaces reactive rule nudges with learned policies.

    The optimizer observes ``(context, advisor, reward)`` tuples over time
    and learns which advisors are most effective in each context.  This
    information is surfaced as:

    * **Capability weight multipliers** — applied by DecisionEngine *before*
      competitive selection to condition the field for the current task type.
    * **Uncertainty-ordered exploration candidates** — instead of picking a
      random non-winner, the system explores the advisor with the *highest
      uncertainty* in its recent confidence, maximising information gain.
    * **Per-context policy parameters** — ``exploration_rate``,
      ``risk_preference``, and ``priority_mode`` are computed from episode
      history rather than updated by fixed deltas.

    Args:
        cognitive_identity: :class:`~modules.cognitive_identity.CognitiveIdentity`
                            instance.  When provided, ``record_episode``
                            writes learned policy back to the identity
                            layer for persistence.
    """

    def __init__(self, cognitive_identity: Optional[Any] = None) -> None:
        self._identity = cognitive_identity
        self._lock = threading.Lock()

        # Rolling episode log.
        self._episodes: List[DecisionEpisode] = []

        # Per-advisor running uncertainty (variance of recent confidences).
        # Initialised to 0.5 so all advisors start equally uncertain.
        self._advisor_uncertainty: Dict[str, float] = {
            adv: 0.5 for adv in ("memory", "reasoning", "goal", "llm", "quality")
        }

        # Per-advisor rolling confidence sum & count for variance tracking.
        self._conf_sum: Dict[str, float] = {}
        self._conf_sq_sum: Dict[str, float] = {}
        self._conf_count: Dict[str, int] = {}

        # Learned per-context policy overrides (updated every _LEARN_EVERY episodes).
        # Structure: {context_type: {exploration_rate, risk_preference, priority_mode}}
        self._context_policies: Dict[str, Dict[str, Any]] = {}

        # Per-context capability multiplier adjustments learned from episode history.
        # These *add to* (or scale) the static _CAPABILITY_PROFILES.
        self._learned_multipliers: Dict[str, Dict[str, float]] = {}

        self._total_episodes = 0
        self._learn_cycles = 0

        log.info("[PolicyOptimizer] Initialised — context-aware policy learning active")

    # ── Primary API ───────────────────────────────────────────────────────────

    def record_episode(
        self,
        context_type: str,
        advisor_chosen: str,
        advisor_confidences: Dict[str, float],
        outcome_score: float,
    ) -> None:
        """Log a completed decision episode and trigger incremental learning.

        Args:
            context_type:        Task type from :meth:`classify_context`.
            advisor_chosen:      Name of the winning advisor.
            advisor_confidences: Confidence values for all advisors this cycle.
            outcome_score:       RewardModel quality score in [0, 1].
        """
        # Normalise reward: centre on 0.5 so [0,1] → [-1,+1] range-ish.
        reward = (outcome_score - 0.50) * 2.0

        episode = DecisionEpisode(
            context_type=context_type,
            advisor_chosen=advisor_chosen,
            advisor_confidences=dict(advisor_confidences),
            outcome_score=outcome_score,
            reward=reward,
        )

        with self._lock:
            self._episodes.append(episode)
            if len(self._episodes) > _MAX_EPISODES:
                self._episodes.pop(0)
            self._total_episodes += 1

            # Update uncertainty tracking for all advisors this cycle.
            for adv, conf in advisor_confidences.items():
                self.__update_uncertainty(adv, conf)

            # Trigger learning every _LEARN_EVERY episodes.
            should_learn = (self._total_episodes % _LEARN_EVERY == 0)

        if should_learn:
            self._learn_from_episodes()

    def get_context_overrides(self, context_type: str) -> Dict[str, float]:
        """Return per-advisor weight multipliers for the given *context_type*.

        Combines the static capability profile with any learned adjustments
        from episode history.  The DecisionEngine applies these on top of
        the base adaptive weights so context shapes the competition.

        Returns a ``{advisor_name: multiplier}`` dict.
        """
        base = dict(_CAPABILITY_PROFILES.get(context_type, _DEFAULT_CAPABILITY))
        with self._lock:
            learned = self._learned_multipliers.get(context_type, {})
        for adv in base:
            base[adv] = round(base[adv] * learned.get(adv, 1.0), 4)
        return base

    def classify_context(
        self, user_input: str, state: Optional[Any] = None
    ) -> str:
        """Infer the task type from *user_input* using keyword matching.

        Priority order: trading > code > research > chat.
        Also checks ``state.context["task_type"]`` if available (caller-set).

        Returns one of ``"chat"``, ``"code"``, ``"trading"``, ``"research"``.
        """
        # Allow callers to set an explicit task_type in state.
        if state is not None:
            ctx = getattr(state, "context", {}) or {}
            explicit = ctx.get("task_type")
            if explicit in _CAPABILITY_PROFILES:
                return explicit

        text = (user_input or "").lower()
        if _TRADING_KEYWORDS.search(text):
            return "trading"
        if _CODE_KEYWORDS.search(text):
            return "code"
        if _RESEARCH_KEYWORDS.search(text):
            return "research"
        return "chat"

    def get_exploration_candidates(
        self, signals: List[Any], chosen_name: str
    ) -> List[Any]:
        """Return non-winning *signals* sorted by advisor uncertainty, highest first.

        This replaces blind random exploration with *informed* exploration:
        the advisor whose confidence has varied the most recently is explored
        first, maximising information gain per exploration step.

        Args:
            signals:      List of :class:`~modules.decision_engine.AdvisorSignal`.
            chosen_name:  Name of the advisor already selected as winner.

        Returns:
            Filtered, sorted list of ``AdvisorSignal`` (non-winners, non-empty).
        """
        non_winners = [
            s for s in signals
            if s.suggestion and s.name != chosen_name
        ]
        with self._lock:
            unc = dict(self._advisor_uncertainty)
        return sorted(
            non_winners,
            key=lambda s: unc.get(s.name, 0.5),
            reverse=True,
        )

    def get_context_policy(self, context_type: str) -> Dict[str, Any]:
        """Return the learned policy dict for *context_type*.

        Falls back to sensible defaults when not enough history exists.
        """
        with self._lock:
            pol = self._context_policies.get(context_type)
        if pol:
            return dict(pol)
        # Default fallbacks per context type.
        defaults: Dict[str, Dict[str, Any]] = {
            "trading":  {"exploration_rate": 0.05, "risk_preference": "conservative", "priority_mode": "quality_first"},
            "code":     {"exploration_rate": 0.08, "risk_preference": "balanced",     "priority_mode": "quality_first"},
            "research": {"exploration_rate": 0.12, "risk_preference": "balanced",     "priority_mode": "balanced"},
            "chat":     {"exploration_rate": 0.15, "risk_preference": "balanced",     "priority_mode": "balanced"},
        }
        return defaults.get(context_type, {
            "exploration_rate": 0.10,
            "risk_preference":  "balanced",
            "priority_mode":    "balanced",
        })

    def record_meta_insight(
        self,
        patterns: List[str],
        slope: float,
        avg_quality: float,
    ) -> None:
        """Notify the optimizer of MetaEngine behavioral patterns.

        When the MetaEngine detects systematic issues (over-reliance,
        coherence drift, quality degradation), the PolicyOptimizer can
        use these signals to boost exploration or tighten policy for the
        affected context.

        Args:
            patterns:    List of pattern strings from ``MetaInsight``.
            slope:       Quality slope from trajectory analysis.
            avg_quality: Rolling average quality score.
        """
        if not patterns:
            return

        # Any systematic problem → increase exploration to escape the current policy.
        explore_boost = 0.0
        if any("over_reliance" in p or "coherence_drift" in p for p in patterns):
            explore_boost = 0.03
        if "quality_degradation" in patterns:
            explore_boost = max(explore_boost, 0.02)

        if explore_boost > 0.0 and self._identity is not None and hasattr(
            self._identity, "update_decision_policy"
        ):
            try:
                self._identity.update_decision_policy(exploration_nudge=explore_boost)
                log.debug(
                    "[PolicyOptimizer] Meta insight applied — exploration +%.3f for patterns=%s",
                    explore_boost, patterns,
                )
            except Exception as exc:
                log.debug("[PolicyOptimizer] identity update_decision_policy failed: %s", exc)

    def status(self) -> Dict[str, Any]:
        """Return serialisable status for health/status endpoints."""
        with self._lock:
            return {
                "total_episodes": self._total_episodes,
                "learn_cycles": self._learn_cycles,
                "context_policies": dict(self._context_policies),
                "advisor_uncertainty": {k: round(v, 4) for k, v in self._advisor_uncertainty.items()},
            }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def __update_uncertainty(self, advisor: str, confidence: float) -> None:
        """Update rolling variance for *advisor* using Welford's online algorithm.

        Uncertainty is the variance of the advisor's confidence stream.
        High variance → advisor is unpredictable → worth exploring.
        Low variance → advisor is consistent → less urgency to explore.

        Threading: **Must be called while ``self._lock`` is held.**
        All call sites in this class hold the lock before calling this method.
        External callers must not invoke this method directly.
        """
        n = self._conf_count.get(advisor, 0) + 1
        self._conf_count[advisor] = n
        self._conf_sum[advisor] = self._conf_sum.get(advisor, 0.0) + confidence
        self._conf_sq_sum[advisor] = self._conf_sq_sum.get(advisor, 0.0) + confidence * confidence

        mean = self._conf_sum[advisor] / n
        # Population variance = E[X²] − E[X]²
        variance = max(0.0, (self._conf_sq_sum[advisor] / n) - mean ** 2)
        self._advisor_uncertainty[advisor] = round(math.sqrt(variance), 4)

    def _learn_from_episodes(self) -> None:
        """Recompute per-context policies from the rolling episode log.

        For each context type seen in the last ``_MAX_EPISODES`` episodes:

        1. Compute per-advisor average reward when chosen (win-weighted quality).
        2. Update learned capability multipliers: advisors with above-average
           reward get a small boost; below-average get a gentle decay.
        3. Derive exploration_rate from reward variance (high variance →
           explore more; low variance + good scores → reduce exploration).
        4. Derive risk_preference from rolling average reward.
        5. Derive priority_mode from which capability dimension is dominant.

        All changes are conservative (clamped) to prevent oscillation.
        """
        with self._lock:
            episodes = list(self._episodes)

        if len(episodes) < 5:
            return

        # Group by context_type.
        by_context: Dict[str, List[DecisionEpisode]] = {}
        for ep in episodes:
            by_context.setdefault(ep.context_type, []).append(ep)

        new_policies: Dict[str, Dict[str, Any]] = {}
        new_multipliers: Dict[str, Dict[str, float]] = {}

        for ctx, eps in by_context.items():
            if len(eps) < 3:
                continue

            # ── Per-advisor average reward when chosen ─────────────────────
            adv_rewards: Dict[str, List[float]] = {}
            for ep in eps:
                adv_rewards.setdefault(ep.advisor_chosen, []).append(ep.reward)

            adv_avg_reward: Dict[str, float] = {
                adv: sum(rs) / len(rs) for adv, rs in adv_rewards.items()
            }

            overall_avg = sum(ep.reward for ep in eps) / len(eps)

            # ── Update capability multipliers ──────────────────────────────
            current_mult = dict(self._learned_multipliers.get(ctx, {}))
            for adv, avg_r in adv_avg_reward.items():
                curr = current_mult.get(adv, 1.0)
                if avg_r > overall_avg + 0.05:
                    curr = min(1.50, curr + 0.02)
                elif avg_r < overall_avg - 0.10:
                    curr = max(0.60, curr - 0.02)
                current_mult[adv] = round(curr, 4)
            new_multipliers[ctx] = current_mult

            # ── Exploration rate from reward variance ──────────────────────
            rewards = [ep.reward for ep in eps]
            reward_mean = sum(rewards) / len(rewards)
            reward_var = sum((r - reward_mean) ** 2 for r in rewards) / len(rewards)
            reward_std = math.sqrt(reward_var)

            # High std → policy is unstable → explore more.
            # Low std + positive mean → stable → explore less.
            if reward_mean > 0.2 and reward_std < 0.20:
                exploration_rate = max(_MIN_EXPLORE, 0.08 - reward_mean * 0.05)
            else:
                exploration_rate = min(_MAX_EXPLORE, 0.10 + reward_std * 0.20)
            exploration_rate = round(exploration_rate, 4)

            # ── Risk preference from average quality ───────────────────────
            avg_quality = sum(ep.outcome_score for ep in eps) / len(eps)
            if avg_quality < 0.38:
                risk_preference = "conservative"
            elif avg_quality > 0.65:
                risk_preference = "bold"
            else:
                risk_preference = "balanced"

            # ── Priority mode from dominant capability area ─────────────────
            # If goal-aligned advisors (goal) win most, use goal_first.
            # If quality advisor wins most, use quality_first.
            # Otherwise balanced.
            goal_wins = adv_rewards.get("goal", [])
            quality_wins = adv_rewards.get("quality", [])
            goal_score = sum(goal_wins) / len(goal_wins) if goal_wins else -1.0
            quality_score = sum(quality_wins) / len(quality_wins) if quality_wins else -1.0

            if goal_score > 0.10 and goal_score > quality_score:
                priority_mode = "goal_first"
            elif quality_score > 0.10:
                priority_mode = "quality_first"
            else:
                priority_mode = "balanced"

            new_policies[ctx] = {
                "exploration_rate": exploration_rate,
                "risk_preference":  risk_preference,
                "priority_mode":    priority_mode,
            }

        with self._lock:
            self._context_policies.update(new_policies)
            self._learned_multipliers.update(new_multipliers)
            self._learn_cycles += 1

        # Publish learned policies to any subscribers.
        if _EVENT_BUS_AVAILABLE and _get_event_bus is not None:
            try:
                _get_event_bus().publish(_NiblitEvent(
                    type=EVENT_POLICY_OPTIMIZED,
                    source="policy_optimizer",
                    payload={
                        "learn_cycle": self._learn_cycles,
                        "contexts_updated": list(new_policies.keys()),
                        "new_policies": new_policies,
                    },
                ))
            except Exception:
                pass

        log.info(
            "[PolicyOptimizer] learn_cycle=%d contexts=%s",
            self._learn_cycles, list(new_policies.keys()),
        )

        # Propagate the most-used context policy to CognitiveIdentity.
        with self._lock:
            episodes_snap = list(self._episodes)
        if episodes_snap and self._identity is not None and hasattr(
            self._identity, "update_decision_policy"
        ):
            dominant_ctx = max(
                set(ep.context_type for ep in episodes_snap),
                key=lambda c: sum(1 for ep in episodes_snap if ep.context_type == c),
            )
            dominant_policy = new_policies.get(dominant_ctx)
            if dominant_policy and hasattr(self._identity, "update_decision_policy"):
                try:
                    self._identity.update_decision_policy(
                        risk_preference=dominant_policy["risk_preference"],
                        priority_mode=dominant_policy["priority_mode"],
                    )
                except Exception as exc:
                    log.debug("[PolicyOptimizer] identity sync failed: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────────────────

_optimizer: Optional[PolicyOptimizer] = None
_optimizer_lock = threading.Lock()


def get_policy_optimizer(**kwargs: Any) -> PolicyOptimizer:
    """Return the process-level :class:`PolicyOptimizer` singleton.

    Note: kwargs are only applied on first call.
    """
    global _optimizer  # pylint: disable=global-statement
    with _optimizer_lock:
        if _optimizer is None:
            _optimizer = PolicyOptimizer(**kwargs)
        return _optimizer


if __name__ == "__main__":
    from modules.cognitive_identity import get_cognitive_identity

    ident = get_cognitive_identity()
    opt = get_policy_optimizer(cognitive_identity=ident)

    # Simulate 25 episodes across three context types.
    import random as _rand
    _rand.seed(42)
    for i in range(25):
        ctx = _rand.choice(["chat", "code", "trading"])
        adv = _rand.choice(["memory", "reasoning", "llm", "quality", "goal"])
        confs = {a: round(_rand.uniform(0.1, 0.9), 3) for a in ["memory", "reasoning", "llm", "quality", "goal"]}
        score = round(_rand.uniform(0.3, 0.9), 3)
        opt.record_episode(ctx, adv, confs, score)

    print("Status:", opt.status())
    print("Code overrides:", opt.get_context_overrides("code"))
    print("Trading policy:", opt.get_context_policy("trading"))
    print("Context classify:", opt.classify_context("debug my python function"))
