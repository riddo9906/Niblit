"""Tests for Niblit Phase 2 — Complete Cognitive Foundation Upgrade.

Covers all 12 phases:
    Phase 1  — Cognitive Coordinator (subsystem registry)
    Phase 2  — Closed Cognitive Feedback Loop
    Phase 3  — Reflection Engine integration
    Phase 4  — Knowledge Distillation (memory→knowledge→understanding→behaviour)
    Phase 5  — Structural Self-Awareness
    Phase 6  — Local LLM Consultation
    Phase 7  — Provenance Graph
    Phase 8  — Behaviour Adaptation
    Phase 9  — ALE Integration (event-bus coordination)
    Phase 10 — Unified Event Bus
    Phase 11 — Human-Readable Cognitive Memory Journal
    Phase 12 — Unified Runtime Architecture validation
"""

from __future__ import annotations

from pathlib import Path

import pytest

from modules.behaviour_adaptation import BehaviourAdaptationEngine, DecisionBias
from modules.cognitive_feedback_loop import (
    PIPELINE_STAGES,
    CognitiveFeedbackLoop,
    CognitivePipelineTrace,
)
from modules.cognitive_journal import CognitiveJournal, JournalEntry
from modules.foundation_architecture import FoundationArchitecture
from modules.knowledge_distillation import KnowledgeDistillationLayer


# ── Phase 2: Cognitive Feedback Loop ─────────────────────────────────────────


class TestCognitiveFeedbackLoop:
    def test_all_pipeline_stages_defined(self) -> None:
        assert len(PIPELINE_STAGES) == 16
        assert PIPELINE_STAGES[0] == "event"
        assert PIPELINE_STAGES[-1] == "return_response"

    def test_process_returns_trace_with_all_stages(self) -> None:
        loop = CognitiveFeedbackLoop()
        event = {
            "type": "test.event",
            "source": "test",
            "payload": {"trace_id": "trace-test-001"},
        }
        trace = loop.process(event)
        assert isinstance(trace, CognitivePipelineTrace)
        assert trace.trace_id == "trace-test-001"
        assert trace.source == "test"
        assert len(trace.stages) == len(PIPELINE_STAGES)

    def test_stages_without_handlers_are_skipped(self) -> None:
        loop = CognitiveFeedbackLoop()
        trace = loop.process({"type": "x", "source": "y", "payload": {}})
        skipped = [s for s in trace.stages if s.status == "skipped"]
        assert len(skipped) == len(PIPELINE_STAGES), "all stages should skip when no handlers"

    def test_registered_handler_executes_and_returns_output(self) -> None:
        loop = CognitiveFeedbackLoop()
        results: list[dict] = []

        def reflection_handler(ctx: dict) -> dict:
            results.append(ctx)
            return {"reflected": True}

        loop.register_stage_handler("reflection", reflection_handler)
        trace = loop.process({"type": "t", "source": "s", "payload": {}})
        reflection_stages = [s for s in trace.stages if s.stage == "reflection"]
        assert len(reflection_stages) == 1
        assert reflection_stages[0].status == "ok"
        assert reflection_stages[0].output.get("reflected") is True
        assert len(results) == 1

    def test_handler_exception_marks_stage_error_but_continues(self) -> None:
        loop = CognitiveFeedbackLoop()

        def bad_handler(ctx: dict) -> None:
            raise ValueError("intentional error")

        loop.register_stage_handler("planning", bad_handler)
        trace = loop.process({"type": "t", "source": "s", "payload": {}})
        planning = next(s for s in trace.stages if s.stage == "planning")
        assert planning.status == "error"
        assert "intentional error" in planning.error
        # Pipeline should still complete all stages
        assert len(trace.stages) == len(PIPELINE_STAGES)

    def test_knowledge_extraction_populates_trace_field(self) -> None:
        loop = CognitiveFeedbackLoop()

        def extractor(ctx: dict) -> dict:
            return {"knowledge_items": ["fact:routing-improved"]}

        loop.register_stage_handler("knowledge_extraction", extractor)
        trace = loop.process({"type": "t", "source": "s", "payload": {}})
        assert "fact:routing-improved" in trace.knowledge_created

    def test_status_counts_processed_events(self) -> None:
        loop = CognitiveFeedbackLoop()
        for _ in range(3):
            loop.process({"type": "t", "source": "s", "payload": {}})
        status = loop.status()
        assert status["processed_count"] == 3

    def test_recent_traces_returns_dicts(self) -> None:
        loop = CognitiveFeedbackLoop()
        loop.process({"type": "t", "source": "s", "payload": {"trace_id": "xyz"}})
        traces = loop.recent_traces(limit=1)
        assert len(traces) == 1
        assert traces[0]["trace_id"] == "xyz"

    def test_unknown_stage_registration_is_ignored(self) -> None:
        loop = CognitiveFeedbackLoop()
        loop.register_stage_handler("nonexistent_stage", lambda ctx: {})
        # Should not raise and pipeline should still work
        trace = loop.process({"type": "t", "source": "s", "payload": {}})
        assert trace is not None

    def test_trace_duration_is_positive(self) -> None:
        loop = CognitiveFeedbackLoop()
        trace = loop.process({"type": "t", "source": "s", "payload": {}})
        assert trace.duration_ms >= 0.0


