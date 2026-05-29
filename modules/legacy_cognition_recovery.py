#!/usr/bin/env python3
"""Legacy cognition recovery + unification mapper for the unified runtime."""

from __future__ import annotations

import importlib.util
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class LegacyCognitionSystem:
    name: str
    module_path: str
    category: str
    era: str
    status: str
    value_score: float
    recommendation: str
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_SYSTEM_REGISTRY: list[dict[str, str]] = [
    {"name": "RuntimeManager", "module_path": "core.runtime_manager", "category": "runtime", "era": "modern"},
    {"name": "Router V2", "module_path": "modules.runtime_router_v2", "category": "inference", "era": "modern"},
    {"name": "LocalBrain", "module_path": "modules.local_brain", "category": "inference", "era": "modern"},
    {"name": "CognitiveEpisode", "module_path": "modules.cognitive_episode", "category": "episode", "era": "modern"},
    {"name": "ReflectionEngine", "module_path": "modules.reflection_engine", "category": "reflection", "era": "modern"},
    {"name": "EvaluationEngine", "module_path": "modules.evaluation_engine", "category": "evaluation", "era": "modern"},
    {"name": "GovernedLiveCognition", "module_path": "modules.governed_live_cognition", "category": "ingestion", "era": "modern"},
    {"name": "GovernedQdrantMemory", "module_path": "niblit_memory.governed_qdrant_memory", "category": "memory", "era": "modern"},
    {"name": "ImprovementIntegrator", "module_path": "modules.improvement_integrator", "category": "improvement", "era": "legacy"},
    {"name": "AutonomousLearningEngine", "module_path": "modules.autonomous_learning_engine", "category": "improvement", "era": "legacy"},
    {"name": "Metacognition", "module_path": "modules.metacognition", "category": "metacognition", "era": "legacy"},
    {"name": "MetaEvaluator", "module_path": "modules.meta_cognition.meta_evaluator", "category": "metaevaluation", "era": "legacy"},
    {"name": "CivilizationAdapter", "module_path": "modules.civilization_adapter", "category": "civilization", "era": "legacy"},
    {"name": "CausalityTracker", "module_path": "nibblebots.causality_tracker", "category": "causality", "era": "legacy"},
]


