#!/usr/bin/env python3
"""Phase 8 — Behaviour Adaptation Engine.

Understanding must influence future behaviour.  This module converts
validated understanding records into concrete behaviour rules and applies
decision bias to future reasoning.

Pipeline (Phase 8):
    Understanding
        ↓
    Behaviour Rules
        ↓
    Planning
        ↓
    Reasoning
        ↓
    Decision Bias
        ↓
    Execution
        ↓
    Reflection

Learning is only considered complete when future behaviour changes
appropriately in response to updated understanding.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

log = logging.getLogger("Niblit.BehaviourAdaptation")


@dataclass
class BehaviourRule:
    """A concrete decision rule derived from accumulated understanding."""

    rule_id: str
    concept: str
    trigger_condition: str
    recommended_action: str
    confidence: float
    source: str
    created_at: float = field(default_factory=time.time)
    activation_count: int = 0
    last_activated_at: float = 0.0
    outcome_positive: int = 0
    outcome_negative: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def effectiveness(self) -> float:
        total = self.outcome_positive + self.outcome_negative
        if total == 0:
            return self.confidence
        return round(self.outcome_positive / total, 3)


@dataclass
class DecisionBias:
    """Bias applied to a decision context based on active behaviour rules."""

    trace_id: str
    applied_rules: list[str]
    bias_direction: str  # "prefer" | "avoid" | "neutral"
    reasoning: str
    confidence_modifier: float  # -1.0 to +1.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BehaviourAdaptationEngine:
    """Derives behaviour rules from understanding and biases future decisions.

    This engine is the final stage of the learning loop.  Validated
    understanding here translates into concrete changes in how Niblit
    plans, reasons, and decides in future interactions.

    Rules are updated (not replaced) when new understanding arrives for
    the same concept, using an exponential moving average so the rule
    gradually adapts rather than jumping discontinuously.
    """

    _CONFIDENCE_EMA_ALPHA = 0.30

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rules: dict[str, BehaviourRule] = {}
        self._bias_history: list[DecisionBias] = []

    # ── rule management ─────────────────────────────────────────────────────

    def record_understanding(
        self,
        concept: str,
        *,
        understanding_score: float,
        confidence: float,
        evidence: str = "",
        source: str = "foundation",
    ) -> str:
        """Convert a validated understanding item into a behaviour rule.

        Returns the ``rule_id`` of the created or updated rule.
        """
        rule_id = f"rule:{concept}"
        with self._lock:
            if rule_id in self._rules:
                rule = self._rules[rule_id]
                old_conf = rule.confidence
                rule.confidence = round(
                    old_conf * (1 - self._CONFIDENCE_EMA_ALPHA)
                    + confidence * self._CONFIDENCE_EMA_ALPHA,
                    3,
                )
                rule.recommended_action = self._derive_action(
                    concept, understanding_score, evidence
                )
            else:
                rule = BehaviourRule(
                    rule_id=rule_id,
                    concept=concept,
                    trigger_condition=f"when '{concept}' is contextually relevant",
                    recommended_action=self._derive_action(
                        concept, understanding_score, evidence
                    ),
                    confidence=round(min(1.0, max(0.0, confidence)), 3),
                    source=source,
                )
                self._rules[rule_id] = rule
        return rule_id

    def apply_decision_bias(
        self,
        trace_id: str,
        context: dict[str, Any],
    ) -> DecisionBias:
        """Apply behaviour rules to bias a decision context.

        Matches active rules against the context topic/intent and returns
        a :class:`DecisionBias` that the planning stage can incorporate.
        """
        with self._lock:
            active = [r for r in self._rules.values() if r.confidence >= 0.55]

        if not active:
            bias = DecisionBias(
                trace_id=trace_id,
                applied_rules=[],
                bias_direction="neutral",
                reasoning="No applicable behaviour rules found.",
                confidence_modifier=0.0,
            )
            with self._lock:
                self._bias_history.append(bias)
            return bias

        topic = str(
            context.get("topic")
            or context.get("intent")
            or context.get("event_type")
            or ""
        ).lower()
        matched = [
            r
            for r in active
            if r.concept.lower() in topic or topic in r.concept.lower()
        ]
        if not matched:
            matched = sorted(active, key=lambda r: r.confidence, reverse=True)[:3]

        now = time.time()
        with self._lock:
            for rule in matched:
                rule.activation_count += 1
                rule.last_activated_at = now

        avg_confidence = sum(r.confidence for r in matched) / len(matched)
        direction = "prefer" if avg_confidence >= 0.65 else "neutral"
        bias = DecisionBias(
            trace_id=trace_id,
            applied_rules=[r.rule_id for r in matched],
            bias_direction=direction,
            reasoning="; ".join(r.recommended_action for r in matched[:3]),
            confidence_modifier=round(avg_confidence - 0.5, 3),
        )
        with self._lock:
            self._bias_history.append(bias)
            if len(self._bias_history) > 500:
                self._bias_history[:] = self._bias_history[-500:]
        return bias

    def record_outcome(self, rule_id: str, *, positive: bool) -> None:
        """Record the outcome of a rule activation to improve effectiveness."""
        with self._lock:
            rule = self._rules.get(rule_id)
            if rule is None:
                return
            if positive:
                rule.outcome_positive += 1
                rule.confidence = round(min(1.0, rule.confidence + 0.02), 3)
            else:
                rule.outcome_negative += 1
                rule.confidence = round(max(0.0, rule.confidence - 0.03), 3)

    def _derive_action(self, concept: str, score: float, evidence: str) -> str:
        if score >= 0.75:
            return (
                f"Apply high-confidence understanding of '{concept}' "
                "to guide the decision."
            )
        if score >= 0.55:
            short = (evidence or "no evidence recorded")[:120]
            return f"Consider '{concept}' as moderately relevant: {short}"
        return (
            f"Treat '{concept}' with caution — "
            "understanding is still developing."
        )

    # ── read access ─────────────────────────────────────────────────────────

    def active_rules(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rules = sorted(
                self._rules.values(), key=lambda r: r.confidence, reverse=True
            )
            return [r.to_dict() for r in rules[: max(1, limit)]]

    def rule_count(self) -> int:
        with self._lock:
            return len(self._rules)

    def status(self) -> dict[str, Any]:
        with self._lock:
            rules = list(self._rules.values())
            high_conf = [r for r in rules if r.confidence >= 0.7]
            return {
                "total_rules": len(rules),
                "high_confidence_rules": len(high_conf),
                "bias_applications": len(self._bias_history),
                "pipeline": [
                    "understanding",
                    "behaviour_rules",
                    "planning",
                    "reasoning",
                    "decision_bias",
                    "execution",
                    "reflection",
                ],
            }
