"""AgentRuntime — orchestrates executor, planner, and research sub-agents.

Usage example::

    runtime = AgentRuntime(executor, planner, research)
    result = runtime.process_task({"type": "research", "goal": "AI safety"})
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

log = logging.getLogger("AgentRuntime")


class AgentRuntime:
    """Coordinates task processing across sub-agent components.

    Args:
        executor: TaskExecutor instance.
        planner: PlannerAgent instance.
        research: ResearchAgent instance.
    """

    def __init__(self, executor: Any, planner: Any, research: Any) -> None:
        self._executor = executor
        self._planner = planner
        self._research = research
        self._running = False
        self._tasks_processed = 0
        self._started_at: Optional[float] = None

    # ── public API ──

    def process_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Route and process *task* through the appropriate sub-agent."""
        task_type = task.get("type", "generic")
        log.info("AgentRuntime: processing task type=%s", task_type)
        start = time.time()
        try:
            if task_type == "research":
                output = self._research.research(task.get("goal", task.get("topic", "")))
            elif task_type == "plan":
                output = self._planner.create_plan(task)
            else:
                output = self._executor.execute(task)
        except Exception as exc:
            log.warning("AgentRuntime: error processing task — %s", exc)
            output = {"error": str(exc)}
        self._tasks_processed += 1
        return {
            "task": task,
            "output": output,
            "elapsed_ms": round((time.time() - start) * 1000, 2),
        }

    def get_status(self) -> Dict[str, Any]:
        """Return runtime status."""
        return {
            "running": self._running,
            "tasks_processed": self._tasks_processed,
            "started_at": self._started_at,
        }

    def stop(self) -> None:
        """Signal the runtime to stop."""
        self._running = False
        log.info("AgentRuntime: stopped")
