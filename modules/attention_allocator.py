#!/usr/bin/env python3
"""Phase Ω.6 attention allocation across active cognitive subsystems."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

from modules.cognitive_budget_manager import get_cognitive_budget_manager
from modules.salience_engine import SalienceAssessment, get_salience_engine


@dataclass
class AttentionAllocation:
    allocations: dict[str, float]
    salience: dict[str, float]
    suppressed_subsystems: list[str]
    attention_pressure: float
    budget_utilization: float
    rationale: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allocations": {key: round(value, 4) for key, value in self.allocations.items()},
            "salience": {key: round(value, 4) for key, value in self.salience.items()},
            "suppressed_subsystems": list(self.suppressed_subsystems),
            "attention_pressure": round(self.attention_pressure, 4),
            "budget_utilization": round(self.budget_utilization, 4),
            "rationale": self.rationale,
            "timestamp": self.timestamp,
        }


class AttentionAllocator:
    """Allocate scarce cognition to the most important active subsystems."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_allocation: AttentionAllocation | None = None
        self._history: list[AttentionAllocation] = []

    def allocate(self, items: list[dict[str, Any]], *, total_budget: float = 1.0, context_pressure: float = 0.0) -> dict[str, Any]:
        budget_manager = get_cognitive_budget_manager()
        salience_engine = get_salience_engine()
        effective_budget = budget_manager.reset_cycle(total_budget=total_budget, context_pressure=context_pressure)

        indexed: list[tuple[dict[str, Any], SalienceAssessment]] = []
        for index, item in enumerate(items):
            subsystem = item.get("subsystem") or item.get("target") or f"subsystem_{index}"
            indexed.append(
                (
                    {**item, "subsystem": subsystem},
                    salience_engine.assess(
                        subsystem,
                        urgency=item.get("urgency", 0.0),
                        relevance=item.get("relevance", 0.0),
                        novelty=item.get("novelty", 0.0),
                        recency=item.get("recency", 0.5),
                        governance_weight=item.get("governance_weight", 0.0),
                        user_impact=item.get("user_impact", 0.0),
                        contradiction_penalty=item.get("contradiction_penalty", 0.0),
                    ),
                )
            )

        indexed.sort(key=lambda item: item[1].salience, reverse=True)
        allocations = {item["subsystem"]: 0.0 for item, _ in indexed}
        salience = {item["subsystem"]: assessment.salience for item, assessment in indexed}
        active = [item for item, assessment in indexed if item.get("requested_units", 0.0) > 0.0 and assessment.salience >= 0.15]
        fairness_floor = min(0.12, effective_budget / max(1, len(active)) * 0.5) if active else 0.0

        for item, assessment in indexed:
            requested = max(0.0, float(item.get("requested_units", 0.0)))
            if requested <= 0.0:
                continue
            if assessment.salience < 0.15:
                continue
            minimum_reserve = min(requested, fairness_floor)
            decision = budget_manager.allocate(
                item["subsystem"],
                minimum_reserve,
                salience=assessment.salience,
                recursion_depth=item.get("recursion_depth", 0),
                minimum_reserve=minimum_reserve,
            )
            allocations[item["subsystem"]] = decision.granted_units

        for item, assessment in indexed:
            requested = max(0.0, float(item.get("requested_units", 0.0)))
            if requested <= 0.0:
                continue
            remaining_request = max(0.0, requested - allocations[item["subsystem"]])
            if remaining_request <= 0.0:
                continue
            decision = budget_manager.allocate(
                item["subsystem"],
                remaining_request,
                salience=assessment.salience,
                recursion_depth=item.get("recursion_depth", 0),
                minimum_reserve=0.0,
            )
            allocations[item["subsystem"]] += decision.granted_units

        budget_status = budget_manager.status()
        suppressed = [name for name, value in allocations.items() if value <= 0.0]
        attention_pressure = 1.0 - (budget_status["remaining_budget"] / max(0.0001, budget_status["effective_budget"]))
        allocation = AttentionAllocation(
            allocations=allocations,
            salience=salience,
            suppressed_subsystems=suppressed,
            attention_pressure=attention_pressure,
            budget_utilization=budget_status["budget_utilization"],
            rationale="Attention allocated by salience under recursive budget caps and starvation floors.",
        )
        with self._lock:
            self._last_allocation = allocation
            self._history.append(allocation)
            if len(self._history) > 200:
                self._history = self._history[-200:]
        self._emit(allocation)
        return allocation.to_dict()

    def status(self) -> dict[str, Any]:
        with self._lock:
            last = self._last_allocation
            return {
                "history_count": len(self._history),
                "last_allocation": last.to_dict() if last else None,
                "attention_pressure": round(last.attention_pressure, 4) if last else 0.0,
                "budget_utilization": round(last.budget_utilization, 4) if last else 0.0,
            }

    def _emit(self, allocation: AttentionAllocation) -> None:
        try:
            from modules.event_bus import EVENT_ATTENTION_ALLOCATED, NiblitEvent, get_event_bus

            get_event_bus().publish(
                NiblitEvent(
                    type=EVENT_ATTENTION_ALLOCATED,
                    source="attention_allocator",
                    payload=allocation.to_dict(),
                )
            )
        except Exception:
            pass


_attention_allocator: AttentionAllocator | None = None
_attention_lock = threading.Lock()


def get_attention_allocator() -> AttentionAllocator:
    global _attention_allocator
    with _attention_lock:
        if _attention_allocator is None:
            _attention_allocator = AttentionAllocator()
    return _attention_allocator


if __name__ == "__main__":
    print('Running attention_allocator.py')
