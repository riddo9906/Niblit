#!/usr/bin/env python3
"""
aios_scheduler.py — NIBLIT-AIOS Formal Scheduler
=================================================
Promotes the ``LifecycleEngine`` to a proper AIOS scheduler with:

* **Priority task queues** — tasks carry an integer priority (0 = highest).
  The scheduler always executes the highest-priority pending task before
  resuming lower-priority background work.
* **Named phases** — the eight AIOS phases (INIT → INTERFACE) map to the
  canonical AIOS layer model so the orchestrator can query the current
  scheduler phase.
* **Lifecycle delegation** — the underlying ``LifecycleEngine`` still owns
  heartbeat, trainer, and task loops.  ``AIOSScheduler`` wraps it and adds
  the priority queue on top.
* **Thread-safe submit/cancel** — external code submits ``ScheduledTask``
  objects via ``submit()`` and cancels them via ``cancel(task_id)``.

Singleton access via ``get_aios_scheduler()``.

Typical usage::

    scheduler = get_aios_scheduler()
    scheduler.start()

    task_id = scheduler.submit(
        fn=my_function,
        args=(arg1,),
        priority=1,
        label="my-task",
    )

    # Later …
    scheduler.cancel(task_id)
    scheduler.stop()
"""

from __future__ import annotations

import heapq
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ── Optional LifecycleEngine integration ──────────────────────────────────────
try:
    from lifecycle_engine import LifecycleEngine as _LifecycleEngine
    _LC_AVAILABLE = True
except Exception as _e:
    log.debug("AIOSScheduler: LifecycleEngine unavailable — %s", _e)
    _LC_AVAILABLE = False
    _LifecycleEngine = None  # type: ignore[assignment]


# ── AIOS phase constants ───────────────────────────────────────────────────────

AIOS_PHASES: List[str] = [
    "ENV",          # Phase 0 — environment setup
    "HAL",          # Phase 1 — hardware abstraction
    "BOOTLOADER",   # Phase 2 — kernel + runtime start
    "MEMORY",       # Phase 3 — memory subsystem
    "BRAIN",        # Phase 4 — AI reasoning layer
    "LEARNING",     # Phase 5 — ALE / self-improvement
    "AGENTS",       # Phase 6 — router / agent dispatch
    "INTERFACE",    # Phase 7 — CLI / API / notification layer
]

# Default worker poll interval (seconds)
_POLL_INTERVAL = float(0.2)


# ── ScheduledTask ─────────────────────────────────────────────────────────────

@dataclass(order=False)
class ScheduledTask:
    """
    A unit of work managed by the AIOS scheduler.

    Lower ``priority`` numbers are executed first (0 = highest priority).
    ``run_after`` is a Unix timestamp; the task is not eligible until
    ``time.time() >= run_after``.
    """

    fn: Callable[..., Any]
    args: Tuple[Any, ...] = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    priority: int = 5
    label: str = "task"
    run_after: float = field(default_factory=time.time)
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    cancelled: bool = field(default=False, init=False)
    completed: bool = field(default=False, init=False)
    result: Any = field(default=None, init=False)
    error: Optional[Exception] = field(default=None, init=False)

    # Heap key: (priority, run_after, task_id) — fully sortable
    def _heap_key(self) -> Tuple[int, float, str]:
        return (self.priority, self.run_after, self.task_id)


# ── AIOSScheduler ─────────────────────────────────────────────────────────────

