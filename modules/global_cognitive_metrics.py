#!/usr/bin/env python3
"""Phase Ω.5 Global Cognitive Metrics."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GlobalCognitiveSnapshot:
    coherence: float
    stability: float
    identity_integrity: float
    governance_health: float
    emergence_index: float
    prediction_reliability: float
    memory_integrity: float
    resonance_dependency: float
    reflection_usefulness: float
    adaptation_velocity: float
    causal_consistency: float
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
            "coherence": self.coherence,
            "stability": self.stability,
            "identity_integrity": self.identity_integrity,
            "governance_health": self.governance_health,
            "emergence_index": self.emergence_index,
            "prediction_reliability": self.prediction_reliability,
            "memory_integrity": self.memory_integrity,
            "resonance_dependency": self.resonance_dependency,
            "reflection_usefulness": self.reflection_usefulness,
            "adaptation_velocity": self.adaptation_velocity,
            "causal_consistency": self.causal_consistency,
            "confidence": self.confidence,
            "stability_impact": self.stability_impact,
            "coherence_impact": self.coherence_impact,
            "causal_trace_metadata": self.causal_trace_metadata,
            "rationale": self.rationale,
            "explanation": self.explanation,
            "epoch": self.epoch,
            "timestamp": self.timestamp,
        }


class GlobalCognitiveMetrics:
    """Unified consciousness telemetry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: GlobalCognitiveSnapshot | None = None

    def aggregate_metrics(self) -> dict[str, float]:
        coherence = _extract_metric(
            "modules.cognitive_coherence_engine", "get_cognitive_coherence_engine", "last_report.coherence_score", 0.7
        )
        stability_pressure = _extract_metric(
            "modules.recursive_stability_governor",
            "get_recursive_stability_governor",
            "last_report.stability_pressure",
            0.3,
        )
        identity = _extract_metric("modules.niblit_identity", "get_niblit_identity", "identity_drift_score", 0.2)
        governance_capture = _extract_metric(
            "modules.meta_governance_engine", "get_meta_governance_engine", "last_report.governance_capture_risk", 0.2
        )
        emergence = _extract_metric(
            "modules.emergence_monitor", "get_emergence_monitor", "last_report.emergence_index", 0.0
        )
        prediction = _extract_metric(
            "modules.reality_validation_engine", "get_reality_validation_engine", "last_report.reality_alignment", 0.6
        )
        reflection = _extract_metric("modules.reflection_engine", "get_reflection_engine", "quality_ema", 0.7)
        resonance_dependency = _extract_resonance_dependency()
        memory_integrity = _extract_metric(
            "niblit_memory.unified_memory_engine", "get_unified_memory", "total_records", 1.0
        )
        memory_integrity = min(
            1.0, float(memory_integrity) / 500.0 if memory_integrity > 1.0 else float(memory_integrity)
        )
        adaptation_velocity = _extract_metric(
            "modules.recursive_stability_governor",
            "get_recursive_stability_governor",
            "last_report.adaptation_velocity",
            0.3,
        )
        causal_consistency = _extract_metric(
            "modules.causal_temporal_engine", "get_causal_temporal_engine", "event_count", 1.0
        )
        causal_consistency = min(
            1.0, float(causal_consistency) / 200.0 if causal_consistency > 1.0 else float(causal_consistency)
        )

        metrics = {
            "coherence": float(coherence),
            "stability": max(0.0, 1.0 - float(stability_pressure)),
            "identity_integrity": max(0.0, 1.0 - float(identity)),
            "governance_health": max(0.0, 1.0 - float(governance_capture)),
            "emergence_index": float(emergence),
            "prediction_reliability": float(prediction),
            "memory_integrity": float(memory_integrity),
            "resonance_dependency": float(resonance_dependency),
            "reflection_usefulness": float(reflection),
            "adaptation_velocity": float(adaptation_velocity),
            "causal_consistency": float(causal_consistency),
        }
        return metrics

    def compute_global_health(self, metrics: dict[str, float]) -> float:
        positive = [
            metrics["coherence"],
            metrics["stability"],
            metrics["identity_integrity"],
            metrics["governance_health"],
            metrics["prediction_reliability"],
            metrics["memory_integrity"],
            metrics["reflection_usefulness"],
            metrics["causal_consistency"],
        ]
        negative = [metrics["emergence_index"], metrics["resonance_dependency"], metrics["adaptation_velocity"]]
        return max(0.0, min(1.0, (sum(positive) / len(positive)) - (sum(negative) / len(negative)) * 0.25))

    def generate_cognitive_report(self) -> dict[str, Any]:
        metrics = self.aggregate_metrics()
        health = self.compute_global_health(metrics)
        snapshot = GlobalCognitiveSnapshot(
            **metrics,
            confidence=health,
            stability_impact=metrics["stability"],
            coherence_impact=metrics["coherence"],
            causal_trace_metadata={"health": health},
            rationale="Global health computed from coherence, stability, identity, governance, and grounding metrics.",
            explanation="Unified telemetry generated for Ω.5 recursive cognition supervision.",
            epoch=_safe_epoch(),
        )
        with self._lock:
            self._snapshot = snapshot
        self._emit(snapshot)
        return snapshot.to_dict()

    # compatibility API
    def refresh(self) -> dict[str, float]:
        report = self.generate_cognitive_report()
        return {
            k: float(report[k])
            for k in (
                "coherence",
                "stability",
                "identity_integrity",
                "adaptation_velocity",
                "prediction_reliability",
                "governance_health",
                "memory_integrity",
                "emergence_index",
                "reflection_usefulness",
                "resonance_dependency",
                "causal_consistency",
            )
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "snapshot": self._snapshot.to_dict() if self._snapshot else None,
                "last_report": self._snapshot.to_dict() if self._snapshot else None,
                "metrics": self._snapshot.to_dict() if self._snapshot else {},
            }

    def _emit(self, snapshot: GlobalCognitiveSnapshot) -> None:
        try:
            from modules.event_bus import (
                EVENT_GLOBAL_COGNITIVE_UPDATE,
                EVENT_GLOBAL_METRICS_UPDATED,
                NiblitEvent,
                get_event_bus,
            )

            payload = snapshot.to_dict()
            bus = get_event_bus()
            bus.publish(
                NiblitEvent(type=EVENT_GLOBAL_COGNITIVE_UPDATE, source="global_cognitive_metrics", payload=payload)
            )
            bus.publish(
                NiblitEvent(type=EVENT_GLOBAL_METRICS_UPDATED, source="global_cognitive_metrics", payload=payload)
            )
        except Exception:
            pass