# ── Phase 4: Knowledge Distillation ──────────────────────────────────────────


class TestKnowledgeDistillationLayer:
    def test_ingest_raw_event_creates_memory_record(self) -> None:
        layer = KnowledgeDistillationLayer()
        event = {"type": "test.event", "source": "test", "payload": {}}
        record = layer.ingest_raw_event(event)
        assert record.memory_id.startswith("mem-")
        assert layer.memory_count() == 1

    def test_distill_memory_to_knowledge_succeeds_above_threshold(self) -> None:
        layer = KnowledgeDistillationLayer()
        event = {"type": "e", "source": "s", "payload": {}}
        mem = layer.ingest_raw_event(event)
        k = layer.distill_memory_to_knowledge(
            mem.memory_id,
            concept="routing",
            fact="Local routing improved quality by 20%.",
            confidence=0.85,
        )
        assert k is not None
        assert k.concept == "routing"
        assert k.confidence == 0.85
        assert layer.knowledge_count() == 1

    def test_distill_returns_none_below_threshold(self) -> None:
        layer = KnowledgeDistillationLayer()
        event = {"type": "e", "source": "s", "payload": {}}
        mem = layer.ingest_raw_event(event)
        k = layer.distill_memory_to_knowledge(
            mem.memory_id,
            concept="low-conf",
            fact="Unverified claim.",
            confidence=0.30,
        )
        assert k is None
        assert layer.knowledge_count() == 0

    def test_build_understanding_from_knowledge_records(self) -> None:
        layer = KnowledgeDistillationLayer()
        event = {"type": "e", "source": "s", "payload": {}}
        mem = layer.ingest_raw_event(event)
        k = layer.distill_memory_to_knowledge(
            mem.memory_id,
            concept="routing",
            fact="routing fact",
            confidence=0.9,
        )
        assert k is not None
        u = layer.build_understanding(
            "routing",
            related_concepts=["latency", "quality"],
            relationship="improves",
            strength=0.8,
            source_knowledge_ids=[k.knowledge_id],
        )
        assert u.primary_concept == "routing"
        assert "latency" in u.related_concepts
        assert layer.understanding_count() == 1

    def test_derive_behaviour_rule_from_understanding(self) -> None:
        layer = KnowledgeDistillationLayer()
        event = {"type": "e", "source": "s", "payload": {}}
        mem = layer.ingest_raw_event(event)
        k = layer.distill_memory_to_knowledge(
            mem.memory_id, concept="c", fact="f", confidence=0.9
        )
        assert k is not None
        u = layer.build_understanding(
            "c",
            related_concepts=[],
            relationship="causes",
            strength=0.75,
            source_knowledge_ids=[k.knowledge_id],
        )
        b = layer.derive_behaviour_rule(
            u.understanding_id,
            condition="when latency is high",
            action="prefer local model",
            confidence=0.8,
        )
        assert b is not None
        assert layer.behaviour_count() == 1

    def test_layers_are_never_confused(self) -> None:
        layer = KnowledgeDistillationLayer()
        # Memory records don't appear in knowledge without explicit distillation
        layer.ingest_raw_event({"type": "e", "source": "s", "payload": {}})
        assert layer.memory_count() == 1
        assert layer.knowledge_count() == 0
        assert layer.understanding_count() == 0
        assert layer.behaviour_count() == 0

    def test_status_shows_all_four_layers(self) -> None:
        layer = KnowledgeDistillationLayer()
        status = layer.status()
        assert set(status["layers"].keys()) == {
            "memory", "knowledge", "understanding", "behaviour"
        }
        assert status["confidence_threshold"] == 0.60


