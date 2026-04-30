#!/usr/bin/env python3
"""modules/quality_feedback.py — Answer-Quality Feedback Loop for Niblit.

Closes the loop between *generating* an answer and *improving* the knowledge
that was used to generate it:

  Query + Answer + used-KB-facts
        ↓
  RewardModel.score()  →  quality ∈ [0, 1]
        ↓
  quality ≥ threshold  →  reinforce each used fact (confidence ↑)
  quality <  threshold  →  decay each used fact (confidence ↓ + re-queue)

This ensures that confidence in a fact is not just a static number assigned
at ingestion time but a running estimate of how useful that fact actually is
when Niblit uses it to answer questions.

Public API
----------
``record_answer_quality(query, answer, knowledge_db, ...)``
    Score the answer and propagate quality deltas to the KB facts.

``get_quality_feedback()``
    Return the process-wide singleton.

Design
------
* Pure stdlib + the existing RewardModel — no new dependencies.
* Never raises — all errors are logged at DEBUG level.
* Thread-safe singleton.
* Additive — does not alter any existing ingestion or retrieval paths.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("QualityFeedback")

# ─────────────────────────────────────────────────────────────────────────────
# Thresholds
# ─────────────────────────────────────────────────────────────────────────────
# These values are calibrated against the RewardModel's BM25-based score
# distribution.  Typical answer scores span 0.2–0.9:
#   • Well-grounded answers with direct KB evidence  →  0.6–0.9
#   • Partially-relevant or vague answers            →  0.35–0.6
#   • Off-topic, empty, or error-string responses    →  0.0–0.35

# Answers scoring at or above this are "good" — reinforce the facts used.
_GOOD_THRESHOLD: float = 0.60

# Answers scoring at or below this are "poor" — decay the facts used.
_POOR_THRESHOLD: float = 0.35

# How much confidence to add per reinforcement event (capped at 1.0).
_REINFORCE_AMOUNT: float = 0.08

# How much confidence to subtract per decay event (floored at 0.05).
_DECAY_AMOUNT: float = 0.10

# Maximum facts to update in a single call (prevents O(n) lock contention).
_MAX_FACTS_TO_UPDATE: int = 10

# ─────────────────────────────────────────────────────────────────────────────
# QualityFeedback
# ─────────────────────────────────────────────────────────────────────────────


class QualityFeedback:
    """Score answers and propagate quality deltas back to knowledge-base facts.

    Parameters
    ----------
    reward_model:
        :class:`modules.reward_model.RewardModel` instance.  When ``None``,
        the singleton is loaded lazily on first use.
    """

    def __init__(self, reward_model: Optional[Any] = None) -> None:
        self._rm = reward_model

    # ── public API ────────────────────────────────────────────────────────────

    def record_answer_quality(
        self,
        query: str,
        answer: str,
        knowledge_db: Any,
        snippets: Optional[List[str]] = None,
        used_facts: Optional[List[Dict[str, Any]]] = None,
        is_good: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Score *answer* against *query* and update fact confidence in *knowledge_db*.

        Parameters
        ----------
        query:        The original user query.
        answer:       The generated answer to evaluate.
        knowledge_db: :class:`niblit_memory.KnowledgeDB` instance.
        snippets:     Source snippets that were retrieved for context (optional).
        used_facts:   Pre-retrieved fact dicts (from smart_recall).  When
                      ``None``, the method calls ``smart_recall(query)``
                      itself to find which facts were relevant.
        is_good:      Explicit override — ``True`` → treat as high-quality,
                      ``False`` → treat as poor.  ``None`` → use RewardModel.

        Returns
        -------
        Dict with keys: ``score``, ``verdict``, ``reinforced``, ``decayed``,
        ``re_queued``, ``error`` (only on failure).
        """
        try:
            return self._record_safe(
                query=query,
                answer=answer,
                knowledge_db=knowledge_db,
                snippets=snippets or [],
                used_facts=used_facts,
                is_good=is_good,
            )
        except Exception as exc:
            log.debug("[QualityFeedback] record_answer_quality error: %s", exc)
            return {"score": 0.5, "error": str(exc), "reinforced": 0, "decayed": 0}

    # ── internal ──────────────────────────────────────────────────────────────

    def _record_safe(
        self,
        query: str,
        answer: str,
        knowledge_db: Any,
        snippets: List[str],
        used_facts: Optional[List[Dict[str, Any]]],
        is_good: Optional[bool],
    ) -> Dict[str, Any]:
        # 1. Score the answer
        if is_good is True:
            quality = 1.0
            method = "explicit_good"
        elif is_good is False:
            quality = 0.0
            method = "explicit_bad"
        else:
            rm = self._get_reward_model()
            if rm is not None:
                verdict = rm.verdict(query, answer, snippets)
                quality = float(verdict.get("score", 0.5))
                method = verdict.get("method", "heuristic")
            else:
                quality = 0.5
                method = "unavailable"

        # 2. Find which KB facts were relevant to this query
        facts_to_update = []
        if used_facts is not None:
            facts_to_update = used_facts[:_MAX_FACTS_TO_UPDATE]
        elif knowledge_db is not None and query:
            try:
                if hasattr(knowledge_db, "smart_recall"):
                    facts_to_update = (
                        knowledge_db.smart_recall(query, limit=_MAX_FACTS_TO_UPDATE) or []
                    )
            except Exception as exc:
                log.debug("[QualityFeedback] smart_recall failed: %s", exc)

        reinforced = 0
        decayed = 0
        re_queued: List[str] = []

        if not facts_to_update or knowledge_db is None:
            # Still feed the quality score into PolicyOptimizer even without KB facts.
            try:
                from modules.policy_optimizer import get_policy_optimizer
                po = get_policy_optimizer()
                ctx = po.classify_context(query)
                po.record_episode(
                    context_type=ctx,
                    advisor_chosen="quality",
                    advisor_confidences={"quality": quality},
                    outcome_score=quality,
                )
            except Exception as _po_err:
                log.debug("[QualityFeedback] PolicyOptimizer episode (early path) skipped: %s", _po_err)
            return {
                "score": quality,
                "method": method,
                "reinforced": 0,
                "decayed": 0,
                "re_queued": [],
            }

        # 3. Apply quality deltas
        if quality >= _GOOD_THRESHOLD:
            # Good answer → facts that contributed are more trustworthy
            for fact in facts_to_update:
                key = fact.get("key") if isinstance(fact, dict) else None
                if key:
                    try:
                        knowledge_db.reinforce(key, amount=_REINFORCE_AMOUNT)
                        reinforced += 1
                    except Exception as exc:
                        log.debug("[QualityFeedback] reinforce(%r) failed: %s", key, exc)

        elif quality <= _POOR_THRESHOLD:
            # Poor answer → decay confidence of contributing facts and
            # re-queue their topics so the ALE can research them again
            for fact in facts_to_update:
                if not isinstance(fact, dict):
                    continue
                key = fact.get("key")
                if key:
                    try:
                        _decay_fact_confidence(knowledge_db, key, amount=_DECAY_AMOUNT)
                        decayed += 1
                    except Exception as exc:
                        log.debug("[QualityFeedback] decay(%r) failed: %s", key, exc)

                # Derive a re-research topic from the fact key
                topic = _topic_from_key(key or "")
                if topic and topic not in re_queued:
                    re_queued.append(topic)

            # Store a re-research note in the KB so the ALE picks it up
            if re_queued and knowledge_db:
                try:
                    knowledge_db.add_fact(
                        f"quality_requeue:{int(time.time())}",
                        {
                            "topics": re_queued,
                            "reason": "low_answer_quality",
                            "quality": round(quality, 3),
                            "query": query[:120],
                        },
                        tags=["quality_feedback", "requeue", "metacognition"],
                    )
                except Exception:
                    pass

        # 4. Log the outcome for observability
        try:
            knowledge_db.add_fact(
                f"quality_feedback:{int(time.time())}",
                {
                    "query": query[:120],
                    "quality": round(quality, 3),
                    "method": method,
                    "reinforced": reinforced,
                    "decayed": decayed,
                    "re_queued": re_queued,
                },
                tags=["quality_feedback", "feedback_loop", "autonomous"],
            )
        except Exception:
            pass

        log.debug(
            "[QualityFeedback] score=%.3f  reinforced=%d  decayed=%d  re_queued=%d",
            quality, reinforced, decayed, len(re_queued),
        )

        # ── Feed quality score into PolicyOptimizer as a decision episode ────
        # This closes the loop between KB-level quality feedback and the policy
        # learning layer so every scored answer improves routing over time.
        try:
            from modules.policy_optimizer import get_policy_optimizer
            po = get_policy_optimizer()
            ctx = po.classify_context(query)
            po.record_episode(
                context_type=ctx,
                advisor_chosen="quality",  # quality scoring path always involves quality advisor
                advisor_confidences={"quality": quality},
                outcome_score=quality,
            )
        except Exception as _po_err:
            log.debug("[QualityFeedback] PolicyOptimizer episode skipped: %s", _po_err)

        return {
            "score": quality,
            "method": method,
            "reinforced": reinforced,
            "decayed": decayed,
            "re_queued": re_queued,
        }

    def _get_reward_model(self) -> Optional[Any]:
        if self._rm is None:
            try:
                from modules.reward_model import get_reward_model
                self._rm = get_reward_model()
            except Exception as exc:
                log.debug("[QualityFeedback] RewardModel unavailable: %s", exc)
        return self._rm


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _decay_fact_confidence(knowledge_db: Any, key: str, amount: float = 0.10) -> bool:
    """Lower the confidence of an existing KB fact.

    Mirrors KnowledgeDB.reinforce() in the negative direction.  Kept as a
    module-level helper here rather than a KnowledgeDB method so that the
    quality-feedback module can be imported without circular-importing the
    full niblit_memory package in every callsite.

    Returns True when a matching fact was found and updated.
    """
    try:
        with knowledge_db.lock:
            facts = knowledge_db.data.get("facts", [])
            for fact in reversed(facts):
                if isinstance(fact, dict) and fact.get("key") == key:
                    old_conf = float(fact.get("confidence", 0.8))
                    fact["confidence"] = max(0.05, old_conf - amount)
                    return True
    except Exception:
        pass
    return False


