from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from modules.unified_runtime import (
    NiblitUnifiedRuntime,
    ProviderRuntimeManager,
    RuntimeEventBus,
)


def test_event_bus_emit_and_replay() -> None:
    bus = RuntimeEventBus()
    bus.emit("provider.started", "test", {"provider": "qwen"})
    bus.emit("provider.failed", "test", {"provider": "hf"})
    events = bus.events(since=0, limit=10)
    assert len(events) == 2
    assert events[0]["type"] == "provider.started"
    assert events[1]["type"] == "provider.failed"
    assert "significance" in events[0]


def test_event_bus_since_cursor() -> None:
    bus = RuntimeEventBus()
    e1 = bus.emit("a", "t", {})
    bus.emit("b", "t", {})
    events = bus.events(since=e1.id, limit=10)
    assert len(events) == 1
    assert events[0]["type"] == "b"


def test_provider_runtime_set_active_unknown() -> None:
    mgr = ProviderRuntimeManager(RuntimeEventBus())
    out = mgr.set_active("unknown-provider")
    assert "Unknown provider" in out


def test_provider_runtime_route_prefers_local_for_offline() -> None:
    mgr = ProviderRuntimeManager(RuntimeEventBus())
    selected, _ = mgr._route_provider(  # pylint: disable=protected-access
        task_type="fast",
        local_first=True,
        offline_mode=True,
        context_window=None,
    )
    assert selected in {"qwen", "local_llama"}


def test_provider_runtime_generate_normalized_shape() -> None:
    mgr = ProviderRuntimeManager(RuntimeEventBus())
    fake_mgr = MagicMock()
    fake_mgr.ask.return_value = "hello from provider"
    fake_mgr.switch.return_value = "ok"
    fake_mgr.status.return_value = {"active": "qwen", "qwen": True, "hf": True, "anthropic": True, "ruflo": True}
    fake_rr_cls = MagicMock()
    fake_rr = MagicMock()
    fake_rr.generate.return_value = ""
    fake_rr_cls.return_value = fake_rr

    with patch("modules.llm_provider_manager.get_llm_provider_manager", return_value=fake_mgr), patch(
        "modules.runtime_router_v2.NiblitUnifiedRuntimeRouterV2", fake_rr_cls
    ):
        out = mgr.generate(prompt="hello", task_type="general", local_first=False)

    assert out["stream_format"] == "niblit.runtime.stream.v1"
    assert out["type"] == "inference.result"
    assert "telemetry" in out
    assert "provider" in out
    assert "market_intelligence" in out["telemetry"]


def test_unified_runtime_dispatch_runtime_status(tmp_path: Path) -> None:
    state_file = tmp_path / "runtime_state.json"
    rt = NiblitUnifiedRuntime(state_file=state_file)
    out = rt.dispatch_command(command="runtime status", core=None)
    assert "runtime_mode" in out


def test_unified_runtime_state_persistence(tmp_path: Path) -> None:
    state_file = tmp_path / "runtime_state.json"
    rt = NiblitUnifiedRuntime(state_file=state_file)
    rt.dispatch_command(command="runtime provider qwen", core=None)
    state = rt.state(core=None)["state"]
    assert state_file.exists()
    reloaded = NiblitUnifiedRuntime(state_file=state_file)
    new_state = reloaded.state(core=None)["state"]
    assert new_state["active_provider"] == state["active_provider"]


def test_unified_runtime_stream_frame_shape(tmp_path: Path) -> None:
    rt = NiblitUnifiedRuntime(state_file=tmp_path / "runtime_state.json")
    frame = rt.stream_frame(core=None, since=0)
    assert frame["stream_format"] == "niblit.runtime.stream.v1"
    assert frame["type"] == "runtime.frame"
    assert "state" in frame
    assert "telemetry" in frame
    assert "events" in frame
    assert "episodes" in frame
    assert "confidence" in frame


def test_unified_runtime_promotes_high_signal_episodes(tmp_path: Path) -> None:
    rt = NiblitUnifiedRuntime(state_file=tmp_path / "runtime_state.json")
    rt.ingest_external_event(
        event_type="reflection.complete",
        source="reflection_engine",
        payload={
            "trace_id": "trace-1",
            "cognition_id": "cog-1",
            "topic": "provider routing quality",
            "reflection_summary": "Provider effectiveness drift detected and memory usefulness degraded.",
            "evaluation_score": 0.84,
            "provider": "qwen",
            "memory_id": "mem-1",
        },
    )
    episodes = rt.episodes(limit=10)
    assert episodes
    assert episodes[-1]["trace_id"] == "trace-1"
    assert episodes[-1]["confidence_breakdown"]["synthesis_confidence"] > 0


