from __future__ import annotations

from dataclasses import dataclass

from core.cognitive_contract import CognitiveExecutionRecord, normalize_event_envelope
from modules.cognitive_ingress import CognitiveIngress
from modules.unified_runtime import NiblitUnifiedRuntime
from niblit_memory import PersistenceManager


def test_normalize_event_envelope_populates_canonical_fields() -> None:
    envelope = normalize_event_envelope(
        event_type="execution.complete",
        source="test",
        payload={"response": "ok"},
        runtime_id="rt-1",
    )

    assert envelope.payload["trace_id"]
    assert envelope.payload["runtime_id"] == "rt-1"
    assert envelope.payload["cognition_id"]
    assert envelope.event_category == "orchestration"


def test_persistence_manager_checkpoint_round_trip(tmp_path) -> None:
    manager = PersistenceManager(root_dir=str(tmp_path))
    manager.initialize_runtime_assets()

    manager.write_cognitive_checkpoint("chk-1", {"status": "pending", "trace_id": "trace-1"})
    loaded = manager.read_cognitive_checkpoint("chk-1")

    assert loaded["status"] == "pending"
    assert loaded["trace_id"] == "trace-1"


@dataclass
class _FakeProfile:
    intent: str = "operational"
    confidence: float = 0.9

    def to_dict(self):
        return {"intent": self.intent, "confidence": self.confidence}


@dataclass
class _FakeMode:
    mode_name: str = "operational"
    intent: str = "operational"
    confidence: float = 0.9
    run_governance: bool = True


@dataclass
class _FakeExecResult:
    response: str = "done"
    steps_run: list[str] = None
    tools_called: list[str] = None
    forecast_signal: str = "HOLD"
    reflection_notes: str = "mode=operational"
    elapsed_ms: float = 12.0
    quality_score: float = 0.8
    step_results: list = None

    def __post_init__(self):
        self.steps_run = self.steps_run or ["retrieve_memory", "call_tools", "reflect"]
        self.tools_called = self.tools_called or ["calculator"]
        self.step_results = self.step_results or []


class _DummyMemory:
    def __init__(self) -> None:
        self.stored = []

    def recall_contract(self, request):
        return [{"uid": "mem-1", "text": request.normalized_text}]

    def remember_contract(self, record):
        self.stored.append(record.to_dict())
        return "mem-x"


class _DummyKnowledgeDB:
    def __init__(self) -> None:
        self.facts = []

    def add_fact(self, key, value, tags=None):
        self.facts.append((key, value, tags or []))


class _DummyProvenance:
    def __init__(self) -> None:
        self.updates = []
        self.checkpoints = []

    def update(self, trace_id, **kwargs):
        self.updates.append((trace_id, kwargs))
        return {"trace_id": trace_id, **kwargs}

    def save_checkpoint(self, checkpoint):
        self.checkpoints.append(checkpoint.to_dict())

    def get(self, trace_id):
        return {"trace_id": trace_id}


class _DummyArchitecture:
    def __init__(self) -> None:
        self.events = []

    def observe_event(self, event, lineage_channel=""):
        self.events.append((event, lineage_channel))


def test_cognitive_ingress_enforces_contract_with_specialists(monkeypatch) -> None:
    ingress = CognitiveIngress(
        unified_memory=_DummyMemory(),
        knowledge_db=_DummyKnowledgeDB(),
        provenance_service=_DummyProvenance(),
        architecture_model=_DummyArchitecture(),
    )

    monkeypatch.setattr(ingress, "_intent_engine", lambda: type("Engine", (), {"classify": lambda self, text: _FakeProfile()})())
    monkeypatch.setattr(ingress, "_router", lambda: type("Router", (), {"route": lambda self, profile: _FakeMode()})())
    monkeypatch.setattr(ingress, "_graph", lambda: type("Graph", (), {"run": lambda self, text, context=None, mode=None: _FakeExecResult()})())

    execution = ingress.ingest("run calculator", source="cli")

    assert execution.request_id
    assert execution.trace_id
    assert execution.selected_function == "ExecutionGraph.run"
    assert execution.tools_called == ["calculator"]


def test_unified_runtime_run_cognitive_cycle_returns_contract_payload(monkeypatch, tmp_path) -> None:
    runtime = NiblitUnifiedRuntime(state_file=tmp_path / "runtime.json")

    def _fake_ingest(self, text, source="api", metadata=None):
        return CognitiveExecutionRecord(
            request_id="req-1",
            trace_id="trace-1",
            cognition_id="cog-1",
            mode_name="operational",
            intent="operational",
            response=f"handled:{text}",
            steps_run=["normalize", "execute"],
            tools_called=["tool"],
            quality_score=0.7,
        )

    monkeypatch.setattr("modules.cognitive_ingress.CognitiveIngress.ingest", _fake_ingest)
    payload = runtime.run_cognitive_cycle("do thing", source="api")

    assert payload["request_id"] == "req-1"
    assert payload["response"] == "handled:do thing"
    assert any(event["type"] == "cognitive.execution.completed" for event in runtime.events(since=0, limit=20))
