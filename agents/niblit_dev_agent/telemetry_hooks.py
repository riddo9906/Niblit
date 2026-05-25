#!/usr/bin/env python3
"""Telemetry hooks for NiblitDevAgent using existing TelemetryCollector."""

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