def test_unified_runtime_episode_includes_causality_and_metaevaluation(tmp_path: Path) -> None:
    rt = NiblitUnifiedRuntime(state_file=tmp_path / "runtime_state.json")
    rt.ingest_external_event(
        event_type="response.complete",
        source="evaluation_engine",
        payload={
            "trace_id": "trace-causal-1",
            "cognition_id": "cog-causal-1",
            "topic": "provider influence",
            "evaluation_score": 0.78,
            "quality_score": 0.78,
            "provider": "qwen",
            "memory_id": "mem-causal-1",
            "runtime_mode": "api",
            "event_priority": "high",
            "decision_lineage": ["retrieval", "reflection", "evaluation"],
            "downstream_effect": "learning.cycle.complete",
        },
    )
    episodes = rt.episodes(limit=10)
    assert episodes
    latest = episodes[-1]
    assert "causal_influences" in latest
    assert "provider_influence" in latest["causal_influences"]
    assert "metaevaluation" in latest
    assert "runtime_coherence" in latest["metaevaluation"]
    state = rt.state(core=None)
    assert "causality" in state["cognition"]


def test_unified_runtime_cognition_recovery_command(tmp_path: Path) -> None:
    rt = NiblitUnifiedRuntime(state_file=tmp_path / "runtime_state.json")
    raw = rt.dispatch_command(command="runtime cognition recovery", core=None)
    data = json.loads(raw)
    assert "A_historical_cognition_topology_map" in data
    assert "F_causal_cognition_architecture" in data
    assert "K_actual_implementation" in data


def test_unified_runtime_market_intelligence_command(tmp_path: Path) -> None:
    rt = NiblitUnifiedRuntime(state_file=tmp_path / "runtime_state.json")
    rt.ingest_external_event(
        event_type="market_regime.forecast",
        source="predictive_world_model",
        payload={
            "trace_id": "market-trace-1",
            "topic": "btc volatile breakout",
            "symbol": "BTCUSDT",
            "regime": "volatile",
            "volatility_regime": "high",
            "confidence_score": 0.62,
            "evaluation_score": 0.58,
            "signal": "breakout",
            "signal_strength": 0.71,
            "drawdown": 0.22,
            "exposure": 0.48,
            "concentration_risk": 0.34,
            "uncertainty": 0.67,
        },
    )
    raw = rt.dispatch_command(command="market intelligence", core=None)
    data = json.loads(raw)
    assert data["experience_count"] >= 1
    assert data["market_cognition_timeline"]
    assert data["risk_intelligence"]
    assert data["dqi_scores"]


def test_unified_runtime_state_and_stream_include_market_intelligence(tmp_path: Path) -> None:
    rt = NiblitUnifiedRuntime(state_file=tmp_path / "runtime_state.json")
    rt.ingest_external_event(
        event_type="trade_reflection.ingested",
        source="reflection_engine",
        payload={
            "trace_id": "market-stream-1",
            "topic": "eth drawdown replay",
            "symbol": "ETHUSDT",
            "regime": "bear",
            "volatility_regime": "medium",
            "reflection_summary": "Risk controls mattered more than confidence.",
            "confidence_score": 0.44,
            "evaluation_score": 0.69,
            "drawdown": 0.31,
            "exposure": 0.27,
            "concentration_risk": 0.12,
            "uncertainty": 0.55,
        },
    )
    state = rt.state(core=None)
    assert "market_intelligence" in state["state"]
    assert state["state"]["market_intelligence"]["experience_count"] >= 1
    frame = rt.stream_frame(core=None, since=0)
    assert "market_intelligence" in frame
    assert frame["market_intelligence"]["experience_count"] >= 1


def test_unified_runtime_filters_repetitive_noise(tmp_path: Path) -> None:
    rt = NiblitUnifiedRuntime(state_file=tmp_path / "runtime_state.json")
    for _ in range(8):
        rt.ingest_external_event(
            event_type="telemetry.tick",
            source="telemetry",
            payload={"event_priority": "normal"},
        )
    assert rt.episodes(limit=20) == []