def _extract_metric(module_name: str, getter: str, key: str, fallback: float) -> float:
    try:
        mod = __import__(module_name, fromlist=[getter])
        obj = getattr(mod, getter)()
        st = obj.status() if hasattr(obj, "status") else {}
        if key.startswith("last_report."):
            lr = st.get("last_report") or st.get("snapshot") or {}
            return float(lr.get(key.split(".", 1)[1], fallback))
        return float(st.get(key, fallback))
    except Exception:
        return float(fallback)


def _extract_resonance_dependency() -> float:
    try:
        mod = __import__("nibblebots.system_interface_layer", fromlist=["get_system_interface_layer"])
        sil = mod.get_system_interface_layer()
        st = sil.status()
        count = st.get("profiles", 0) or len(st.get("authority_matrix", {}))
        return min(1.0, float(count) / 10.0)
    except Exception:
        return 0.0


def _safe_epoch() -> int:
    try:
        from modules.unified_cognitive_state import get_unified_state

        return int(get_unified_state().status().get("epoch", 0))
    except Exception:
        return 0


_gcm: GlobalCognitiveMetrics | None = None
_gcm_lock = threading.Lock()


def get_global_cognitive_metrics() -> GlobalCognitiveMetrics:
    global _gcm
    with _gcm_lock:
        if _gcm is None:
            _gcm = GlobalCognitiveMetrics()
    return _gcm
