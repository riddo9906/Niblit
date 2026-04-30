#!/usr/bin/env python3
"""modules/decision_engine.py — Single Decision Authority Layer (SDAL) for Niblit.

The DecisionEngine is the architectural "single gate" that all cognitive
signals pass through before any output reaches the user or the execution
layer.  No advisor writes directly to the user — all suggestions are
aggregated here and a single, authoritative response is chosen.

Advisor pipeline (called per request)
--------------------------------------
1. ``MemoryAdvisor``    — ``SmartRecall.think_about()`` + fact recall
2. ``ReasoningAdvisor`` — ``ReasoningEngine.chain_of_thought()``
3. ``GoalAdvisor``      — checks alignment with ``state.active_goal``
4. ``LLMAdvisor``       — ``LocalBrain`` / ``NiblitCloudBrain`` inference
5. ``QualityAdvisor``   — ``RewardModel.score()`` applied to LLM output

Confidence aggregation
-----------------------
The final confidence is a weighted average of all advisor scores.  Default
weights are::

    Memory    : NIBLIT_SDAL_W_MEMORY    (0.20)
    Reasoning : NIBLIT_SDAL_W_REASONING (0.20)
    Goal      : NIBLIT_SDAL_W_GOAL      (0.10)
    LLM       : NIBLIT_SDAL_W_LLM       (0.40)
    Quality   : NIBLIT_SDAL_W_QUALITY   (0.10)

Selection priority
-------------------
``llm`` > ``reasoning`` > ``memory`` — the first advisor with a non-empty
suggestion wins.  A bare fallback echo is used only when all advisors
return empty strings.

Public API
----------
``DecisionResult``
    Dataclass with ``action``, ``chosen_advisor``, ``confidence``,
    ``rationale``, ``signals``, ``latency_ms``, ``ts``.

``DecisionEngine.decide(state, user_input, llm_fn) → DecisionResult``
    Run the full advisor pipeline and return the selected action.

``get_decision_engine(**kwargs) → DecisionEngine``
    Process-level singleton.

Configuration (environment variables)::

    NIBLIT_SDAL_W_MEMORY     — Memory advisor weight   (default 0.20)
    NIBLIT_SDAL_W_REASONING  — Reasoning advisor weight (default 0.20)
    NIBLIT_SDAL_W_GOAL       — Goal advisor weight      (default 0.10)
    NIBLIT_SDAL_W_LLM        — LLM advisor weight       (default 0.40)
    NIBLIT_SDAL_W_QUALITY    — Quality advisor weight   (default 0.10)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("DecisionEngine")

# ── Advisor weights (tuneable via env) ────────────────────────────────────────

_W_MEMORY    = float(os.environ.get("NIBLIT_SDAL_W_MEMORY",    "0.20"))
_W_REASONING = float(os.environ.get("NIBLIT_SDAL_W_REASONING", "0.20"))
_W_GOAL      = float(os.environ.get("NIBLIT_SDAL_W_GOAL",      "0.10"))
_W_LLM       = float(os.environ.get("NIBLIT_SDAL_W_LLM",       "0.40"))
_W_QUALITY   = float(os.environ.get("NIBLIT_SDAL_W_QUALITY",   "0.10"))

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


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class AdvisorSignal:
    """Output produced by a single advisor during one decide() call."""

    name: str
    suggestion: str
    confidence: float
    weight: float
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
                }
                for s in self.signals
            ],
            "latency_ms": round(self.latency_ms, 1),
            "ts": self.ts,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Individual advisor functions (module-private)
# ─────────────────────────────────────────────────────────────────────────────

def _run_memory_advisor(
    user_input: str,
    state: Any,
    knowledge_db: Optional[Any],
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

    return AdvisorSignal(
        name="memory",
        suggestion=suggestion,
        confidence=confidence,
        weight=_W_MEMORY,
        latency_ms=latency_ms,
    )


def _run_reasoning_advisor(
    user_input: str,
    state: Any,
    knowledge_db: Optional[Any],
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

    return AdvisorSignal(
        name="reasoning",
        suggestion=suggestion,
        confidence=confidence,
        weight=_W_REASONING,
        latency_ms=latency_ms,
    )


def _run_goal_advisor(user_input: str, state: Any) -> AdvisorSignal:
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

    return AdvisorSignal(
        name="goal",
        suggestion=suggestion,
        confidence=confidence,
        weight=_W_GOAL,
        latency_ms=latency_ms,
    )


def _run_llm_advisor(
    user_input: str,
    llm_fn: Optional[Callable[[str], str]],
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

    return AdvisorSignal(
        name="llm",
        suggestion=suggestion,
        confidence=confidence,
        weight=_W_LLM,
        latency_ms=latency_ms,
    )


def _run_quality_advisor(user_input: str, candidate: str) -> AdvisorSignal:
    """QualityAdvisor: score the LLM candidate with the RewardModel."""
    t0 = time.time()
    confidence = 0.50  # neutral fallback

    if _REWARD_MODEL_AVAILABLE and _get_reward_model is not None and candidate:
        try:
            rm = _get_reward_model()
            confidence = float(rm.score(user_input, candidate, snippets=[]))
        except Exception as exc:
            log.debug("[QualityAdvisor] failed: %s", exc)

    latency_ms = (time.time() - t0) * 1000

    return AdvisorSignal(
        name="quality",
        suggestion=candidate,
        confidence=confidence,
        weight=_W_QUALITY,
        latency_ms=latency_ms,
    )


# ─────────────────────────────────────────────────────────────────────────────
# DecisionEngine
# ─────────────────────────────────────────────────────────────────────────────

class DecisionEngine:
    """Single Decision Authority Layer (SDAL) for Niblit.

    Runs all five advisors for each request and selects the highest-
    quality response using weighted confidence aggregation.

    Args:
        knowledge_db: Optional KnowledgeDB instance used by advisors.
    """

    def __init__(self, knowledge_db: Optional[Any] = None) -> None:
        self.knowledge_db = knowledge_db
        self._lock = threading.Lock()
        self._stats: Dict[str, Any] = {
            "decide_calls": 0,
            "by_advisor": {},
            "avg_confidence": 0.0,
            "total_confidence": 0.0,
        }
        log.info("[DecisionEngine] Initialised — SDAL gate active")

    # ── Primary API ───────────────────────────────────────────────────────────

    def decide(
        self,
        state: Any,
        user_input: str,
        llm_fn: Optional[Callable[[str], str]] = None,
    ) -> DecisionResult:
        """Run all advisors and return the best response.

        Args:
            state:      :class:`~modules.niblit_state.NiblitState` instance.
            user_input: Raw user message string.
            llm_fn:     Callable ``(user_input: str) -> str`` for the LLM
                        advisor.  When ``None`` the LLM advisor is skipped.

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

        # ── Gather advisor signals ────────────────────────────────────────────
        signals: List[AdvisorSignal] = []

        mem_sig = _run_memory_advisor(user_input, state, kb)
        signals.append(mem_sig)

        reason_sig = _run_reasoning_advisor(user_input, state, kb)
        signals.append(reason_sig)

        goal_sig = _run_goal_advisor(user_input, state)
        signals.append(goal_sig)

        # LLM runs before quality so quality can score the LLM output.
        llm_sig = _run_llm_advisor(user_input, llm_fn)
        signals.append(llm_sig)

        quality_sig = _run_quality_advisor(user_input, llm_sig.suggestion)
        signals.append(quality_sig)

        # ── Weighted confidence aggregation ───────────────────────────────────
        total_weight = sum(s.weight for s in signals)
        weighted_conf = (
            sum(s.confidence * s.weight for s in signals) / total_weight
            if total_weight > 0 else 0.0
        )

        # ── Select best action ────────────────────────────────────────────────
        # Priority: llm (authoritative text) > reasoning (structured) > memory
        chosen: Optional[AdvisorSignal] = None
        for preferred in ("llm", "reasoning", "memory"):
            sig = next(
                (s for s in signals if s.name == preferred and s.suggestion), None
            )
            if sig:
                chosen = sig
                break

        if chosen is None:
            chosen = AdvisorSignal(
                name="fallback",
                suggestion=f"I hear you: {user_input}",
                confidence=0.10,
                weight=0.0,
            )

        latency_ms = (time.time() - t0) * 1000

        result = DecisionResult(
            action=chosen.suggestion,
            chosen_advisor=chosen.name,
            confidence=round(weighted_conf, 3),
            rationale=(
                f"Selected '{chosen.name}' advisor "
                f"(weighted confidence: {weighted_conf:.2f})"
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
            "[DecisionEngine] decided: advisor=%s conf=%.2f latency=%.0fms",
            chosen.name, weighted_conf, latency_ms,
        )
        return result

    # ── Configuration helpers ─────────────────────────────────────────────────

    def set_knowledge_db(self, knowledge_db: Any) -> None:
        """Update the KnowledgeDB used by advisors at runtime."""
        self.knowledge_db = knowledge_db

    def status(self) -> Dict[str, Any]:
        """Return current engine statistics."""
        with self._lock:
            return dict(self._stats)


# ── Singleton ─────────────────────────────────────────────────────────────────

_engine: Optional[DecisionEngine] = None
_engine_lock = threading.Lock()


def get_decision_engine(**kwargs: Any) -> DecisionEngine:
    """Return the process-level :class:`DecisionEngine` singleton."""
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
