#!/usr/bin/env python3
"""
ADAPTIVE LEARNING MODULE
Learn user preferences and adapt learning strategy dynamically.

Improvements over original:
- Bounded feedback history (50-entry cap) to avoid unbounded memory growth.
- Rolling average satisfaction computed over all recorded feedback rather
  than a single data point, so the strategy reacts to trends not spikes.
- KB persistence: preference changes and strategy updates are written as
  facts so the identity survives restarts.
- QualityFeedback integration: if available, record_feedback() also calls
  QualityFeedback.record_answer_quality() so the SDAL's policy optimizer
  gets the signal.
"""

import logging
from typing import Dict, List, Any
from collections import defaultdict

log = logging.getLogger("AdaptiveLearning")

# Maximum number of feedback entries to keep in memory.
# Oldest entries are discarded when this limit is reached.
_MAX_FEEDBACK_HISTORY: int = 50

# Satisfaction thresholds for strategy selection (1–5 scale).
_AGGRESSIVE_THRESHOLD: float = 3.8   # mean ≥ this → aggressive
_CONSERVATIVE_THRESHOLD: float = 2.5  # mean ≤ this → conservative


class AdaptiveLearning:
    """Adapt learning based on user feedback and preferences."""

    def __init__(self, knowledge_db=None, quality_feedback=None):
        self.user_preferences: defaultdict = defaultdict(int)
        # Each entry: {"query", "satisfaction"} — response text excluded to
        # avoid storing arbitrarily large strings.
        self.feedback_history: List[Dict[str, Any]] = []
        self.learning_strategy: str = "balanced"
        self._db = knowledge_db
        self._quality_feedback = quality_feedback

    def track_user_interest(self, topic: str, interest_level: int = 1) -> None:
        """Track topics the user is interested in.

        Higher *interest_level* numbers indicate stronger interest.  Preference
        counts are persisted to the KB so they survive restarts.
        """
        log.info("📌 [ADAPTIVE] Tracking interest in '%s' (level: %d)", topic, interest_level)
        self.user_preferences[topic] += interest_level
        self._persist(f"adaptive:preference:{topic}", {
            "topic": topic,
            "total_interest": self.user_preferences[topic],
        })

    def record_feedback(
        self,
        query: str,
        response: str,
        satisfaction: int,
        propagate_quality: bool = True,
    ) -> None:
        """Record user feedback on a response.

        Parameters
        ----------
        query:        The user's original question.
        response:     The assistant's answer (stored only as a length hint, not
                      the full text, to bound memory usage).
        satisfaction: 1–5 rating (1 = poor, 5 = excellent).
        """
        satisfaction = max(1, min(5, int(satisfaction)))
        log.info("💬 [ADAPTIVE] Recording feedback: %d/5", satisfaction)

        # Keep history bounded
        if len(self.feedback_history) >= _MAX_FEEDBACK_HISTORY:
            self.feedback_history.pop(0)

        self.feedback_history.append({
            "query": query,
            "response_length": len(response),
            "satisfaction": satisfaction,
        })

        # Recompute strategy from rolling mean
        old_strategy = self.learning_strategy
        self.learning_strategy = self._compute_strategy()

        # Persist strategy change to KB
        if self.learning_strategy != old_strategy:
            self._persist("adaptive:strategy", {
                "strategy": self.learning_strategy,
                "mean_satisfaction": self._mean_satisfaction(),
                "feedback_count": len(self.feedback_history),
            })

        # Wire user satisfaction into the same unified quality / policy loop
        # used by the rest of Niblit.
        if propagate_quality and self._quality_feedback is not None:
            try:
                self._quality_feedback.record_answer_quality(
                    query=query,
                    answer=response,
                    knowledge_db=self._db,
                    score_override=satisfaction / 5.0,
                )
            except Exception as exc:
                log.debug("[AdaptiveLearning] QualityFeedback call failed: %s", exc)

    def get_recommended_topics(self, count: int = 5) -> List[str]:
        """Return recommended research topics sorted by accumulated interest."""
        log.info("🎯 [ADAPTIVE] Getting recommendations")
        sorted_topics = sorted(
            self.user_preferences.items(), key=lambda x: x[1], reverse=True
        )
        recommendations = [topic for topic, _ in sorted_topics[:count]]
        log.info("✅ [ADAPTIVE] Recommended: %s", recommendations)
        return recommendations

    def adjust_learning_pace(self) -> Dict[str, Any]:
        """Return recommended learning pace parameters based on current strategy."""
        log.info("⚙️ [ADAPTIVE] Adjusting learning pace")
        mean_sat = self._mean_satisfaction()

        pace = {
            "strategy": self.learning_strategy,
            "average_satisfaction": round(mean_sat, 2),
            "cycles_per_hour": 6 if self.learning_strategy == "aggressive" else (
                3 if self.learning_strategy == "balanced" else 1
            ),
            "topics_per_cycle": 3 if self.learning_strategy == "aggressive" else (
                2 if self.learning_strategy == "balanced" else 1
            ),
            "explanation": (
                f"Learning pace '{self.learning_strategy}' based on rolling "
                f"mean satisfaction {mean_sat:.2f}/5 over "
                f"{len(self.feedback_history)} feedback entries."
            ),
        }
        log.info("✅ [ADAPTIVE] Pace: %s", self.learning_strategy)
        return pace

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _mean_satisfaction(self) -> float:
        """Return the rolling mean satisfaction score (1.0–5.0).  Defaults to 3.0."""
        if not self.feedback_history:
            return 3.0
        return sum(f["satisfaction"] for f in self.feedback_history) / len(self.feedback_history)

    def _compute_strategy(self) -> str:
        """Compute the learning strategy from the rolling mean satisfaction."""
        mean = self._mean_satisfaction()
        if mean >= _AGGRESSIVE_THRESHOLD:
            return "aggressive"
        if mean <= _CONSERVATIVE_THRESHOLD:
            return "conservative"
        return "balanced"

    def _persist(self, key: str, data: Any) -> None:
        """Write a KB fact if a knowledge_db is wired in."""
        if self._db is None:
            return
        try:
            if hasattr(self._db, "add_fact"):
                self._db.add_fact(key, data, tags=["adaptive_learning"])
            elif hasattr(self._db, "store_learning"):
                self._db.store_learning({"key": key, "data": data, "tags": ["adaptive_learning"]})
        except Exception as exc:
            log.debug("[AdaptiveLearning] KB persist failed: %s", exc)


if __name__ == "__main__":
    print('Running adaptive_learning.py')
