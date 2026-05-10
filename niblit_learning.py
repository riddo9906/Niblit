#!/usr/bin/env python3
"""Niblit Self-Learning System.

Phase 19 upgrade:
Move from a simple sentiment counter to a richer interaction-feedback model that
can participate in Niblit's unified feedback loop.  Each interaction now stores
not just sentiment, but also response richness and any quality signals produced
elsewhere in the system (EvaluationEngine / QualityFeedback).

Phase 21 upgrade:
Accept ``quality_axes`` (multi-axis quality dict from Phase 20 arbitration) in
``process_interaction()`` and persist the axes alongside the learning entry so
that downstream analysis can consume per-dimension quality rather than only
the aggregated scalar.  The axes dict contains: reasoning, engagement,
factuality, strategic_alignment, stability.
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_POSITIVE_RE = re.compile(r"\b(good|great|awesome|thanks|helpful|nice|love)\b")
_NEGATIVE_RE = re.compile(r"\b(bad|angry|sad|tired|pain|wrong|broken|useless)\b")
_QUESTION_RE = re.compile(r"\b(what|why|how|when|where|which|can|could|should)\b")

_EVOLVE_WINDOW_DEFAULT = max(1, int(os.environ.get("NIBLIT_LEARNING_EVOLVE_WINDOW", "300")))
_EVOLVE_SCAN_MULTIPLIER = max(2, int(os.environ.get("NIBLIT_LEARNING_SCAN_MULTIPLIER", "3")))


class NiblitLearning:
    def __init__(self, memory):
        self.memory = memory

    def process_interaction(
        self,
        user_message: str,
        ai_response: str,
        quality_score: Optional[float] = None,
        feedback_score: Optional[float] = None,
        chosen_advisor: str = "",
        loop_source: str = "niblit_core",
        epoch_tag: Optional[int] = None,
        quality_axes: Optional[Dict[str, float]] = None,
    ) -> None:
        """Analyze one interaction and store a quality-aware learning entry.

        Phase 21: ``quality_axes`` is an optional dict produced by
        ``NiblitCore._arbitrate_turn_quality()`` containing per-dimension
        quality scores (reasoning, engagement, factuality, strategic_alignment,
        stability).  When provided, the axes are persisted in the learning
        record alongside the aggregated scalar so that future analysis and
        adaptive modules can consume the most relevant dimension.
        """
        if not user_message:
            return

        cleaned = user_message.lower().strip()
        response = (ai_response or "").strip()

        positivity = len(_POSITIVE_RE.findall(cleaned))
        negativity = len(_NEGATIVE_RE.findall(cleaned))
        is_question = "?" in user_message or bool(_QUESTION_RE.search(cleaned))
        response_length = len(response)
        response_lines = len([ln for ln in response.splitlines() if ln.strip()])
        response_has_structure = int(any(tok in response for tok in ("•", "-", "1.", "2.", ":")))

        response_richness = min(
            1.0,
            (response_length / 400.0)
            + min(0.2, response_lines * 0.03)
            + (0.10 if response_has_structure else 0.0),
        )

        external_scores = [
            float(s) for s in (quality_score, feedback_score) if s is not None
        ]
        if external_scores:
            interaction_quality = sum(external_scores) / len(external_scores)
            quality_source = "external"
        else:
            heuristic = 0.50 + min(0.20, response_richness * 0.20)
            heuristic += min(0.10, positivity * 0.05)
            heuristic -= min(0.15, negativity * 0.05)
            interaction_quality = heuristic
            quality_source = "heuristic"

        interaction_quality = round(max(0.0, min(1.0, interaction_quality)), 4)

        data = {
            "learning_type": "interaction_feedback",
            "raw": user_message,
            "normalized": cleaned,
            "positivity": positivity,
            "negativity": negativity,
            "is_question": is_question,
            "response": response[:2000],
            "response_length": response_length,
            "response_lines": response_lines,
            "response_richness": round(response_richness, 4),
            "interaction_quality": interaction_quality,
            "quality_source": quality_source,
            "quality_score": round(float(quality_score), 4) if quality_score is not None else None,
            "feedback_score": round(float(feedback_score), 4) if feedback_score is not None else None,
            "chosen_advisor": chosen_advisor,
            "loop_source": loop_source,
            "loop_success": interaction_quality >= 0.55,
            "epoch_tag": epoch_tag,
            # Phase 21: multi-axis quality dimensions from arbitration
            "quality_axes": quality_axes if isinstance(quality_axes, dict) else None,
        }

        self.memory.store_learning(data)
        log.debug("Learning module stored quality-aware interaction entry.")

    def evolve(self) -> Optional[Dict[str, Any]]:
        """Aggregate stored interaction-feedback entries into persistent prefs."""
        log_entries: List[Any] = self.memory.get_learning_log()
        if not log_entries:
            return None

        evolve_window = _EVOLVE_WINDOW_DEFAULT
        scan_limit = max(evolve_window * _EVOLVE_SCAN_MULTIPLIER, evolve_window)
        candidate_entries = log_entries[-scan_limit:]
        interactions = [
            d for d in candidate_entries
            if isinstance(d, dict) and d.get("learning_type") == "interaction_feedback"
        ]
        if len(interactions) > evolve_window:
            interactions = interactions[-evolve_window:]
        if not interactions:
            return None

        total = len(interactions)
        total_positive = sum(int(d.get("positivity", 0)) for d in interactions)
        total_negative = sum(int(d.get("negativity", 0)) for d in interactions)
        avg_quality = sum(float(d.get("interaction_quality", 0.5)) for d in interactions) / total
        avg_response_length = sum(int(d.get("response_length", 0)) for d in interactions) / total
        success_rate = (
            sum(1 for d in interactions if d.get("loop_success")) / total
        )
        question_ratio = (
            sum(1 for d in interactions if d.get("is_question")) / total
        )

        if avg_response_length >= 280:
            response_style = "rich"
        elif avg_response_length <= 100:
            response_style = "brief"
        else:
            response_style = "balanced"

        pref = {
            "positive_bias": total_positive,
            "negative_bias": total_negative,
            "interactions": total,
            "avg_interaction_quality": round(avg_quality, 4),
            "success_rate": round(success_rate, 4),
            "avg_response_length": round(avg_response_length, 2),
            "question_ratio": round(question_ratio, 4),
            "preferred_response_style": response_style,
            "feedback_loop_coherence": round((avg_quality * 0.6) + (success_rate * 0.4), 4),
            "aggregation_window": evolve_window,
            "all_time_log_entries": len(log_entries),
        }

        self.memory.store_preferences(pref)
        return pref

# Direct test
if __name__ == "__main__":
    from niblit_memory import NiblitMemory
    mem = NiblitMemory()
    L = NiblitLearning(mem)
    L.process_interaction("This is good", "I’m glad.")
    print(L.evolve())
