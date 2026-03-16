"""PlannerAgent — decomposes high-level goals into executable steps.

Usage example::

    planner = PlannerAgent()
    plan = planner.create_plan({"goal": "build a recommender system"})
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

log = logging.getLogger("PlannerAgent")


class PlannerAgent:
    """Creates structured execution plans from natural-language goals."""

    def __init__(self) -> None:
        self._plans: List[Dict[str, Any]] = []

    # ── public API ──

    def create_plan(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Return a plan dict with steps, goal, and estimated_steps."""
        goal = task.get("goal", task.get("description", "unknown goal"))
        steps = self.decompose(goal)
        plan: Dict[str, Any] = {
            "goal": goal,
            "steps": steps,
            "estimated_steps": len(steps),
            "created_at": time.time(),
        }
        self._plans.append(plan)
        log.info("PlannerAgent: created plan with %d steps for %s", len(steps), goal[:50])
        return plan

    def decompose(self, goal: str) -> List[Dict[str, Any]]:
        """Break *goal* string into a list of step dicts."""
        keywords = goal.lower().split()
        steps = [
            {"step": 1, "action": "analyse", "description": f"Analyse requirements for: {goal}"},
            {"step": 2, "action": "research", "description": f"Research existing solutions for: {goal}"},
            {"step": 3, "action": "design", "description": "Design architecture and interfaces"},
            {"step": 4, "action": "implement", "description": "Implement core components"},
            {"step": 5, "action": "validate", "description": "Validate and benchmark output"},
        ]
        if any(k in keywords for k in ("deploy", "release", "production")):
            steps.append({"step": 6, "action": "deploy", "description": "Deploy to target environment"})
        return steps
