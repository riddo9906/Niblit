#!/usr/bin/env python3
"""Structured boot diagnostics for runtime startup."""

from __future__ import annotations

import logging
import socket
import threading
import time
import traceback
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("Niblit.Boot")


@dataclass
class BootStageRecord:
    index: int
    name: str
    started_at: float
    status: str = "running"
    elapsed_ms: Optional[float] = None
    detail: str = ""


class BootDiagnostics:
    """Emit numbered boot-stage logs with timings and a final summary."""

    def __init__(self, emitter: Optional[Callable[[str], None]] = None) -> None:
        self._emitter = emitter
        self._lock = threading.Lock()
        self._records: list[BootStageRecord] = []
        self._next_index = 1
        self._last_successful: Optional[str] = None

    def start(self, name: str) -> BootStageRecord:
        with self._lock:
            record = BootStageRecord(index=self._next_index, name=name, started_at=time.monotonic())
            self._next_index += 1
            self._records.append(record)
        self._emit(f"[BOOT {record.index:02d}] {name} — start")
        return record

    def success(self, record: BootStageRecord, detail: str = "") -> None:
        record.status = "success"
        record.elapsed_ms = round((time.monotonic() - record.started_at) * 1000.0, 1)
        record.detail = detail
        self._last_successful = record.name
        suffix = f" — {detail}" if detail else ""
        self._emit(f"[BOOT {record.index:02d}] {record.name} — success ({_fmt_ms(record.elapsed_ms)}){suffix}")

    def failure(
        self,
        record: BootStageRecord,
        exc: BaseException,
        *,
        detail: str = "",
        include_traceback: bool = True,
    ) -> None:
        record.status = "failure"
        record.elapsed_ms = round((time.monotonic() - record.started_at) * 1000.0, 1)
        record.detail = detail or str(exc)
        suffix = f" — {record.detail}" if record.detail else ""
        self._emit(f"[BOOT {record.index:02d}] {record.name} — failure ({_fmt_ms(record.elapsed_ms)}){suffix}")
        self._emit(f"[BOOT {record.index:02d}] exception: {type(exc).__name__}: {exc}")
        if include_traceback:
            tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip()
            if tb:
                self._emit(tb)
        if self._last_successful:
            self._emit(f"[BOOT] last successful phase: {self._last_successful}")

    def summary(self, *, final_message: str = "Niblit Runtime Fully Operational") -> None:
        self._emit("[BOOT SUMMARY] Startup stage timings:")
        for record in self._records:
            elapsed = _fmt_ms(record.elapsed_ms)
            self._emit(
                f"[BOOT SUMMARY] {record.index:02d}. {record.name}: {record.status}"
                f"{f' ({elapsed})' if record.elapsed_ms is not None else ''}"
            )
        if self._last_successful:
            self._emit(f"[BOOT SUMMARY] last successful phase: {self._last_successful}")
        self._emit(final_message)

    @property
    def last_successful_phase(self) -> Optional[str]:
        return self._last_successful

    def _emit(self, message: str) -> None:
        log.info(message)
        if self._emitter is not None:
            self._emitter(message)


class ProcessDiagnostics:
    """Capture child-process metadata and recent output for failure diagnostics."""

    def __init__(
        self,
        *,
        name: str,
        command: list[str],
        cwd: Optional[Path],
        pid: int,
        stdout,
        stderr,
        emitter: Callable[[str], None],
        max_lines: int = 120,
    ) -> None:
        self.name = name
        self.command = list(command)
        self.cwd = cwd
        self.pid = pid
        self._emit = emitter
        self._stdout_tail: deque[str] = deque(maxlen=max_lines)
        self._stderr_tail: deque[str] = deque(maxlen=max_lines)
        self._threads: list[threading.Thread] = []
        self._start_reader(stdout, self._stdout_tail, f"{name}:stdout")
        self._start_reader(stderr, self._stderr_tail, f"{name}:stderr")

    def log_started(self) -> None:
        cwd = str(self.cwd) if self.cwd is not None else "-"
        self._emit(
            f"[BOOT PROC] {self.name} pid={self.pid} cwd={cwd} cmd={' '.join(self.command)}"
        )

    def dump_failure(self, *, exit_code: Optional[int] = None) -> None:
        self._emit(
            f"[BOOT PROC] {self.name} failed"
            f"{f' exit_code={exit_code}' if exit_code is not None else ''}"
        )
        stdout = "".join(self._stdout_tail).strip()
        stderr = "".join(self._stderr_tail).strip()
        if stdout:
            self._emit(f"[BOOT PROC] {self.name} stdout tail:\n{stdout}")
        if stderr:
            self._emit(f"[BOOT PROC] {self.name} stderr tail:\n{stderr}")

    def _start_reader(self, stream, sink: deque[str], name: str) -> None:
        if stream is None:
            return

        def _reader() -> None:
            with suppress(Exception):
                for line in iter(stream.readline, ""):
                    sink.append(line)

        thread = threading.Thread(target=_reader, name=name, daemon=True)
        thread.start()
        self._threads.append(thread)


def is_port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _fmt_ms(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    if value >= 1000.0:
        return f"{value / 1000.0:.2f} s"
    return f"{value:.1f} ms"
