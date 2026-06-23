#!/usr/bin/env python3
"""
modules/autonomic_runtime_manager.py — Phase Ω Autonomic Runtime Manager

Expands ``runtime_resource_manager`` into a full **autonomic** runtime
intelligence layer that makes Niblit resilient under constrained hardware.

Niblit runs primarily on Termux / mobile hardware.  Constraints include:

    - RAM pressure (limited heap)
    - CPU thermal limits
    - Battery drain
    - High inference latency
    - Intermittent connectivity

This module continuously monitors these resources and **autonomically**
applies adaptations:

    ADAPTATION                  TRIGGER
    ──────────────────────────────────────────────────────────
    reduce_context_window       RAM > 80 % or memory_pressure > 0.8
    disable_heavy_forecasts     battery < 20 %
    prefer_qwen (fast routing)  latency > 3 s or battery < 15 %
    compress_memory             RAM > 70 % and memory pressure high
    pause_background_jobs       battery < 10 % or thermal > 85 °C
    low_resource_survival_mode  RAM > 90 % and battery < 10 %
    re-enable normal mode       all metrics return to normal range

Architecture::

    ResourceMonitor (psutil, /proc, /sys)
         │
         ▼
    AdaptationEngine
         │
         ├── trigger_reduce_context_window()
         ├── trigger_disable_heavy_forecasts()
         ├── trigger_prefer_qwen()
         ├── trigger_compress_memory()
         ├── trigger_pause_background_jobs()
         └── trigger_survival_mode()
                   │
                   ▼
             ResourceStatus + EventBus

Configuration (env vars)
------------------------
    NIBLIT_ARM_ENABLED      — "0" to disable (default 1)
    NIBLIT_ARM_RAM_HIGH     — RAM fraction for high pressure (default 0.80)
    NIBLIT_ARM_BATT_LOW     — battery fraction for low battery (default 0.20)
    NIBLIT_ARM_LATENCY_HIGH — latency in ms for high latency (default 3000)

Usage::

    from modules.autonomic_runtime_manager import get_autonomic_runtime_manager

    arm = get_autonomic_runtime_manager()
    arm.record_latency(1200.0)     # ms
    recommendations = arm.assess()
    for r in recommendations:
        print(r)                   # e.g. "prefer_qwen"
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

_ENABLED: bool = os.getenv("NIBLIT_ARM_ENABLED", "1").strip() not in ("0", "false")
_RAM_HIGH: float = float(os.getenv("NIBLIT_ARM_RAM_HIGH", "0.80"))
_BATT_LOW: float = float(os.getenv("NIBLIT_ARM_BATT_LOW", "0.20"))
_LATENCY_HIGH: float = float(os.getenv("NIBLIT_ARM_LATENCY_HIGH", "3000"))


# ── ResourceSnapshot ──────────────────────────────────────────────────────────

@dataclass
class ResourceSnapshot:
    """Current hardware resource state."""
    ram_used_fraction: float     # 0.0–1.0
    cpu_fraction: float          # 0.0–1.0
    battery_fraction: float      # 0.0–1.0 (1.0 = full, -1.0 = plugged in / unknown)
    thermal_celsius: float       # CPU temperature (0 if unavailable)
    avg_latency_ms: float        # EMA of recent inference latency
    timestamp: float = field(default_factory=time.time)

    @property
    def is_memory_critical(self) -> bool:
        return self.ram_used_fraction > _RAM_HIGH

    @property
    def is_battery_critical(self) -> bool:
        return 0.0 < self.battery_fraction < _BATT_LOW

    @property
    def is_latency_high(self) -> bool:
        return self.avg_latency_ms > _LATENCY_HIGH

    @property
    def is_thermal_critical(self) -> bool:
        return 0.0 < self.thermal_celsius > 85.0

    def to_dict(self) -> Dict:
        return {
            "ram_used_fraction": round(self.ram_used_fraction, 4),
            "cpu_fraction": round(self.cpu_fraction, 4),
            "battery_fraction": round(self.battery_fraction, 4),
            "thermal_celsius": round(self.thermal_celsius, 1),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "is_memory_critical": self.is_memory_critical,
            "is_battery_critical": self.is_battery_critical,
            "is_latency_high": self.is_latency_high,
            "is_thermal_critical": self.is_thermal_critical,
        }


# ── AutonomicRuntimeManager ───────────────────────────────────────────────────

class AutonomicRuntimeManager:
    """Autonomic resource intelligence manager.

    Continuously monitors hardware constraints and emits adaptation
    recommendations.  Thread-safe singleton.

    psutil is used when available; graceful degradation otherwise.
    """

    _ADAPTATIONS = [
        "reduce_context_window",
        "disable_heavy_forecasts",
        "prefer_qwen",
        "compress_memory",
        "pause_background_jobs",
        "low_resource_survival_mode",
    ]

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._avg_latency_ms: float = 0.0
        self._assess_count: int = 0
        self._active_adaptations: set = set()
        self._adaptation_log: List[Dict] = []
        self._psutil_available: bool = self._check_psutil()
        log.debug("[ARM] initialised (psutil=%s)", self._psutil_available)

    # ── Observation ───────────────────────────────────────────────────────────

    def record_latency(self, latency_ms: float) -> None:
        """Update the EMA of inference latency."""
        with self._lock:
            if self._avg_latency_ms <= 0:
                self._avg_latency_ms = latency_ms
            else:
                self._avg_latency_ms = 0.2 * latency_ms + 0.8 * self._avg_latency_ms

    # ── Assessment ────────────────────────────────────────────────────────────

    def read_snapshot(self) -> ResourceSnapshot:
        """Read current hardware metrics."""
        ram_frac = 0.5
        cpu_frac = 0.3
        battery_frac = -1.0
        thermal = 0.0

        if self._psutil_available:
            try:
                import psutil
                vm = psutil.virtual_memory()
                ram_frac = vm.percent / 100.0
                cpu_frac = psutil.cpu_percent(interval=None) / 100.0
                battery = psutil.sensors_battery()
                if battery is not None:
                    battery_frac = battery.percent / 100.0
                temps = getattr(psutil, "sensors_temperatures", lambda: {})()
                if temps:
                    all_temps = [t.current for ts in temps.values() for t in ts if t.current]
                    if all_temps:
                        thermal = max(all_temps)
            except Exception as exc:
                log.debug("[ARM] psutil read error: %s", exc)

        with self._lock:
            latency = self._avg_latency_ms

        return ResourceSnapshot(
            ram_used_fraction=ram_frac,
            cpu_fraction=cpu_frac,
            battery_fraction=battery_frac,
            thermal_celsius=thermal,
            avg_latency_ms=latency,
        )

    def assess(self) -> List[str]:
        """Assess current resource state and return active adaptation list.

        Returns:
            List of active adaptation labels.
        """
        if not _ENABLED:
            return []

        snap = self.read_snapshot()
        recommendations: set = set()

        if snap.is_memory_critical:
            recommendations.add("reduce_context_window")
            recommendations.add("compress_memory")

        if snap.ram_used_fraction > 0.90 and snap.is_battery_critical:
            recommendations.add("low_resource_survival_mode")
            recommendations.add("prefer_qwen")
            recommendations.add("disable_heavy_forecasts")
            recommendations.add("pause_background_jobs")
        else:
            if snap.is_battery_critical:
                recommendations.add("disable_heavy_forecasts")
            if snap.battery_fraction > 0.0 and snap.battery_fraction < 0.15:
                recommendations.add("prefer_qwen")
            if snap.is_latency_high:
                recommendations.add("prefer_qwen")
            if snap.is_thermal_critical:
                recommendations.add("pause_background_jobs")
                recommendations.add("prefer_qwen")

        with self._lock:
            added = recommendations - self._active_adaptations
            removed = self._active_adaptations - recommendations
            self._active_adaptations = set(recommendations)
            self._assess_count += 1

        for a in added:
            log.info("[ARM] activate: %s (ram=%.0f%% batt=%.0f%% lat=%.0fms)",
                     a, snap.ram_used_fraction * 100,
                     snap.battery_fraction * 100 if snap.battery_fraction >= 0 else -1,
                     snap.avg_latency_ms)
            self._log_adaptation(a, "activated", snap)
        for r in removed:
            log.info("[ARM] deactivate: %s", r)
            self._log_adaptation(r, "deactivated", snap)

        self._emit_event(recommendations)
        return sorted(recommendations)

    def is_active(self, adaptation: str) -> bool:
        """Return True if *adaptation* is currently active."""
        with self._lock:
            return adaptation in self._active_adaptations

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> Dict:
        snap = self.read_snapshot()
        with self._lock:
            return {
                "enabled": _ENABLED,
                "psutil_available": self._psutil_available,
                "assess_count": self._assess_count,
                "active_adaptations": sorted(self._active_adaptations),
                "snapshot": snap.to_dict(),
            }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _check_psutil(self) -> bool:
        try:
            import psutil  # noqa: F401
            return True
        except ImportError:
            return False

    def _log_adaptation(self, label: str, action: str, snap: ResourceSnapshot) -> None:
        with self._lock:
            self._adaptation_log.append({
                "label": label, "action": action,
                "timestamp": time.time(), "snap": snap.to_dict(),
            })
            if len(self._adaptation_log) > 100:
                self._adaptation_log.pop(0)

    def _emit_event(self, active: set) -> None:
        try:
            from modules.event_bus import get_event_bus, NiblitEvent, EVENT_RESOURCE_ADAPTED
            get_event_bus().publish(NiblitEvent(
                type=EVENT_RESOURCE_ADAPTED,
                source="autonomic_runtime_manager",
                payload={"active_adaptations": sorted(active)},
            ))
        except Exception:
            pass


# ── Singleton ─────────────────────────────────────────────────────────────────
_arm: Optional[AutonomicRuntimeManager] = None
_arm_lock = threading.Lock()


def get_autonomic_runtime_manager() -> AutonomicRuntimeManager:
    """Return the module-level :class:`AutonomicRuntimeManager` singleton."""
    global _arm
    with _arm_lock:
        if _arm is None:
            _arm = AutonomicRuntimeManager()
    return _arm


if __name__ == "__main__":
    print('Running autonomic_runtime_manager.py')
