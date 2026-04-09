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

        # Optionally augment the plan with LLM-proposed steps from the HF
        # inference provider.  Each non-empty line becomes an additional step.
        llm_plan = self._ask_llm(
            f"List exactly 3 concise, actionable steps to achieve: '{goal}'. "
            "One step per line, no numbering, no bullet points."
        )
        if llm_plan and not llm_plan.startswith("[HFBrain"):
            for i, step_text in enumerate(llm_plan.strip().splitlines()[:3], start=len(steps) + 1):
                step_text = step_text.strip()
                if step_text:
                    steps.append({"step": i, "action": "llm_proposed", "description": step_text[:200]})

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
