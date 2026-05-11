#!/usr/bin/env python3
"""Phase Ω.5 Global Cognitive Metrics."""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional


class GlobalCognitiveMetrics:
    """Unified consciousness telemetry surface for Niblit."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._metrics: Dict[str, float] = {}
        self._updated_at = 0.0

    def refresh(self) -> Dict[str, float]:
        coherence = _extract_metric(
            "modules.cognitive_coherence_engine",
            "get_cognitive_coherence_engine",
            "last_report.coherence_score",
            fallback=0.7,
        )
        stability = _extract_metric(
            "modules.recursive_stability_governor",
            "get_recursive_stability_governor",
            "last_report.stability_pressure",
            fallback=0.0,
        )
        identity = _extract_metric(
            "modules.niblit_identity",
            "get_niblit_identity",
            "continuity_score",
            fallback=0.8,
        )
        prediction = _extract_metric(
            "modules.reality_validation_engine",
            "get_reality_validation_engine",
            "last_report.reality_score",
            fallback=0.5,
        )
        governance_sat = _extract_metric(
            "modules.meta_governance_engine",
            "get_meta_governance_engine",
            "last_report.governance_saturation",
            fallback=0.1,
        )
        emergence = _extract_metric(
            "modules.emergence_monitor",
            "get_emergence_monitor",
            "last_report.emergence_index",
            fallback=0.0,
        )
        reflection_use = _extract_metric(
            "modules.reflection_engine",
            "get_reflection_engine",
            "quality_ema",
            fallback=0.7,
        )
        memory_health = _extract_metric(
            "niblit_memory.unified_memory_engine",
            "get_unified_memory",
            "total_records",
            fallback=1.0,
        )
        memory_health = min(1.0, float(memory_health) / 500.0 if memory_health > 1 else float(memory_health))
        metrics = {
            "coherence": float(coherence),
            "stability": max(0.0, 1.0 - float(stability)),
            "identity_integrity": float(identity),
            "adaptation_velocity": float(stability),
            "prediction_reliability": float(prediction),
            "governance_saturation": float(governance_sat),
            "memory_health": float(memory_health),
            "emergence_index": float(emergence),
            "reflection_usefulness": float(reflection_use),
            "resonance_dependency": _extract_resonance_dependency(),
            "causal_calibration": float(prediction),
            "human_alignment_stability": _extract_metric(
                "modules.human_alignment_engine",
                "get_human_alignment_engine",
                "trust_level",
                fallback=0.7,
            ),
        }
        with self._lock:
            self._metrics = metrics
            self._updated_at = time.time()
        self._emit(metrics)
        return dict(metrics)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {"updated_at": self._updated_at, "metrics": dict(self._metrics)}

    def _emit(self, metrics: Dict[str, float]) -> None:
        try:
            from modules.event_bus import EVENT_GLOBAL_METRICS_UPDATED, NiblitEvent, get_event_bus

            get_event_bus().publish(
                NiblitEvent(
                    type=EVENT_GLOBAL_METRICS_UPDATED,
                    source="global_cognitive_metrics",
                    payload={"coherence": metrics.get("coherence", 0.0)},
                )
            )
        except Exception:
            pass


def _extract_metric(module_name: str, getter: str, key: str, fallback: float) -> float:
    try:
        mod = __import__(module_name, fromlist=[getter])
        obj = getattr(mod, getter)()
        st = obj.status() if hasattr(obj, "status") else {}
        if key.startswith("last_report."):
            lr = st.get("last_report") or {}
            return float(lr.get(key.split(".", 1)[1], fallback))
        return float(st.get(key, fallback))
    except Exception:
        return float(fallback)


def _extract_resonance_dependency() -> float:
    try:
        mod = __import__("nibblebots.system_interface_layer", fromlist=["get_system_interface_layer"])
        sil = mod.get_system_interface_layer()
        st = sil.status()
        profiles = st.get("profiles", 0) or len(st.get("authority_matrix", {}))
        return min(1.0, float(profiles) / 10.0)
    except Exception:
        return 0.0


_gcm: Optional[GlobalCognitiveMetrics] = None
_gcm_lock = threading.Lock()


def get_global_cognitive_metrics() -> GlobalCognitiveMetrics:
    global _gcm
    with _gcm_lock:
        if _gcm is None:
            _gcm = GlobalCognitiveMetrics()
    return _gcm
