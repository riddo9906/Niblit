#!/usr/bin/env python3
"""
modules/background_jobs.py — Robust BackgroundJobManager for Niblit.

All periodic or one-shot background work (topic refresh, parameter sync,
self-heal probes, agent tasks …) should be registered here so they run in
true daemon threads that **never** block the interactive shell or print
anything directly to stdout/stderr.

Results and status updates are pushed to :data:`~core.notification_queue.notif_queue`
so the main shell loop can display them after the user presses Enter —
preserving a 100 % non-blocking, non-overwriting typing experience in
Termux and every other terminal environment.

Usage::

    from modules.background_jobs import bg_jobs

    # One-shot background job
    bg_jobs.add(lambda: my_task(), name="my_task")

    # Repeating job (runs every 600 s)
    bg_jobs.add(my_periodic_fn, interval=600, name="periodic_sync")

    # Stop all managed jobs at shutdown
    bg_jobs.stop()

Module-level singleton :data:`bg_jobs` is shared process-wide so all
modules use the same manager without circular imports.
"""

from __future__ import annotations

import logging
import threading
import time
import traceback
from typing import Callable, List, Optional

# ── notification queue ─────────────────────────────────────────────────────────
try:
    from core.notification_queue import notif_queue as _notif_queue
except ImportError:
    # Fallback: no-op stub so this module is importable stand-alone
    class _NopQueue:  # type: ignore[no-redef]
        def push(self, msg: str) -> None:
            pass  # silently drop when core package not on path

    _notif_queue = _NopQueue()  # type: ignore[assignment]

log = logging.getLogger("BackgroundJobs")


# ─────────────────────────────────────────────────────────────────────────────
# BackgroundJobManager
# ─────────────────────────────────────────────────────────────────────────────

class BackgroundJobManager:
    """Manages daemon background threads for periodic / one-shot jobs.

    Key properties
    --------------
    * All threads are started as ``daemon=True`` so they never prevent the
      process from exiting.
    * Jobs never print to stdout/stderr.  Status messages go into the
      :data:`~core.notification_queue.notif_queue`.
    * A shared :class:`threading.Event` (``self._stop_event``) lets all
      threads exit cleanly on :meth:`stop`.
    """

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._threads: List[threading.Thread] = []
        self._lock = threading.Lock()

    # ── public API ─────────────────────────────────────────────────────────

    def add(
        self,
        fn: Callable[[], object],
        interval: Optional[float] = None,
        name: Optional[str] = None,
        push_result: bool = False,
        initial_delay: float = 0.0,
    ) -> threading.Thread:
        """Register and immediately start a background job.

        Parameters
        ----------
        fn:
            Callable to execute.  Must take no arguments.
        interval:
            If ``None`` (default) the job runs once.  If a positive number,
            the job re-runs every *interval* seconds until :meth:`stop` is
            called.
        name:
            Human-readable thread name shown in ``threads`` command output.
        push_result:
            If ``True``, the return value of *fn* (stringified) is pushed to
            the notification queue after each successful run.
        initial_delay:
            Seconds to wait before the first run (useful for letting the
            system fully initialise).  Defaults to 0 (run immediately).
        """
        job_name = name or getattr(fn, "__name__", "bg_job")

        def _thread_fn() -> None:
            # Optional initial delay
            if initial_delay > 0:
                if self._stop_event.wait(timeout=initial_delay):
                    return  # stop was requested during initial delay

            first_run = True
            while not self._stop_event.is_set():
                if not first_run and interval:
                    # Sleep in small chunks so stop_event is checked frequently
                    remaining = float(interval)
                    chunk = min(10.0, remaining)
                    while remaining > 0 and not self._stop_event.is_set():
                        self._stop_event.wait(timeout=chunk)
                        remaining -= chunk
                        chunk = min(10.0, remaining)
                    if self._stop_event.is_set():
                        break
                first_run = False

                try:
                    result = fn()
                    if push_result and result is not None:
                        _notif_queue.push(f"[{job_name}] {result}")
                except Exception as exc:
                    # Never crash the loop — capture error in notification queue
                    tb = traceback.format_exc()
                    _notif_queue.push(
                        f"[{job_name}] ERROR: {exc}\n{tb[-300:]}"
                    )
                    log.debug("[BackgroundJobs] %s raised: %s", job_name, exc)

                if interval is None:
                    break  # one-shot job: exit after first run

        t = threading.Thread(target=_thread_fn, name=job_name, daemon=True)
        t.start()
        with self._lock:
            self._threads.append(t)
        log.debug("[BackgroundJobs] Started thread: %s (interval=%s)", job_name, interval)
        return t

    def stop(self) -> None:
        """Signal all managed background threads to stop gracefully."""
        self._stop_event.set()
        log.debug("[BackgroundJobs] stop_event set — threads will exit on next sleep")

    def alive_threads(self) -> List[threading.Thread]:
        """Return the subset of managed threads that are still alive."""
        with self._lock:
            return [t for t in self._threads if t.is_alive()]

    def status_summary(self) -> str:
        """Return a human-readable status string suitable for display."""
        with self._lock:
            total = len(self._threads)
            alive = sum(1 for t in self._threads if t.is_alive())
        return f"BackgroundJobs: {alive}/{total} threads alive, stop_event={self._stop_event.is_set()}"


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton
# ─────────────────────────────────────────────────────────────────────────────

#: Global BackgroundJobManager singleton.  Import and use this everywhere.
bg_jobs: BackgroundJobManager = BackgroundJobManager()
