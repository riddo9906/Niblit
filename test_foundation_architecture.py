from __future__ import annotations

from pathlib import Path

from core.runtime_manager import RuntimeManager
from modules.foundation_architecture import FoundationArchitecture
from modules.unified_runtime import NiblitUnifiedRuntime


def test_foundation_architecture_tracks_dialogue_understanding_and_governance() -> None:
    foundation = FoundationArchitecture(runtime_id="rt-foundation")

    foundation.observe_event(
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

    status = foundation.status(
        provider_status={"active_provider": "qwen", "manager_status": {"provider_rankings": {"qwen": 0.92}}},
        cognitive_status={"reflections": [{"summary": "quality improved"}]},
        market_status={"experience_count": 3},
    )

    assert status["runtime_engineering"]["event_bus_only"] is True
    assert status["understanding_layer"]["concept_count"] >= 1
    assert status["runtime_dialogue"][-1]["event_type"] == "reflection.complete"
    assert status["memory_layers"]["reflection_memory"]["entries"] == 1
    assert status["governance"]["proposals"][-1]["requires_validation"] is True


def test_runtime_manager_registers_foundation_architecture_service(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(RuntimeManager, "_resolve_project_root", lambda self: tmp_path)
    monkeypatch.chdir(tmp_path)
    runtime = RuntimeManager()

    diagnostics = runtime.get_diagnostics()

    assert "foundation_architecture" in diagnostics["services"]
    assert diagnostics["services"]["foundation_architecture"]["status"] == "ready"
    assert "foundation_architecture" in diagnostics["extension_points"]


def test_unified_runtime_state_and_stream_include_foundation_status(tmp_path: Path) -> None:
    runtime = NiblitUnifiedRuntime(state_file=tmp_path / "runtime_state.json")
    runtime.ingest_external_event(
        event_type="response.complete",
        source="foundation_test",
        payload={
            "trace_id": "foundation-trace-1",
            "topic": "unified runtime foundation",
            "summary": "The runtime updated understanding from feedback.",
            "evaluation_score": 0.76,
            "selected_module": "modules.local_brain",
            "selected_function": "generate",
        },
    )

    state = runtime.state(core=None)
    frame = runtime.stream_frame(core=None, since=0)

    assert "foundation" in state
    assert "memory_layers" in state["state"]
    assert state["state"]["runtime_dialogue"]
    assert "foundation" in frame
    assert "runtime_dialogue" in frame
    assert "understanding_layer" in frame
