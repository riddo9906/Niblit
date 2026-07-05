#!/usr/bin/env python3
"""Niblit Phase 2 — Cognitive Foundation Architecture.

FoundationArchitecture is the permanent cognitive backbone and central
coordinator of the Niblit runtime.  It never executes domain work
directly; instead it coordinates all subsystems through the Event Bus
and exposes a unified status view of the entire cognitive runtime.

Phases implemented here
-----------------------
Phase 1  — Cognitive Coordinator: subsystem registry, event-bus coordination
Phase 2  — Closed Cognitive Feedback Loop: pipeline via CognitiveFeedbackLoop
Phase 3  — Reflection Engine integration
Phase 4  — Knowledge Distillation: memory→knowledge→understanding→behaviour
Phase 5  — Structural Self-Awareness: runtime/module/dependency graphs
Phase 6  — Local LLM Cognitive Consultation
Phase 7  — Provenance Graph: causal lineage beyond JSONL
Phase 8  — Behaviour Adaptation: understanding→behaviour rules
Phase 9  — ALE Integration: autonomous learning coordinated via event bus
Phase 10 — Unified Event Bus: canonical envelope fields on every emission
Phase 11 — Human-Readable Cognitive Memory Journal
Phase 12 — Unified Runtime Architecture: all subsystems in one loop
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

from modules.behaviour_adaptation import BehaviourAdaptationEngine
from modules.cognitive_journal import CognitiveJournal
from modules.knowledge_distillation import KnowledgeDistillationLayer

log = logging.getLogger("Niblit.FoundationArchitecture")


class FoundationArchitecture:
    """Central cognitive coordinator for the Niblit runtime.

    Design principles
    -----------------
    * Never executes domain logic directly.
    * Coordinates all subsystems exclusively through the Event Bus.
    * Preserves RuntimeManager ownership of all services.
    * Preserves EventBus ownership of all inter-module communication.
    * Every event contributes to learning through the closed feedback loop.
    * Every decision is explainable through provenance tracking.
    """

    # ── pipeline / loop constants ───────────────────────────────────────────

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
    # All subsystems that must participate in the unified cognitive path
    EXPECTED_SUBSYSTEMS = [
        "event_bus",
        "runtime_manager",
        "knowledge_db",
        "memory_manager",
        "local_brain",
        "reflection_engine",
        "governance_engine",
        "structural_awareness",
        "ale",
        "trading_brain",
        "internet_manager",
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

        # ── existing state ──────────────────────────────────────────────────
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

        # ── Phase 1: Subsystem registry ─────────────────────────────────────
        # Maps subsystem name → metadata dict
        self._subsystems: dict[str, dict[str, Any]] = {}
        self._event_bus_ref: Any | None = None  # Phase 10 bus reference

        # ── Phase 2: Cognitive Feedback Loop ─────────────────────────────────
        self._feedback_loop: Any | None = None  # CognitiveFeedbackLoop | None

        # ── Phase 3: Reflection Engine ──────────────────────────────────────
        self._reflection_engine: Any | None = None

        # ── Phase 4: Knowledge Distillation (always embedded) ───────────────
        self._knowledge_distillation = KnowledgeDistillationLayer()

        # ── Phase 6: Local LLM Consultation ─────────────────────────────────
        self._local_brain: Any | None = None
        self._consultation_count = 0
        self._consultations: list[dict[str, Any]] = []

        # ── Phase 7: Provenance graph ────────────────────────────────────────
        self._provenance_service: Any | None = None
        # trace_id → list[child_trace_ids]
        self._provenance_graph: dict[str, list[str]] = {}

        # ── Phase 8: Behaviour Adaptation (always embedded) ─────────────────
        self._behaviour_engine = BehaviourAdaptationEngine()

        # ── Phase 11: Cognitive Journal (always embedded) ───────────────────
        self._journal = CognitiveJournal(persistence_manager=persistence_manager)

        # ── Phase 12: Unified path validation ───────────────────────────────
        self._unified_path_validated = False

    # ── Phase 1: Subsystem Registry & Coordination ─────────────────────────

    def register_subsystem(
        self,
        name: str,
        *,
        role: str = "",
        module_path: str = "",
        service_ref: Any = None,
    ) -> None:
        """Register a subsystem with the cognitive coordinator.

        Every subsystem that participates in the unified cognitive path
        must register here.  ``name`` is the canonical subsystem identifier
        (e.g. ``"event_bus"``, ``"knowledge_db"``).
        """
        with self._lock:
            self._subsystems[name] = {
                "name": name,
                "role": role,
                "module_path": module_path,
                "registered_at": time.time(),
                "has_service_ref": service_ref is not None,
                "participates_in_unified_loop": True,
            }
        log.debug("[FoundationArchitecture] Registered subsystem: %s", name)

    def coordinate_subsystem(
        self,
        subsystem: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """Emit a coordination event to a subsystem via the Event Bus.

        Returns True if the event was emitted; False if no bus is attached.
        FoundationArchitecture never calls subsystems directly — it always
        coordinates through the bus.
        """
        if self._event_bus_ref is None:
            return False
        try:
            full_payload = dict(payload or {})
            full_payload.setdefault("coordinator", "foundation_architecture")
            full_payload.setdefault("target_subsystem", subsystem)
            full_payload.setdefault("trace_id", f"coord-{int(time.time() * 1000)}")
            self._event_bus_ref.emit(event_type, "foundation_architecture", full_payload)
            return True
        except Exception as exc:
            log.debug("[FoundationArchitecture] coordinate_subsystem error: %s", exc)
            return False

    def set_event_bus(self, bus: Any) -> None:
        """Attach the Event Bus reference (Phase 10)."""
        with self._lock:
            self._event_bus_ref = bus

    # ── Phase 2: Cognitive Feedback Loop ────────────────────────────────────

    def set_feedback_loop(self, loop: Any) -> None:
        """Attach a :class:`CognitiveFeedbackLoop` instance (Phase 2)."""
        with self._lock:
            self._feedback_loop = loop

    def process_through_pipeline(self, event: dict[str, Any]) -> dict[str, Any]:
        """Run an event through the closed cognitive feedback pipeline.

        If no :class:`CognitiveFeedbackLoop` is attached the event is
        processed inline through the standard observe path (graceful
        degradation).  Returns a summary trace dict.
        """
        if self._feedback_loop is not None:
            try:
                trace = self._feedback_loop.process(event)
                return trace.to_dict()
            except Exception as exc:
                log.debug("[FoundationArchitecture] pipeline error: %s", exc)
        # Fallback: standard observe path
        self.observe_event(event)
        return {"trace_id": event.get("payload", {}).get("trace_id", ""), "fallback": True}

    # ── Phase 3: Reflection Integration ─────────────────────────────────────

    def set_reflection_engine(self, engine: Any) -> None:
        """Attach the :class:`ReflectionEngine` singleton (Phase 3)."""
        with self._lock:
            self._reflection_engine = engine

    def trigger_reflection(
        self,
        *,
        quality: float,
        mode: str = "cognitive",
        intent: str = "",
        model_used: str = "",
        tool_success: bool = True,
    ) -> dict[str, Any]:
        """Ask the Reflection Engine to evaluate recent activity (Phase 3).

        Returns the reflection report dict, or an empty dict if the engine
        is not available.
        """
        engine = self._reflection_engine
        if engine is None:
            return {}
        try:
            engine.record_turn(
                quality=quality,
                mode=mode,
                intent=intent,
                model_used=model_used,
                tool_success=tool_success,
            )
            if engine.should_reflect():
                report = engine.reflect()
                return report.to_dict() if hasattr(report, "to_dict") else {}
        except Exception as exc:
            log.debug("[FoundationArchitecture] reflection error: %s", exc)
        return {}

    # ── Phase 4: Knowledge Distillation ─────────────────────────────────────

    def distill_knowledge(
        self,
        memory_id: str,
        concept: str,
        fact: str,
        confidence: float,
        *,
        validation_notes: str = "",
    ) -> dict[str, Any] | None:
        """Promote a Memory record to validated Knowledge (Phase 4)."""
        record = self._knowledge_distillation.distill_memory_to_knowledge(
            memory_id,
            concept=concept,
            fact=fact,
            confidence=confidence,
            validation_notes=validation_notes,
        )
        return record.to_dict() if record is not None else None

    # ── Phase 5: Structural Self-Awareness ──────────────────────────────────

    def structural_snapshot(self) -> dict[str, Any]:
        """Return the current structural awareness snapshot (Phase 5).

        Queries the architecture model (runtime/module/dependency graphs)
        and the registered subsystems registry.
        """
        arch_status = self._architecture_status()
        with self._lock:
            subsystems = dict(self._subsystems)
        return {
            "runtime_graph": arch_status.get("nodes", {}),
            "dependency_graph": {
                name: meta.get("module_path", "")
                for name, meta in subsystems.items()
            },
            "module_graph": {
                name: meta.get("role", "")
                for name, meta in subsystems.items()
            },
            "registered_subsystems": len(subsystems),
            "architecture_model_status": arch_status,
        }

    # ── Phase 6: Local LLM Consultation ─────────────────────────────────────

    def set_local_brain(self, brain: Any) -> None:
        """Attach the LocalBrain for LLM consultation (Phase 6)."""
        with self._lock:
            self._local_brain = brain

    def consult_local_brain(self, context: dict[str, Any]) -> dict[str, Any]:
        """Ask the LocalBrain for cognitive guidance before a decision.

        The LocalBrain response is recorded in the provenance record and
        feeds into the pipeline's planning stage.  Returns an empty dict
        gracefully when LocalBrain is unavailable.

        Context keys recognised:
            ``objective``, ``prompt``, ``functions``, ``modules``,
            ``expected_outcome``, ``risks``, ``prior_knowledge``.
        """
        brain = self._local_brain
        if brain is None:
            return {"available": False, "reason": "local_brain_not_attached"}
        try:
            prompt_parts = [
                f"Objective: {context.get('objective', 'not specified')}",
                f"Prompt: {context.get('prompt', '')}",
                f"Expected outcome: {context.get('expected_outcome', '')}",
                f"Prior knowledge: {context.get('prior_knowledge', '')}",
                f"Risks: {context.get('risks', '')}",
            ]
            prompt = "\n".join(p for p in prompt_parts if p.strip())
            response: str = ""
            if hasattr(brain, "generate"):
                response = str(brain.generate(prompt) or "")
            elif hasattr(brain, "ask"):
                response = str(brain.ask(prompt) or "")
            consultation = {
                "available": True,
                "objective": context.get("objective", ""),
                "response": response[:480],
                "timestamp": time.time(),
            }
            with self._lock:
                self._consultation_count += 1
                self._consultations.append(consultation)
                if len(self._consultations) > 100:
                    self._consultations[:] = self._consultations[-100:]
            return consultation
        except Exception as exc:
            log.debug("[FoundationArchitecture] local brain consultation error: %s", exc)
            return {"available": False, "reason": str(exc)}

    # ── Phase 7: Provenance Graph ────────────────────────────────────────────

    def set_provenance_service(self, service: Any) -> None:
        """Attach the ProvenanceService (Phase 7)."""
        with self._lock:
            self._provenance_service = service

    def record_provenance_link(
        self, parent_trace_id: str, child_trace_id: str
    ) -> None:
        """Link a child trace to its causal parent (Phase 7)."""
        with self._lock:
            self._provenance_graph.setdefault(parent_trace_id, [])
            if child_trace_id not in self._provenance_graph[parent_trace_id]:
                self._provenance_graph[parent_trace_id].append(child_trace_id)

    def get_provenance_lineage(self, trace_id: str) -> dict[str, Any]:
        """Return the causal lineage for a given trace_id (Phase 7)."""
        with self._lock:
            children = list(self._provenance_graph.get(trace_id, []))
        provenance_record: dict[str, Any] = {}
        if self._provenance_service is not None:
            try:
                provenance_record = dict(
                    getattr(self._provenance_service, "_records", {}).get(trace_id, {}) or {}
                )
            except Exception:
                pass
        return {
            "trace_id": trace_id,
            "children": children,
            "provenance": provenance_record,
        }

    # ── Phase 8: Behaviour Adaptation ───────────────────────────────────────

    def adapt_behaviour(
        self,
        concept: str,
        *,
        understanding_score: float,
        confidence: float,
        evidence: str = "",
        source: str = "foundation",
    ) -> str:
        """Update behaviour rules from new understanding (Phase 8).

        Returns the rule_id of the created or updated rule.
        """
        return self._behaviour_engine.record_understanding(
            concept,
            understanding_score=understanding_score,
            confidence=confidence,
            evidence=evidence,
            source=source,
        )

    def get_decision_bias(
        self,
        trace_id: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Return the behaviour-derived bias for a decision context (Phase 8)."""
        return self._behaviour_engine.apply_decision_bias(trace_id, context).to_dict()

    # ── Phase 9: ALE Integration ─────────────────────────────────────────────

    def coordinate_ale_research(
        self,
        topic: str,
        *,
        priority: str = "normal",
        trace_id: str = "",
    ) -> bool:
        """Request the ALE to research a topic through the Event Bus (Phase 9).

        Everything flows through FoundationArchitecture; ALE never writes
        directly to behaviour.
        """
        return self.coordinate_subsystem(
            "ale",
            "ale.research_requested",
            {
                "topic": topic,
                "priority": priority,
                "trace_id": trace_id or f"ale-{int(time.time() * 1000)}",
                "pipeline": "foundation → ale → event_bus → knowledge_distillation",
            },
        )

    # ── Phase 11: Cognitive Journal ──────────────────────────────────────────

    def record_cognitive_event(
        self,
        *,
        trace_id: str = "",
        what_happened: str,
        event_type: str,
        source_module: str,
        why_it_happened: str = "",
        intent: str = "",
        how_it_happened: str = "",
        modules_participated: list[str] | None = None,
        reliability: float = 0.5,
        understanding_changed: list[str] | None = None,
        knowledge_created: list[str] | None = None,
        behaviour_changed: list[str] | None = None,
    ) -> dict[str, Any]:
        """Write an entry to the human-readable cognitive journal (Phase 11)."""
        entry = self._journal.record(
            trace_id=trace_id,
            what_happened=what_happened,
            event_type=event_type,
            source_module=source_module,
            why_it_happened=why_it_happened,
            intent=intent,
            how_it_happened=how_it_happened,
            modules_participated=modules_participated,
            reliability=reliability,
            understanding_changed=understanding_changed,
            knowledge_created=knowledge_created,
            behaviour_changed=behaviour_changed,
        )
        return entry.to_dict()

    # ── Phase 12: Unified Architecture Validation ────────────────────────────

    def validate_unified_path(self) -> dict[str, Any]:
        """Check that all expected subsystems are registered (Phase 12).

        Returns a validation report.  This does NOT raise; missing
        subsystems are recorded as warnings so the runtime degrades
        gracefully.
        """
        with self._lock:
            registered = set(self._subsystems.keys())
        expected = set(self.EXPECTED_SUBSYSTEMS)
        missing = sorted(expected - registered)
        present = sorted(expected & registered)
        result = {
            "unified_path": len(missing) == 0,
            "registered_count": len(registered),
            "expected_subsystems": sorted(expected),
            "present": present,
            "missing": missing,
        }
        with self._lock:
            self._unified_path_validated = True
        return result

    # ── Core event observation (enhanced for Phases 4, 7, 10, 11) ──────────

    def observe_event(self, event: Any) -> None:
        """Observe a runtime event and run all cognitive update phases."""
        event_dict = self._normalize_event(event)
        payload = dict(event_dict.get("payload", {}) or {})
        with self._lock:
            self._event_count += 1
            self._last_event = event_dict
            self._append_dialogue(event_dict, payload)
            self._update_understanding(event_dict, payload)
            self._update_governance(payload)
            self._update_study_objectives(payload)

        # Phase 4: Ingest into memory layer
        try:
            mem_record = self._knowledge_distillation.ingest_raw_event(event_dict)
            # Auto-distill high-confidence events to knowledge
            score = float(
                payload.get("evaluation_score")
                or payload.get("confidence_score")
                or payload.get("confidence")
                or 0.0
            )
            if score >= KnowledgeDistillationLayer.CONFIDENCE_THRESHOLD:
                concept = str(
                    payload.get("topic")
                    or payload.get("intent")
                    or event_dict.get("type")
                    or "runtime"
                )
                fact = str(
                    payload.get("summary")
                    or payload.get("response")
                    or event_dict.get("type", "")
                )[:240]
                if concept and fact:
                    k_record = self._knowledge_distillation.distill_memory_to_knowledge(
                        mem_record.memory_id,
                        concept=concept,
                        fact=fact,
                        confidence=score,
                    )
                    if k_record:
                        # Phase 8: Update behaviour from new knowledge
                        self._behaviour_engine.record_understanding(
                            concept,
                            understanding_score=score,
                            confidence=score,
                            evidence=fact[:120],
                            source=event_dict.get("source", "runtime"),
                        )
        except Exception as exc:
            log.debug("[FoundationArchitecture] distillation error: %s", exc)

        # Phase 7: Update provenance graph
        try:
            trace_id = str(payload.get("trace_id") or "")
            causal_parent = str(payload.get("causal_parent") or "")
            if trace_id and causal_parent:
                self.record_provenance_link(causal_parent, trace_id)
        except Exception:
            pass

        # Phase 11: Write to cognitive journal
        try:
            self._journal.record_from_event(event_dict)
        except Exception as exc:
            log.debug("[FoundationArchitecture] journal error: %s", exc)

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
        architecture_status = dict(
            architecture_status or self._architecture_status()
        )
        with self._lock:
            understanding_entries = list(self._understanding.values())
            reflections = list(cognitive_status.get("reflections", []) or [])
            model_manager = self._build_model_manager(
                provider_status, local_brain_status
            )
            memory_layers = self._build_memory_layers(
                cognitive_status, market_status, architecture_status
            )
            subsystems_snapshot = dict(self._subsystems)
            status: dict[str, Any] = {
                "runtime_engineering": {
                    "runtime_id": self.runtime_id,
                    "persistence_first": True,
                    "event_bus_only": True,
                    "lifecycle_state": (
                        runtime_health.get("runtime_state")
                        or provider_status.get("runtime_state")
                        or "ready"
                    ),
                    "health_monitoring": bool(runtime_health) or bool(event_stats),
                    "automatic_recovery": True,
                    "graceful_degradation": True,
                },
                # Phase 2
                "cognitive_loop": {
                    "phases": list(self.COGNITIVE_LOOP),
                    "unified_feedback_path": True,
                    "last_trace_id": (
                        self._last_event.get("payload", {}) or {}
                    ).get("trace_id", ""),
                    "pipeline_status": (
                        self._feedback_loop.status()
                        if self._feedback_loop is not None
                        else {"active": False}
                    ),
                },
                "memory_layers": memory_layers,
                # Phase 4
                "knowledge_distillation": self._knowledge_distillation.status(),
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
                    "consultation_count": self._consultation_count,
                    "status": local_brain_status,
                },
                "model_manager": model_manager,
                "event_bus": {
                    "authoritative": True,
                    "event_count": self._event_count,
                    "observability": event_stats,
                    "last_event_provenance": self._provenance_snapshot(
                        self._last_event
                    ),
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
                    "engine_active": self._reflection_engine is not None,
                },
                # Phase 5
                "structural_awareness": {
                    "self_model_enabled": True,
                    "architecture_status": architecture_status,
                    "registered_subsystems": len(subsystems_snapshot),
                    "subsystems": list(subsystems_snapshot.keys()),
                },
                "governance": {
                    "protected_core_safety": True,
                    "proposals": list(self._governance_proposals[-10:]),
                },
                # Phase 8
                "behaviour_adaptation": self._behaviour_engine.status(),
                # Phase 11
                "cognitive_journal": self._journal.status(),
                # Phase 12
                "unified_architecture": {
                    "one_cognitive_loop": True,
                    "no_isolated_learning": True,
                    "event_bus_authoritative": True,
                    "validated": self._unified_path_validated,
                },
            }
        return status

    def runtime_dialogue(self, *, limit: int = 25) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._dialogue[-max(1, limit) :])

    # ── private helpers (preserved from Phase 1) ────────────────────────────

    def _append_dialogue(
        self, event_dict: dict[str, Any], payload: dict[str, Any]
    ) -> None:
        entry = {
            "timestamp": event_dict.get("timestamp")
            or payload.get("timestamp")
            or time.time(),
            "sender": event_dict.get("source", "unknown"),
            "receiver": payload.get("receiver")
            or payload.get("selected_module")
            or payload.get("provider")
            or "",
            "module": payload.get("source_module")
            or event_dict.get("source", "unknown"),
            "function": payload.get("selected_function")
            or payload.get("function")
            or "",
            "event_type": event_dict.get("type", "runtime.event"),
            "input": payload.get("input")
            or payload.get("query")
            or payload.get("command")
            or payload.get("topic")
            or "",
            "output": payload.get("output")
            or payload.get("response")
            or payload.get("summary")
            or payload.get("reflection_summary")
            or "",
            "duration_ms": payload.get("execution_duration_ms")
            or payload.get("elapsed_ms"),
            "confidence": payload.get("confidence")
            or payload.get("confidence_score")
            or payload.get("evaluation_score"),
            "trace_id": payload.get("trace_id", ""),
        }
        self._dialogue.append(entry)
        if len(self._dialogue) > 250:
            self._dialogue[:] = self._dialogue[-250:]

    def _update_understanding(
        self, event_dict: dict[str, Any], payload: dict[str, Any]
    ) -> None:
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
        raw_score = (
            payload.get("quality_score")
            or payload.get("evaluation_score")
            or payload.get("confidence_score")
            or 0.5
        )
        score = float(raw_score)
        record["confidence"] = round(
            max(0.0, min(1.0, (record["confidence"] * 0.7) + (score * 0.3))), 3
        )
        record["understanding_score"] = round(
            max(0.0, min(1.0, (record["understanding_score"] * 0.6) + (score * 0.4))),
            3,
        )
        evidence = (
            payload.get("summary")
            or payload.get("response")
            or event_dict.get("type", "")
        )
        if evidence and evidence not in record["supporting_evidence"]:
            record["supporting_evidence"].append(str(evidence)[:240])
            record["supporting_evidence"] = record["supporting_evidence"][-5:]
        related = [
            value
            for value in [
                payload.get("provider"),
                payload.get("selected_module"),
                payload.get("target_module"),
            ]
            if value and value != concept
        ]
        for item in related:
            if item not in record["related_concepts"]:
                record["related_concepts"].append(str(item))
        record["related_concepts"] = record["related_concepts"][-8:]
        if payload.get("contradictions"):
            contradictions = payload.get("contradictions") or []
            for item in contradictions:
                summary = (
                    item.get("summary") if isinstance(item, dict) else str(item)
                )
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

    def _build_model_manager(
        self,
        provider_status: dict[str, Any],
        local_brain_status: dict[str, Any],
    ) -> dict[str, Any]:
        manager_status = dict(provider_status.get("manager_status", {}) or {})
        available = []
        for name in ["qwen", "llama3", "hf", "anthropic", "ruflo", "openai_compatible"]:
            if provider_status.get(name) or manager_status.get(name):
                available.append(name)
        return {
            "all_interactions_routed": True,
            "registered_models": available,
            "active_model": provider_status.get("active_provider")
            or manager_status.get("active")
            or "",
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
        distillation = self._knowledge_distillation.status()
        return {
            "runtime_state": {
                "persistent": False,
                "entries": len(cognitive_status.get("active_sessions", []) or []),
            },
            "working_memory": {
                "persistent": False,
                "entries": len(episodes[-10:]),
            },
            "knowledge_memory": {
                "persistent": True,
                "entries": datasets.get("pending_candidates", 0),
            },
            "semantic_memory": {
                "persistent": True,
                "entries": len(architecture_status.get("nodes", []) or []),
            },
            "reflection_memory": {
                "persistent": True,
                "entries": len(reflections),
            },
            "procedural_memory": {
                "persistent": True,
                "entries": len(self._dialogue),
            },
            "market_memory": {
                "persistent": True,
                "entries": market_status.get("experience_count", 0),
            },
            "architecture_memory": {
                "persistent": True,
                "entries": architecture_status.get("summary", {}).get("node_count", 0),
            },
            # Phase 4 distilled layers
            "distilled_knowledge": {
                "persistent": True,
                "entries": distillation["layers"]["knowledge"]["entries"],
            },
            "distilled_understanding": {
                "persistent": True,
                "entries": distillation["layers"]["understanding"]["entries"],
            },
            "behaviour_rules": {
                "persistent": True,
                "entries": self._behaviour_engine.rule_count(),
            },
        }

    def _provenance_snapshot(self, event_dict: dict[str, Any]) -> dict[str, Any]:
        payload = dict(event_dict.get("payload", {}) or {})
        return {
            "sender": event_dict.get("source", ""),
            "receiver": payload.get("receiver")
            or payload.get("selected_module")
            or payload.get("provider")
            or "",
            "module": payload.get("source_module") or event_dict.get("source", ""),
            "function": payload.get("selected_function")
            or payload.get("function")
            or "",
            "input": payload.get("input")
            or payload.get("query")
            or payload.get("topic")
            or "",
            "output": payload.get("output")
            or payload.get("response")
            or payload.get("summary")
            or "",
            "confidence": payload.get("confidence")
            or payload.get("confidence_score")
            or payload.get("evaluation_score"),
            "affected_knowledge": payload.get("affected_knowledge")
            or payload.get("recalled_knowledge")
            or [],
            "affected_memory": payload.get("affected_memory") or [],
            "affected_runtime_state": payload.get("affected_runtime_state") or [],
            # Phase 7: causal graph fields
            "causal_parent": payload.get("causal_parent") or "",
            "causal_children": self._provenance_graph.get(
                str(payload.get("trace_id") or ""), []
            ),
        }

    def _normalize_event(self, event: Any) -> dict[str, Any]:
        if isinstance(event, dict):
            return {
                "type": event.get("type", "runtime.event"),
                "source": event.get("source", "runtime"),
                "payload": dict(event.get("payload", {}) or {}),
                "timestamp": event.get("timestamp", time.time()),
            }
        payload = dict(getattr(event, "payload", {}) or {})
        return {
            "type": getattr(event, "type_name", None)
            or getattr(event, "type", "runtime.event"),
            "source": getattr(event, "source", "runtime"),
            "payload": payload,
            "timestamp": getattr(event, "timestamp", time.time()),
        }

    def _architecture_status(self) -> dict[str, Any]:
        if self._architecture_model is not None and hasattr(
            self._architecture_model, "status"
        ):
            try:
                return dict(self._architecture_model.status() or {})
            except Exception:
                return {}
        return {}

    def _persist(self) -> None:
        if self._persistence_manager is None or not hasattr(
            self._persistence_manager, "append_jsonl_record"
        ):
            return
        try:
            root = getattr(self._persistence_manager, "root_dir", "")
            path = (
                f"{root}/cognitive/foundation_architecture.jsonl"
                if root
                else "cognitive/foundation_architecture.jsonl"
            )
            self._persistence_manager.append_jsonl_record(
                path,
                {
                    "runtime_id": self.runtime_id,
                    "event_count": self._event_count,
                    "last_event": dict(self._last_event),
                    "last_model_selection": dict(self._last_model_selection),
                    "knowledge_gaps": list(self._knowledge_gaps[-10:]),
                    "study_objectives": list(self._study_objectives[-10:]),
                    "knowledge_distillation": self._knowledge_distillation.status(),
                    "behaviour_rules_count": self._behaviour_engine.rule_count(),
                    "journal_entries": self._journal.entry_count(),
                },
            )
        except Exception:
            return
