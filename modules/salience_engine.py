#!/usr/bin/env python3
"""Phase Ω.6 Salience scoring for cognitive attention allocation."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


@dataclass
class SalienceAssessment:
    target: str
    salience: float
    urgency: float
    relevance: float
    novelty: float
    recency: float
    governance_weight: float
    user_impact: float
    confidence: float
    rationale: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "salience": round(self.salience, 4),
            "urgency": round(self.urgency, 4),
            "relevance": round(self.relevance, 4),
            "novelty": round(self.novelty, 4),
            "recency": round(self.recency, 4),
            "governance_weight": round(self.governance_weight, 4),
            "user_impact": round(self.user_impact, 4),
            "confidence": round(self.confidence, 4),
            "rationale": self.rationale,
            "timestamp": self.timestamp,
        }


class SalienceEngine:
    """Convert raw cognitive signals into a comparable attention score."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._history: list[SalienceAssessment] = []
        self._last_assessment: SalienceAssessment | None = None

    def assess(
        self,
        target: str,
        *,
        urgency: float = 0.0,
        relevance: float = 0.0,
        novelty: float = 0.0,
        recency: float = 0.5,
        governance_weight: float = 0.0,
        user_impact: float = 0.0,
        contradiction_penalty: float = 0.0,
    ) -> SalienceAssessment:
        urgency = _clamp(urgency)
        relevance = _clamp(relevance)
        novelty = _clamp(novelty)
        recency = _clamp(recency)
        governance_weight = _clamp(governance_weight)
        user_impact = _clamp(user_impact)
        contradiction_penalty = _clamp(contradiction_penalty)

        salience = _clamp(
            0.28 * urgency
            + 0.28 * relevance
            + 0.16 * novelty
            + 0.12 * recency
            + 0.08 * governance_weight
            + 0.08 * user_impact
            - 0.12 * contradiction_penalty
        )
        if governance_weight >= 0.85 and relevance >= 0.7:
            salience = max(salience, 0.85)

        rationale = self._build_rationale(
            urgency=urgency,
            relevance=relevance,
            novelty=novelty,
            governance_weight=governance_weight,
            contradiction_penalty=contradiction_penalty,
        )
        assessment = SalienceAssessment(
            target=target,
            salience=salience,
            urgency=urgency,
            relevance=relevance,
            novelty=novelty,
            recency=recency,
            governance_weight=governance_weight,
            user_impact=user_impact,
            confidence=max(0.5, salience),
            rationale=rationale,
        )
        with self._lock:
            self._last_assessment = assessment
            self._history.append(assessment)
            if len(self._history) > 500:
                self._history = self._history[-500:]
        self._emit(assessment)
        return assessment

    def rank(self, items: list[dict[str, Any]]) -> list[SalienceAssessment]:
        assessments = [
            self.assess(
                item.get("target") or item.get("subsystem") or f"item_{index}",
                urgency=item.get("urgency", 0.0),
                relevance=item.get("relevance", 0.0),
                novelty=item.get("novelty", 0.0),
                recency=item.get("recency", 0.5),
                governance_weight=item.get("governance_weight", 0.0),
                user_impact=item.get("user_impact", 0.0),
                contradiction_penalty=item.get("contradiction_penalty", 0.0),
            )
            for index, item in enumerate(items)
        ]
        return sorted(assessments, key=lambda assessment: assessment.salience, reverse=True)

    def status(self) -> dict[str, Any]:
        with self._lock:
            history = list(self._history)
            last = self._last_assessment
        avg_salience = sum(item.salience for item in history) / len(history) if history else 0.0
        return {
            "history_count": len(history),
            "average_salience": round(avg_salience, 4),
            "last_assessment": last.to_dict() if last else None,
            "top_targets": [item.target for item in sorted(history, key=lambda item: item.salience, reverse=True)[:5]],
        }

    @staticmethod
    def _build_rationale(
        *,
        urgency: float,
        relevance: float,
        novelty: float,
        governance_weight: float,
        contradiction_penalty: float,
    ) -> str:
        primary = max(
            (
                ("urgency", urgency),
                ("relevance", relevance),
                ("novelty", novelty),
                ("governance", governance_weight),
            ),
            key=lambda item: item[1],
        )[0]
        if contradiction_penalty >= 0.6:
            return f"Salience constrained by contradiction pressure despite {primary}-driven demand."
        return f"Salience dominated by {primary} with governance-aware weighting."

    def _emit(self, assessment: SalienceAssessment) -> None:
        try:
            from modules.event_bus import EVENT_SALIENCE_SCORED, NiblitEvent, get_event_bus

            get_event_bus().publish(
                NiblitEvent(
                    type=EVENT_SALIENCE_SCORED,
                    source="salience_engine",
                    payload=assessment.to_dict(),
                )
            )
        except Exception:
            pass


_salience_engine: SalienceEngine | None = None
_salience_lock = threading.Lock()


def get_salience_engine() -> SalienceEngine:
    global _salience_engine
    with _salience_lock:
        if _salience_engine is None:
            _salience_engine = SalienceEngine()
    return _salience_engine
