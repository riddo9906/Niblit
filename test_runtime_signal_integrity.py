from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from core.event_bus import EventType
from core.runtime_manager import RuntimeManager
from modules.event_bus import EventBus as ModuleEventBus
from modules.event_bus import NiblitEvent
from modules.governed_live_cognition import GovernedLiveCognitionCollector
from modules.unified_runtime import NiblitUnifiedRuntime


class _FakeUnifiedRuntime:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict]] = []

    def ingest_external_event(self, *, event_type: str, source: str, payload: dict | None = None) -> None:
        self.events.append((event_type, source, dict(payload or {})))


class _StubRouter:
    def generate(self, prompt: str, context: str | None = None) -> str:  # noqa: ARG002
        return "Fresh governed summary with source metadata and confidence notes."


class _StubKnowledgeDB:
    def __init__(self) -> None:
        self.facts: list[tuple[str, object, list[str]]] = []

    def add_fact(self, key: str, value: object, tags: list[str] | None = None) -> None:
        self.facts.append((key, value, list(tags or [])))


class _StubBrainTrainer:
    def __init__(self) -> None:
        self.records: list[tuple[str, str]] = []

    def ingest_research(self, topic: str, text: str) -> None:
        self.records.append((topic, text))


class _StubCluster:
    def __init__(self) -> None:
        self.writes: list[tuple[str, str, dict]] = []

    def write_memory(self, text: str, *, memory_type: str = "semantic_memory", payload: dict | None = None) -> dict:
        self.writes.append((text, memory_type, dict(payload or {})))
        return {"stored": True}


def test_runtime_manager_bridges_module_learning_events() -> None:
    module_bus = ModuleEventBus()
    fake_runtime = _FakeUnifiedRuntime()
    with patch("modules.event_bus.get_event_bus", return_value=module_bus), patch(
        "modules.unified_runtime.get_unified_runtime", return_value=fake_runtime
    ):
        rm = RuntimeManager()
        received: list[str] = []
        rm.subscribe(EventType.LEARNING_CYCLE_COMPLETED, lambda event: received.append(event.type_name))
        module_bus.publish(
            NiblitEvent(
                type="learning.cycle.complete",
                source="ale",
                payload={"cycle": 1},
            )
        )

    assert received == [EventType.LEARNING_CYCLE_COMPLETED.value]
    report = rm.event_bus.observability_report()
    assert report["total_emissions"] >= 2
    assert fake_runtime.events
    assert fake_runtime.events[-1][0] == "learning.cycle.complete"


def test_governed_live_cognition_persists_governed_outputs() -> None:
    collector = GovernedLiveCognitionCollector()
    knowledge_db = _StubKnowledgeDB()
    brain_trainer = _StubBrainTrainer()
    cluster = _StubCluster()
    module_bus = ModuleEventBus()
    captured: list[str] = []
    module_bus.subscribe_all(lambda event: captured.append(event.type))
    with patch("modules.event_bus.get_event_bus", return_value=module_bus), patch(
        "niblit_memory.governed_qdrant_memory.get_governed_qdrant_memory_cluster", return_value=cluster
    ):
        result = collector.ingest(
            query="python asyncio task groups",
            items=[{"text": "TaskGroup coordinates async tasks.", "source": "docs"}],
            source_type="technical_documentation",
            source_module="self_researcher",
            router=_StubRouter(),
            knowledge_db=knowledge_db,
            brain_trainer=brain_trainer,
            runtime_id="runtime-test",
        )

    assert result["success"] is True
    assert knowledge_db.facts
    assert brain_trainer.records
    assert cluster.writes
    assert "live.ingestion.completed" in captured
    assert "memory.synthesis.created" in captured


def test_unified_runtime_ingests_module_events(tmp_path: Path) -> None:
    module_bus = ModuleEventBus()
    with patch("modules.event_bus.get_event_bus", return_value=module_bus):
        runtime = NiblitUnifiedRuntime(state_file=tmp_path / "runtime_state.json")
        module_bus.publish(
            NiblitEvent(
                type="cognition.synthesis.complete",
                source="knowledge_gap_cognition",
                payload={"trace_id": "abc123"},
            )
        )

    events = runtime.events(since=0, limit=20)
    assert any(event["type"] == "cognition.synthesis.complete" for event in events)
    stats = runtime.state(core=None)["events"]
    assert "dropped_events" in stats
    assert "unconsumed_events" in stats
