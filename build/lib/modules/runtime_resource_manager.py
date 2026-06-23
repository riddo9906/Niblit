#!/usr/bin/env python3
"""
modules/runtime_resource_manager.py — Phase 21 Runtime Resource Intelligence

Makes Niblit aware of its physical runtime constraints (RAM, CPU, battery,
thermal state, token latency) so it can adapt its own behaviour:

    if memory_pressure > 0.8:   reduce_context_window()
    if battery_low:             disable_heavy_forecasts()
    if latency_high:            switch_to_qwen_0_5b()

This transforms Niblit into a real AIOS runtime that treats hardware
as a first-class cognitive input — essential on Termux / mobile hardware.

Resource metrics
----------------
:class:`ResourceSnapshot`::

    ram_used_mb       : float   — current RSS
    ram_available_mb  : float   — system available RAM
    ram_pressure      : float   — 0.0–1.0 (1.0 = fully saturated)
    cpu_percent       : float   — 0.0–100.0
    battery_percent   : float   — 0.0–100.0 (100.0 when AC or unknown)
    battery_charging  : bool
    avg_token_latency_ms : float — EMA of recent token generation times
    thermal_ok        : bool    — True when CPU is not throttling

Adaptive recommendations (from ``recommend()``)
------------------------------------------------
Returns a :class:`ResourceRecommendation`::

    reduce_context        : bool   — context window should be shortened
    disable_heavy_forecasts: bool  — TFT/pytorch should be skipped
    prefer_qwen           : bool   — switch to lighter Qwen 0.5B model
    compress_memory       : bool   — trigger memory compression cycle
    reason                : str    — human-readable explanation

Configuration (env vars)
------------------------
    NIBLIT_RRM_ENABLED              — "0" to disable (default 1)
    NIBLIT_RRM_RAM_PRESSURE_HIGH    — threshold for reduce_context (default 0.80)
    NIBLIT_RRM_RAM_PRESSURE_MEDIUM  — threshold for compress_memory (default 0.60)
    NIBLIT_RRM_BATTERY_LOW          — battery % below which heavy ops stop (default 15)
    NIBLIT_RRM_LATENCY_HIGH_MS      — EMA latency above which we switch models (default 5000)

Usage::

    from modules.runtime_resource_manager import get_resource_manager

    rrm = get_resource_manager()
    snap = rrm.snapshot()
    rec  = rrm.recommend()
    print(snap.ram_pressure, rec.prefer_qwen)

    # Record a token generation latency observation
    rrm.record_token_latency(1234.5)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

_ENABLED: bool = os.getenv("NIBLIT_RRM_ENABLED", "1").strip() not in ("0", "false")
_RAM_HIGH: float  = float(os.getenv("NIBLIT_RRM_RAM_PRESSURE_HIGH",   "0.80"))
_RAM_MEDIUM: float = float(os.getenv("NIBLIT_RRM_RAM_PRESSURE_MEDIUM", "0.60"))
_BATTERY_LOW: float = float(os.getenv("NIBLIT_RRM_BATTERY_LOW",        "15"))
_LATENCY_HIGH_MS: float = float(os.getenv("NIBLIT_RRM_LATENCY_HIGH_MS", "5000"))
_EMA_ALPHA: float = 0.2


# ── Optional psutil import ────────────────────────────────────────────────────
try:
    import psutil as _psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False
    log.debug("[RRM] psutil not installed — RAM/CPU metrics unavailable (pip install psutil)")


# ── ResourceSnapshot ──────────────────────────────────────────────────────────

@dataclass
class ResourceSnapshot:
    """Point-in-time hardware resource usage."""
    ram_used_mb: float
    ram_available_mb: float
    ram_pressure: float
    cpu_percent: float
    battery_percent: float
    battery_charging: bool
    avg_token_latency_ms: float
    thermal_ok: bool

    def to_dict(self) -> Dict:
        return {
            "ram_used_mb": round(self.ram_used_mb, 1),
            "ram_available_mb": round(self.ram_available_mb, 1),
            "ram_pressure": round(self.ram_pressure, 4),
            "cpu_percent": round(self.cpu_percent, 1),
            "battery_percent": round(self.battery_percent, 1),
            "battery_charging": self.battery_charging,
            "avg_token_latency_ms": round(self.avg_token_latency_ms, 1),
            "thermal_ok": self.thermal_ok,
        }


# ── ResourceRecommendation ────────────────────────────────────────────────────

@dataclass
class ResourceRecommendation:
    """Adaptive recommendations based on current resource state."""
    reduce_context: bool
    disable_heavy_forecasts: bool
    prefer_qwen: bool
    compress_memory: bool
    reason: str

    def to_dict(self) -> Dict:
        return {
            "reduce_context": self.reduce_context,
            "disable_heavy_forecasts": self.disable_heavy_forecasts,
            "prefer_qwen": self.prefer_qwen,
            "compress_memory": self.compress_memory,
            "reason": self.reason,
        }


# ── RuntimeResourceManager ────────────────────────────────────────────────────

class RuntimeResourceManager:
    """Monitors hardware resources and issues adaptive recommendations.

    Thread-safe.  Designed to be polled at low frequency (e.g. every
    30–60 seconds) to minimise overhead on constrained hardware.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._avg_token_latency_ms: float = 0.0
        self._snapshot_count: int = 0
        log.debug("[RRM] initialised (psutil=%s)", _PSUTIL)

    # ── Public API ────────────────────────────────────────────────────────────

    def snapshot(self) -> ResourceSnapshot:
        """Capture and return current resource metrics.

        Returns:
            :class:`ResourceSnapshot` — always valid.  Missing metrics are
            replaced with safe defaults.
        """
        if not _ENABLED:
            return self._default_snapshot()
        try:
            snap = self._collect()
            with self._lock:
                self._snapshot_count += 1
            return snap
        except Exception as exc:
            log.debug("[RRM] snapshot error: %s", exc)
            return self._default_snapshot()

    def recommend(self) -> ResourceRecommendation:
        """Return adaptive recommendations based on current resource state."""
        snap = self.snapshot()
        reasons = []

        reduce_context = False
        disable_heavy = False
        prefer_qwen = False
        compress_memory = False

        if snap.ram_pressure >= _RAM_HIGH:
            reduce_context = True
            prefer_qwen = True
            reasons.append(f"RAM pressure {snap.ram_pressure:.0%} (high)")

        if snap.ram_pressure >= _RAM_MEDIUM:
            compress_memory = True
            if not reasons:
                reasons.append(f"RAM pressure {snap.ram_pressure:.0%} (medium)")

        if snap.battery_percent <= _BATTERY_LOW and not snap.battery_charging:
            disable_heavy = True
            prefer_qwen = True
            reasons.append(f"battery low ({snap.battery_percent:.0f}%)")

        if snap.avg_token_latency_ms >= _LATENCY_HIGH_MS:
            prefer_qwen = True
            reasons.append(f"token latency high ({snap.avg_token_latency_ms:.0f}ms)")

        if not snap.thermal_ok:
            disable_heavy = True
            prefer_qwen = True
            reasons.append("CPU throttling detected")

        reason = "; ".join(reasons) if reasons else "resources nominal"

        rec = ResourceRecommendation(
            reduce_context=reduce_context,
            disable_heavy_forecasts=disable_heavy,
            prefer_qwen=prefer_qwen,
            compress_memory=compress_memory,
            reason=reason,
        )
        log.debug("[RRM] recommend: %s", rec.to_dict())
        return rec

    def record_token_latency(self, latency_ms: float) -> None:
        """Record a token generation latency observation (EMA update).

        Args:
            latency_ms: Wall-clock time in milliseconds for a token batch.
        """
        latency_ms = max(0.0, float(latency_ms))
        with self._lock:
            if self._avg_token_latency_ms <= 0:
                self._avg_token_latency_ms = latency_ms
            else:
                self._avg_token_latency_ms = (
                    _EMA_ALPHA * latency_ms + (1.0 - _EMA_ALPHA) * self._avg_token_latency_ms
                )

    def status(self) -> Dict:
        snap = self.snapshot()
        rec = self.recommend()
        with self._lock:
            return {
                "enabled": _ENABLED,
                "psutil_available": _PSUTIL,
                "snapshot_count": self._snapshot_count,
                "snapshot": snap.to_dict(),
                "recommendation": rec.to_dict(),
            }

    # ── Internal collection ───────────────────────────────────────────────────

    def _collect(self) -> ResourceSnapshot:
        ram_used_mb = 0.0
        ram_available_mb = 8192.0  # safe default
        ram_pressure = 0.0
        cpu_percent = 0.0
        battery_pct = 100.0
        battery_charging = True
        thermal_ok = True

        if _PSUTIL:
            try:
                vm = _psutil.virtual_memory()
                ram_used_mb = vm.used / (1024 ** 2)
                ram_available_mb = vm.available / (1024 ** 2)
                ram_pressure = vm.percent / 100.0
            except Exception:
                pass

            try:
                cpu_percent = _psutil.cpu_percent(interval=None)
            except Exception:
                pass

            try:
                bat = _psutil.sensors_battery()
                if bat is not None:
                    battery_pct = bat.percent
                    battery_charging = bat.power_plugged
            except Exception:
                pass

            try:
                # Thermal throttling heuristic: CPU freq much lower than max
                temps = _psutil.sensors_temperatures()  # type: ignore[attr-defined]
                if temps:
                    all_temps = [t.current for group in temps.values() for t in group]
                    if all_temps and max(all_temps) > 80:
                        thermal_ok = False
            except Exception:
                pass

        with self._lock:
            avg_latency = self._avg_token_latency_ms

        return ResourceSnapshot(
            ram_used_mb=ram_used_mb,
            ram_available_mb=ram_available_mb,
            ram_pressure=ram_pressure,
            cpu_percent=cpu_percent,
            battery_percent=battery_pct,
            battery_charging=battery_charging,
            avg_token_latency_ms=avg_latency,
            thermal_ok=thermal_ok,
        )

    def _default_snapshot(self) -> ResourceSnapshot:
        with self._lock:
            avg_lat = self._avg_token_latency_ms
        return ResourceSnapshot(
            ram_used_mb=0.0, ram_available_mb=8192.0, ram_pressure=0.0,
            cpu_percent=0.0, battery_percent=100.0, battery_charging=True,
            avg_token_latency_ms=avg_lat, thermal_ok=True,
        )


# ── Singleton ─────────────────────────────────────────────────────────────────
_rrm: Optional[RuntimeResourceManager] = None
_rrm_lock = threading.Lock()


def get_resource_manager() -> RuntimeResourceManager:
    """Return the module-level :class:`RuntimeResourceManager` singleton."""
    global _rrm
    with _rrm_lock:
        if _rrm is None:
            _rrm = RuntimeResourceManager()
    return _rrm


if __name__ == "__main__":
    print('Running runtime_resource_manager.py')
