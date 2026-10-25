"""Phase 5C tests: governed tool runtime for the canonical Core boundary.

Covers: capability registration + absence of execution surface; run_research
single-flight guard, missing-topic and structural-failure handling; store/
EventBus wiring with budget clamps; truthful trading unavailability vs real
runtime; singleton identity; /v1/inference/chat enable_tools branch.
"""
from __future__ import annotations

import json

import pytest

import modules.core_tool_runtime as ctr
from modules.core_tool_runtime import (
    HARD_CAP_FETCHES,
    HARD_CAP_ROUNDS,
    HARD_CAP_SEARCHES,
    ORIGINAL_READONLY_PROMOTIONS,
    build_governed_tool_loop,
    get_governed_tool_loop,
    reset_governed_tool_loop,
)
from modules.event_bus import get_event_bus
from modules.tiered_knowledge_system import get_tiered_knowledge_system
from modules.trading_read_tools import FORBIDDEN_EXECUTION_NAMES

EXPECTED_TOOLS = {"runtime_status", "web_search", "web_fetch",
                  "trading_runtime_status", "run_research",
                  # Phase 5D: governed workspace surface (bounded, no
                  # arbitrary execution; run_tests is a fixed pytest command
                  # behind a single-flight lock).
                  "workspace_list", "workspace_search", "workspace_read",
                  "workspace_read_pdf", "workspace_inspect_python",
                  "workspace_write", "workspace_edit", "run_tests",
                  # Phase 5F: restored ORIGINAL knowledge commands
                  "recall", "acquired_data", "knowledge_stats", "memory",
                  # Phase 5G: evidence-traced ORIGINAL read-only commands
                  } | {spec["canonical_id"]
                       for spec in ORIGINAL_READONLY_PROMOTIONS.values()}


class FakeCore:
    def __init__(self, db=None, runtime=None):
        self.db = db
        self.trading_runtime_manager = runtime


class FakeResult:
    def __init__(self, artifact):
        self._artifact = artifact

    def artifact(self):
        return self._artifact


ARTIFACT = {
    "promotion": {"status": "approved", "reasons": ["all checks passed"]},
    "stored": "cand123",
    "recall": {"verified": True, "claim_hit": "claim"},
    "usage": {"rounds": 1, "searches": 1, "fetches": 1, "llm_chat_calls": 3},
    "errors": [],
    "candidate": {"learned_claims": ["claim one", "claim two"]},
    "events": [{"type": "research.started"},
               {"type": "research.completed"}],
}


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_governed_tool_loop()
    yield
    reset_governed_tool_loop()


def test_build_loop_registers_all_capabilities_and_no_execution():
    loop = build_governed_tool_loop(lambda: FakeCore())
    assert set(loop.allowed_tool_names()) == EXPECTED_TOOLS
    for name in FORBIDDEN_EXECUTION_NAMES:
        assert name not in loop.allowed_tool_names()
        assert name not in json.dumps(getattr(loop, "_schemas", {}))
    for schema in loop._schemas.values():
        assert schema["type"] == "function"
        assert "parameters" in schema["function"]


def test_run_research_missing_topic():
    loop = build_governed_tool_loop(lambda: FakeCore())
    assert loop._tool_map["run_research"]() == {"error": "missing_topic"}


def test_run_research_single_flight_guard():
    loop = build_governed_tool_loop(lambda: FakeCore())
    assert ctr._RESEARCH_LOCK.acquire(blocking=False)
    try:
        out = loop._tool_map["run_research"](topic="t")
        assert out["error"] == "research_run_in_progress"
    finally:
        ctr._RESEARCH_LOCK.release()