# ── Phase 8: Behaviour Adaptation ────────────────────────────────────────────


class TestBehaviourAdaptationEngine:
    def test_record_understanding_creates_rule(self) -> None:
        engine = BehaviourAdaptationEngine()
        rule_id = engine.record_understanding(
            "routing",
            understanding_score=0.8,
            confidence=0.75,
            evidence="Routing improved outcome",
        )
        assert rule_id == "rule:routing"
        assert engine.rule_count() == 1

    def test_subsequent_record_updates_existing_rule(self) -> None:
        engine = BehaviourAdaptationEngine()
        engine.record_understanding(
            "routing", understanding_score=0.7, confidence=0.7
        )
        engine.record_understanding(
            "routing", understanding_score=0.9, confidence=0.9
        )
        # Rule count should stay at 1 (update, not duplicate)
        assert engine.rule_count() == 1

    def test_apply_decision_bias_returns_bias(self) -> None:
        engine = BehaviourAdaptationEngine()
        engine.record_understanding(
            "routing", understanding_score=0.8, confidence=0.8
        )
        bias = engine.apply_decision_bias("trace-1", {"topic": "routing latency"})
        assert isinstance(bias, DecisionBias)
        assert bias.trace_id == "trace-1"
        assert bias.bias_direction in ("prefer", "neutral", "avoid")

    def test_neutral_bias_returned_when_no_rules(self) -> None:
        engine = BehaviourAdaptationEngine()
        bias = engine.apply_decision_bias("t", {})
        assert bias.bias_direction == "neutral"
        assert bias.confidence_modifier == 0.0

    def test_record_outcome_adjusts_confidence(self) -> None:
        engine = BehaviourAdaptationEngine()
        engine.record_understanding(
            "routing", understanding_score=0.8, confidence=0.75
        )
        engine.record_outcome("rule:routing", positive=True)
        rules = engine.active_rules()
        routing_rule = next(r for r in rules if r["rule_id"] == "rule:routing")
        assert routing_rule["confidence"] > 0.75

    def test_status_shows_pipeline(self) -> None:
        engine = BehaviourAdaptationEngine()
        status = engine.status()
        assert "pipeline" in status
        assert "understanding" in status["pipeline"]
        assert "behaviour_rules" in status["pipeline"]


# ── Phase 11: Cognitive Journal ───────────────────────────────────────────────


class TestCognitiveJournal:
    def test_record_creates_entry(self) -> None:
        journal = CognitiveJournal()
        entry = journal.record(
            trace_id="trace-01",
            what_happened="Local routing selected for low-latency task.",
            event_type="routing.decision",
            source_module="modules.local_brain",
            why_it_happened="Latency threshold exceeded.",
            intent="serve_user_query",
            how_it_happened="RoutingEngine.select_provider",
            modules_participated=["modules.local_brain", "modules.router"],
            reliability=0.88,
            understanding_changed=["routing"],
            knowledge_created=["routing:local_wins_at_low_latency"],
        )
        assert isinstance(entry, JournalEntry)
        assert entry.trace_id == "trace-01"
        assert journal.entry_count() == 1

    def test_record_from_event_extracts_fields(self) -> None:
        journal = CognitiveJournal()
        event = {
            "type": "reflection.complete",
            "source": "planner",
            "payload": {
                "trace_id": "t-02",
                "summary": "Quality improved.",
                "evaluation_score": 0.82,
                "topic": "provider routing",
                "selected_function": "reflect",
            },
        }
        entry = journal.record_from_event(event)
        assert entry.event_type == "reflection.complete"
        assert entry.source_module == "planner"
        assert "Quality improved" in entry.what_happened

    def test_recent_entries_returns_dicts(self) -> None:
        journal = CognitiveJournal()
        journal.record(
            trace_id="t",
            what_happened="x",
            event_type="e",
            source_module="m",
        )
        entries = journal.recent_entries(limit=1)
        assert len(entries) == 1
        assert "what_happened" in entries[0]

    def test_to_narrative_contains_key_fields(self) -> None:
        journal = CognitiveJournal()
        entry = journal.record(
            trace_id="t",
            what_happened="Provider selected.",
            event_type="provider.selected",
            source_module="router",
            why_it_happened="Latency was low.",
            how_it_happened="Router.select",
        )
        narrative = entry.to_narrative()
        assert "Provider selected" in narrative
        assert "Why:" in narrative
        assert "How:" in narrative

    def test_status_describes_purpose(self) -> None:
        journal = CognitiveJournal()
        status = journal.status()
        assert status["purpose"] == "human_readable_cognitive_memory"
        assert "what_happened" in status["fields"]


