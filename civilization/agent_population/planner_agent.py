"""PlannerAgent — civilisation agent specialised for strategic planning.

Usage example::

    agent = PlannerAgent("p1", "planner")
    result = agent.execute({"goal": "deploy ML pipeline"})
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

from .base_agent import BaseAgent

log = logging.getLogger("PlannerAgent")


class PlannerAgent(BaseAgent):
    """Decomposes goals into actionable plans."""

    # ── public API ──

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute planning task; return plan_steps/goal/complexity dict."""
        goal = task.get("goal", task.get("description", "unknown"))
        steps = self.decompose_goal(goal)
        effort = self.estimate_effort({"steps": steps})
        result = {
            "plan_steps": steps,
            "goal": goal,
            "complexity": effort,
            "planned_at": time.time(),
        }
        self._record_task()
        log.info("PlannerAgent %s: created plan with %d steps", self._agent_id, len(steps))
        return result

    def decompose_goal(self, goal: str) -> List[Dict[str, Any]]:
        """Break *goal* into structured steps."""
        return [
            {"step": 1, "action": "analyse", "description": f"Analyse: {goal}"},
            {"step": 2, "action": "research", "description": "Research existing approaches"},
            {"step": 3, "action": "design", "description": "Design solution architecture"},
            {"step": 4, "action": "implement", "description": "Implement solution"},
            {"step": 5, "action": "test", "description": "Test and validate"},
        ]

    def estimate_effort(self, plan: Dict[str, Any]) -> int:
        """Return estimated effort score (1–10) for *plan*."""
        steps = plan.get("steps", [])
        return min(10, max(1, len(steps) * 2))
