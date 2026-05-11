#!/usr/bin/env python3
"""Phase Ω.5 Recursive Stability Governor."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_STATE_PATH = Path(__file__).resolve().parent.parent / "recursive_stability_state.json"


@dataclass
class GovernorReport:
    stability_pressure: float
    recursion_depth: int
    adaptation_velocity: float
    subsystem_pressure: dict[str, float]
    intervention_count: int
    stabilized_cycles: int
    governor_interventions: list[str]
    confidence: float
    stability_impact: float
    coherence_impact: float
    causal_trace_metadata: dict[str, Any]
    rationale: str
    explanation: str
    epoch: int
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stability_pressure": round(self.stability_pressure, 4),
            "recursion_depth": self.recursion_depth,
            "adaptation_velocity": round(self.adaptation_velocity, 4),
            "subsystem_pressure": {k: round(v, 4) for k, v in self.subsystem_pressure.items()},
            "intervention_count": self.intervention_count,
            "stabilized_cycles": self.stabilized_cycles,
            "governor_interventions": list(self.governor_interventions),
            "confidence": round(self.confidence, 4),
            "stability_impact": round(self.stability_impact, 4),
            "coherence_impact": round(self.coherence_impact, 4),
            "causal_trace_metadata": dict(self.causal_trace_metadata),
            "rationale": self.rationale,
            "explanation": self.explanation,
            "epoch": self.epoch,
            "timestamp": self.timestamp,
        }


class RecursiveStabilityGovernor:
    """Prevent runaway recursive adaptation loops."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[dict[str, Any]] = []
        self._graph: dict[str, dict[str, int]] = {}
        self._cooldowns: dict[str, float] = {}
        self._damping: dict[str, float] = {}
        self._intervention_count = 0
        self._stabilized_cycles = 0
        self._last_report: GovernorReport | None = None
        self._run_count = 0
        self._load_state()

    def record_adaptation_event(self, subsystem: str, magnitude: float, cause: str = "") -> None:
        now = time.time()
        with self._lock:
            self._events.append(
                {"ts": now, "subsystem": subsystem, "magnitude": max(0.0, float(magnitude)), "cause": cause}
            )
            if len(self._events) > 1000:
                self._events = self._events[-1000:]
            if len(self._events) >= 2:
                src = self._events[-2]["subsystem"]
                dst = self._events[-1]["subsystem"]
                self._graph.setdefault(src, {})[dst] = self._graph.setdefault(src, {}).get(dst, 0) + 1

    def trace_feedback_loops(self) -> int:
        with self._lock:
            chain = [e["subsystem"] for e in self._events[-80:]]
        if len(chain) < 4:
            return 0
        depth = 0
        for i in range(len(chain) - 3):
            a, b, c, d = chain[i : i + 4]
            if a == d and len({a, b, c}) >= 3:
                depth = max(depth, 4)
        return depth

    def compute_adaptation_velocity(self) -> float:
        now = time.time()
        with self._lock:
            recent = [e for e in self._events if now - e["ts"] <= 60]
        if not recent:
            return 0.0
        return min(1.0, sum(float(e["magnitude"]) for e in recent) / max(1.0, len(recent)))

    def apply_damping(self, subsystem: str, coefficient: float) -> float:
        with self._lock:
            c = min(1.0, max(0.1, float(coefficient)))
            old = self._damping.get(subsystem, 1.0)
            self._damping[subsystem] = min(old, c)
            self._intervention_count += 1
            return self._damping[subsystem]

    def enforce_cooldowns(self, subsystem: str, seconds: int = 30) -> bool:
        with self._lock:
            self._cooldowns[subsystem] = time.time() + max(1, int(seconds))
            self._intervention_count += 1
        return True

    def emergency_stabilize(self) -> list[str]:
        actions = [
            "reduce_exploration",
            "freeze_subsystem_updates",
            "lower_resonance_influence",
            "reduce_planner_horizon",
            "suppress_unstable_causal_rules",
        ]
        self.apply_damping("global", 0.45)
        self.enforce_cooldowns("reflection_engine", 45)
        self.enforce_cooldowns("governance", 45)
        with self._lock:
            self._stabilized_cycles += 1
        return actions

    def evaluate(self) -> GovernorReport:
        recursion_depth = self.trace_feedback_loops()
        velocity = self.compute_adaptation_velocity()
        subsystem_pressure = self._subsystem_pressure()
        pressure = min(1.0, 0.15 * recursion_depth + 0.55 * velocity)
        interventions: list[str] = []
        if recursion_depth >= 4:
            interventions.extend(["runaway_recursion_breaker", "reduce_exploration"])
            self.apply_damping("global", 0.6)
        if velocity > 0.7:
            interventions.append("adaptation_velocity_limiter")
            self.enforce_cooldowns("reflection_engine", 30)
        if pressure > 0.8:
            interventions.extend(self.emergency_stabilize())

        with self._lock:
            self._run_count += 1
            self._intervention_count += len(interventions)
            if pressure < 0.4:
                self._stabilized_cycles += 1
            report = GovernorReport(
                stability_pressure=pressure,
                recursion_depth=recursion_depth,
                adaptation_velocity=velocity,
                subsystem_pressure=subsystem_pressure,
                intervention_count=self._intervention_count,
                stabilized_cycles=self._stabilized_cycles,
                governor_interventions=interventions,
                confidence=max(0.0, 1.0 - pressure),
                stability_impact=max(0.0, 1.0 - pressure),
                coherence_impact=max(0.0, 1.0 - velocity),
                causal_trace_metadata={"trace_graph_edges": sum(len(v) for v in self._graph.values())},
                rationale=self._rationale(pressure, recursion_depth, velocity),
                explanation="Recursive loop depth and adaptation velocity jointly governed.",
                epoch=_safe_epoch(),
            )
            self._last_report = report
            self._save_state()

        self._emit(report)
        return report

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "run_count": self._run_count,
                "event_count": len(self._events),
                "recursion_graph": self._graph,
                "cooldowns": dict(self._cooldowns),
                "damping_coefficients": dict(self._damping),
                "last_report": self._last_report.to_dict() if self._last_report else None,
            }

    def _subsystem_pressure(self) -> dict[str, float]:
        now = time.time()
        with self._lock:
            recent = [e for e in self._events if now - e["ts"] <= 60]
        out: dict[str, float] = {}
        for e in recent:
            out[e["subsystem"]] = out.get(e["subsystem"], 0.0) + float(e["magnitude"]) * 0.1
        return {k: min(1.0, v) for k, v in out.items()}

    @staticmethod
    def _rationale(pressure: float, depth: int, velocity: float) -> str:
        if pressure > 0.8:
            return f"High recursive risk depth={depth} velocity={velocity:.2f}"
        if pressure > 0.5:
            return f"Moderate recursive pressure depth={depth} velocity={velocity:.2f}"
        return "Stable recursion profile under damping constraints."

    def _emit(self, report: GovernorReport) -> None:
        try:
            from modules.event_bus import (
                EVENT_RECURSION_GOVERNED,
                EVENT_RECURSION_STABILIZED,
                EVENT_RECURSIVE_WARNING,
                NiblitEvent,
                get_event_bus,
            )

            bus = get_event_bus()
            payload = {
                "recursion_depth": report.recursion_depth,
                "stability_pressure": report.stability_pressure,
                "adaptation_velocity": report.adaptation_velocity,
                "confidence": report.confidence,
                "stability_impact": report.stability_impact,
                "coherence_impact": report.coherence_impact,
                "causal_trace_metadata": report.causal_trace_metadata,
                "rationale": report.rationale,
                "epoch": report.epoch,
            }
            if report.stability_pressure >= 0.6:
                bus.publish(
                    NiblitEvent(type=EVENT_RECURSIVE_WARNING, source="recursive_stability_governor", payload=payload)
                )
            bus.publish(
                NiblitEvent(type=EVENT_RECURSION_STABILIZED, source="recursive_stability_governor", payload=payload)
            )
            bus.publish(
                NiblitEvent(type=EVENT_RECURSION_GOVERNED, source="recursive_stability_governor", payload=payload)
            )
        except Exception:
            pass

    def _save_state(self) -> None:
        try:
            data = {
                "run_count": self._run_count,
                "intervention_count": self._intervention_count,
                "stabilized_cycles": self._stabilized_cycles,
                "cooldowns": self._cooldowns,
                "damping": self._damping,
            }
            tmp = _STATE_PATH.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            tmp.replace(_STATE_PATH)
        except Exception:
            pass

    def _load_state(self) -> None:
        try:
            if not _STATE_PATH.exists():
                return
            with _STATE_PATH.open(encoding="utf-8") as fh:
                data = json.load(fh)
            self._run_count = int(data.get("run_count", 0))
            self._intervention_count = int(data.get("intervention_count", 0))
            self._stabilized_cycles = int(data.get("stabilized_cycles", 0))
            self._cooldowns = dict(data.get("cooldowns", {}))
            self._damping = dict(data.get("damping", {}))
        except Exception:
            pass


def _safe_epoch() -> int:
    try:
        from modules.unified_cognitive_state import get_unified_state

        return int(get_unified_state().status().get("epoch", 0))
    except Exception:
        return 0


_rsg: RecursiveStabilityGovernor | None = None
_rsg_lock = threading.Lock()


def get_recursive_stability_governor() -> RecursiveStabilityGovernor:
    global _rsg
    with _rsg_lock:
        if _rsg is None:
            _rsg = RecursiveStabilityGovernor()
    return _rsg
