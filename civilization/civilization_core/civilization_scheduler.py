"""CivilizationScheduler — assigns tasks to agents in the civilization.

Usage example::

    sched = CivilizationScheduler()
    sched.register_task_type("research", {"priority": 5})
    task = sched.assign_task({"role": "researcher"})
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List

log = logging.getLogger("CivilizationScheduler")

_DEFAULT_TASK_TYPES: Dict[str, Dict[str, Any]] = {
    "research": {"priority": 5, "duration_s": 60},
    "build": {"priority": 4, "duration_s": 120},
    "plan": {"priority": 6, "duration_s": 30},
    "analyse": {"priority": 3, "duration_s": 90},
    "evolve": {"priority": 7, "duration_s": 300},
}


class CivilizationScheduler:
    """Assigns structured tasks to agents."""

    def __init__(self) -> None:
        self._task_types: Dict[str, Dict[str, Any]] = dict(_DEFAULT_TASK_TYPES)
        self._queue: List[Dict[str, Any]] = []

    # ── public API ──

    def register_task_type(self, task_type: str, config: Dict[str, Any]) -> None:
        """Register a new *task_type* with *config*."""
        self._task_types[task_type] = config
        log.debug("CivilizationScheduler: registered task type %s", task_type)

    def assign_task(self, agent: Dict[str, Any]) -> Dict[str, Any]:
        """Generate and queue a task appropriate for *agent*."""
        role = agent.get("role", "researcher")
        role_task_map = {
            "researcher": "research",
            "builder": "build",
            "planner": "plan",
            "analyst": "analyse",
            "evolution_agent": "evolve",
        }
        task_type = role_task_map.get(role, "research")
        config = self._task_types.get(task_type, {"priority": 5})
        task: Dict[str, Any] = {
            "task_id": str(uuid.uuid4()),
            "task_type": task_type,
            "agent_id": agent.get("agent_id"),
            "priority": config.get("priority", 5),
            "created_at": time.time(),
            "status": "assigned",
        }
        self._queue.append(task)
        log.debug("CivilizationScheduler: assigned %s to agent %s", task_type, agent.get("agent_id"))
        return task

    def get_task_queue(self) -> List[Dict[str, Any]]:
        """Return current task queue."""
        return list(self._queue)

    def drain(self) -> List[Dict[str, Any]]:
        """Return and clear all queued tasks."""
        tasks = list(self._queue)
        self._queue.clear()
        return tasks


if __name__ == "__main__":
    print('Running civilization_scheduler.py')
