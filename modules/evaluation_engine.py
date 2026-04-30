#!/usr/bin/env python3
"""modules/evaluation_engine.py — Outcome Evaluation & Adaptive Weight Loop.

Closes the learning loop between decision-making and outcome quality:

1. Every DecisionEngine output is scored using the RewardModel.
2. The winning advisor's weight is reinforced (good outcome) or decayed
   (poor outcome), so the system learns *which advisors to trust*.
3. Updated weights are persisted to the CognitiveIdentity layer so
   decision bias evolves over the lifetime of the process.
4. A ``response.complete`` event is published after each evaluation so ALE
   and other subscribers know a cycle has finished.

Public API
----------
``EvaluationRecord``
    Immutable snapshot of one evaluation cycle.

``EvaluationEngine.score_outcome(user_input, response, decision_result)``
    Score a response and update advisor weights.  Returns an
    :class:`EvaluationRecord`.

``EvaluationEngine.reinforce(advisor, delta)``
    Manually nudge an advisor weight by *delta* (positive → reinforce,
    negative → decay).

``EvaluationEngine.get_weights() → Dict[str, float]``
    Current adaptive weights for all advisors.

``get_evaluation_engine(**kwargs) → EvaluationEngine``
    Process-level singleton.

Configuration (environment variables)::

    NIBLIT_EVAL_GOOD_THRESHOLD  — score ≥ this → reinforce  (default 0.60)
    NIBLIT_EVAL_POOR_THRESHOLD  — score ≤ this → decay      (default 0.35)
    NIBLIT_EVAL_REINFORCE_DELTA — weight +delta on good      (default 0.05)
    NIBLIT_EVAL_DECAY_DELTA     — weight -delta on poor      (default 0.05)
    NIBLIT_EVAL_MIN_WEIGHT      — floor for any weight       (default 0.05)
    NIBLIT_EVAL_MAX_WEIGHT      — cap for any weight         (default 2.00)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("EvaluationEngine")

# ── Thresholds & deltas (env-tuneable) ────────────────────────────────────────

_GOOD_THRESHOLD    = float(os.environ.get("NIBLIT_EVAL_GOOD_THRESHOLD",   "0.60"))
_POOR_THRESHOLD    = float(os.environ.get("NIBLIT_EVAL_POOR_THRESHOLD",   "0.35"))
_REINFORCE_DELTA   = float(os.environ.get("NIBLIT_EVAL_REINFORCE_DELTA",  "0.05"))
_DECAY_DELTA       = float(os.environ.get("NIBLIT_EVAL_DECAY_DELTA",      "0.05"))
_MIN_WEIGHT        = float(os.environ.get("NIBLIT_EVAL_MIN_WEIGHT",       "0.05"))
_MAX_WEIGHT        = float(os.environ.get("NIBLIT_EVAL_MAX_WEIGHT",       "2.00"))

# ── Default starting weights (mirrors decision_engine.py defaults) ─────────
_DEFAULT_WEIGHTS: Dict[str, float] = {
    "memory":    0.20,
    "reasoning": 0.20,
    "goal":      0.10,
    "llm":       0.40,
    "quality":   0.10,
}

# ── Optional dependency imports ───────────────────────────────────────────────

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
        EVENT_RESPONSE_COMPLETE,
    )
    _EVENT_BUS_AVAILABLE = True
except ImportError:
    _get_event_bus = None  # type: ignore[assignment]
    _NiblitEvent = None  # type: ignore[assignment,misc]
    EVENT_RESPONSE_COMPLETE = "response.complete"
    _EVENT_BUS_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# EvaluationRecord
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class EvaluationRecord:
    """Immutable snapshot of a single evaluation cycle.

    Attributes
    ----------
    user_input:      The original user query.
    response:        The response that was evaluated.
    quality_score:   RewardModel score in [0, 1].
    chosen_advisor:  The advisor whose output was selected.
    outcome:         ``"good"`` | ``"poor"`` | ``"neutral"``.
    weight_updates:  Per-advisor delta applied this cycle.
    ts:              UNIX timestamp of the evaluation.
    """

    user_input: str
    response: str
    quality_score: float
    chosen_advisor: str
    outcome: str
    weight_updates: Dict[str, float] = field(default_factory=dict)
    ts: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_input": self.user_input[:100],
            "quality_score": round(self.quality_score, 3),
            "chosen_advisor": self.chosen_advisor,
            "outcome": self.outcome,
            "weight_updates": {k: round(v, 4) for k, v in self.weight_updates.items()},
            "ts": self.ts,
        }


# ─────────────────────────────────────────────────────────────────────────────
# EvaluationEngine
# ─────────────────────────────────────────────────────────────────────────────

class EvaluationEngine:
    """Outcome scoring and adaptive weight reinforcement loop.

    After each ``DecisionEngine.decide()`` call, pass the result here via
    ``score_outcome()`` to:

    * Score the response quality.
    * Reinforce or decay the winning advisor's weight.
    * Optionally persist the updated weights to CognitiveIdentity.
    * Emit a ``response.complete`` event.

    Args:
        knowledge_db:      KnowledgeDB used by QualityFeedback (optional).
        identity:          CognitiveIdentity instance for persistent weights.
        initial_weights:   Seed weights; defaults to ``_DEFAULT_WEIGHTS``.
    """

    def __init__(
        self,
        knowledge_db: Optional[Any] = None,
        identity: Optional[Any] = None,
        initial_weights: Optional[Dict[str, float]] = None,
    ) -> None:
        self.knowledge_db = knowledge_db
        self._identity = identity

        # Initialise weights — prefer persisted weights from identity.
        if identity is not None and hasattr(identity, "get_advisor_weights"):
            try:
                persisted = identity.get_advisor_weights()
                if persisted:
                    self._weights = dict(persisted)
                else:
                    self._weights = dict(initial_weights or _DEFAULT_WEIGHTS)
            except Exception:
                self._weights = dict(initial_weights or _DEFAULT_WEIGHTS)
        else:
            self._weights = dict(initial_weights or _DEFAULT_WEIGHTS)

        self._lock = threading.Lock()
        self._history: List[EvaluationRecord] = []
        self._max_history = 200
        self._total_evals = 0
        log.info("[EvaluationEngine] Initialised — adaptive weight loop active")

    # ── Primary API ───────────────────────────────────────────────────────────

    def score_outcome(
        self,
        user_input: str,
        response: str,
        decision_result: Optional[Any] = None,
    ) -> EvaluationRecord:
        """Score *response* and update advisor weights.

        Args:
            user_input:       The original user query.
            response:         The response text to evaluate.
            decision_result:  A :class:`~modules.decision_engine.DecisionResult`
                              (used to identify which advisor to update).

        Returns:
            :class:`EvaluationRecord` with outcome and weight changes.
        """
        quality = self._score_response(user_input, response)
        chosen_advisor = "unknown"
        if decision_result is not None:
            chosen_advisor = getattr(decision_result, "chosen_advisor", "unknown")

        # Determine outcome label.
        if quality >= _GOOD_THRESHOLD:
            outcome = "good"
            delta = +_REINFORCE_DELTA
        elif quality <= _POOR_THRESHOLD:
            outcome = "poor"
            delta = -_DECAY_DELTA
        else:
            outcome = "neutral"
            delta = 0.0

        # Apply weight update to the winning advisor.
        weight_updates: Dict[str, float] = {}
        if delta != 0.0 and chosen_advisor in self._weights:
            self.reinforce(chosen_advisor, delta)
            weight_updates[chosen_advisor] = delta

        record = EvaluationRecord(
            user_input=user_input,
            response=response,
            quality_score=quality,
            chosen_advisor=chosen_advisor,
            outcome=outcome,
            weight_updates=weight_updates,
        )

        # Store in rolling history.
        with self._lock:
            self._history.append(record)
            if len(self._history) > self._max_history:
                self._history.pop(0)
            self._total_evals += 1

        # Propagate quality to KB facts (QualityFeedback loop).
        if self.knowledge_db is not None:
            try:
                from modules.quality_feedback import get_quality_feedback
                snippets = []
                if decision_result is not None:
                    sigs = getattr(decision_result, "signals", [])
                    snippets = [
                        s.suggestion[:200]
                        for s in sigs
                        if getattr(s, "suggestion", "")
                    ]
                get_quality_feedback().record_answer_quality(
                    query=user_input,
                    answer=response,
                    knowledge_db=self.knowledge_db,
                    snippets=snippets,
                )
            except Exception as _qf_err:
                log.debug("[EvaluationEngine] QualityFeedback failed: %s", _qf_err)

        # Persist weights to identity layer.
        if self._identity is not None and hasattr(self._identity, "update"):
            try:
                self._identity.update(chosen_advisor, quality)
            except Exception as _id_err:
                log.debug("[EvaluationEngine] Identity update failed: %s", _id_err)

        # Publish response.complete event.
        if _EVENT_BUS_AVAILABLE and _get_event_bus is not None:
            try:
                _get_event_bus().publish(_NiblitEvent(
                    type=EVENT_RESPONSE_COMPLETE,
                    source="evaluation_engine",
                    payload=record.to_dict(),
                ))
            except Exception:
                pass

        log.debug(
            "[EvaluationEngine] outcome=%s score=%.2f advisor=%s delta=%.3f",
            outcome, quality, chosen_advisor, delta,
        )
        return record

    def reinforce(self, advisor: str, delta: float) -> None:
        """Manually nudge an advisor's weight by *delta*.

        *delta* > 0 reinforces; *delta* < 0 decays.
        Weight is clamped to [NIBLIT_EVAL_MIN_WEIGHT, NIBLIT_EVAL_MAX_WEIGHT].
        """
        with self._lock:
            current = self._weights.get(advisor, 0.20)
            updated = max(_MIN_WEIGHT, min(_MAX_WEIGHT, current + delta))
            self._weights[advisor] = updated
        log.debug(
            "[EvaluationEngine] weight update: %s %.4f → %.4f (Δ%+.4f)",
            advisor, current, updated, delta,
        )

    def get_weights(self) -> Dict[str, float]:
        """Return a copy of the current adaptive weights for all advisors."""
        with self._lock:
            return dict(self._weights)

    def get_weight(self, advisor: str, default: float = 0.20) -> float:
        """Return the current weight for a single advisor."""
        with self._lock:
            return self._weights.get(advisor, default)

    def get_history(self) -> List[Dict[str, Any]]:
        """Return a thread-safe snapshot of the evaluation history.

        Returns a list of serialisable dicts (one per :class:`EvaluationRecord`).
        Callers should use this instead of accessing ``_history`` directly.
        """
        with self._lock:
            return [r.to_dict() for r in self._history]

    def last_quality_score(self) -> Optional[float]:
        """Return the quality score from the most recent evaluation, or None."""
        with self._lock:
            return self._history[-1].quality_score if self._history else None

    def status(self) -> Dict[str, Any]:
        """Return engine statistics and current weights."""
        with self._lock:
            outcome_counts: Dict[str, int] = {}
            for r in self._history:
                outcome_counts[r.outcome] = outcome_counts.get(r.outcome, 0) + 1
            avg_quality = (
                sum(r.quality_score for r in self._history) / len(self._history)
                if self._history else 0.0
            )
            return {
                "total_evals": self._total_evals,
                "weights": dict(self._weights),
                "outcome_counts": outcome_counts,
                "avg_quality": round(avg_quality, 3),
                "history_len": len(self._history),
            }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _score_response(self, query: str, response: str) -> float:
        """Use RewardModel to score *response*.  Returns 0.50 on any failure."""
        if not response:
            return 0.0
        if _REWARD_MODEL_AVAILABLE and _get_reward_model is not None:
            try:
                rm = _get_reward_model()
                return float(rm.score(query, response, snippets=[]))
            except Exception as exc:
                log.debug("[EvaluationEngine] RewardModel.score failed: %s", exc)
        return 0.50  # neutral default when model unavailable


# ── Singleton ─────────────────────────────────────────────────────────────────

_eval_engine: Optional[EvaluationEngine] = None
_eval_lock = threading.Lock()


def get_evaluation_engine(**kwargs: Any) -> EvaluationEngine:
    """Return the process-level :class:`EvaluationEngine` singleton.

    Note: kwargs are only applied on first call.  Subsequent calls return
    the existing singleton regardless of kwargs provided.
    """
    global _eval_engine  # pylint: disable=global-statement
    with _eval_lock:
        if _eval_engine is None:
            _eval_engine = EvaluationEngine(**kwargs)
        return _eval_engine


if __name__ == "__main__":
    engine = get_evaluation_engine()
    record = engine.score_outcome(
        user_input="what is machine learning",
        response="Machine learning is a subfield of AI that allows systems to learn from data.",
    )
    print("Outcome:", record.outcome)
    print("Quality:", record.quality_score)
    print("Weights:", engine.get_weights())
    print("Status:", engine.status())
