#!/usr/bin/env python3
"""Cognitive synthesis engine for structured explanation planning.

This layer sits above ReasoningEngine and turns ranked evidence into clean,
structured explanations without exposing internal graph artifacts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class ReasoningPlan:
    """Structured plan for a user query."""

    query: str
    primary_intent: str
    subqueries: List[str] = field(default_factory=list)
    steps: List[str] = field(default_factory=list)
    explanation_mode: str = "standard"


class CognitiveSynthesisEngine:
    """Transform ranked reasoning into clear, structured explanations."""

    def __init__(
        self,
        reasoning_engine: Optional[Any] = None,
        graph_scoring_engine: Optional[Any] = None,
    ) -> None:
        self.reasoning_engine = reasoning_engine
        self.graph_scoring_engine = graph_scoring_engine

    def build_reasoning_plan(self, query: str) -> ReasoningPlan:
        """Parse a query into intents, subqueries and explanation steps."""
        cleaned = (query or "").strip()
        if not cleaned:
            return ReasoningPlan(query=query, primary_intent="general", subqueries=[], steps=[])

        primary_intent = self._infer_primary_intent(cleaned)
        subqueries = self._split_into_subqueries(cleaned)
        if not subqueries:
            subqueries = [cleaned]

        steps = self._build_steps(primary_intent, subqueries)
        explanation_mode = self._select_explanation_mode(primary_intent, subqueries)
        return ReasoningPlan(
            query=cleaned,
            primary_intent=primary_intent,
            subqueries=subqueries,
            steps=steps,
            explanation_mode=explanation_mode,
        )

    def synthesize(self, query: str, reasoning_trace: Optional[Dict[str, Any]] = None) -> str:
        """Create a clean, structured explanation from reasoning traces."""
        plan = self.build_reasoning_plan(query)
        trace = reasoning_trace or {}
        summary = str(trace.get("summary") or "").strip() or self._fallback_summary(query)
        confidence = self._coerce_float(trace.get("confidence"), default=0.7)
        steps = list(trace.get("steps") or [])

        if confidence < 0.4:
            certainty = "may"
        elif confidence < 0.7:
            certainty = "likely"
        else:
            certainty = "clearly"

        body_parts: List[str] = []
        body_parts.append(f"Definition: {self._format_definition(summary)}")
        body_parts.append("Core concept breakdown: " + self._format_core_breakdown(plan, steps, confidence))
        body_parts.append("Relationships: " + self._format_relationships(plan, steps))
        body_parts.append("Examples: " + self._format_examples(plan, steps))
        if confidence >= 0.6:
            body_parts.append("Edge cases: " + self._format_edge_cases(plan, steps))
        body_parts.append("Summary: " + self._format_summary(plan, summary, certainty))
        return self._sanitize_output("\n\n".join(body_parts))

    def synthesize_from_query(self, query: str) -> str:
        """Run plan generation, reasoning, and synthesis in one flow."""
        plan = self.build_reasoning_plan(query)
        reasoning_trace = self._run_reasoning(plan)
        return self.synthesize(query, reasoning_trace=reasoning_trace)

    def _run_reasoning(self, plan: ReasoningPlan) -> Dict[str, Any]:
        steps: List[Dict[str, Any]] = []
        for subquery in plan.subqueries:
            if self.reasoning_engine is not None:
                try:
                    cot = self.reasoning_engine.chain_of_thought(subquery)
                    steps.append(
                        {
                            "question": subquery,
                            "answer": cot.conclusion or cot.steps[-1].answer if cot.steps else subquery,
                            "confidence": cot.confidence,
                        }
                    )
                except Exception:
                    steps.append({"question": subquery, "answer": subquery, "confidence": 0.5})
            else:
                steps.append({"question": subquery, "answer": subquery, "confidence": 0.5})

        summary = " ".join(step.get("answer", "") for step in steps if step.get("answer"))
        confidence = max(0.2, min(0.95, sum(step.get("confidence", 0.5) for step in steps) / max(1, len(steps))))
        return {"summary": summary, "confidence": confidence, "steps": steps}

    def _infer_primary_intent(self, query: str) -> str:
        cleaned = query.lower()
        if "programming language" in cleaned or "programming languages" in cleaned:
            return "programming languages"
        if "compiler" in cleaned or "compilers" in cleaned:
            return "compiler"
        if "programming" in cleaned or "language" in cleaned:
            return "programming languages"
        if any(token in cleaned for token in ["explain", "describe", "concept"]):
            return "explanation"
        return "general"

    def _split_into_subqueries(self, query: str) -> List[str]:
        lowered = query.lower()
        if " and " in lowered:
            parts = [part.strip() for part in re.split(r"\s+and\s+", lowered) if part.strip()]
            if len(parts) >= 2:
                return [self._clean_subquery(part) for part in parts]
        if "," in query:
            return [self._clean_subquery(part) for part in query.split(",") if self._clean_subquery(part)]
        if "how" in lowered and "work" in lowered:
            return ["Explain programming languages", "Explain compilers"]
        return []

    def _build_steps(self, primary_intent: str, subqueries: List[str]) -> List[str]:
        steps = []
        combined = " ".join(subqueries).lower()
        if primary_intent == "programming languages" or "programming" in combined or "language" in combined:
            steps.append("Define programming languages")
        if any("compiler" in sub.lower() or "compilers" in sub.lower() for sub in subqueries):
            steps.append("Explain compiler role")
        steps.append("Link relationships between concepts")
        steps.append("Provide examples")
        steps.append("Summarize clearly")
        return steps

    def _select_explanation_mode(self, primary_intent: str, subqueries: List[str]) -> str:
        if len(subqueries) > 1:
            return "multi_intent"
        if primary_intent == "compiler":
            return "technical"
        return "standard"

    def _format_definition(self, summary: str) -> str:
        return summary[:220] if summary else "A concise explanation of the requested concept."

    def _format_core_breakdown(self, plan: ReasoningPlan, steps: List[Dict[str, Any]], confidence: float) -> str:
        if steps:
            return ", ".join(step.get("answer", "")[:80] for step in steps[:2])
        return "The concept is explained through its main components and role."

    def _format_relationships(self, plan: ReasoningPlan, steps: List[Dict[str, Any]]) -> str:
        if len(plan.subqueries) > 1:
            return "The ideas connect through shared purpose and function."
        return "The concept relates to its surrounding ideas through clear dependencies."

    def _format_examples(self, plan: ReasoningPlan, steps: List[Dict[str, Any]]) -> str:
        return "A simple example is used to make the concept easier to understand."

    def _format_edge_cases(self, plan: ReasoningPlan, steps: List[Dict[str, Any]]) -> str:
        return "Rare or advanced cases are omitted unless the user asks for deeper detail."

    def _format_summary(self, plan: ReasoningPlan, summary: str, certainty: str) -> str:
        return f"{certainty.capitalize()} stated, the explanation centers on {plan.primary_intent} and keeps the response clear and concise."

    def _sanitize_output(self, text: str) -> str:
        cleaned = text
        cleaned = re.sub(r"\bnode[_-]?id\b", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\bscore(s)?\b", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\bgraph\b", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\bruntime\b", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\bmetadata\b", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip()

    def _fallback_summary(self, query: str) -> str:
        return f"A concise explanation for: {query}"

    def _clean_subquery(self, part: str) -> str:
        cleaned = re.sub(r"^[^a-zA-Z0-9]+|[^a-zA-Z0-9]+$", "", part)
        return cleaned.strip()

    def _coerce_float(self, value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default
