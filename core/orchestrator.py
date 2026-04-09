#!/usr/bin/env python3
"""
core/orchestrator.py — Central orchestration layer for the Niblit runtime.

The Orchestrator sits between the task queue and the individual agents.  It
receives Tasks from the RuntimeManager, routes them to the appropriate agent,
and publishes result events back onto the EventBus.

Architecture role (Phase 1 + Phase 2)
--------------------------------------

    RuntimeManager
          │
          ▼
      Orchestrator
     ┌────┼───────┐
     │    │       │
  Research Coding Testing …
  Agent   Agent  Agent

Agents register themselves with::

    orchestrator.register_agent("research", research_agent)

Tasks are dispatched by task_type matching the agent name.

Example::

    from core.orchestrator import Orchestrator
    from core.event_bus import EventBus
    from core.task_queue import TaskQueue, Task, Priority

    bus = EventBus()
    queue = TaskQueue()
    orch = Orchestrator(bus, queue)

    # Register an agent callable
    orch.register_agent("research", lambda task, bus: {"result": "done"})

    task = queue.enqueue_simple("research", {"topic": "neural nets"})
    orch.dispatch(task)
"""

import logging
import time
from typing import Any, Callable, Dict, Optional

from core.event_bus import Event, EventBus, EventType
from core.task_queue import Task, TaskQueue, TaskStatus

log = logging.getLogger("Orchestrator")

# Type alias: agent handler receives (Task, EventBus) and returns any result
AgentHandler = Callable[[Task, EventBus], Any]


class Orchestrator:
    """
    Routes tasks to registered agents and publishes lifecycle events.

    Args:
        event_bus:  The shared EventBus instance.
        task_queue: The shared TaskQueue instance.
    """

    def __init__(self, event_bus: EventBus, task_queue: TaskQueue) -> None:
        self._bus = event_bus
        self._queue = task_queue
        self._agents: Dict[str, AgentHandler] = {}

    # ── agent registry ────────────────────────────────────────────────────────

    def register_agent(self, task_type: str, handler: AgentHandler) -> None:
        """
        Register an agent callable for a given task type.

        Args:
            task_type: String key that matches ``Task.task_type``.
            handler:   Callable ``(task, event_bus) → result``.
        """
        self._agents[task_type] = handler
        log.info("[Orchestrator] registered agent for task_type=%r", task_type)

    def unregister_agent(self, task_type: str) -> bool:
        """Remove a registered agent. Returns True if it existed."""
        return self._agents.pop(task_type, None) is not None

    @property
    def registered_task_types(self) -> list:
        return list(self._agents.keys())

    # ── dispatch ──────────────────────────────────────────────────────────────

    def dispatch(self, task: Task) -> Any:
        """
        Route *task* to its registered agent handler.

        Publishes ``TASK_CREATED`` before dispatch and
        ``TASK_COMPLETED`` / ``TASK_FAILED`` on completion.

        Returns:
            The result returned by the agent handler.
        """
        self._bus.publish(Event(
            type=EventType.TASK_CREATED,
            payload={"task_id": task.task_id, "task_type": task.task_type},
            source="orchestrator",
        ))

        handler = self._agents.get(task.task_type)
        if handler is None:
            error = f"No agent registered for task_type={task.task_type!r}"
            log.warning("[Orchestrator] %s", error)
            self._queue.fail(task.task_id, error=error)
            self._bus.publish(Event(
                type=EventType.TASK_FAILED,
                payload={"task_id": task.task_id, "error": error},
                source="orchestrator",
            ))
            return None

        start = time.monotonic()
        try:
            result = handler(task, self._bus)
            elapsed = time.monotonic() - start
            self._queue.complete(task.task_id, result=result)
            self._bus.publish(Event(
                type=EventType.TASK_COMPLETED,
                payload={
                    "task_id": task.task_id,
                    "task_type": task.task_type,
                    "elapsed_ms": round(elapsed * 1000),
                    "result": result,
                },
                source="orchestrator",
            ))
            log.debug("[Orchestrator] task %s completed in %.0fms", task.task_id[:8], elapsed * 1000)
            return result
        except Exception as exc:
            elapsed = time.monotonic() - start
            error = str(exc)
            log.warning("[Orchestrator] task %s failed: %s", task.task_id[:8], exc)
            self._queue.fail(task.task_id, error=error)
            self._bus.publish(Event(
                type=EventType.TASK_FAILED,
                payload={
                    "task_id": task.task_id,
                    "task_type": task.task_type,
                    "error": error,
                    "elapsed_ms": round(elapsed * 1000),
                },
                source="orchestrator",
            ))
            return None

    def dispatch_next(self) -> Optional[Any]:
        """Dequeue the next pending task and dispatch it. Returns None if empty."""
        task = self._queue.dequeue()
        if task is None:
            return None
        return self.dispatch(task)

    # ── stats ─────────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        return {
            "registered_agents": len(self._agents),
            "agent_types": self.registered_task_types,
            "queue": self._queue.get_stats(),
        }


if __name__ == "__main__":
    print('Running orchestrator.py')
