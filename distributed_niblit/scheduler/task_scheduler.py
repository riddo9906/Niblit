"""TaskScheduler — time-based task scheduling with future run-at support.

Usage example::

    scheduler = TaskScheduler()
    task_id = scheduler.schedule({"type": "research", "topic": "AI"})
    executed = scheduler.run_due()
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

log = logging.getLogger("TaskScheduler")


class TaskScheduler:
    """Schedules tasks for future or immediate execution."""

    def __init__(self) -> None:
        self._tasks: Dict[str, Dict[str, Any]] = {}

    # ── public API ──

    def schedule(
        self, task: Dict[str, Any], run_at: Optional[float] = None
    ) -> str:
        """Schedule *task*; *run_at* defaults to now."""
        task_id = str(uuid.uuid4())
        self._tasks[task_id] = {
            "task_id": task_id,
            "task": task,
            "run_at": run_at if run_at is not None else time.time(),
            "status": "pending",
        }
        log.debug("TaskScheduler: scheduled %s", task_id)
        return task_id

    def cancel(self, task_id: str) -> None:
        """Cancel a pending task."""
        entry = self._tasks.get(task_id)
        if entry and entry["status"] == "pending":
            entry["status"] = "cancelled"
            log.info("TaskScheduler: cancelled %s", task_id)

    def get_pending(self) -> List[Dict[str, Any]]:
        """Return all tasks with status 'pending'."""
        return [t for t in self._tasks.values() if t["status"] == "pending"]

    def run_due(self) -> List[Dict[str, Any]]:
        """Execute all tasks whose run_at <= now; return executed list."""
        now = time.time()
        executed = []
        for entry in self._tasks.values():
            if entry["status"] == "pending" and entry["run_at"] <= now:
                entry["status"] = "executed"
                entry["executed_at"] = now
                executed.append(entry)
                log.debug("TaskScheduler: executed %s", entry["task_id"])
        return executed


if __name__ == "__main__":
    print('Running task_scheduler.py')