# ── Phase 1 + 3-12: FoundationArchitecture as Coordinator ───────────────────


class TestFoundationArchitectureCognitiveFull:
    def _make_foundation(self) -> FoundationArchitecture:
        return FoundationArchitecture(runtime_id="rt-phase2-test")

    # Phase 1: Subsystem registry
    def test_register_subsystem_records_entry(self) -> None:
        fa = self._make_foundation()
        fa.register_subsystem("event_bus", role="MessageBroker", module_path="core.event_bus")
        fa.register_subsystem("knowledge_db", role="Storage", module_path="modules.storage")
        validation = fa.validate_unified_path()
        assert validation["registered_count"] >= 2
        assert "event_bus" in validation["present"]
        assert "knowledge_db" in validation["present"]

    # Phase 2: Pipeline delegation
    def test_process_through_pipeline_with_loop(self) -> None:
        fa = self._make_foundation()
        loop = CognitiveFeedbackLoop()
        calls: list[dict] = []

        def reflection_handler(ctx: dict) -> dict:
            calls.append(ctx)
            return {"reflected": True}

        loop.register_stage_handler("reflection", reflection_handler)
        fa.set_feedback_loop(loop)

        result = fa.process_through_pipeline(
            {
                "type": "response.complete",
                "source": "api",
                "payload": {"trace_id": "p2-trace", "topic": "routing"},
            }
        )
        assert result.get("trace_id") == "p2-trace"
        assert len(calls) == 1

    def test_process_through_pipeline_fallback_without_loop(self) -> None:
        fa = self._make_foundation()
        result = fa.process_through_pipeline(
            {"type": "t", "source": "s", "payload": {"trace_id": "fb-1"}}
        )
        assert "trace_id" in result
        assert result.get("fallback") is True

    # Phase 3: Reflection integration
    def test_trigger_reflection_with_stub_engine(self) -> None:
        fa = self._make_foundation()

        class StubEngine:
            def __init__(self) -> None:
                self.turns: list = []
                self._should_reflect = False

            def record_turn(self, **kwargs: object) -> None:
                self.turns.append(kwargs)
                self._should_reflect = True

            def should_reflect(self) -> bool:
                return self._should_reflect

            def reflect(self) -> object:
                class R:
                    def to_dict(self) -> dict:
                        return {"summary": "all ok"}
                return R()

        engine = StubEngine()
        fa.set_reflection_engine(engine)
        report = fa.trigger_reflection(quality=0.8, intent="test")
        assert report.get("summary") == "all ok"
        assert len(engine.turns) == 1

    def test_trigger_reflection_without_engine_returns_empty(self) -> None:
        fa = self._make_foundation()
        assert fa.trigger_reflection(quality=0.5) == {}

    # Phase 4: Knowledge distillation through observe_event
    def test_observe_event_feeds_distillation_on_high_confidence(self) -> None:
        fa = self._make_foundation()
        fa.observe_event(
            {
                "type": "reflection.complete",
                "source": "planner",
                "payload": {
                    "trace_id": "dist-1",
                    "topic": "provider-routing",
                    "summary": "Routing improved quality consistently.",
                    "evaluation_score": 0.88,
                },
            }
        )
        status = fa.status()
        kd = status["knowledge_distillation"]
        assert kd["layers"]["memory"]["entries"] >= 1
        # High-confidence event should be promoted to knowledge
        assert kd["layers"]["knowledge"]["entries"] >= 1

    def test_distill_knowledge_method(self) -> None:
        fa = self._make_foundation()
        event = {"type": "e", "source": "s", "payload": {}}
        mem = fa._knowledge_distillation.ingest_raw_event(event)
        result = fa.distill_knowledge(
            mem.memory_id,
            "routing",
            "Local routing reduces latency.",
            0.9,
        )
        assert result is not None
        assert result["concept"] == "routing"

    # Phase 5: Structural self-awareness
    def test_structural_snapshot_includes_subsystems(self) -> None:
        fa = self._make_foundation()
        fa.register_subsystem("event_bus", role="broker")
        fa.register_subsystem("knowledge_db", role="storage")
        snap = fa.structural_snapshot()
        assert "registered_subsystems" in snap
        assert snap["registered_subsystems"] >= 2
        assert "event_bus" in snap["dependency_graph"]

    # Phase 6: Local LLM consultation
    def test_consult_local_brain_returns_unavailable_when_not_set(self) -> None:
        fa = self._make_foundation()
        result = fa.consult_local_brain({"objective": "test"})
        assert result["available"] is False

    def test_consult_local_brain_with_stub_brain(self) -> None:
        fa = self._make_foundation()

        class StubBrain:
            model_name = "stub-model"

            def generate(self, prompt: str) -> str:
                return "Use local model for latency-sensitive tasks."

        fa.set_local_brain(StubBrain())
        result = fa.consult_local_brain(
            {"objective": "route a query", "prompt": "which model to use?"}
        )
        assert result["available"] is True
        assert "local model" in result["response"]

    # Phase 7: Provenance graph
    def test_provenance_link_records_parent_child(self) -> None:
        fa = self._make_foundation()
        fa.record_provenance_link("parent-01", "child-01")
        fa.record_provenance_link("parent-01", "child-02")
        lineage = fa.get_provenance_lineage("parent-01")
        assert "child-01" in lineage["children"]
        assert "child-02" in lineage["children"]

    def test_provenance_snapshot_in_status_includes_causal_fields(self) -> None:
        fa = self._make_foundation()
        fa.observe_event(
            {
                "type": "t",
                "source": "s",
                "payload": {"trace_id": "prov-1", "causal_parent": ""},
            }
        )
        status = fa.status()
        provenance = status["event_bus"]["last_event_provenance"]
        assert "causal_parent" in provenance
        assert "causal_children" in provenance

    # Phase 8: Behaviour adaptation through observe_event
    def test_observe_event_updates_behaviour_engine(self) -> None:
        fa = self._make_foundation()
        fa.observe_event(
            {
                "type": "reflection.complete",
                "source": "planner",
                "payload": {
                    "topic": "model-selection",
                    "summary": "qwen beats llama on coding.",
                    "evaluation_score": 0.90,
                },
            }
        )
        status = fa.status()
        beh = status["behaviour_adaptation"]
        assert beh["total_rules"] >= 1

    def test_adapt_behaviour_and_get_bias(self) -> None:
        fa = self._make_foundation()
        fa.adapt_behaviour(
            "routing",
            understanding_score=0.85,
            confidence=0.80,
            evidence="Local wins at latency",
        )
        bias = fa.get_decision_bias("trace-99", {"topic": "routing latency"})
        assert "bias_direction" in bias
        assert "applied_rules" in bias

    # Phase 9: ALE coordination via event bus
    def test_coordinate_ale_research_without_bus_returns_false(self) -> None:
        fa = self._make_foundation()
        result = fa.coordinate_ale_research("machine learning")
        assert result is False

    def test_coordinate_ale_research_with_mock_bus(self) -> None:
        fa = self._make_foundation()
        emitted: list[tuple] = []

        class MockBus:
            def emit(self, event_type: str, source: str, payload: dict) -> None:
                emitted.append((event_type, source, payload))

        fa.set_event_bus(MockBus())
        result = fa.coordinate_ale_research("neural networks", trace_id="nn-basics")
        assert result is True
        assert len(emitted) == 1
        assert emitted[0][0] == "ale.research_requested"
        assert emitted[0][2]["topic"] == "neural networks"

    # Phase 10: Unified Event Bus
    def test_coordinate_subsystem_emits_canonical_envelope(self) -> None:
        fa = self._make_foundation()
        emitted: list[tuple] = []

        class MockBus:
            def emit(self, event_type: str, source: str, payload: dict) -> None:
                emitted.append((event_type, source, payload))

        fa.set_event_bus(MockBus())
        fa.coordinate_subsystem("knowledge_db", "knowledge.store_requested", {"key": "val"})
        assert len(emitted) == 1
        payload = emitted[0][2]
        assert "coordinator" in payload
        assert payload["coordinator"] == "foundation_architecture"
        assert "target_subsystem" in payload
        assert "trace_id" in payload

    # Phase 11: Cognitive Journal
    def test_observe_event_writes_to_journal(self) -> None:
        fa = self._make_foundation()
        fa.observe_event(
            {
                "type": "response.complete",
                "source": "api",
                "payload": {
                    "trace_id": "j-1",
                    "summary": "Response delivered.",
                    "evaluation_score": 0.75,
                },
            }
        )
        status = fa.status()
        assert status["cognitive_journal"]["entry_count"] >= 1

    def test_record_cognitive_event_returns_entry_dict(self) -> None:
        fa = self._make_foundation()
        entry = fa.record_cognitive_event(
            trace_id="j-2",
            what_happened="Provider selected after consultation.",
            event_type="provider.selected",
            source_module="router",
            why_it_happened="LLM recommended local model.",
            how_it_happened="RoutingEngine.select",
            understanding_changed=["routing"],
            knowledge_created=["routing:local_preferred"],
        )
        assert entry["what_happened"] == "Provider selected after consultation."
        assert "routing" in entry["understanding_changed"]

    # Phase 12: Unified architecture
    def test_validate_unified_path_returns_report(self) -> None:
        fa = self._make_foundation()
        for sub in ["event_bus", "runtime_manager", "knowledge_db", "local_brain"]:
            fa.register_subsystem(sub, role=sub)
        report = fa.validate_unified_path()
        assert "unified_path" in report
        assert isinstance(report["missing"], list)
        assert isinstance(report["present"], list)

    def test_status_includes_all_phase_keys(self) -> None:
        fa = self._make_foundation()
        status = fa.status()
        # Phase 1
        assert "structural_awareness" in status
        # Phase 2
        assert "cognitive_loop" in status
        assert status["cognitive_loop"]["unified_feedback_path"] is True
        # Phase 4
        assert "knowledge_distillation" in status
        assert "distilled_knowledge" in status["memory_layers"]
        # Phase 8
        assert "behaviour_adaptation" in status
        # Phase 11
        assert "cognitive_journal" in status
        # Phase 12
        assert "unified_architecture" in status
        assert status["unified_architecture"]["one_cognitive_loop"] is True

    # Regression: existing Phase 1 assertions still hold
    def test_existing_observe_and_governance_still_work(self) -> None:
        fa = self._make_foundation()
        fa.observe_event(
            {
                "type": "reflection.complete",
                "source": "planner",
                "payload": {
                    "trace_id": "trace-1",
                    "topic": "provider routing quality",
                    "summary": "Local routing improved quality.",
                    "evaluation_score": 0.82,
                    "selected_module": "modules.local_brain",
                    "selected_function": "generate",
                    "adaptation_proposals": ["prefer local model for low-latency tasks"],
                },
            }
        )
        status = fa.status(
            provider_status={
                "active_provider": "qwen",
                "manager_status": {"provider_rankings": {"qwen": 0.92}},
            },
            cognitive_status={"reflections": [{"summary": "quality improved"}]},
            market_status={"experience_count": 3},
        )
        assert status["runtime_engineering"]["event_bus_only"] is True
        assert status["understanding_layer"]["concept_count"] >= 1
        assert status["runtime_dialogue"][-1]["event_type"] == "reflection.complete"
        assert status["memory_layers"]["reflection_memory"]["entries"] == 1
        assert status["governance"]["proposals"][-1]["requires_validation"] is True


