#!/usr/bin/env python3
"""Additive unified foundation architecture for the Niblit runtime."""

from __future__ import annotations

import threading
import time
from typing import Any


class FoundationArchitecture:
    """Composes existing runtime subsystems into one explainable foundation."""

    COGNITIVE_LOOP = [
        "request",
        "intent_analysis",
        "planning",
        "reasoning",
        "execution",
        "observation",
        "reflection",
        "knowledge_extraction",
        "knowledge_validation",
        "knowledge_storage",
        "understanding_update",
        "structural_awareness_update",
        "future_decision_improvement",
    ]
    KNOWLEDGE_PIPELINE = [
        "capture",
        "parsing",
        "semantic_understanding",
        "reflection",
        "validation",
        "knowledge_extraction",
        "relationship_detection",
        "confidence_scoring",
        "knowledge_graph",
        "knowledge_db",
        "retrieval_index",
    ]
    SELF_STUDY_SOURCES = [
        "documentation",
        "pdfs",
        "source_code",
        "internet_research",
        "market_reports",
        "financial_data",
        "runtime_history",
        "previous_mistakes",
    ]

    def __init__(
        self,
        *,
        runtime_id: str = "",
        persistence_manager: Any | None = None,
        architecture_model: Any | None = None,
    ) -> None:
        self.runtime_id = runtime_id or "niblit-foundation"
        self._lock = threading.RLock()
        self._persistence_manager = persistence_manager
        self._architecture_model = architecture_model
        self._dialogue: list[dict[str, Any]] = []
        self._understanding: dict[str, dict[str, Any]] = {}
        self._governance_proposals: list[dict[str, Any]] = []
        self._event_count = 0
        self._last_event: dict[str, Any] = {}
        self._last_model_selection: dict[str, Any] = {}
        self._study_objectives: list[str] = []
        self._knowledge_gaps: list[str] = []

    def observe_event(self, event: Any) -> None:
        event_dict = self._normalize_event(event)
        payload = dict(event_dict.get("payload", {}) or {})
        with self._lock:
            self._event_count += 1
            self._last_event = event_dict
            self._append_dialogue(event_dict, payload)
            self._update_understanding(event_dict, payload)
            self._update_governance(payload)
            self._update_study_objectives(payload)
        self._persist()

    def record_model_selection(self, selection: dict[str, Any]) -> None:
        with self._lock:
            self._last_model_selection = dict(selection or {})
        self._persist()

    def status(
        self,
        *,
        provider_status: dict[str, Any] | None = None,
        event_stats: dict[str, Any] | None = None,
        cognitive_status: dict[str, Any] | None = None,
        market_status: dict[str, Any] | None = None,
        runtime_health: dict[str, Any] | None = None,
        local_brain_status: dict[str, Any] | None = None,
        architecture_status: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        provider_status = dict(provider_status or {})
        event_stats = dict(event_stats or {})
        cognitive_status = dict(cognitive_status or {})
        market_status = dict(market_status or {})
        runtime_health = dict(runtime_health or {})
        local_brain_status = dict(local_brain_status or {})
        architecture_status = dict(architecture_status or self._architecture_status())
        with self._lock:
            understanding_entries = list(self._understanding.values())
            reflections = list(cognitive_status.get("reflections", []) or [])
            model_manager = self._build_model_manager(provider_status, local_brain_status)
            memory_layers = self._build_memory_layers(cognitive_status, market_status, architecture_status)
            status = {
                "runtime_engineering": {
                    "runtime_id": self.runtime_id,
                    "persistence_first": True,
                    "event_bus_only": True,
                    "lifecycle_state": runtime_health.get("runtime_state") or provider_status.get("runtime_state") or "ready",
                    "health_monitoring": bool(runtime_health) or bool(event_stats),
                    "automatic_recovery": True,
                    "graceful_degradation": True,
                },
                "cognitive_loop": {
                    "phases": list(self.COGNITIVE_LOOP),
                    "unified_feedback_path": True,
                    "last_trace_id": (self._last_event.get("payload", {}) or {}).get("trace_id", ""),
                },
                "memory_layers": memory_layers,
                "knowledge_processing": {
                    "pipeline": list(self.KNOWLEDGE_PIPELINE),
                    "raw_information_persisted": False,
                },
                "understanding_layer": {
                    "concept_count": len(understanding_entries),
                    "concepts": understanding_entries[-25:],
                },
                "niblit_brain": {
                    "identity_source": "accumulated_knowledge_and_reflection",
                    "reflection_count": len(reflections),
                    "historical_reasoning_available": len(reflections) > 0,
                },
                "local_brain": {
                    "role": "language_reasoning",
                    "persistent_identity": False,
                    "status": local_brain_status,
                },
                "model_manager": model_manager,
                "event_bus": {
                    "authoritative": True,
                    "event_count": self._event_count,
                    "observability": event_stats,
                    "last_event_provenance": self._provenance_snapshot(self._last_event),
                },
                "runtime_dialogue": self.runtime_dialogue(limit=25),
                "self_study": {
                    "continuous": True,
                    "sources": list(self.SELF_STUDY_SOURCES),
                    "knowledge_gaps": list(self._knowledge_gaps[-10:]),
                    "future_learning_objectives": list(self._study_objectives[-10:]),
                },
                "trading_intelligence": {
                    "participates_in_unified_loop": True,
                    "market_memory_persistent": True,
                    "status": market_status,
                },
                "reflection": {
                    "permanent_knowledge": True,
                    "reflection_count": len(reflections),
                    "latest": reflections[-1] if reflections else {},
                },
                "structural_awareness": {
                    "self_model_enabled": True,
                    "architecture_status": architecture_status,
                },
                "governance": {
                    "protected_core_safety": True,
                    "proposals": list(self._governance_proposals[-10:]),
                },
            }
        return status

    def runtime_dialogue(self, *, limit: int = 25) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._dialogue[-max(1, limit):])

    def _append_dialogue(self, event_dict: dict[str, Any], payload: dict[str, Any]) -> None:
        entry = {
            "timestamp": event_dict.get("timestamp") or payload.get("timestamp") or time.time(),
            "sender": event_dict.get("source", "unknown"),
            "receiver": payload.get("receiver") or payload.get("selected_module") or payload.get("provider") or "",
            "module": payload.get("source_module") or event_dict.get("source", "unknown"),
            "function": payload.get("selected_function") or payload.get("function") or "",
            "event_type": event_dict.get("type", "runtime.event"),
            "input": payload.get("input") or payload.get("query") or payload.get("command") or payload.get("topic") or "",
            "output": payload.get("output") or payload.get("response") or payload.get("summary") or payload.get("reflection_summary") or "",
            "duration_ms": payload.get("execution_duration_ms") or payload.get("elapsed_ms"),
            "confidence": payload.get("confidence") or payload.get("confidence_score") or payload.get("evaluation_score"),
            "trace_id": payload.get("trace_id", ""),
        }
        self._dialogue.append(entry)
        if len(self._dialogue) > 250:
            self._dialogue[:] = self._dialogue[-250:]

    def _update_understanding(self, event_dict: dict[str, Any], payload: dict[str, Any]) -> None:
        concept = str(
            payload.get("topic")
            or payload.get("intent")
            or payload.get("selected_module")
            or payload.get("provider")
            or event_dict.get("type")
            or "runtime"
        ).strip()
        if not concept:
            return
        record = self._understanding.setdefault(
            concept,
            {
                "concept": concept,
                "understanding_score": 0.5,
                "confidence": 0.5,
                "supporting_evidence": [],
                "contradictions": [],
                "related_concepts": [],
                "runtime_usage": 0,
                "reflection_count": 0,
                "successful_predictions": 0,
                "failed_predictions": 0,
                "last_validation": None,
                "applicability": payload.get("event_category") or "runtime",
                "limitations": [],
            },
        )
        record["runtime_usage"] += 1
        score = float(payload.get("quality_score", payload.get("evaluation_score", payload.get("confidence_score", 0.5))) or 0.5)
        record["confidence"] = round(max(0.0, min(1.0, (record["confidence"] * 0.7) + (score * 0.3))), 3)
        record["understanding_score"] = round(max(0.0, min(1.0, (record["understanding_score"] * 0.6) + (score * 0.4))), 3)
        evidence = payload.get("summary") or payload.get("response") or event_dict.get("type", "")
        if evidence and evidence not in record["supporting_evidence"]:
            record["supporting_evidence"].append(str(evidence)[:240])
            record["supporting_evidence"] = record["supporting_evidence"][-5:]
        related = [
            value for value in [payload.get("provider"), payload.get("selected_module"), payload.get("target_module")]
            if value and value != concept
        ]
        for item in related:
            if item not in record["related_concepts"]:
                record["related_concepts"].append(str(item))
        record["related_concepts"] = record["related_concepts"][-8:]
        if payload.get("contradictions"):
            contradictions = payload.get("contradictions") or []
            for item in contradictions:
                summary = item.get("summary") if isinstance(item, dict) else str(item)
                if summary and summary not in record["contradictions"]:
                    record["contradictions"].append(str(summary)[:180])
            record["failed_predictions"] += len(contradictions)
        if "reflection" in str(event_dict.get("type", "")):
            record["reflection_count"] += 1
        if score >= 0.65:
            record["successful_predictions"] += 1
        else:
            record["failed_predictions"] += 1
        record["last_validation"] = payload.get("timestamp") or time.time()

    def _update_governance(self, payload: dict[str, Any]) -> None:
        proposals = list(payload.get("adaptation_proposals", []) or [])
        if not proposals:
            return
        for proposal in proposals:
            self._governance_proposals.append(
                {
                    "proposal": proposal,
                    "status": "recorded_for_governance",
                    "requires_validation": True,
                }
            )
        self._governance_proposals[:] = self._governance_proposals[-100:]

    def _update_study_objectives(self, payload: dict[str, Any]) -> None:
        gaps = []
        if payload.get("contradictions"):
            gaps.append("resolve_contradictions")
        if payload.get("evaluation_score", 1.0) < 0.55:
            gaps.append("improve_low_confidence_reasoning")
        if payload.get("knowledge_gap"):
            gaps.append(str(payload.get("knowledge_gap")))
        for gap in gaps:
            if gap not in self._knowledge_gaps:
                self._knowledge_gaps.append(gap)
        for gap in self._knowledge_gaps[-5:]:
            objective = f"study:{gap}"
            if objective not in self._study_objectives:
                self._study_objectives.append(objective)

    def _build_model_manager(self, provider_status: dict[str, Any], local_brain_status: dict[str, Any]) -> dict[str, Any]:
        manager_status = dict(provider_status.get("manager_status", {}) or {})
        available = []
        for name in ["qwen", "llama3", "hf", "anthropic", "ruflo", "openai_compatible"]:
            if provider_status.get(name) or manager_status.get(name):
                available.append(name)
        return {
            "all_interactions_routed": True,
            "registered_models": available,
            "active_model": provider_status.get("active_provider") or manager_status.get("active") or "",
            "last_selection": dict(self._last_model_selection),
            "latency_tracking": dict(manager_status.get("provider_metrics", {})),
            "confidence_tracking": dict(manager_status.get("provider_rankings", {})),
            "local_brain": local_brain_status,
        }

    def _build_memory_layers(
        self,
        cognitive_status: dict[str, Any],
        market_status: dict[str, Any],
        architecture_status: dict[str, Any],
    ) -> dict[str, Any]:
        reflections = list(cognitive_status.get("reflections", []) or [])
        episodes = list(cognitive_status.get("episodes", []) or [])
        datasets = dict(cognitive_status.get("datasets", {}) or {})
        return {
            "runtime_state": {"persistent": False, "entries": len(cognitive_status.get("active_sessions", []) or [])},
            "working_memory": {"persistent": False, "entries": len(episodes[-10:])},
            "knowledge_memory": {"persistent": True, "entries": datasets.get("pending_candidates", 0)},
            "semantic_memory": {"persistent": True, "entries": len(architecture_status.get("nodes", []) or [])},
            "reflection_memory": {"persistent": True, "entries": len(reflections)},
            "procedural_memory": {"persistent": True, "entries": len(self._dialogue)},
            "market_memory": {"persistent": True, "entries": market_status.get("experience_count", 0)},
            "architecture_memory": {"persistent": True, "entries": architecture_status.get("summary", {}).get("node_count", 0)},
        }

    def _provenance_snapshot(self, event_dict: dict[str, Any]) -> dict[str, Any]:
        payload = dict(event_dict.get("payload", {}) or {})
        return {
            "sender": event_dict.get("source", ""),
            "receiver": payload.get("receiver") or payload.get("selected_module") or payload.get("provider") or "",
            "module": payload.get("source_module") or event_dict.get("source", ""),
            "function": payload.get("selected_function") or payload.get("function") or "",
            "input": payload.get("input") or payload.get("query") or payload.get("topic") or "",
            "output": payload.get("output") or payload.get("response") or payload.get("summary") or "",
            "confidence": payload.get("confidence") or payload.get("confidence_score") or payload.get("evaluation_score"),
            "affected_knowledge": payload.get("affected_knowledge") or payload.get("recalled_knowledge") or [],
            "affected_memory": payload.get("affected_memory") or [],
            "affected_runtime_state": payload.get("affected_runtime_state") or [],
        }

    def _normalize_event(self, event: Any) -> dict[str, Any]:
        if isinstance(event, dict):
            return {"type": event.get("type", "runtime.event"), "source": event.get("source", "runtime"), "payload": dict(event.get("payload", {}) or {}), "timestamp": event.get("timestamp", time.time())}
        payload = dict(getattr(event, "payload", {}) or {})
        return {
            "type": getattr(event, "type_name", None) or getattr(event, "type", "runtime.event"),
            "source": getattr(event, "source", "runtime"),
            "payload": payload,
            "timestamp": getattr(event, "timestamp", time.time()),
        }

    def _architecture_status(self) -> dict[str, Any]:
        if self._architecture_model is not None and hasattr(self._architecture_model, "status"):
            try:
                return dict(self._architecture_model.status() or {})
            except Exception:
                return {}
        return {}

    def _persist(self) -> None:
        if self._persistence_manager is None or not hasattr(self._persistence_manager, "append_jsonl_record"):
            return
        try:
            root = getattr(self._persistence_manager, "root_dir", "")
            path = f"{root}/cognitive/foundation_architecture.jsonl" if root else "cognitive/foundation_architecture.jsonl"
            self._persistence_manager.append_jsonl_record(
                path,
                {
                    "runtime_id": self.runtime_id,
                    "event_count": self._event_count,
                    "last_event": dict(self._last_event),
                    "last_model_selection": dict(self._last_model_selection),
                    "knowledge_gaps": list(self._knowledge_gaps[-10:]),
                    "study_objectives": list(self._study_objectives[-10:]),
                },
            )
        except Exception:
            return
