#!/usr/bin/env python3
"""Phase Ω.5 Cognitive Coherence Engine."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_STATE_PATH = Path(__file__).resolve().parent.parent / "cognitive_coherence_state.json"


@dataclass
class CoherenceReport:
    coherence_score: float
    contradiction_count: int
    fragmentation_score: float
    recursive_instability: float
    subsystem_alignment: dict[str, float]
    contradiction_vectors: list[dict[str, Any]]
    unstable_clusters: list[str]
    rationale: str
    confidence: float
    stability_impact: float
    coherence_impact: float
    causal_trace_metadata: dict[str, Any]
    explanation: str
    epoch: int
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "coherence_score": round(self.coherence_score, 4),
            "contradiction_count": self.contradiction_count,
            "fragmentation_score": round(self.fragmentation_score, 4),
            "recursive_instability": round(self.recursive_instability, 4),
            "subsystem_alignment": {k: round(v, 4) for k, v in self.subsystem_alignment.items()},
            "contradiction_vectors": list(self.contradiction_vectors),
            "unstable_clusters": list(self.unstable_clusters),
            "rationale": self.rationale,
            "confidence": round(self.confidence, 4),
            "stability_impact": round(self.stability_impact, 4),
            "coherence_impact": round(self.coherence_impact, 4),
            "causal_trace_metadata": dict(self.causal_trace_metadata),
            "explanation": self.explanation,
            "epoch": self.epoch,
            "timestamp": self.timestamp,
        }


class CognitiveCoherenceEngine:
    """Detect and prevent internal cognitive fragmentation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_report: CoherenceReport | None = None
        self._run_count = 0
        self._load_state()

    def analyze(self) -> CoherenceReport:
        state = self._collect_state()
        contradiction_vectors = self.detect_contradictions(state)
        alignment = self.measure_goal_alignment(state)
        recursive_instability = self.detect_recursive_feedback_loops(state)
        fragmentation_map, unstable_clusters = self.identify_fragmentation_clusters(state)
        coherence_score = self.compute_global_coherence(
            contradiction_vectors=contradiction_vectors,
            alignment=alignment,
            recursive_instability=recursive_instability,
            fragmentation_map=fragmentation_map,
        )
        fragmentation_score = sum(fragmentation_map.values()) / max(1, len(fragmentation_map))
        report = CoherenceReport(
            coherence_score=coherence_score,
            contradiction_count=len(contradiction_vectors),
            fragmentation_score=fragmentation_score,
            recursive_instability=recursive_instability,
            subsystem_alignment=alignment,
            contradiction_vectors=contradiction_vectors,
            unstable_clusters=unstable_clusters,
            rationale=self._rationale(coherence_score, contradiction_vectors, unstable_clusters),
            confidence=max(0.0, min(1.0, 1.0 - fragmentation_score)),
            stability_impact=max(0.0, min(1.0, 1.0 - recursive_instability)),
            coherence_impact=coherence_score,
            causal_trace_metadata={
                "phase": "omega_5",
                "contradiction_sources": [v.get("type", "unknown") for v in contradiction_vectors],
            },
            explanation="Subsystem cross-check complete with constitutional and temporal context.",
            epoch=int(state.get("epoch", 0)),
        )
        with self._lock:
            self._last_report = report
            self._run_count += 1
            self._save_state()
        self._emit(report)
        return report

    def detect_contradictions(self, state: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        governance = state.get("governance", {})
        reflection = state.get("reflection_engine", {})
        world = state.get("predictive_world_model", {})
        identity = state.get("niblit_identity", {})
        human = state.get("human_alignment_engine", {})

        if governance.get("suppressed_exploration_rate", 0.0) < 0.1 and world.get("last_regime") == "volatile":
            out.append({"type": "opposing_governance_directives", "detail": "volatile_without_suppression"})
        if reflection.get("quality_ema", 1.0) > 0.8 and human.get("trust_level", 1.0) < 0.35:
            out.append({"type": "reflection_vs_reality_mismatch", "detail": "internal_high_external_low"})
        if identity.get("identity_drift_score", 0.0) > 0.6:
            out.append({"type": "identity_inconsistency", "detail": "high_drift"})
        if state.get("event_bus_stats", {}).get("governance.adapted", 0) > 20 and state.get("event_bus_stats", {}).get("reflection.complete", 0) > 20:
            out.append({"type": "unstable_adaptation_cycles", "detail": "high_loop_volume"})
        if state.get("constitutional_layer", {}).get("block_count", 0) > state.get("constitutional_layer", {}).get("validation_count", 1) * 0.6:
            out.append({"type": "conflicting_goals", "detail": "constitutional_block_dominance"})
        return out

    def measure_goal_alignment(self, state: dict[str, Any]) -> dict[str, float]:
        baseline = 1.0
        constitution = state.get("constitutional_layer", {})
        unified = state.get("unified_cognitive_state", {})
        identity = state.get("niblit_identity", {})
        planner = state.get("strategic_planner", {})
        model_ecology = state.get("model_ecology", {})
        return {
            "constitutional_layer": max(0.0, baseline - min(0.6, constitution.get("block_count", 0) * 0.05)),
            "unified_cognitive_state": 0.7 if unified.get("key_count", 0) >= 5 else 0.4,
            "niblit_identity": float(identity.get("continuity_score", 0.8)),
            "strategic_planner": float(planner.get("plan_count", 1) > 0) * 0.8 + 0.2,
            "model_ecology": 0.8 if model_ecology.get("model_count", 1) >= 1 else 0.5,
        }

    def detect_recursive_feedback_loops(self, state: dict[str, Any]) -> float:
        stats = state.get("event_bus_stats", {})
        r = float(stats.get("reflection.complete", 0))
        g = float(stats.get("governance.adapted", 0))
        p = float(stats.get("world_model.updated", 0))
        if min(r, g, p) <= 0:
            return 0.0
        skew = max(r, g, p) / max(1.0, min(r, g, p))
        volume = min(1.0, (r + g + p) / 90.0)
        return max(0.0, min(1.0, (skew - 1.0) / 4.0 + 0.5 * volume))

    def identify_fragmentation_clusters(self, state: dict[str, Any]) -> tuple[dict[str, float], list[str]]:
        reflection_q = float(state.get("reflection_engine", {}).get("quality_ema", 0.7))
        mapping: dict[str, float] = {}
        for name in (
            "constitutional_layer",
            "predictive_world_model",
            "human_alignment_engine",
            "model_ecology",
            "self_model",
            "strategic_planner",
            "governance",
        ):
            s = state.get(name, {})
            local = s.get("overall_health") or s.get("quality_ema") or s.get("trust_level") or s.get("continuity_score") or 0.7
            mapping[name] = min(1.0, abs(float(local) - reflection_q))
        return mapping, [k for k, v in mapping.items() if v >= 0.55]

    def compute_global_coherence(
        self,
        contradiction_vectors: list[dict[str, Any]],
        alignment: dict[str, float],
        recursive_instability: float,
        fragmentation_map: dict[str, float],
    ) -> float:
        align_score = sum(alignment.values()) / max(1, len(alignment))
        contradiction_penalty = 0.12 * len(contradiction_vectors)
        fragmentation_penalty = 0.25 * (sum(fragmentation_map.values()) / max(1, len(fragmentation_map)))
        score = align_score - contradiction_penalty - fragmentation_penalty - 0.2 * recursive_instability
        return max(0.0, min(1.0, score))

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "run_count": self._run_count,
                "last_report": self._last_report.to_dict() if self._last_report else None,
                "confidence": self._last_report.confidence if self._last_report else 0.0,
                "stability_impact": self._last_report.stability_impact if self._last_report else 0.0,
                "coherence_impact": self._last_report.coherence_impact if self._last_report else 0.0,
                "causal_trace_metadata": self._last_report.causal_trace_metadata if self._last_report else {},
                "rationale": self._last_report.rationale if self._last_report else "not_initialized",
            }

    def _collect_state(self) -> dict[str, Any]:
        st: dict[str, Any] = {
            "constitutional_layer": _safe_status("modules.constitutional_layer", "get_constitutional_layer"),
            "unified_cognitive_state": _safe_status("modules.unified_cognitive_state", "get_unified_state"),
            "reflection_engine": _safe_status("modules.reflection_engine", "get_reflection_engine"),
            "predictive_world_model": _safe_status("modules.predictive_world_model", "get_predictive_world_model"),
            "human_alignment_engine": _safe_status("modules.human_alignment_engine", "get_human_alignment_engine"),
            "model_ecology": _safe_status("modules.model_ecology", "get_model_ecology"),
            "strategic_planner": _safe_status("modules.deliberative_planner", "get_deliberative_planner"),
            "self_model": _safe_status("modules.self_model", "get_self_model"),
            "niblit_identity": _safe_status("modules.niblit_identity", "get_niblit_identity"),
            "governance": _safe_status("nibblebots.governance_evolution_engine", "get_governance_engine"),
            "event_bus_stats": _safe_event_stats(),
        }
        st["epoch"] = st.get("unified_cognitive_state", {}).get("epoch", 0)
        return st

    def _rationale(self, score: float, contradictions: list[dict[str, Any]], unstable: list[str]) -> str:
        if score < 0.4:
            return f"Low coherence due to contradictions={len(contradictions)} unstable_clusters={len(unstable)}"
        if contradictions:
            return f"Moderate coherence with contradictions={len(contradictions)}"
        return "High coherence; subsystem alignment remains stable."

    def _emit(self, report: CoherenceReport) -> None:
        try:
            from modules.event_bus import (
                EVENT_COHERENCE_ANALYZED,
                EVENT_COHERENCE_EVALUATED,
                NiblitEvent,
                get_event_bus,
            )

            bus = get_event_bus()
            payload = {
                "coherence_score": report.coherence_score,
                "contradiction_count": report.contradiction_count,
                "confidence": report.confidence,
                "stability_impact": report.stability_impact,
                "coherence_impact": report.coherence_impact,
                "causal_trace_metadata": report.causal_trace_metadata,
                "rationale": report.rationale,
                "epoch": report.epoch,
            }
            bus.publish(NiblitEvent(type=EVENT_COHERENCE_ANALYZED, source="cognitive_coherence_engine", payload=payload))
            bus.publish(NiblitEvent(type=EVENT_COHERENCE_EVALUATED, source="cognitive_coherence_engine", payload=payload))
        except Exception:
            pass

    def _save_state(self) -> None:
        try:
            data = {"run_count": self._run_count, "last_report": self._last_report.to_dict() if self._last_report else None}
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
        except Exception:
            pass


def _safe_status(module_name: str, getter: str) -> dict[str, Any]:
    try:
        mod = __import__(module_name, fromlist=[getter])
        obj = getattr(mod, getter)()
        if hasattr(obj, "status"):
            return obj.status()
    except Exception:
        return {}
    return {}


def _safe_event_stats() -> dict[str, int]:
    try:
        from modules.event_bus import get_event_bus

        return get_event_bus().stats()
    except Exception:
        return {}


_coherence_engine: CognitiveCoherenceEngine | None = None
_coherence_lock = threading.Lock()


def get_cognitive_coherence_engine() -> CognitiveCoherenceEngine:
    global _coherence_engine
    with _coherence_lock:
        if _coherence_engine is None:
            _coherence_engine = CognitiveCoherenceEngine()
    return _coherence_engine
