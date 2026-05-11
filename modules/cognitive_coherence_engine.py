#!/usr/bin/env python3
"""Phase Ω.5 Cognitive Coherence Engine."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


@dataclass
class CoherenceReport:
    coherence_score: float
    contradiction_vectors: List[str]
    instability_clusters: List[str]
    subsystem_divergence_map: Dict[str, float]
    recursive_amplification_warnings: List[str]
    goal_alignment_score: float
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "coherence_score": round(self.coherence_score, 4),
            "contradiction_vectors": list(self.contradiction_vectors),
            "instability_clusters": list(self.instability_clusters),
            "subsystem_divergence_map": {
                k: round(v, 4) for k, v in self.subsystem_divergence_map.items()
            },
            "recursive_amplification_warnings": list(self.recursive_amplification_warnings),
            "goal_alignment_score": round(self.goal_alignment_score, 4),
            "timestamp": self.timestamp,
        }


class CognitiveCoherenceEngine:
    """Measures whether major subsystems share a consistent internal reality."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_report: Optional[CoherenceReport] = None
        self._run_count = 0

    def analyze(self) -> CoherenceReport:
        state = self._collect_state()
        contradictions = self.detect_contradictions(state)
        goal_alignment = self.measure_goal_alignment(state)
        warnings = self.detect_recursive_feedback_loops(state)
        divergence = self.identify_cognitive_fragmentation(state)
        instability = [k for k, v in divergence.items() if v > 0.6]
        coherence = self.compute_global_coherence(
            contradictions=contradictions,
            warnings=warnings,
            divergence=divergence,
            goal_alignment=goal_alignment,
        )
        report = CoherenceReport(
            coherence_score=coherence,
            contradiction_vectors=contradictions,
            instability_clusters=instability,
            subsystem_divergence_map=divergence,
            recursive_amplification_warnings=warnings,
            goal_alignment_score=goal_alignment,
        )
        with self._lock:
            self._last_report = report
            self._run_count += 1
        self._emit(report)
        return report

    def detect_contradictions(self, state: Dict[str, Any]) -> List[str]:
        issues: List[str] = []
        reflection = state.get("reflection_engine", {})
        governance = state.get("governance", {})
        world = state.get("predictive_world_model", {})
        human = state.get("human_alignment_engine", {})
        if reflection.get("quality_ema", 1.0) < 0.4 and governance.get("stability_preservation_score", 1.0) > 0.8:
            issues.append("reflection_low_quality_vs_governance_high_stability")
        if world.get("last_regime") == "volatile" and governance.get("suppressed_exploration_rate", 0.0) < 0.1:
            issues.append("volatile_regime_without_exploration_suppression")
        if human.get("trust_level", 1.0) < 0.35 and reflection.get("quality_ema", 1.0) > 0.8:
            issues.append("high_internal_quality_vs_low_human_trust")
        return issues

    def measure_goal_alignment(self, state: Dict[str, Any]) -> float:
        constitution = state.get("constitutional_layer", {})
        identity = state.get("niblit_identity", {})
        coherence = state.get("unified_cognitive_state", {})
        score = 1.0
        if constitution.get("block_count", 0) > constitution.get("validation_count", 1) * 0.4:
            score -= 0.2
        if identity.get("continuity_score", 1.0) < 0.6:
            score -= 0.2
        if coherence.get("key_count", 0) < 5:
            score -= 0.1
        return max(0.0, min(1.0, score))

    def detect_recursive_feedback_loops(self, state: Dict[str, Any]) -> List[str]:
        warnings: List[str] = []
        stats = state.get("event_bus_stats", {})
        r = stats.get("reflection.complete", 0)
        g = stats.get("governance.adapted", 0)
        w = stats.get("world_model.updated", 0)
        if r > 0 and g > 0 and w > 0:
            dominant = max(r, g, w) / max(1, min(r, g, w))
            if dominant > 3:
                warnings.append("asymmetric_feedback_amplification")
        if r > 20 and g > 20:
            warnings.append("reflection_governance_loop_pressure")
        return warnings

    def compute_global_coherence(
        self,
        contradictions: List[str],
        warnings: List[str],
        divergence: Dict[str, float],
        goal_alignment: float,
    ) -> float:
        penalty = len(contradictions) * 0.12 + len(warnings) * 0.08
        if divergence:
            penalty += sum(divergence.values()) / len(divergence) * 0.25
        score = goal_alignment - penalty
        return max(0.0, min(1.0, score))

    def identify_cognitive_fragmentation(self, state: Dict[str, Any]) -> Dict[str, float]:
        result: Dict[str, float] = {}
        baseline = state.get("reflection_engine", {}).get("quality_ema", 0.7)
        comps = [
            "constitutional_layer",
            "predictive_world_model",
            "human_alignment_engine",
            "model_ecology",
            "self_model",
            "governance",
        ]
        for name in comps:
            st = state.get(name, {})
            if isinstance(st, dict):
                local = (
                    st.get("overall_health")
                    or st.get("quality_ema")
                    or st.get("trust_level")
                    or st.get("continuity_score")
                    or 0.7
                )
                result[name] = min(1.0, abs(float(local) - float(baseline)))
        return result

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "run_count": self._run_count,
                "last_report": self._last_report.to_dict() if self._last_report else None,
            }

    def _collect_state(self) -> Dict[str, Any]:
        state: Dict[str, Any] = {}
        state["constitutional_layer"] = _safe_status("modules.constitutional_layer", "get_constitutional_layer")
        state["unified_cognitive_state"] = _safe_status("modules.unified_cognitive_state", "get_unified_state")
        state["reflection_engine"] = _safe_status("modules.reflection_engine", "get_reflection_engine")
        state["predictive_world_model"] = _safe_status("modules.predictive_world_model", "get_predictive_world_model")
        state["human_alignment_engine"] = _safe_status("modules.human_alignment_engine", "get_human_alignment_engine")
        state["model_ecology"] = _safe_status("modules.model_ecology", "get_model_ecology")
        state["self_model"] = _safe_status("modules.self_model", "get_self_model")
        state["niblit_identity"] = _safe_status("modules.niblit_identity", "get_niblit_identity")
        state["governance"] = _safe_status("nibblebots.governance_evolution_engine", "get_governance_engine")
        state["event_bus_stats"] = _safe_event_stats()
        return state

    def _emit(self, report: CoherenceReport) -> None:
        try:
            from modules.event_bus import (
                EVENT_COHERENCE_EVALUATED,
                NiblitEvent,
                get_event_bus,
            )

            get_event_bus().publish(
                NiblitEvent(
                    type=EVENT_COHERENCE_EVALUATED,
                    source="cognitive_coherence_engine",
                    payload={
                        "coherence_score": report.coherence_score,
                        "contradictions": len(report.contradiction_vectors),
                    },
                )
            )
        except Exception:
            pass


def _safe_status(module_name: str, getter: str) -> Dict[str, Any]:
    try:
        mod = __import__(module_name, fromlist=[getter])
        obj = getattr(mod, getter)()
        if hasattr(obj, "status"):
            return obj.status()
    except Exception:
        return {}
    return {}


def _safe_event_stats() -> Dict[str, int]:
    try:
        from modules.event_bus import get_event_bus

        return get_event_bus().stats()
    except Exception:
        return {}


_coherence_engine: Optional[CognitiveCoherenceEngine] = None
_coherence_lock = threading.Lock()


def get_cognitive_coherence_engine() -> CognitiveCoherenceEngine:
    global _coherence_engine
    with _coherence_lock:
        if _coherence_engine is None:
            _coherence_engine = CognitiveCoherenceEngine()
    return _coherence_engine

