#!/usr/bin/env python3
"""
agents/planner_agent.py — Planner agent for goal decomposition.

The PlannerAgent breaks high-level goals into ordered subtasks and publishes
them onto the EventBus so other agents can pick them up.

Architecture role (Phase 2)
---------------------------
Receives ``task_type="plan"`` tasks with::

    payload = {
        "goal": "Improve code generation quality",
        "context": "..."      # optional
    }

Produces a list of sub-tasks and publishes a ``PLAN_GENERATED`` event::

    payload = {
        "goal": "...",
        "subtasks": [
            {"task_type": "research", "payload": {...}},
            {"task_type": "code_generation", "payload": {...}},
            ...
        ]
    }

Also enqueues the subtasks directly into the TaskQueue when one is provided.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from base_agent import BaseAgent
from core.event_bus import Event, EventBus, EventType
from core.task_queue import Priority, Task, TaskQueue

log = logging.getLogger("PlannerAgent")


class PlannerAgent(BaseAgent):
    """
    Decomposes goals into executable subtask sequences.

    Args:
        task_queue:  Optional TaskQueue to enqueue subtasks directly.
        llm:         Optional LLM adapter (must have ``generate_code`` or a
                     ``query`` / ``query_llm`` method) for LLM-assisted planning.
    """

    HANDLED_TASK_TYPES = ["plan", "decompose_goal", "plan_improvement"]

    def __init__(
        self,
        task_queue: Optional[TaskQueue] = None,
        llm: Optional[Any] = None,
    ) -> None:
        super().__init__("planner")
        self._task_queue = task_queue
        self._llm = llm

    # ── execution ─────────────────────────────────────────────────────────────

    def _execute(self, task: Task, event_bus: EventBus) -> Dict[str, Any]:
        goal = task.payload.get("goal", "")
        context = task.payload.get("context", "")

        if not goal:
            return {"error": "No goal provided", "subtasks": []}

        subtasks = self._plan(goal, context)
        self._log.info("planned %d subtasks for goal: %s", len(subtasks), goal[:60])

        # Enqueue subtasks if a TaskQueue is wired in
        if self._task_queue is not None:
            for spec in subtasks:
                self._task_queue.enqueue_simple(
                    task_type=spec["task_type"],
                    payload=spec.get("payload", {}),
                    priority=Priority.NORMAL,
                    source="planner",
                )

        result = {"goal": goal, "subtasks": subtasks}
        self._publish(event_bus, EventType.PLAN_GENERATED, result)
        return result

    # ── planning logic ────────────────────────────────────────────────────────

    def _plan(self, goal: str, context: str = "") -> List[Dict[str, Any]]:
        """Return a list of subtask specification dicts."""
        if self._llm is not None:
            llm_plan = self._llm_plan(goal, context)
            if llm_plan:
                return llm_plan

        return self._rule_based_plan(goal)

    def _llm_plan(self, goal: str, context: str) -> Optional[List[Dict[str, Any]]]:
        """Ask the LLM to produce a numbered subtask list."""
        prompt = (
            f"Break down this goal into 3-6 concrete subtasks:\n\nGoal: {goal}\n"
            + (f"Context: {context[:300]}\n" if context else "")
            + "\nRespond with a numbered list only (1. ..., 2. ..., etc.)."
        )
        try:
            if hasattr(self._llm, "query_llm"):
                text = self._llm.query_llm([{"role": "user", "content": prompt}])
            elif hasattr(self._llm, "query"):
                text = self._llm.query([{"role": "user", "content": prompt}])
            else:
                return None
            if not text:
                return None
            return self._parse_numbered_list(text, goal)
        except Exception as exc:
            self._log.debug("LLM planning failed: %s", exc)
            return None

    def _parse_numbered_list(
        self, text: str, goal: str
    ) -> List[Dict[str, Any]]:
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        subtasks = []
        for line in lines:
            m = re.match(r"^\d+[\.\)]\s+(.+)$", line)
            if m:
                desc = m.group(1).strip()
                subtasks.append(self._spec_from_description(desc, goal))
        return subtasks or self._rule_based_plan(goal)

    @staticmethod
    def _spec_from_description(description: str, goal: str) -> Dict[str, Any]:
        desc_lower = description.lower()
        if any(w in desc_lower for w in ("research", "search", "find", "study")):
            task_type = "research"
            payload: Dict[str, Any] = {"topic": description, "context": goal}
        elif any(w in desc_lower for w in ("generat", "write code", "implement", "code")):
            task_type = "code_generation"
            payload = {"purpose": description, "context": goal}
        elif any(w in desc_lower for w in ("test", "validat", "check")):
            task_type = "testing"
            payload = {"description": description}
        elif any(w in desc_lower for w in ("refactor", "improve", "optim")):
            task_type = "refactor"
            payload = {"description": description}
        elif any(w in desc_lower for w in ("deploy", "publish", "release")):
            task_type = "deploy"
            payload = {"description": description}
        else:
            task_type = "general"
            payload = {"description": description, "goal": goal}
        return {"task_type": task_type, "description": description, "payload": payload}

    @staticmethod
    def _rule_based_plan(goal: str) -> List[Dict[str, Any]]:
        """Fallback rule-based planner when no LLM is available."""
        return [
            {
                "task_type": "research",
                "description": f"Research solutions for: {goal}",
                "payload": {"topic": goal},
            },
            {
                "task_type": "code_generation",
                "description": f"Generate code to achieve: {goal}",
                "payload": {"purpose": goal},
            },
            {
                "task_type": "testing",
                "description": "Validate the generated code",
                "payload": {"description": "run tests on generated code"},
            },
            {
                "task_type": "reflection",
                "description": "Reflect on results and update knowledge",
                "payload": {"goal": goal},
            },
        ]
