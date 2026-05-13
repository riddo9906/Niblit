#!/usr/bin/env python3
"""Phase Ω.6 cognitive budget enforcement and recursion caps."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, float(value)))


@dataclass
class BudgetDecision:
    subsystem: str
    requested_units: float
    granted_units: float
    remaining_units: float
    recursion_depth: int
    salience: float
    capped: bool
    rationale: str
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subsystem": self.subsystem,
            "requested_units": round(self.requested_units, 4),
            "granted_units": round(self.granted_units, 4),
            "remaining_units": round(self.remaining_units, 4),
            "recursion_depth": self.recursion_depth,
            "salience": round(self.salience, 4),
            "capped": self.capped,
            "rationale": self.rationale,
            "timestamp": self.timestamp,
        }


class CognitiveBudgetManager:
    """Hard cap cognitive work so recursive reasoning cannot consume the loop."""

    def __init__(self, total_budget: float = 1.0, recursion_limit: int = 4) -> None:
        self._lock = threading.Lock()
        self._base_budget = max(0.1, float(total_budget))
        self._recursion_limit = max(1, int(recursion_limit))
        self._effective_budget = self._base_budget
        self._remaining_budget = self._base_budget
        self._context_pressure = 0.0
        self._cycle_count = 0
        self._capped_requests = 0
        self._last_decision: BudgetDecision | None = None
        self._history: list[BudgetDecision] = []

    def reset_cycle(self, *, total_budget: float | None = None, context_pressure: float = 0.0) -> float:
        with self._lock:
            if total_budget is not None:
                self._base_budget = max(0.1, float(total_budget))
            self._context_pressure = _clamp(context_pressure)
            self._effective_budget = self._base_budget * (1.0 - 0.5 * self._context_pressure)
            self._remaining_budget = self._effective_budget
            self._cycle_count += 1
            return self._effective_budget

    def allocate(
        self,
        subsystem: str,
        requested_units: float,
        *,
        salience: float = 0.5,
        recursion_depth: int = 0,
        minimum_reserve: float = 0.0,
    ) -> BudgetDecision:
        requested_units = max(0.0, float(requested_units))
        salience = _clamp(salience)
        recursion_depth = max(0, int(recursion_depth))
        minimum_reserve = max(0.0, float(minimum_reserve))

        with self._lock:
            remaining_before = self._remaining_budget
            recursion_penalty = max(0.15, 1.0 - 0.18 * max(0, recursion_depth - 1))
            if recursion_depth > self._recursion_limit:
                recursion_penalty = min(recursion_penalty, 0.25)
            demand_cap = self._effective_budget * recursion_penalty * (0.35 + 0.65 * salience)
            guaranteed = min(requested_units, minimum_reserve, remaining_before)
            extra_cap = max(0.0, min(remaining_before - guaranteed, demand_cap - guaranteed))
            granted = guaranteed + min(max(0.0, requested_units - guaranteed), extra_cap)
            self._remaining_budget = max(0.0, remaining_before - granted)
            capped = granted + 1e-9 < requested_units
            if capped:
                self._capped_requests += 1
            decision = BudgetDecision(
                subsystem=subsystem,
                requested_units=requested_units,
                granted_units=granted,
                remaining_units=self._remaining_budget,
                recursion_depth=recursion_depth,
                salience=salience,
                capped=capped,
                rationale=self._rationale(capped, recursion_depth, salience),
            )
            self._last_decision = decision
            self._history.append(decision)
            if len(self._history) > 500:
                self._history = self._history[-500:]
        self._emit(decision)
        return decision

    def status(self) -> dict[str, Any]:
        with self._lock:
            utilization = 1.0 - (self._remaining_budget / max(0.0001, self._effective_budget))
            return {
                "base_budget": round(self._base_budget, 4),
                "effective_budget": round(self._effective_budget, 4),
                "remaining_budget": round(self._remaining_budget, 4),
                "budget_utilization": round(utilization, 4),
                "context_pressure": round(self._context_pressure, 4),
                "cycle_count": self._cycle_count,
                "capped_requests": self._capped_requests,
                "recursion_limit": self._recursion_limit,
                "last_decision": self._last_decision.to_dict() if self._last_decision else None,
            }

    @staticmethod
    def _rationale(capped: bool, recursion_depth: int, salience: float) -> str:
        if capped:
            return f"Budget capped at recursion_depth={recursion_depth} salience={salience:.2f}."
        return "Budget granted within recursive attention envelope."

    def _emit(self, decision: BudgetDecision) -> None:
        try:
            from modules.event_bus import EVENT_COGNITIVE_BUDGET_ENFORCED, NiblitEvent, get_event_bus

            get_event_bus().publish(
                NiblitEvent(
                    type=EVENT_COGNITIVE_BUDGET_ENFORCED,
                    source="cognitive_budget_manager",
                    payload=decision.to_dict(),
                )
            )
        except Exception:
            pass


_budget_manager: CognitiveBudgetManager | None = None
_budget_lock = threading.Lock()


def get_cognitive_budget_manager() -> CognitiveBudgetManager:
    global _budget_manager
    with _budget_lock:
        if _budget_manager is None:
            _budget_manager = CognitiveBudgetManager()
    return _budget_manager


if __name__ == "__main__":
    print('Running cognitive_budget_manager.py')
