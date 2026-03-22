#!/usr/bin/env python3
"""
core/task_queue.py — Priority task queue for the Niblit runtime.

Provides a thread-safe, priority-based queue that the Orchestrator uses to
schedule agent work.  Tasks are ordered by Priority (HIGH → NORMAL → LOW)
and within the same priority by arrival time (FIFO).

Example::

    from core.task_queue import TaskQueue, Task, Priority

    q = TaskQueue()
    q.enqueue(Task("research", payload={"topic": "transformers"}, priority=Priority.HIGH))
    task = q.dequeue()   # returns the highest-priority pending task
    q.complete(task.task_id, result={"snippets": [...]})

Architecture role (Phase 1)
---------------------------
Every request that enters the system (from the user, from an ALE cycle, or
from another agent) is expressed as a Task and placed in this queue.  The
RuntimeManager drains the queue and dispatches work to the Orchestrator.
"""

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("TaskQueue")


class Priority(IntEnum):
    """Task priority levels — higher numeric value = higher priority."""
    LOW = 1
    NORMAL = 5
    HIGH = 10
    CRITICAL = 20


class TaskStatus(str):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    """
    A unit of work that can be enqueued and dispatched to an agent.

    Attributes:
        task_type:   String tag identifying the type of work
                     (e.g. ``"research"``, ``"code_generation"``).
        payload:     Arbitrary dict of task parameters.
        priority:    Scheduling priority.
        source:      Agent / component that created the task.
        task_id:     Auto-assigned UUID string.
        status:      Current lifecycle status.
        created_at:  Unix timestamp of creation.
        started_at:  Unix timestamp when execution began.
        completed_at: Unix timestamp of completion or failure.
        result:      Output produced by the executing agent.
        error:       Error message if the task failed.
    """

    task_type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    priority: Priority = Priority.NORMAL
    source: str = "orchestrator"
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: str = field(default=TaskStatus.PENDING)
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[Any] = None
    error: Optional[str] = None

    # ── comparison for heapq-style sorting (higher priority = lower heap key) ──

    def __lt__(self, other: "Task") -> bool:
        if self.priority != other.priority:
            return self.priority > other.priority  # higher priority first
        return self.created_at < other.created_at  # FIFO within same priority

    def __repr__(self) -> str:
        return (
            f"Task(type={self.task_type!r}, priority={self.priority.name}, "
            f"status={self.status!r}, id={self.task_id[:8]})"
        )


class TaskQueue:
    """
    Thread-safe priority task queue.

    All public methods are safe to call from multiple threads.

    Args:
        max_size:    Maximum number of pending tasks (0 = unlimited).
    """

    def __init__(self, max_size: int = 0) -> None:
        self._pending: List[Task] = []
        self._running: Dict[str, Task] = {}
        self._completed: List[Task] = []
        self._max_size = max_size
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)

    # ── enqueue ───────────────────────────────────────────────────────────────

    def enqueue(self, task: Task) -> bool:
        """
        Add *task* to the queue.

        Returns:
            True if the task was accepted, False if the queue is full.
        """
        with self._not_empty:
            if self._max_size > 0 and len(self._pending) >= self._max_size:
                log.warning("[TaskQueue] queue full, dropping %s", task)
                return False
            self._pending.append(task)
            self._pending.sort()  # maintain priority order
            self._not_empty.notify_all()
        log.debug("[TaskQueue] enqueued %s", task)
        return True

    def enqueue_simple(
        self,
        task_type: str,
        payload: Optional[Dict[str, Any]] = None,
        priority: Priority = Priority.NORMAL,
        source: str = "orchestrator",
    ) -> Task:
        """Convenience wrapper that creates and enqueues a Task."""
        task = Task(
            task_type=task_type,
            payload=payload or {},
            priority=priority,
            source=source,
        )
        self.enqueue(task)
        return task

    # ── dequeue ───────────────────────────────────────────────────────────────

    def dequeue(self, block: bool = False, timeout: Optional[float] = None) -> Optional[Task]:
        """
        Remove and return the highest-priority pending task.

        Args:
            block:   If True, block until a task is available.
            timeout: Maximum seconds to wait (only used when block=True).

        Returns:
            The next Task, or None if the queue is empty (or timeout expired).
        """
        with self._not_empty:
            if block:
                deadline = time.monotonic() + (timeout or float("inf"))
                while not self._pending:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return None
                    self._not_empty.wait(timeout=min(remaining, 1.0))
            if not self._pending:
                return None
            task = self._pending.pop(0)
            task.status = TaskStatus.RUNNING
            task.started_at = time.time()
            self._running[task.task_id] = task
        return task

    # ── completion ────────────────────────────────────────────────────────────

    def complete(self, task_id: str, result: Any = None) -> bool:
        """Mark a running task as completed."""
        return self._finish(task_id, TaskStatus.COMPLETED, result=result)

    def fail(self, task_id: str, error: str = "") -> bool:
        """Mark a running task as failed."""
        return self._finish(task_id, TaskStatus.FAILED, error=error)

    def _finish(self, task_id: str, status: str, **kwargs: Any) -> bool:
        with self._lock:
            task = self._running.pop(task_id, None)
            if task is None:
                return False
            task.status = status
            task.completed_at = time.time()
            for k, v in kwargs.items():
                setattr(task, k, v)
            self._completed.append(task)
        return True

    # ── inspection ────────────────────────────────────────────────────────────

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def running_count(self) -> int:
        with self._lock:
            return len(self._running)

    def completed_count(self) -> int:
        with self._lock:
            return len(self._completed)

    def get_stats(self) -> Dict[str, int]:
        with self._lock:
            return {
                "pending": len(self._pending),
                "running": len(self._running),
                "completed": len(self._completed),
            }

    def cancel_pending(self, task_type: Optional[str] = None) -> int:
        """Cancel all pending tasks, optionally filtered by task_type."""
        with self._lock:
            cancelled = 0
            remaining = []
            for t in self._pending:
                if task_type is None or t.task_type == task_type:
                    t.status = TaskStatus.CANCELLED
                    t.completed_at = time.time()
                    self._completed.append(t)
                    cancelled += 1
                else:
                    remaining.append(t)
            self._pending = remaining
        return cancelled

    def __repr__(self) -> str:
        s = self.get_stats()
        return (
            f"TaskQueue(pending={s['pending']}, running={s['running']}, "
            f"completed={s['completed']})"
        )
