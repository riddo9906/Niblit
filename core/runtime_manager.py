#!/usr/bin/env python3
"""
core/runtime_manager.py — Top-level runtime coordinator for Niblit.

The RuntimeManager owns the shared EventBus, TaskQueue, and Orchestrator
instances.  It exposes a simple facade so the rest of the system never needs
to import from multiple ``core/`` sub-modules.

Architecture role (Phase 1)
---------------------------

    niblit_core.py  (or any entry point)
           │
           ▼
    RuntimeManager.start()
           │
      ┌────┴────┐
      │         │
   EventBus  TaskQueue
      │         │
      └────┬────┘
           │
       Orchestrator
           │
        Agents…

Usage::

    from core.runtime_manager import RuntimeManager

    rm = RuntimeManager()
    rm.register_agent("research", my_research_handler)
    rm.submit_task("research", payload={"topic": "neural nets"}, priority="high")
    rm.dispatch_pending()   # or run rm.start_loop() in a background thread
"""

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from core.event_bus import Event, EventBus, EventType
from core.orchestrator import Orchestrator
from core.task_queue import Priority, Task, TaskQueue

log = logging.getLogger("RuntimeManager")

_PRIORITY_MAP: Dict[str, Priority] = {
    "low": Priority.LOW,
    "normal": Priority.NORMAL,
    "high": Priority.HIGH,
    "critical": Priority.CRITICAL,
}


class RuntimeManager:
    """
    Facade that wires together EventBus, TaskQueue, and Orchestrator.

    Args:
        history_limit:  Maximum events kept in the event bus history.
        queue_max_size: Maximum pending tasks (0 = unlimited).
    """

    def __init__(
        self,
        history_limit: int = 1000,
        queue_max_size: int = 0,
    ) -> None:
        self.event_bus = EventBus(history_limit=history_limit)
        self.task_queue = TaskQueue(max_size=queue_max_size)
        self.orchestrator = Orchestrator(self.event_bus, self.task_queue)

        self._running = False
        self._loop_thread: Optional[threading.Thread] = None

        # Publish system-started event
        self.event_bus.publish(Event(
            type=EventType.SYSTEM_STARTED,
            payload={"time": time.time()},
            source="runtime_manager",
        ))

    # ── agent registration ────────────────────────────────────────────────────

    def register_agent(
        self,
        task_type: str,
        handler: Callable[[Task, EventBus], Any],
    ) -> None:
        """Register an agent handler for a task type."""
        self.orchestrator.register_agent(task_type, handler)

    # ── task submission ───────────────────────────────────────────────────────

    def submit_task(
        self,
        task_type: str,
        payload: Optional[Dict[str, Any]] = None,
        priority: str = "normal",
        source: str = "runtime_manager",
    ) -> Task:
        """
        Create and enqueue a task.

        Args:
            task_type: Type string matched to an agent handler.
            payload:   Dict of task parameters.
            priority:  One of ``"low"``, ``"normal"``, ``"high"``, ``"critical"``.
            source:    Identifying label for the submitter.

        Returns:
            The enqueued Task object.
        """
        pri = _PRIORITY_MAP.get(priority.lower(), Priority.NORMAL)
        return self.task_queue.enqueue_simple(
            task_type=task_type,
            payload=payload or {},
            priority=pri,
            source=source,
        )

    # ── dispatch ──────────────────────────────────────────────────────────────

    def dispatch_pending(self, max_tasks: int = 0) -> int:
        """
        Dispatch all pending tasks (or up to *max_tasks*).

        Returns:
            Number of tasks dispatched.
        """
        dispatched = 0
        while True:
            if max_tasks and dispatched >= max_tasks:
                break
            result = self.orchestrator.dispatch_next()
            if result is None and self.task_queue.pending_count() == 0:
                break
            dispatched += 1
        return dispatched

    # ── background loop ───────────────────────────────────────────────────────

    def start_loop(self, poll_interval: float = 0.5) -> None:
        """Start the background dispatch loop in a daemon thread."""
        if self._running:
            return
        self._running = True
        self._loop_thread = threading.Thread(
            target=self._loop, args=(poll_interval,), daemon=True, name="RuntimeLoop"
        )
        self._loop_thread.start()
        log.info("[RuntimeManager] background loop started")

    def stop_loop(self) -> None:
        """Signal the background loop to stop."""
        self._running = False
        self.event_bus.publish(Event(
            type=EventType.SYSTEM_STOPPING,
            payload={},
            source="runtime_manager",
        ))
        if self._loop_thread and self._loop_thread.is_alive():
            self._loop_thread.join(timeout=5)
        log.info("[RuntimeManager] background loop stopped")

    def _loop(self, poll_interval: float) -> None:
        while self._running:
            try:
                self.dispatch_pending(max_tasks=10)
            except Exception as exc:
                log.warning("[RuntimeManager] dispatch error: %s", exc)
            time.sleep(poll_interval)

    # ── stats / introspection ─────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "orchestrator": self.orchestrator.get_stats(),
            "event_history": len(self.event_bus.get_history()),
        }

    def subscribe(self, event_type: EventType, handler: Callable) -> None:
        """Shortcut to subscribe an event handler via the runtime."""
        self.event_bus.subscribe(event_type, handler)


if __name__ == "__main__":
    print('Running runtime_manager.py')