def test_run_research_wires_store_bus_and_clamps_budgets(monkeypatch):
    sentinel_db = object()
    captured = {}

    class FakeOrchestrator:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def run(self, topic):
            assert topic == "some topic"
            return FakeResult(ARTIFACT)

    monkeypatch.setattr(ctr, "ResearchOrchestrator", FakeOrchestrator)
    loop = build_governed_tool_loop(lambda: FakeCore(db=sentinel_db))
    out = loop._tool_map["run_research"](
        topic="some topic", max_searches=99, max_fetches=99, max_rounds=99)

    assert out["promotion"]["status"] == "approved"
    assert out["claims"] == ["claim one", "claim two"]
    assert out["event_types"] == ["research.started", "research.completed"]
    assert captured["max_searches"] == HARD_CAP_SEARCHES
    assert captured["max_fetches"] == HARD_CAP_FETCHES
    assert captured["max_rounds"] == HARD_CAP_ROUNDS
    assert captured["event_bus"] is get_event_bus()
    store = captured["knowledge_store"]
    assert store is get_tiered_knowledge_system()
    assert store.knowledge_db is sentinel_db


def test_run_research_structural_failure_does_not_raise(monkeypatch):
    class BoomOrchestrator:
        def __init__(self, **kwargs):
            pass

        def run(self, topic):
            raise RuntimeError("cloud unreachable")

    monkeypatch.setattr(ctr, "ResearchOrchestrator", BoomOrchestrator)
    loop = build_governed_tool_loop(lambda: FakeCore())
    out = loop._tool_map["run_research"](topic="t")
    assert "research_failed" in out["error"]


def test_trading_truthful_real_runtime_and_unavailable():
    class Runtime:
        state = "ready"
        backend = "paper"
        execution_mode = "paper"
        market_data_provider = "synthetic"
        execution_enabled = False

    loop = build_governed_tool_loop(lambda: FakeCore(runtime=Runtime()))
    status = loop._tool_map["trading_runtime_status"]()
    assert status["available"] is True
    assert status["state"] == "ready"
    assert status["read_only"] is True

    none_loop = build_governed_tool_loop(lambda: FakeCore())
    assert none_loop._tool_map["trading_runtime_status"]() == {
        "available": False,
        "reason": "trading_runtime_not_initialized",
        "execution_tools_exposed": False,
    }


def test_singleton_returns_same_instance():
    first = get_governed_tool_loop(lambda: FakeCore())
    second = get_governed_tool_loop(lambda: FakeCore())
    assert first is second


# ---------------------------------------------------------------------------
# /v1/inference/chat enable_tools branch (canonical Core entry)
# ---------------------------------------------------------------------------

def _client():
    testclient = pytest.importorskip("fastapi.testclient")
    import server as server_module
    return testclient.TestClient(server_module.app), server_module


def test_inference_chat_tools_branch(monkeypatch):
    client, server_module = _client()

    class FakeLoop:
        def __init__(self):
            self.calls = []

        def chat(self, messages, tools=None, model="x"):
            self.calls.append({"messages": messages, "model": model})
            return {"text": "done",
                    "trace": [{"tool": "trading_runtime_status",
                               "status": "success"}],
                    "niblit_model": {"executed_model": model,
                                     "fallback": False}}

    fake = FakeLoop()
    monkeypatch.setattr(server_module, "get_core", lambda: FakeCore())
    monkeypatch.setattr(ctr, "get_governed_tool_loop",
                        lambda getter=None: fake)

    resp = client.post("/v1/inference/chat", json={
        "request_id": "test-1",
        "messages": [{"role": "user", "content": "status?"}],
        "enable_tools": True,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["tools_enabled"] is True
    assert body["text"] == "done"
    assert body["tool_trace"][0]["tool"] == "trading_runtime_status"
    assert body["niblit_model"]["executed_model"] == "qwen2.5-coder-3b"
    assert fake.calls[0]["model"] == "qwen2.5-coder-3b"  # "local" mapped
    assert fake.calls[0]["messages"][0]["content"] == "status?"


def test_inference_chat_rejects_stream_with_tools():
    client, _ = _client()
    resp = client.post("/v1/inference/chat", json={
        "messages": [{"role": "user", "content": "q"}],
        "enable_tools": True,
        "stream": True,
    })
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "unsupported_combination"
