#!/usr/bin/env python3
"""
agents/base_agent.py — Abstract base class for all Niblit agents.

Every agent in the next-gen architecture inherits from BaseAgent and
implements ``handle(task, event_bus)``.  The base class provides:

* Lifecycle state tracking (idle / running / error)
* Uniform logging
* A ``can_handle(task_type)`` predicate
* Helper methods for publishing result events

Architecture role (Phase 2)
---------------------------
Agents register their ``handle`` method with the Orchestrator::

    orchestrator.register_agent("research", research_agent.handle)

Then any task of that type is routed here automatically.
"""

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from core.event_bus import Event, EventBus, EventType
from core.task_queue import Task

log = logging.getLogger("BaseAgent")


class AgentState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    ERROR = "error"


@dataclass
class AgentMetrics:
    """Per-agent performance counters."""
    tasks_handled: int = 0
    tasks_failed: int = 0
    total_time_ms: float = 0.0
    last_run_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        total = self.tasks_handled + self.tasks_failed
        return (self.tasks_handled / total) if total else 1.0

    @property
    def avg_time_ms(self) -> float:
        return (self.total_time_ms / self.tasks_handled) if self.tasks_handled else 0.0


class BaseAgent:
    """
    Abstract base for all Niblit agents.

    Subclasses must implement:
        ``_execute(task: Task, event_bus: EventBus) → Any``

    Subclasses may override:
        ``HANDLED_TASK_TYPES`` — list of task_type strings this agent handles.
    """

    HANDLED_TASK_TYPES: List[str] = []

    def __init__(self, name: str) -> None:
        self.name = name
        self.state = AgentState.IDLE
        self.metrics = AgentMetrics()
        self._log = logging.getLogger(f"Agent[{name}]")

    # ── public interface ──────────────────────────────────────────────────────

    def can_handle(self, task_type: str) -> bool:
        """Return True if this agent handles *task_type*."""
        return not self.HANDLED_TASK_TYPES or task_type in self.HANDLED_TASK_TYPES

    def handle(self, task: Task, event_bus: EventBus) -> Any:
        """
        Entry point called by the Orchestrator.  Wraps ``_execute()`` with
        lifecycle management and metrics tracking.
        """
        self.state = AgentState.RUNNING
        start = time.monotonic()
        try:
            result = self._execute(task, event_bus)
            elapsed_ms = (time.monotonic() - start) * 1000
            self.metrics.tasks_handled += 1
            self.metrics.total_time_ms += elapsed_ms
            self.metrics.last_run_ms = elapsed_ms
            self.state = AgentState.IDLE
            self._log.debug("handled %s in %.0fms", task.task_type, elapsed_ms)
            return result
        except Exception as exc:
            elapsed_ms = (time.monotonic() - start) * 1000
            self.metrics.tasks_failed += 1
            self.metrics.last_run_ms = elapsed_ms
            self.state = AgentState.ERROR
            self._log.warning("failed on %s: %s", task.task_type, exc)
            event_bus.publish(Event(
                type=EventType.ERROR_OCCURRED,
                payload={"agent": self.name, "task_type": task.task_type, "error": str(exc)},
                source=self.name,
            ))
            raise

    # ── helpers ───────────────────────────────────────────────────────────────

    def _publish(
        self,
        event_bus: EventBus,
        event_type: EventType,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        event_bus.publish(Event(
            type=event_type,
            payload=payload or {},
            source=self.name,
        ))

    def get_status(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "metrics": {
                "tasks_handled": self.metrics.tasks_handled,
                "tasks_failed": self.metrics.tasks_failed,
                "success_rate": round(self.metrics.success_rate, 3),
                "avg_time_ms": round(self.metrics.avg_time_ms, 1),
                "last_run_ms": round(self.metrics.last_run_ms, 1),
            },
        }

    # ── abstract method ───────────────────────────────────────────────────────

    def _execute(self, task: Task, event_bus: EventBus) -> Any:
        """Implement agent logic here. Must be overridden by subclasses."""
        raise NotImplementedError(f"{self.__class__.__name__}._execute() not implemented")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, state={self.state.value})"