@pytest.fixture()
def server_client():
    mock_core = MagicMock()
    mock_core.db.get_personality.return_value = {"mood": "steady"}
    mock_core.db.list_facts.return_value = [{"key": "a", "value": "b"}]
    mock_core.handle.return_value = "core-handle-reply"
    mock_core.autonomous_engine = None

    runtime = MagicMock()
    runtime.boot.return_value = {"ok": True}
    runtime.dispatch_command.return_value = "runtime-dispatch-reply"
    runtime.state.return_value = {
        "state": {
            "runtime_mode": "api",
            "active_provider": "qwen",
            "deployment": {"environment": "local"},
        },
        "providers": {"health": {}},
        "telemetry": {"threads": 2, "facts_count": 1},
        "events": {"event_counts": {"boot.sequence": 1}},
        "cognition": {
            "episodes": [{"episode_id": "ep-1", "topic": "runtime ready"}],
            "reflections": [{"type": "session", "summary": "stable"}],
            "datasets": {"pending_candidates": 1},
            "compression": {"semantic_clusters": []},
            "confidence_summary": {"synthesis_confidence": 0.75},
        },
    }
    runtime.events.return_value = [{"id": 1, "type": "boot.sequence", "source": "runtime", "payload": {}}]
    runtime.episodes.return_value = [{"episode_id": "ep-1", "topic": "runtime ready"}]
    runtime.stream_frame.return_value = {
        "stream_format": "niblit.runtime.stream.v1",
        "type": "runtime.frame",
        "state": {"runtime_mode": "api", "active_provider": "qwen"},
        "telemetry": {"threads": 2, "facts_count": 1},
        "events": [{"id": 1, "type": "telemetry.update", "source": "runtime", "payload": {}}],
        "provider": {"active_provider": "qwen"},
        "episodes": [{"episode_id": "ep-1"}],
        "reflections": [{"type": "session"}],
        "dataset": {"pending_candidates": 1},
        "compression": {"semantic_clusters": []},
        "confidence": {"synthesis_confidence": 0.75},
    }

    with patch("server.get_core", return_value=mock_core), patch("server.get_unified_runtime", return_value=runtime):
        import server as srv

        srv._core = mock_core  # pylint: disable=protected-access
        client = TestClient(srv.app, raise_server_exceptions=False)
        yield client, runtime


def test_server_runtime_state_endpoint(server_client) -> None:
    client, _ = server_client
    resp = client.get("/api/runtime/state")
    assert resp.status_code == 200
    data = resp.json()
    assert "state" in data
    assert data["state"]["active_provider"] == "qwen"


def test_server_runtime_events_endpoint(server_client) -> None:
    client, _ = server_client
    resp = client.get("/api/runtime/events?since=0&limit=20")
    assert resp.status_code == 200
    data = resp.json()
    assert "events" in data
    assert isinstance(data["events"], list)


def test_server_runtime_episodes_endpoint(server_client) -> None:
    client, runtime = server_client
    resp = client.get("/api/runtime/episodes?limit=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "episodes" in data
    assert "reflections" in data
    runtime.episodes.assert_called()


def test_server_chat_uses_runtime_dispatch(server_client) -> None:
    client, runtime = server_client
    resp = client.post("/chat", json={"text": "status"})
    assert resp.status_code == 200
    assert resp.json()["reply"] == "runtime-dispatch-reply"
    runtime.dispatch_command.assert_called()


def test_server_boot_calls_runtime_boot(server_client) -> None:
    client, runtime = server_client
    resp = client.get("/api/boot")
    assert resp.status_code == 200
    runtime.boot.assert_called()


def test_server_bg_status_contains_runtime(server_client) -> None:
    client, _ = server_client
    resp = client.get("/api/bg_status")
    assert resp.status_code == 200
    data = resp.json()
    assert "runtime" in data
    assert "active_provider" in data["runtime"]


def test_server_status_contains_runtime(server_client) -> None:
    client, _ = server_client
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "runtime" in data
    assert "active_provider" in data["runtime"]


def test_runtime_websocket_stream(server_client) -> None:
    client, _ = server_client
    with client.websocket_connect("/ws/runtime") as ws:
        msg = ws.receive_json()
        assert msg["stream_format"] == "niblit.runtime.stream.v1"
        assert msg["type"] == "runtime.frame"
