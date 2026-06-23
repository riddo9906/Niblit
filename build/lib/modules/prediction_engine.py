#!/usr/bin/env python3
"""
PREDICTION ENGINE MODULE
Learn patterns and predict trends/outcomes from real KB data.

Improvements over the original:
- Stop-word filtering in extract_patterns() so bigrams like "is the" or
  "of a" don't pollute the pattern index.
- predict_trends() now uses meaningful-word filtering matching the stop-word
  sets used in the rest of the research pipeline.
- forecast_outcomes() derives its forecast from actual KB statistics (fact
  count, mean confidence, recent activity) instead of hardcoded strings.
- All pattern/insight results are persisted to the KB as facts.
"""

import logging
import re
from typing import List, Dict, Any
from collections import Counter

log = logging.getLogger("PredictionEngine")

# Stop words to exclude from bigram/unigram analysis.
_PRED_STOP_WORDS: frozenset = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "to", "of", "in", "for", "on",
    "with", "at", "by", "from", "this", "that", "it", "its", "and", "or",
    "but", "not", "so", "as", "if", "which", "who", "what", "how", "when",
    "where", "also", "very", "such", "more", "than", "all", "any", "most",
    "some", "each", "use", "used", "using", "about", "into", "then",
    "their", "they", "them", "these", "those", "you", "we", "our",
})

# Minimum word length to be considered meaningful in pattern extraction.
_MIN_WORD_LEN: int = 4


class PredictionEngine:
    """Learn patterns from KB data and predict trends."""

    def __init__(self, knowledge_db):
        self.db = knowledge_db
        self.patterns: Dict[str, int] = {}
        self.predictions: List[str] = []

    def extract_patterns(self, data: List[Dict]) -> Dict[str, int]:
        """Extract bigram patterns from research data, filtering stop words.

        Parameters
        ----------
        data:
            List of dicts with a ``"value"`` key containing text.
        """
        log.info("📊 [PREDICT] Extracting patterns from %d data points", len(data))

        pattern_counter: Counter = Counter()

        for item in data:
            text = str(item.get("value", "")).lower()
            # Keep only meaningful words before building bigrams
            words = [
                w for w in re.findall(r"[a-z]+", text)
                if len(w) >= _MIN_WORD_LEN and w not in _PRED_STOP_WORDS
            ]
            for i in range(len(words) - 1):
                bigram = f"{words[i]} {words[i + 1]}"
                pattern_counter[bigram] += 1

        self.patterns = dict(pattern_counter.most_common(20))

        # Persist patterns to KB
        if self.patterns:
            self._persist("prediction:patterns", {
                "top_patterns": list(self.patterns.items())[:10],
                "total_data_points": len(data),
            })

        log.info("✅ [PREDICT] Extracted %d patterns", len(self.patterns))
        return self.patterns

    def predict_trends(self, historical_data: List[str]) -> List[str]:
        """Predict likely trends from historical text data.

        Only considers meaningful words (length ≥ 4, not in stop-word list).
        """
        log.info("🔮 [PREDICT] Predicting trends from %d data points", len(historical_data))

        word_freq: Counter = Counter()
        for text in historical_data:
            words = [
                w for w in re.findall(r"[a-z]+", text.lower())
                if len(w) >= _MIN_WORD_LEN and w not in _PRED_STOP_WORDS
            ]
            word_freq.update(words)

        predictions: List[str] = []
        for word, freq in word_freq.most_common(5):
            predictions.append(f"Trend: {word} (frequency: {freq})")

        self.predictions = predictions

        # Persist predicted trends
        if predictions:
            self._persist("prediction:trends", {"trends": predictions})

        log.info("✅ [PREDICT] Generated %d predictions", len(predictions))
        return predictions

    def forecast_outcomes(self, current_state: Dict[str, Any]) -> Dict[str, str]:
        """Forecast likely outcomes derived from real KB statistics.

        Uses fact_count, mean_confidence (from KnowledgeDB) and any
        research activity data available in *current_state* to produce
        concrete, data-driven forecasts instead of hardcoded strings.
        """
        log.info("🎯 [PREDICT] Forecasting outcomes")

        # Gather live KB statistics
        fact_count = current_state.get("fact_count", 0)
        mean_confidence = current_state.get("mean_confidence", 0.5)
        recent_cycles = current_state.get("recent_cycles", 0)
        top_domain = current_state.get("top_domain", "AI/ML")

        if fact_count == 0 and self.db is not None:
            try:
                facts = self.db.list_facts(1000) if hasattr(self.db, "list_facts") else []
                fact_count = len(facts)
                confidences = [f.get("confidence", 0.5) for f in facts if "confidence" in f]
                if confidences:
                    mean_confidence = sum(confidences) / len(confidences)
            except Exception:
                pass

        # Derive forecasts from statistics
        growth = "rapid" if fact_count > 500 else ("moderate" if fact_count > 100 else "early-stage")
        confidence_label = (
            "high" if mean_confidence >= 0.65
            else "moderate" if mean_confidence >= 0.40
            else "low — more research cycles recommended"
        )
        next_area = (
            "meta-cognition and reasoning"
            if mean_confidence >= 0.60
            else f"deepening {top_domain} coverage"
        )

        forecasts = {
            "learning_direction": f"Expanding into {top_domain} domains (KB: {fact_count} facts)",
            "knowledge_growth": f"{growth.capitalize()} growth trajectory based on current KB size",
            "capability_trajectory": f"Knowledge confidence: {confidence_label}",
            "next_improvement_area": next_area,
            "estimated_timeline": (
                f"~{max(1, 10 - recent_cycles)} more cycles to reach coverage threshold"
                if recent_cycles < 10 else "Coverage threshold likely already met"
            ),
        }

        # Persist forecasts
        self._persist("prediction:forecast", forecasts)

        log.info("✅ [PREDICT] Forecasts generated (fact_count=%d)", fact_count)
        return forecasts

    def extract_insights(self, patterns: Dict[str, int]) -> List[str]:
        """Extract actionable insights from a pattern frequency dict."""
        log.info("💡 [PREDICT] Extracting insights from %d patterns", len(patterns))

        insights: List[str] = []
        for pattern, count in sorted(patterns.items(), key=lambda x: x[1], reverse=True)[:5]:
            insight = f"Strong pattern: '{pattern}' appears {count} times"
            insights.append(insight)

        # Persist insights
        if insights:
            self._persist("prediction:insights", {"insights": insights})

        log.info("✅ [PREDICT] Generated %d insights", len(insights))
        return insights

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _persist(self, key: str, data: Any) -> None:
        """Persist a prediction fact to the KB."""
        if self.db is None:
            return
        try:
            if hasattr(self.db, "add_fact"):
                self.db.add_fact(key, data, tags=["prediction"])
            elif hasattr(self.db, "store_learning"):
                self.db.store_learning({"key": key, "data": data, "tags": ["prediction"]})
        except Exception as exc:
            log.debug("[PredictionEngine] KB persist failed: %s", exc)


if __name__ == "__main__":
    print('Running prediction_engine.py')