# ── RuntimeManager wires new services ───────────────────────────────────────


class TestRuntimeManagerPhase2Wiring:
    def test_foundation_architecture_has_feedback_loop(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from core.runtime_manager import RuntimeManager

        monkeypatch.setattr(RuntimeManager, "_resolve_project_root", lambda self: tmp_path)
        monkeypatch.chdir(tmp_path)
        manager = RuntimeManager()
        foundation = manager.get_foundation_architecture()
        assert foundation._feedback_loop is not None, (
            "CognitiveFeedbackLoop should be wired into FoundationArchitecture"
        )

    def test_cognitive_feedback_loop_in_diagnostics(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from core.runtime_manager import RuntimeManager

        monkeypatch.setattr(RuntimeManager, "_resolve_project_root", lambda self: tmp_path)
        monkeypatch.chdir(tmp_path)
        manager = RuntimeManager()
        diagnostics = manager.get_diagnostics()
        assert "cognitive_feedback_loop" in diagnostics["services"]

    def test_foundation_registers_subsystems_from_service_registry(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        from core.runtime_manager import RuntimeManager

        monkeypatch.setattr(RuntimeManager, "_resolve_project_root", lambda self: tmp_path)
        monkeypatch.chdir(tmp_path)
        manager = RuntimeManager()
        foundation = manager.get_foundation_architecture()
        validation = foundation.validate_unified_path()
        # At minimum the services initialized by RuntimeManager should appear
        assert validation["registered_count"] >= 1
