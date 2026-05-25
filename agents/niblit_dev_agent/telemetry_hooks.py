#!/usr/bin/env python3
"""Telemetry hooks for NiblitDevAgent using existing TelemetryCollector (Phase 2)."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


class DevAgentTelemetryHooks:
    """Thin adapter over TelemetryCollector with graceful no-op behavior."""

    def __init__(self, telemetry: Any | None = None) -> None:
        self._telemetry = telemetry

    @contextmanager
    def timed(self, metric_name: str) -> Iterator[None]:
        start = time.monotonic()
        try:
            yield
        finally:
            self.record_timing(metric_name, (time.monotonic() - start) * 1000.0)

    def increment(self, metric_name: str, value: int = 1) -> None:
        if self._telemetry and hasattr(self._telemetry, "increment_counter"):
            self._telemetry.increment_counter(metric_name, value)

    def gauge(self, metric_name: str, value: float) -> None:
        if self._telemetry and hasattr(self._telemetry, "set_gauge"):
            self._telemetry.set_gauge(metric_name, value)

    def record_timing(self, metric_name: str, duration_ms: float) -> None:
        if self._telemetry and hasattr(self._telemetry, "record_timing"):
            self._telemetry.record_timing(metric_name, float(duration_ms))

    def snapshot(self) -> dict[str, Any]:
        if self._telemetry and hasattr(self._telemetry, "get_stats"):
            try:
                return dict(self._telemetry.get_stats())
            except Exception:
                return {}
        return {}

    # ── Phase-2 convenience wrappers ──────────────────────────────────────────

    def record_task_planned(self, duration_ms: float, affected_modules: int = 0) -> None:
        """Record that a DevTask was planned."""
        self.record_timing("dev_agent_task_planning_ms", duration_ms)
        self.increment("dev_agent_tasks_planned_total", 1)
        self.gauge("dev_agent_plan_affected_modules_latest", float(affected_modules))

    def record_architecture_analysis(self, duration_ms: float, touched_modules: int = 0) -> None:
        """Record that an architecture analysis was completed."""
        self.record_timing("dev_agent_architecture_analysis_ms", duration_ms)
        self.increment("dev_agent_architecture_analyses_total", 1)
        self.gauge("dev_agent_analysis_touched_modules_latest", float(touched_modules))

    def record_execution_approval(self, approved: bool) -> None:
        """Record a task approval or denial event."""
        if approved:
            self.increment("dev_agent_task_approvals_total", 1)
        else:
            self.increment("dev_agent_task_denials_total", 1)

    def record_rollback_event(self, task_id: str = "") -> None:
        """Record a rollback event for a governed task."""
        self.increment("dev_agent_rollback_events_total", 1)
        _ = task_id  # reserved for future trace correlation

    def record_task_completed(self, duration_ms: float, success: bool = True) -> None:
        """Record task completion (success or failure)."""
        self.record_timing("dev_agent_task_completion_ms", duration_ms)
        if success:
            self.increment("dev_agent_tasks_completed_total", 1)
        else:
            self.increment("dev_agent_tasks_failed_total", 1)