def _topic_from_key(key: str) -> str:
    """Extract a human-readable topic from a KB fact key.

    Strips common key prefixes (``research:``, ``topic_knowledge:``, etc.)
    and returns the topic word(s) that follow.

    Examples
    --------
    "research:photosynthesis:1234:0"  → "photosynthesis"
    "topic_knowledge:python best practices"  → "python best practices"
    "concept:recursion:5678"  → "recursion"
    """
    if not key:
        return ""
    _STRIP_PREFIXES = (
        "research:", "topic_knowledge:", "self_teach_summary:",
        "concept:", "ale_concepts:", "ale_self_question:",
        "contradiction_flag:", "quality_feedback:", "quiz:",
    )
    lower = key.lower()
    for prefix in _STRIP_PREFIXES:
        if lower.startswith(prefix):
            rest = key[len(prefix):]
            # Remove trailing :timestamp:index segments
            parts = rest.split(":")
            topic = parts[0].replace("_", " ").strip()
            return topic[:80] if topic else ""
    # Fallback: use first non-noise segment
    parts = key.split(":")
    topic = parts[0].replace("_", " ").strip()
    return topic[:80] if len(topic) > 2 else ""


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_qf_singleton: Optional[QualityFeedback] = None
_qf_lock = threading.Lock()


def get_quality_feedback(reward_model: Optional[Any] = None) -> QualityFeedback:
    """Return the process-wide :class:`QualityFeedback` singleton."""
    global _qf_singleton
    with _qf_lock:
        if _qf_singleton is None:
            _qf_singleton = QualityFeedback(reward_model=reward_model)
        elif reward_model is not None and _qf_singleton._rm is None:
            _qf_singleton._rm = reward_model
    return _qf_singleton


if __name__ == "__main__":
    print("Running quality_feedback.py")
