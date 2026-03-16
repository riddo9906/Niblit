"""TaskAPI — goal and task submission for the civilisation API gateway.

Usage example::

    api = TaskAPI()
    resp = api.submit_goal("Build a recommendation engine")
    status = api.get_task_status(resp["goal_id"])
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

log = logging.getLogger("TaskAPI")


class TaskAPI:
    """Accepts and tracks task and goal submissions."""

    def __init__(self) -> None:
        self._tasks: Dict[str, Dict[str, Any]] = {}

    # ── public API ──

    def submit_goal(self, goal: str) -> Dict[str, Any]:
        """Convert *goal* string into a task; return {goal_id, status}."""
        goal_id = str(uuid.uuid4())
        self._tasks[goal_id] = {
            "task_id": goal_id,
            "goal": goal,
            "task_type": "goal",
            "status": "queued",
            "submitted_at": time.time(),
        }
        log.info("TaskAPI: goal submitted %s", goal_id)
        return {"goal_id": goal_id, "status": "queued"}

    def submit_task(
        self, task_type: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Submit a typed task; return {task_id, status}."""
        task_id = str(uuid.uuid4())
        self._tasks[task_id] = {
            "task_id": task_id,
            "task_type": task_type,
            "payload": payload,
            "status": "queued",
            "submitted_at": time.time(),
        }
        log.info("TaskAPI: task %s submitted (%s)", task_id, task_type)
        return {"task_id": task_id, "status": "queued"}

    def get_task_status(self, task_id: str) -> Dict[str, Any]:
        """Return status dict for *task_id*."""
        entry = self._tasks.get(task_id)
        if entry is None:
            return {"task_id": task_id, "status": "not_found"}
        return {"task_id": task_id, "status": entry["status"]}

    def list_tasks(
        self, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return tasks filtered by *status*, or all if None."""
        tasks = list(self._tasks.values())
        if status is not None:
            tasks = [t for t in tasks if t["status"] == status]
        return tasks