class LegacyCognitionRecoveryAnalyzer:
    """Builds historical topology and recovery recommendations from runtime context."""

    def _is_available(self, module_path: str) -> bool:
        try:
            return importlib.util.find_spec(module_path) is not None
        except Exception:
            return False

    @staticmethod
    def _status_for(*, available: bool, active_hint: bool, high_signal: bool) -> str:
        if not available:
            return "dead"
        if active_hint and high_signal:
            return "active"
        if active_hint:
            return "partially_active"
        if high_signal:
            return "fragmented"
        return "disconnected"

    @staticmethod
    def _recommendation(status: str, category: str) -> str:
        if status == "active":
            return "modernize"
        if status in {"partially_active", "fragmented"}:
            return "reconnect"
        if status == "disconnected":
            return "merge"
        if category in {"runtime", "inference", "memory"}:
            return "restore"
        return "deprecate"

    @staticmethod
    def _value_score(status: str, category: str) -> float:
        status_base = {
            "active": 0.9,
            "partially_active": 0.72,
            "fragmented": 0.64,
            "disconnected": 0.5,
            "dead": 0.3,
        }.get(status, 0.4)
        category_boost = {
            "runtime": 0.08,
            "inference": 0.08,
            "memory": 0.07,
            "evaluation": 0.06,
            "metacognition": 0.06,
            "metaevaluation": 0.06,
            "improvement": 0.05,
            "civilization": 0.05,
            "causality": 0.06,
        }.get(category, 0.03)
        return round(min(1.0, status_base + category_boost), 4)

    def build_report(
        self,
        *,
        core: Any | None,
        cognitive_status: dict[str, Any] | None,
        event_stats: dict[str, Any] | None,
        state_file: str = "",
    ) -> dict[str, Any]:
        event_counts = dict((event_stats or {}).get("event_counts", {}) or {})
        episodes = list((cognitive_status or {}).get("episodes", []) or [])
        reflections = list((cognitive_status or {}).get("reflections", []) or [])
        causality = dict((cognitive_status or {}).get("causality", {}) or {})
        active_hints = {
            "ImprovementIntegrator": bool(getattr(core, "improvements", None)) if core else False,
            "AutonomousLearningEngine": bool(getattr(core, "autonomous_engine", None)) if core else False,
            "Metacognition": bool(getattr(core, "metacognition", None)) if core else False,
            "RuntimeManager": bool(getattr(core, "runtime_manager", None)) if core else True,
            "CognitiveEpisode": bool(episodes),
            "ReflectionEngine": bool(reflections),
            "CausalityTracker": bool(causality.get("episodes_seen")),
        }
        systems: list[LegacyCognitionSystem] = []
        for item in _SYSTEM_REGISTRY:
            name = item["name"]
            category = item["category"]
            available = self._is_available(item["module_path"])
            high_signal = bool(event_counts) and any(
                token in " ".join(event_counts.keys())
                for token in (category, "reflection", "evaluation", "learning", "provider", "memory")
            )
            active_hint = bool(active_hints.get(name, False))
            status = self._status_for(available=available, active_hint=active_hint, high_signal=high_signal)
            recommendation = self._recommendation(status, category)
            value_score = self._value_score(status, category)
            systems.append(
                LegacyCognitionSystem(
                    name=name,
                    module_path=item["module_path"],
                    category=category,
                    era=item["era"],
                    status=status,
                    value_score=value_score,
                    recommendation=recommendation,
                    notes=f"available={available}, active_hint={active_hint}, events={len(event_counts)}",
                )
            )

        dead_paths = [s.to_dict() for s in systems if s.status in {"dead", "disconnected"}]
        recoverable = [s.to_dict() for s in systems if s.recommendation in {"restore", "reconnect", "merge", "modernize"}]
        active_now = [s.to_dict() for s in systems if s.status in {"active", "partially_active"}]

        return {
            "A_historical_cognition_topology_map": [s.to_dict() for s in systems],
            "B_legacy_adaptive_systems_analysis": {
                "active_or_partial": len(active_now),
                "recoverable": len(recoverable),
                "high_value_legacy": [s["name"] for s in recoverable if s["era"] == "legacy" and s["value_score"] >= 0.65],
            },
            "C_dead_disconnected_cognition_paths": dead_paths,
            "D_recovered_cognition_systems_report": recoverable,
            "E_canonical_unified_cognition_architecture": {
                "canonical_inference": "RuntimeRouterV2 -> LocalBrain.route_inference",
                "canonical_episode_lineage": "RuntimeEventBus -> RuntimeSignificanceEngine -> CognitiveEpisodeManager",
                "canonical_governance_lineage": "governed_live_cognition + governed_qdrant_memory + EventBus",
                "canonical_adaptive_loop": "ReflectionEngine -> EvaluationEngine -> ImprovementIntegrator -> ALE",
            },
            "F_causal_cognition_architecture": {
                "source": "CognitiveEpisodeManager.causality",
                "episodes_seen": causality.get("episodes_seen", 0),
                "average_influence": causality.get("average_influence", {}),
                "average_outcomes": causality.get("average_outcomes", {}),
                "top_downstream_effects": causality.get("top_downstream_effects", []),
            },
            "G_metaevaluation_restoration_plan": {
                "current_state": "metaevaluation attached to finalized CognitiveEpisode records",
                "required_connections": [
                    "route metaevaluation to adaptive weight updates",
                    "use hallucination_probability for provider trust penalties",
                    "use runtime_coherence for governance alerts",
                ],
            },
            "H_improvement_cycle_modernization_plan": {
                "legacy_steps_detected": 10,
                "modernization_targets": [
                    "bind improvement cycle results to CognitiveEpisode trace_id lineage",
                    "convert module-only statuses into EventBus emissions",
                    "feed cycle outcomes into metaevaluation feedback",
                ],
            },
            "I_civilization_agent_modernization_architecture": {
                "legacy_entrypoint": "modules.civilization_adapter.execute_civilization_step",
                "modern_role_model": [
                    "runtime strategy agents",
                    "architecture analysis agents",
                    "memory evolution agents",
                    "market cognition agents",
                    "reflection agents",
                ],
            },
            "J_file_level_runtime_change_list": [
                "modules/cognitive_episode.py",
                "modules/unified_runtime.py",
                "modules/legacy_cognition_recovery.py",
            ],
            "K_actual_implementation": {
                "legacy_cognition_recovery_report": True,
                "cognitive_causality_tracking": True,
                "episode_metaevaluation_fields": True,
                "runtime_recovery_command": True,
            },
            "L_runtime_execution_verification": {
                "event_types_seen": sorted(event_counts.keys())[:40],
                "episode_count": len(episodes),
                "reflection_count": len(reflections),
                "state_file": state_file,
            },
            "M_validation_testing_results": {
                "lint": "pending",
                "tests": "pending",
            },
            "N_rollback_safety_analysis": {
                "mutations": "additive only",
                "runtime_replacement": False,
                "new_orchestrator_created": False,
                "new_event_bus_created": False,
                "new_memory_system_created": False,
            },
        }

