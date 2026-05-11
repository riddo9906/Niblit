#!/usr/bin/env python3
"""Phase Ω.5 Recursive Stability Governor."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class GovernorReport:
    stability_pressure: float
    recursion_depth: int
    adaptation_velocity: float
    governor_interventions: List[str]
    damping_coefficients: Dict[str, float]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stability_pressure": round(self.stability_pressure, 4),
            "recursion_depth": self.recursion_depth,
            "adaptation_velocity": round(self.adaptation_velocity, 4),
            "governor_interventions": list(self.governor_interventions),
            "damping_coefficients": {
                k: round(v, 4) for k, v in self.damping_coefficients.items()
            },
            "timestamp": self.timestamp,
        }


class RecursiveStabilityGovernor:
    """Detects runaway adaptation loops and injects damping pressure."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: List[Dict[str, Any]] = []
        self._cooldowns: Dict[str, float] = {}
        self._damping: Dict[str, float] = {}
        self._last_report: Optional[GovernorReport] = None
        self._run_count = 0

    def record_adaptation_event(self, subsystem: str, magnitude: float, cause: str = "") -> None:
        with self._lock:
            self._events.append(
                {
                    "ts": time.time(),
                    "subsystem": subsystem,
                    "magnitude": max(0.0, float(magnitude)),
                    "cause": cause,
                }
            )
            if len(self._events) > 500:
                self._events = self._events[-500:]

    def evaluate(self) -> GovernorReport:
        depth = self.trace_recursive_loops()
        velocity = self.compute_adaptation_velocity()
        pressure = min(1.0, 0.1 * depth + 0.6 * velocity)
        interventions = self._compute_interventions(depth, velocity)
        with self._lock:
            report = GovernorReport(
                stability_pressure=pressure,
                recursion_depth=depth,
                adaptation_velocity=velocity,
                governor_interventions=interventions,
                damping_coefficients=dict(self._damping),
            )
            self._last_report = report
            self._run_count += 1
        self._emit(report)
        return report

    def trace_recursive_loops(self) -> int:
        with self._lock:
            events = list(self._events[-50:])
        if len(events) < 4:
            return 0
        chain = [e["subsystem"] for e in events]
        max_depth = 0
        for i in range(len(chain) - 3):
            a, b, c, d = chain[i : i + 4]
            if a == d and len({a, b, c}) >= 3:
                max_depth = max(max_depth, 4)
        return max_depth

    def compute_adaptation_velocity(self) -> float:
        now = time.time()
        with self._lock:
            recent = [e for e in self._events if now - e["ts"] <= 60]
        if not recent:
            return 0.0
        total_mag = sum(float(e["magnitude"]) for e in recent)
        return min(1.0, total_mag / max(1.0, len(recent)))

    def is_in_cooldown(self, subsystem: str) -> bool:
        with self._lock:
            until = self._cooldowns.get(subsystem, 0.0)
        return time.time() < until

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "run_count": self._run_count,
                "event_count": len(self._events),
                "cooldowns": dict(self._cooldowns),
                "damping_coefficients": dict(self._damping),
                "last_report": self._last_report.to_dict() if self._last_report else None,
            }

    def _compute_interventions(self, depth: int, velocity: float) -> List[str]:
        actions: List[str] = []
        if depth >= 4:
            actions.append("runaway_recursion_breaker")
        if velocity > 0.7:
            actions.append("adaptation_velocity_limiter")
        if depth >= 4 or velocity > 0.7:
            self._apply_damping("global", 0.55)
            actions.append("stability_pressure_injection")
        if velocity > 0.8:
            self._set_cooldown("reflection_engine", seconds=30)
            actions.append("reflection_cooldown")
        return actions

    def _apply_damping(self, subsystem: str, coefficient: float) -> None:
        with self._lock:
            old = self._damping.get(subsystem, 1.0)
            self._damping[subsystem] = min(old, max(0.1, coefficient))

    def _set_cooldown(self, subsystem: str, seconds: int) -> None:
        with self._lock:
            self._cooldowns[subsystem] = time.time() + seconds

    def _emit(self, report: GovernorReport) -> None:
        try:
            from modules.event_bus import EVENT_RECURSION_GOVERNED, NiblitEvent, get_event_bus

            get_event_bus().publish(
                NiblitEvent(
                    type=EVENT_RECURSION_GOVERNED,
                    source="recursive_stability_governor",
                    payload={
                        "recursion_depth": report.recursion_depth,
                        "stability_pressure": report.stability_pressure,
                    },
                )
            )
        except Exception:
            pass


_rsg: Optional[RecursiveStabilityGovernor] = None
_rsg_lock = threading.Lock()


def get_recursive_stability_governor() -> RecursiveStabilityGovernor:
    global _rsg
    with _rsg_lock:
        if _rsg is None:
            _rsg = RecursiveStabilityGovernor()
    return _rsg

