#!/usr/bin/env python3
"""modules/decision_engine.py — Single Decision Authority Layer (SDAL) for Niblit.

The DecisionEngine is the architectural "single gate" that all cognitive
signals pass through before any output reaches the user or the execution
layer.  No advisor writes directly to the user — all signals are collected
independently and the highest-scoring one is selected via true competition.

Competitive advisor model
--------------------------
All five advisors run **independently** and produce ``(suggestion,
confidence)`` pairs.  The winner is chosen by maximum
``effective_score = confidence × weight × identity_bias``.  This is
real cognitive competition, not a sequential fallback pipeline.

Advisors
--------
1. ``MemoryAdvisor``    — ``SmartRecall.think_about()`` + fact recall
2. ``ReasoningAdvisor`` — ``ReasoningEngine.chain_of_thought()``
3. ``GoalAdvisor``      — checks alignment with ``state.active_goal``
4. ``LLMAdvisor``       — ``LocalBrain`` / ``NiblitCloudBrain`` inference
5. ``QualityAdvisor``   — ``RewardModel.score()`` applied to LLM output

Goal enforcement
-----------------
When ``state.active_goal`` is set and a candidate response does not align
with the active goal topic, its effective score is penalised by
``_GOAL_PENALTY`` (default 0.5).  This ensures active goals shape every
decision, not just appear as context.

Adaptive weights
-----------------
Weights are no longer static env-vars.  On every call to ``decide()``,
current weights are fetched from ``EvaluationEngine.get_weights()`` (if
available) so they reflect the reinforcement feedback loop.  The env-var
defaults ``NIBLIT_SDAL_W_*`` are used only as seeds on first initialisation.

Public API
----------
``AdvisorSignal``
    Output of one advisor.  Carries ``name``, ``suggestion``,
    ``confidence``, ``weight``, ``effective_score``, ``latency_ms``.

``DecisionResult``
    Carries ``action``, ``chosen_advisor``, ``confidence``, ``rationale``,
    ``signals``, ``latency_ms``, ``ts``.

``DecisionEngine.decide(state, user_input, llm_fn) → DecisionResult``
    Run all advisors competitively and return the highest-scoring result.

``get_decision_engine(**kwargs) → DecisionEngine``
    Process-level singleton.

Configuration (environment variables)::

    NIBLIT_SDAL_W_MEMORY     — Memory advisor seed weight   (default 0.20)
    NIBLIT_SDAL_W_REASONING  — Reasoning advisor seed weight (default 0.20)
    NIBLIT_SDAL_W_GOAL       — Goal advisor seed weight      (default 0.10)
    NIBLIT_SDAL_W_LLM        — LLM advisor seed weight       (default 0.40)
    NIBLIT_SDAL_W_QUALITY    — Quality advisor seed weight   (default 0.10)
    NIBLIT_SDAL_GOAL_PENALTY — Confidence multiplier when misaligned with
                               the active goal               (default 0.50)
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("DecisionEngine")

# ── Seed weights (env-tuneable; overridden at runtime by EvaluationEngine) ────

_W_MEMORY    = float(os.environ.get("NIBLIT_SDAL_W_MEMORY",    "0.20"))
_W_REASONING = float(os.environ.get("NIBLIT_SDAL_W_REASONING", "0.20"))
_W_GOAL      = float(os.environ.get("NIBLIT_SDAL_W_GOAL",      "0.10"))
_W_LLM       = float(os.environ.get("NIBLIT_SDAL_W_LLM",       "0.40"))
_W_QUALITY   = float(os.environ.get("NIBLIT_SDAL_W_QUALITY",   "0.10"))

# Goal misalignment penalty — applied to effective_score when a response
# does not align with the currently active goal topic.
_GOAL_PENALTY = float(os.environ.get("NIBLIT_SDAL_GOAL_PENALTY", "0.50"))

# ── Optional dependency imports (all gracefully degrade) ──────────────────────

try:
    from modules.knowledge_recall import get_smart_recall as _get_smart_recall
    _SMART_RECALL_AVAILABLE = True
except ImportError:
    _get_smart_recall = None  # type: ignore[assignment]
    _SMART_RECALL_AVAILABLE = False

try:
    from modules.reasoning_engine import get_reasoning_engine as _get_reasoning_engine
    _REASONING_AVAILABLE = True
except ImportError:
    _get_reasoning_engine = None  # type: ignore[assignment]
    _REASONING_AVAILABLE = False

try:
    from modules.reward_model import get_reward_model as _get_reward_model
    _REWARD_MODEL_AVAILABLE = True
except ImportError:
    _get_reward_model = None  # type: ignore[assignment]
    _REWARD_MODEL_AVAILABLE = False

try:
    from modules.event_bus import (
        get_event_bus as _get_event_bus,
        NiblitEvent as _NiblitEvent,
        EVENT_MEMORY_RECALLED,
        EVENT_REASONING_COMPLETE,
        EVENT_DECISION_MADE,
    )
    _EVENT_BUS_AVAILABLE = True
except ImportError:
    _get_event_bus = None  # type: ignore[assignment]
    _NiblitEvent = None  # type: ignore[assignment,misc]
    EVENT_MEMORY_RECALLED = "memory.recalled"
    EVENT_REASONING_COMPLETE = "reasoning.complete"
    EVENT_DECISION_MADE = "decision.made"
    _EVENT_BUS_AVAILABLE = False

# Clamp limits for per-advisor weights after policy/capability adjustments.
_MAX_ADVISOR_WEIGHT = 2.0
_MIN_ADVISOR_WEIGHT = 0.05


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AdvisorSignal:
    """Output produced by a single advisor during one decide() call.

    Attributes
    ----------
    name:            Advisor identifier (e.g. ``"memory"``, ``"llm"``).
    suggestion:      The candidate response text.
    confidence:      Raw confidence from the advisor [0, 1].
    weight:          Adaptive weight used for scoring.
    effective_score: ``confidence × weight`` — used for competitive selection.
    goal_aligned:    ``True`` if the suggestion aligns with the active goal.
                     ``False`` applies ``_GOAL_PENALTY`` to effective_score.
    latency_ms:      Time taken to produce this signal in milliseconds.
    """

    name: str
    suggestion: str
    confidence: float
    weight: float
    effective_score: float = 0.0
    goal_aligned: bool = True
    latency_ms: float = 0.0


@dataclass
class DecisionResult:
    """Output of :meth:`DecisionEngine.decide`.

    Attributes
    ----------
    action:         The chosen response text.
    chosen_advisor: Name of the advisor whose suggestion was selected.
    confidence:     Weighted aggregate confidence score in [0, 1].
    rationale:      Human-readable explanation of the selection.
    signals:        All :class:`AdvisorSignal` objects collected this cycle.
    latency_ms:     Total wall-clock time for the ``decide()`` call in ms.
    ts:             UNIX timestamp of completion.
    """

    action: str
    chosen_advisor: str
    confidence: float
    rationale: str = ""
    signals: List[AdvisorSignal] = field(default_factory=list)
    latency_ms: float = 0.0
    ts: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action[:200],
            "chosen_advisor": self.chosen_advisor,
            "confidence": round(self.confidence, 3),
            "rationale": self.rationale,
            "signals": [
                {
                    "name": s.name,
                    "confidence": round(s.confidence, 3),
                    "weight": round(s.weight, 3),
                    "effective_score": round(s.effective_score, 3),
                    "goal_aligned": s.goal_aligned,
                }
                for s in self.signals
            ],
            "latency_ms": round(self.latency_ms, 1),
            "ts": self.ts,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Individual advisor functions (module-private)
# ─────────────────────────────────────────────────────────────────────────────

def _check_goal_alignment(suggestion: str, state: Any) -> bool:
    """Return True if *suggestion* aligns with the active goal topic.

    Alignment check: the active goal's topic keyword must appear in the
    suggestion (case-insensitive).  When no active goal is set, all
    suggestions are treated as aligned.
    """
    goal = getattr(state, "active_goal", None)
    if goal is None:
        return True
    topic = getattr(goal, "topic", "")
    if not topic or not suggestion:
        return True
    return topic.lower() in suggestion.lower()


def _apply_goal_enforcement(signal: AdvisorSignal, state: Any) -> AdvisorSignal:
    """Apply goal enforcement penalty to *signal.effective_score* if misaligned.

    If the suggestion does not align with the active goal, the effective
    score is multiplied by ``_GOAL_PENALTY`` (default 0.5), making the
    advisor less likely to win the competitive selection.
    """
    aligned = _check_goal_alignment(signal.suggestion, state)
    signal.goal_aligned = aligned
    if not aligned:
        signal.effective_score *= _GOAL_PENALTY
    return signal


def _run_memory_advisor(
    user_input: str,
    state: Any,
    knowledge_db: Optional[Any],
    weight: float,
) -> AdvisorSignal:
    """MemoryAdvisor: recall relevant KB facts and synthesise a summary."""
    t0 = time.time()
    suggestion = ""
    confidence = 0.0

    if _SMART_RECALL_AVAILABLE and _get_smart_recall is not None and knowledge_db is not None:
        try:
            recall = _get_smart_recall(knowledge_db)
            summary = recall.think_about(user_input[:80])
            if summary and len(summary) > 20:
                suggestion = summary
                confidence = 0.50
                # Pull top facts into shared state for downstream advisors.
                facts = recall.recall(user_input[:80], limit=5)
                if hasattr(state, "set_memory"):
                    state.set_memory(facts)
        except Exception as exc:
            log.debug("[MemoryAdvisor] failed: %s", exc)

    latency_ms = (time.time() - t0) * 1000

    if _EVENT_BUS_AVAILABLE and _get_event_bus is not None:
        try:
            _get_event_bus().publish(_NiblitEvent(
                type=EVENT_MEMORY_RECALLED,
                source="memory_advisor",
                payload={"suggestion_len": len(suggestion), "confidence": confidence},
            ))
        except Exception:
            pass

    if hasattr(state, "set_signal"):
        state.set_signal("memory", suggestion, confidence)

    sig = AdvisorSignal(
        name="memory",
        suggestion=suggestion,
        confidence=confidence,
        weight=weight,
        effective_score=confidence * weight,
        latency_ms=latency_ms,
    )
    return _apply_goal_enforcement(sig, state)


def _run_reasoning_advisor(
    user_input: str,
    state: Any,
    knowledge_db: Optional[Any],
    weight: float,
) -> AdvisorSignal:
    """ReasoningAdvisor: chain-of-thought reasoning over KB facts."""
    t0 = time.time()
    suggestion = ""
    confidence = 0.0

    if _REASONING_AVAILABLE and _get_reasoning_engine is not None:
        try:
            re_engine = _get_reasoning_engine(knowledge_db)
            cot = re_engine.chain_of_thought(user_input[:80])
            if cot and getattr(cot, "conclusion", ""):
                suggestion = cot.conclusion
                confidence = float(getattr(cot, "confidence", 0.40))
        except Exception as exc:
            log.debug("[ReasoningAdvisor] failed: %s", exc)

    latency_ms = (time.time() - t0) * 1000

    if _EVENT_BUS_AVAILABLE and _get_event_bus is not None:
        try:
            _get_event_bus().publish(_NiblitEvent(
                type=EVENT_REASONING_COMPLETE,
                source="reasoning_advisor",
                payload={"confidence": confidence},
            ))
        except Exception:
            pass

    if hasattr(state, "set_signal"):
        state.set_signal("reasoning", suggestion, confidence)

    sig = AdvisorSignal(
        name="reasoning",
        suggestion=suggestion,
        confidence=confidence,
        weight=weight,
        effective_score=confidence * weight,
        latency_ms=latency_ms,
    )
    return _apply_goal_enforcement(sig, state)


def _run_goal_advisor(user_input: str, state: Any, weight: float) -> AdvisorSignal:
    """GoalAdvisor: check alignment with the current active learning goal."""
    t0 = time.time()
    suggestion = ""
    confidence = 0.0

    goal = getattr(state, "active_goal", None)
    if goal is not None:
        topic = getattr(goal, "topic", "")
        if topic and topic.lower() in user_input.lower():
            suggestion = f"[Goal aligned: {topic}]"
            confidence = float(getattr(goal, "priority", 0.50))

    latency_ms = (time.time() - t0) * 1000

    if hasattr(state, "set_signal"):
        state.set_signal("goal", suggestion, confidence)

    # GoalAdvisor's suggestion is informational; it is always aligned.
    return AdvisorSignal(
        name="goal",
        suggestion=suggestion,
        confidence=confidence,
        weight=weight,
        effective_score=confidence * weight,
        goal_aligned=True,
        latency_ms=latency_ms,
    )


def _run_llm_advisor(
    user_input: str,
    llm_fn: Optional[Callable[[str], str]],
    state: Any,
    weight: float,
) -> AdvisorSignal:
    """LLMAdvisor: call the configured LLM backend (LocalBrain / Cloud)."""
    t0 = time.time()
    suggestion = ""
    confidence = 0.0

    if llm_fn is not None:
        try:
            result = llm_fn(user_input)
            if result and isinstance(result, str):
                suggestion = result
                confidence = 0.65  # above-average default for LLM outputs
        except Exception as exc:
            log.debug("[LLMAdvisor] failed: %s", exc)

    latency_ms = (time.time() - t0) * 1000

    sig = AdvisorSignal(
        name="llm",
        suggestion=suggestion,
        confidence=confidence,
        weight=weight,
        effective_score=confidence * weight,
        latency_ms=latency_ms,
    )
    return _apply_goal_enforcement(sig, state)


def _extract_memory_snippets(state: Any, max_facts: int = 5, max_chars: int = 300) -> List[str]:
    """Extract plain-text snippets from ``state.memory`` for quality scoring.

    Iterates the top-*max_facts* recalled facts (already populated by
    MemoryAdvisor in the same ``decide()`` call) and converts each to a
    plain string, truncated to *max_chars*.

    Field priority for dict values: ``summary`` > ``text`` > ``content`` >
    the raw value itself.  This mirrors the priority used by
    ``knowledge_recall._fact_text()``.

    Args:
        state:      :class:`~modules.niblit_state.NiblitState` instance.
        max_facts:  Maximum number of facts to include (default 5).
                    Keeps snippet volume comparable to a typical RAG window.
        max_chars:  Maximum characters per snippet (default 300).
                    Matches ``_SCORE_MAX_CHARS`` in ``knowledge_recall.py``.

    Returns:
        A list of non-empty snippet strings.
    """
    snippets: List[str] = []
    for fact in (getattr(state, "memory", []) or [])[:max_facts]:
        if isinstance(fact, dict):
            val = fact.get("value", "")
            if isinstance(val, dict):
                text = str(
                    val.get("summary")
                    or val.get("text")
                    or val.get("content")
                    or val
                )
            else:
                text = str(val)
        else:
            text = str(fact)
        text = text.strip()[:max_chars]
        if text:
            snippets.append(text)
    return snippets


def _run_quality_advisor(
    user_input: str,
    candidate: str,
    state: Any,
    weight: float,
    kb_snippets: Optional[List[str]] = None,
) -> AdvisorSignal:
    """QualityAdvisor: score the LLM candidate with the RewardModel.

    When *kb_snippets* is provided (extracted from ``state.memory`` by the
    caller), the RewardModel's overlap signal is computed against real KB
    context instead of defaulting to 0.5.  This improves scoring accuracy
    since the overlap component carries a 35% weight.
    """
    t0 = time.time()
    confidence = 0.50  # neutral fallback

    if _REWARD_MODEL_AVAILABLE and _get_reward_model is not None and candidate:
        try:
            rm = _get_reward_model()
            confidence = float(rm.score(user_input, candidate, snippets=kb_snippets or []))
        except Exception as exc:
            log.debug("[QualityAdvisor] failed: %s", exc)

    latency_ms = (time.time() - t0) * 1000

    sig = AdvisorSignal(
        name="quality",
        suggestion=candidate,
        confidence=confidence,
        weight=weight,
        effective_score=confidence * weight,
        latency_ms=latency_ms,
    )
    return _apply_goal_enforcement(sig, state)


# ─────────────────────────────────────────────────────────────────────────────
# DecisionEngine
# ─────────────────────────────────────────────────────────────────────────────

class DecisionEngine:
    """Single Decision Authority Layer (SDAL) for Niblit.

    Runs all five advisors **independently** for each request.  The winner
    is selected by maximum ``effective_score = confidence × weight ×
    identity_bias``, not by a fixed priority pipeline.  Weights are
    pulled from ``EvaluationEngine.get_weights()`` on every call so they
    reflect the live reinforcement feedback loop.

    Args:
        knowledge_db:     Optional KnowledgeDB instance used by advisors.
        evaluation_engine: Optional EvaluationEngine for adaptive weights.
    """

    def __init__(
        self,
        knowledge_db: Optional[Any] = None,
        evaluation_engine: Optional[Any] = None,
        policy_optimizer: Optional[Any] = None,
    ) -> None:
        self.knowledge_db = knowledge_db
        self._evaluation_engine = evaluation_engine
        self._policy_optimizer = policy_optimizer
        self._lock = threading.Lock()
        self._stats: Dict[str, Any] = {
            "decide_calls": 0,
            "by_advisor": {},
            "avg_confidence": 0.0,
            "total_confidence": 0.0,
        }
        log.info("[DecisionEngine] Initialised — competitive SDAL gate active")

    # ── Primary API ───────────────────────────────────────────────────────────

    def decide(
        self,
        state: Any,
        user_input: str,
        llm_fn: Optional[Callable[[str], str]] = None,
    ) -> DecisionResult:
        """Run all advisors competitively and return the highest-scoring result.

        Args:
            state:      :class:`~modules.niblit_state.NiblitState` instance.
            user_input: Raw user message string.
            llm_fn:     Callable ``(user_input: str) -> str`` for the LLM
                        advisor.  When ``None`` the LLM advisor produces an
                        empty signal.

        Returns:
            :class:`DecisionResult` with the selected ``action`` and
            per-advisor ``signals``.
        """
        t0 = time.time()
        kb = self.knowledge_db

        # Clear previous signals so stale data from the last request does not
        # influence downstream consumers.
        if hasattr(state, "clear_signals"):
            state.clear_signals()

        # ── Fetch live adaptive weights ───────────────────────────────────────
        weights = self._get_weights()

        # ── Context classification + PolicyOptimizer capability overrides ─────
        # When a PolicyOptimizer is wired in, classify the current task type and
        # apply per-context capability multipliers on top of adaptive weights.
        context_type = "chat"
        if self._policy_optimizer is not None:
            try:
                context_type = self._policy_optimizer.classify_context(
                    user_input, state
                )
                overrides = self._policy_optimizer.get_context_overrides(context_type)
                for adv, mult in overrides.items():
                    if adv in weights:
                        weights[adv] = max(_MIN_ADVISOR_WEIGHT, min(_MAX_ADVISOR_WEIGHT, weights[adv] * mult))
                # Store classified context type so Layer 12 can log it.
                if state is not None and hasattr(state, "update_context"):
                    state.update_context(_context_type=context_type)
            except Exception as _po_err:
                log.debug("[DecisionEngine] PolicyOptimizer overrides failed: %s", _po_err)

        # ── Apply decision_policy weight modifiers ────────────────────────────
        # The decision_policy is stored in CognitiveIdentity and written to
        # NiblitState.identity by niblit_core after each cycle.  We read it
        # from state so no direct CognitiveIdentity import is needed here.
        # Also merge in the per-context learned policy from PolicyOptimizer.
        policy: Dict[str, Any] = {}
        if state is not None:
            identity_snap = getattr(state, "identity", {}) or {}
            policy = dict(identity_snap.get("decision_policy", {}))

        # Learned per-context policy overrides from PolicyOptimizer take
        # precedence over the identity-level policy so context-specific
        # learning wins over general personality settings.
        if self._policy_optimizer is not None:
            try:
                ctx_policy = self._policy_optimizer.get_context_policy(context_type)
                policy.update(ctx_policy)
            except Exception:
                pass

        exploration_rate = float(policy.get("exploration_rate", 0.10))
        risk_preference  = str(policy.get("risk_preference",  "balanced"))
        priority_mode    = str(policy.get("priority_mode",    "balanced"))

        # risk_preference: nudge toward safety or boldness.
        if risk_preference == "conservative":
            weights["memory"]    = min(_MAX_ADVISOR_WEIGHT, weights.get("memory",    0.20) + 0.05)
            weights["reasoning"] = min(_MAX_ADVISOR_WEIGHT, weights.get("reasoning", 0.20) + 0.03)
            weights["llm"]       = max(_MIN_ADVISOR_WEIGHT, weights.get("llm",       0.40) - 0.05)
        elif risk_preference == "bold":
            weights["llm"]       = min(_MAX_ADVISOR_WEIGHT, weights.get("llm",       0.40) + 0.05)
            weights["reasoning"] = min(_MAX_ADVISOR_WEIGHT, weights.get("reasoning", 0.20) + 0.03)

        # ── Run all advisors independently ────────────────────────────────────
        # All five advisors are invoked regardless of each other's output.
        # This is the competitive model — no short-circuiting.
        signals: List[AdvisorSignal] = []

        signals.append(_run_memory_advisor(
            user_input, state, kb, weights["memory"]))
        signals.append(_run_reasoning_advisor(
            user_input, state, kb, weights["reasoning"]))
        signals.append(_run_goal_advisor(
            user_input, state, weights["goal"]))
        llm_sig = _run_llm_advisor(
            user_input, llm_fn, state, weights["llm"])
        signals.append(llm_sig)

        # Extract text snippets from memory (already populated by MemoryAdvisor
        # above) so the QualityAdvisor's overlap signal is computed against real
        # KB context rather than defaulting to 0.5.
        # Limit: top-5 facts keep snippet volume comparable to a typical RAG
        # retrieval window; more facts add noise without improving overlap accuracy.
        # Truncation: 300 chars matches _SCORE_MAX_CHARS in knowledge_recall.py
        # and keeps individual snippet sizes within the RewardModel's scoring window.
        mem_snippets: List[str] = _extract_memory_snippets(state)

        signals.append(_run_quality_advisor(
            user_input, llm_sig.suggestion, state, weights["quality"],
            kb_snippets=mem_snippets))

        # ── Apply priority_mode multipliers ───────────────────────────────────
        # "goal_first"    → boost goal-aligned signals.
        # "quality_first" → boost quality advisor.
        # "balanced"      → no change.
        if priority_mode == "goal_first":
            for sig in signals:
                if sig.goal_aligned:
                    sig.effective_score *= 1.20
        elif priority_mode == "quality_first":
            for sig in signals:
                if sig.name == "quality":
                    sig.effective_score *= 1.20

        # ── Competitive selection: best effective_score wins ──────────────────
        # Only signals that produced a non-empty suggestion are eligible.
        candidates = [s for s in signals if s.suggestion]
        if candidates:
            chosen = max(candidates, key=lambda s: s.effective_score)
        else:
            chosen = AdvisorSignal(
                name="fallback",
                suggestion=f"I hear you: {user_input}",
                confidence=0.10,
                weight=0.0,
                effective_score=0.0,
            )

        # ── Informed exploration ──────────────────────────────────────────────
        # When exploration_rate > 0 and we fire an exploration step, prefer
        # the advisor with the *highest uncertainty* (confidence variance) over
        # a random pick — this maximises information gain per exploration.
        # Falls back to random when PolicyOptimizer is unavailable.
        if (
            exploration_rate > 0.0
            and len(candidates) > 1
            and random.random() < exploration_rate
        ):
            if self._policy_optimizer is not None:
                try:
                    ranked = self._policy_optimizer.get_exploration_candidates(
                        signals, chosen.name
                    )
                    if ranked:
                        chosen = ranked[0]  # highest uncertainty first
                        log.debug(
                            "[DecisionEngine] Informed exploration — switched to %s "
                            "(uncertainty-ranked, rate=%.2f)",
                            chosen.name, exploration_rate,
                        )
                except Exception:
                    non_winners = [s for s in candidates if s.name != chosen.name]
                    if non_winners:
                        chosen = random.choice(non_winners)
            else:
                non_winners = [s for s in candidates if s.name != chosen.name]
                if non_winners:
                    chosen = random.choice(non_winners)
                    log.debug(
                        "[DecisionEngine] Random exploration — switched to %s (rate=%.2f)",
                        chosen.name, exploration_rate,
                    )

        # ── Aggregate confidence (weighted mean across all advisors) ──────────
        total_weight = sum(s.weight for s in signals)
        weighted_conf = (
            sum(s.confidence * s.weight for s in signals) / total_weight
            if total_weight > 0 else 0.0
        )

        latency_ms = (time.time() - t0) * 1000

        result = DecisionResult(
            action=chosen.suggestion,
            chosen_advisor=chosen.name,
            confidence=round(weighted_conf, 3),
            rationale=(
                f"Selected '{chosen.name}' via competitive scoring "
                f"(effective_score={chosen.effective_score:.3f}, "
                f"weighted_confidence={weighted_conf:.2f})"
            ),
            signals=signals,
            latency_ms=latency_ms,
        )

        # ── Persist decision signal to shared state ───────────────────────────
        if hasattr(state, "set_signal"):
            state.set_signal("decision", result.action, weighted_conf)

        # ── Publish decision event ────────────────────────────────────────────
        if _EVENT_BUS_AVAILABLE and _get_event_bus is not None:
            try:
                _get_event_bus().publish(_NiblitEvent(
                    type=EVENT_DECISION_MADE,
                    source="decision_engine",
                    payload=result.to_dict(),
                ))
            except Exception:
                pass

        # ── Update stats ──────────────────────────────────────────────────────
        with self._lock:
            self._stats["decide_calls"] += 1
            self._stats["by_advisor"][chosen.name] = (
                self._stats["by_advisor"].get(chosen.name, 0) + 1
            )
            total = self._stats["decide_calls"]
            running_total = self._stats["total_confidence"] + weighted_conf
            self._stats["total_confidence"] = running_total
            self._stats["avg_confidence"] = round(running_total / total, 3)

        log.debug(
            "[DecisionEngine] winner=%s eff=%.3f agg_conf=%.2f latency=%.0fms",
            chosen.name, chosen.effective_score, weighted_conf, latency_ms,
        )
        return result

    # ── Configuration helpers ─────────────────────────────────────────────────

    def set_knowledge_db(self, knowledge_db: Any) -> None:
        """Update the KnowledgeDB used by advisors at runtime."""
        self.knowledge_db = knowledge_db

    def set_evaluation_engine(self, evaluation_engine: Any) -> None:
        """Wire in an EvaluationEngine for live adaptive weights."""
        self._evaluation_engine = evaluation_engine

    def set_policy_optimizer(self, policy_optimizer: Any) -> None:
        """Wire in a PolicyOptimizer for context-aware + uncertainty-based decisions."""
        self._policy_optimizer = policy_optimizer

    def status(self) -> Dict[str, Any]:
        """Return current engine statistics."""
        with self._lock:
            return {**self._stats, "weights": self._get_weights()}

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_weights(self) -> Dict[str, float]:
        """Return current adaptive weights from EvaluationEngine or defaults."""
        if self._evaluation_engine is not None and hasattr(
            self._evaluation_engine, "get_weights"
        ):
            try:
                return self._evaluation_engine.get_weights()
            except Exception:
                pass
        return {
            "memory":    _W_MEMORY,
            "reasoning": _W_REASONING,
            "goal":      _W_GOAL,
            "llm":       _W_LLM,
            "quality":   _W_QUALITY,
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: Optional[DecisionEngine] = None
_engine_lock = threading.Lock()


def get_decision_engine(**kwargs: Any) -> DecisionEngine:
    """Return the process-level :class:`DecisionEngine` singleton.

    Note: kwargs (``knowledge_db``, ``evaluation_engine``) are only applied
    on the first call.  Subsequent calls return the existing singleton
    regardless of kwargs provided.
    """
    global _engine  # pylint: disable=global-statement
    with _engine_lock:
        if _engine is None:
            _engine = DecisionEngine(**kwargs)
        return _engine


if __name__ == "__main__":
    from modules.niblit_state import get_niblit_state

    state = get_niblit_state()
    engine = get_decision_engine()
    result = engine.decide(state, "explain transformers")
    print(result.action[:80])
    print("Chosen advisor:", result.chosen_advisor)
    print("Confidence:", result.confidence)
    print("Stats:", engine.status())