class AIOSScheduler:
    """
    NIBLIT-AIOS formal task scheduler with priority queues.

    Wraps ``LifecycleEngine`` for background heartbeat / trainer / task loops
    while adding a structured priority queue for on-demand AIOS tasks.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._heap: List[Tuple[int, float, str, ScheduledTask]] = []
        self._tasks: Dict[str, ScheduledTask] = {}
        self._current_phase: str = AIOS_PHASES[0]
        self._running = False
        self._worker_thread: Optional[threading.Thread] = None

        # LifecycleEngine integration
        self._lifecycle: Optional[Any] = None
        if _LC_AVAILABLE and _LifecycleEngine is not None:
            try:
                self._lifecycle = _LifecycleEngine()
            except Exception as exc:
                log.debug("AIOSScheduler: could not instantiate LifecycleEngine — %s", exc)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the scheduler worker thread and the underlying LifecycleEngine."""
        with self._lock:
            if self._running:
                return
            self._running = True

        if self._lifecycle is not None:
            try:
                self._lifecycle.start()
            except Exception as exc:
                log.debug("AIOSScheduler: LifecycleEngine.start() failed — %s", exc)

        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="aios-scheduler-worker",
            daemon=True,
        )
        self._worker_thread.start()
        log.debug("AIOSScheduler: started (phase=%s)", self._current_phase)

    def stop(self) -> None:
        """Stop the scheduler and the underlying LifecycleEngine."""
        with self._lock:
            if not self._running:
                return
            self._running = False

        if self._lifecycle is not None:
            try:
                self._lifecycle.stop()
            except Exception as exc:
                log.debug("AIOSScheduler: LifecycleEngine.stop() failed — %s", exc)

        if self._worker_thread is not None:
            self._worker_thread.join(timeout=5.0)
        log.debug("AIOSScheduler: stopped")

    # ── Task submission ────────────────────────────────────────────────────────

    def submit(
        self,
        fn: Callable[..., Any],
        args: Tuple[Any, ...] = (),
        kwargs: Optional[Dict[str, Any]] = None,
        priority: int = 5,
        label: str = "task",
        delay_secs: float = 0.0,
    ) -> str:
        """
        Submit a callable for scheduled execution.

        Parameters
        ----------
        fn:          The callable to execute.
        args:        Positional arguments.
        kwargs:      Keyword arguments.
        priority:    Execution priority (0 = highest, 9 = lowest).
        label:       Human-readable label for logging / status.
        delay_secs:  Minimum delay before the task becomes eligible.

        Returns the ``task_id`` string for later cancellation.
        """
        task = ScheduledTask(
            fn=fn,
            args=args,
            kwargs=kwargs or {},
            priority=priority,
            label=label,
            run_after=time.time() + delay_secs,
        )
        with self._lock:
            self._tasks[task.task_id] = task
            heapq.heappush(self._heap, task._heap_key() + (task,))  # type: ignore[arg-type]
        log.debug(
            "AIOSScheduler: submitted '%s' (id=%s priority=%d)",
            label, task.task_id, priority,
        )
        return task.task_id

    def cancel(self, task_id: str) -> bool:
        """
        Cancel a pending task by its ``task_id``.

        Returns ``True`` if the task was found and marked cancelled,
        ``False`` if it was not found or already completed.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.completed:
                return False
            task.cancelled = True
        log.debug("AIOSScheduler: cancelled task '%s'", task_id)
        return True

    # ── Phase management ──────────────────────────────────────────────────────

    def advance_phase(self, phase: str) -> None:
        """
        Advance the scheduler to a named AIOS phase.

        ``phase`` must be one of the values in ``AIOS_PHASES``.
        """
        if phase not in AIOS_PHASES:
            log.debug("AIOSScheduler: unknown phase '%s' — ignoring", phase)
            return
        with self._lock:
            self._current_phase = phase
        log.debug("AIOSScheduler: advanced to phase '%s'", phase)

    @property
    def current_phase(self) -> str:
        """Return the current AIOS phase name."""
        with self._lock:
            return self._current_phase

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Return a summary of scheduler state."""
        with self._lock:
            pending = sum(
                1 for t in self._tasks.values()
                if not t.completed and not t.cancelled
            )
            return {
                "running": self._running,
                "current_phase": self._current_phase,
                "pending_tasks": pending,
                "total_tasks": len(self._tasks),
                "lifecycle_available": self._lifecycle is not None,
            }

    # ── Worker loop ───────────────────────────────────────────────────────────

    def _worker_loop(self) -> None:
        """Background thread: drain the priority queue."""
        while self._running:
            task = self._pop_ready_task()
            if task is not None:
                self._execute(task)
            else:
                time.sleep(_POLL_INTERVAL)

    def _pop_ready_task(self) -> Optional[ScheduledTask]:
        """Pop the highest-priority task that is ready to run."""
        now = time.time()
        with self._lock:
            while self._heap:
                # Peek at the top item
                entry = self._heap[0]
                task: ScheduledTask = entry[3]  # type: ignore[index]
                if task.cancelled or task.completed:
                    heapq.heappop(self._heap)
                    continue
                if task.run_after > now:
                    break  # top item not ready yet
                heapq.heappop(self._heap)
                return task
        return None

    def _execute(self, task: ScheduledTask) -> None:
        """Execute a task and record its result or error."""
        log.debug("AIOSScheduler: executing '%s' (id=%s)", task.label, task.task_id)
        try:
            task.result = task.fn(*task.args, **task.kwargs)
        except Exception as exc:
            task.error = exc
            log.debug(
                "AIOSScheduler: task '%s' raised — %s", task.label, exc
            )
        finally:
            task.completed = True


# ── Singleton ──────────────────────────────────────────────────────────────────

_scheduler: Optional[AIOSScheduler] = None
_scheduler_lock = threading.Lock()


def get_aios_scheduler() -> AIOSScheduler:
    """Return the process-level AIOSScheduler singleton."""
    global _scheduler
    if _scheduler is None:
        with _scheduler_lock:
            if _scheduler is None:
                _scheduler = AIOSScheduler()
    return _scheduler
