"""
kernel/process_manager.py — Lightweight process and thread scheduler.

Manages named worker threads and subprocesses on behalf of NiblitCore
subsystems, providing lifecycle control (start / stop / restart) and
basic resource accounting.
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field

log = logging.getLogger("NiblitOSKernel.ProcessManager")

__all__ = ["ProcessRecord", "ProcessManager"]


@dataclass
class ProcessRecord:
    """Tracks a single managed process or thread."""

    pid: str                        # logical name / ID
    kind: str                       # "thread" | "subprocess"
    target: Callable | None = None
    args: tuple = field(default_factory=tuple)
    kwargs: dict = field(default_factory=dict)
    daemon: bool = True
    started_at: float = field(default_factory=time.time)
    stopped_at: float | None = None
    status: str = "running"         # "running" | "stopped" | "failed"

    # Runtime handles (not serialised)
    _thread: threading.Thread | None = field(default=None, repr=False, compare=False)
    _proc: subprocess.Popen | None = field(default=None, repr=False, compare=False)

    def is_alive(self) -> bool:
        if self.kind == "thread" and self._thread:
            return self._thread.is_alive()
        if self.kind == "subprocess" and self._proc:
            return self._proc.poll() is None
        return False


class ProcessManager:
    """
    Scheduler for named threads and subprocesses.

    Provides:
    - ``spawn_thread(pid, target, ...)`` — launch a daemon thread
    - ``spawn_subprocess(pid, cmd, ...)`` — launch a child process
    - ``stop(pid)`` — request graceful stop
    - ``status()`` — serialisable summary
    """

    def __init__(self) -> None:
        self._records: dict[str, ProcessRecord] = {}
        self._lock = threading.Lock()

    # -------------------------------------------------------- spawn_thread ---
    def spawn_thread(
        self,
        pid: str,
        target: Callable,
        args: tuple = (),
        kwargs: dict | None = None,
        daemon: bool = True,
    ) -> ProcessRecord:
        """
        Spawn a daemon thread and register it under *pid*.

        If a live thread with the same *pid* already exists it is returned
        unchanged.
        """
        kwargs = kwargs or {}
        with self._lock:
            existing = self._records.get(pid)
            if existing and existing.is_alive():
                return existing

            record = ProcessRecord(
                pid=pid,
                kind="thread",
                target=target,
                args=args,
                kwargs=kwargs,
                daemon=daemon,
            )
            t = threading.Thread(target=target, args=args, kwargs=kwargs, daemon=daemon, name=pid)
            record._thread = t
            t.start()
            self._records[pid] = record
            log.debug("[PM] Thread started: %s", pid)
            return record

    # ----------------------------------------------------- spawn_subprocess --
    def spawn_subprocess(
        self,
        pid: str,
        cmd: list[str],
        **popen_kwargs,
    ) -> ProcessRecord:
        """
        Spawn a subprocess and register it under *pid*.

        Extra kwargs are forwarded to :class:`subprocess.Popen`.
        """
        with self._lock:
            existing = self._records.get(pid)
            if existing and existing.is_alive():
                return existing

        proc = subprocess.Popen(cmd, **popen_kwargs)  # noqa: S603
        record = ProcessRecord(pid=pid, kind="subprocess")
        record._proc = proc
        with self._lock:
            self._records[pid] = record
        log.debug("[PM] Subprocess started: %s (OS PID %d)", pid, proc.pid)
        return record

    # ----------------------------------------------------------------- stop --
    def stop(self, pid: str, timeout: float = 5.0) -> bool:
        """
        Request stop of the process/thread registered under *pid*.

        For subprocesses, sends SIGTERM then waits *timeout* seconds.
        Threads cannot be forcibly stopped — this marks them as stopped.
        Returns True if the process is now dead.
        """
        with self._lock:
            record = self._records.get(pid)
        if record is None:
            return False

        if record.kind == "subprocess" and record._proc:
            record._proc.terminate()
            try:
                record._proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                record._proc.kill()
                record._proc.wait()
        record.status = "stopped"
        record.stopped_at = time.time()
        log.debug("[PM] Stopped: %s", pid)
        return True

    # -------------------------------------------------------------- list_all --
    def list_all(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "pid": r.pid,
                    "kind": r.kind,
                    "status": r.status,
                    "alive": r.is_alive(),
                    "started_at": r.started_at,
                }
                for r in self._records.values()
            ]

    # --------------------------------------------------------------- status --
    def status(self) -> dict:
        records = self.list_all()
        return {
            "total": len(records),
            "running": sum(1 for r in records if r["alive"]),
            "processes": records,
        }

    # Convenience aliases for kernel/shell.py compatibility
    def spawn(self, pid: str, cmd: list[str], **popen_kwargs) -> ProcessRecord:
        """Alias for spawn_subprocess()."""
        return self.spawn_subprocess(pid, cmd, **popen_kwargs)

    def kill(self, pid: str, timeout: float = 5.0) -> bool:
        """Alias for stop()."""
        return self.stop(pid, timeout=timeout)

    def list_processes(self) -> list[dict]:
        """Alias for list_all(), remaps 'kind' → 'type' for shell display."""
        records = self.list_all()
        for r in records:
            r.setdefault("type", r.get("kind", "unknown"))
        return records

    def shutdown(self) -> None:
        """Stop all managed subprocesses on kernel shutdown."""
        with self._lock:
            pids = list(self._records.keys())
        for pid in pids:
            try:
                self.stop(pid)
            except Exception as exc:
                log.warning("[PM] shutdown stop error for %s: %s", pid, exc)
