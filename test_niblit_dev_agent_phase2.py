#!/usr/bin/env python3
"""Focused Phase 2 tests for NiblitDevAgent governed development task runtime."""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.niblit_dev_agent.agent import NiblitDevAgent
from agents.niblit_dev_agent.architecture_indexer import ArchitectureIndexer
from agents.niblit_dev_agent.event_subscriber import EventSubscriber
from agents.niblit_dev_agent.filesystem_guard import FilesystemGuard, FilesystemGuardError
from agents.niblit_dev_agent.memory_bridge import MemoryBridge
from agents.niblit_dev_agent.planning_engine import PlanningEngine
from agents.niblit_dev_agent.task_contracts import (
    APPROVAL_PENDING,
    EXEC_PLANNING,
    EXEC_QUEUED,
    DevTaskContract,
    ImpactAssessment,
)
from agents.niblit_dev_agent.telemetry_hooks import DevAgentTelemetryHooks
from core.event_bus import Event, EventBus, EventType

# ── Test stubs ────────────────────────────────────────────────────────────────


class _StubTelemetry:
    def __init__(self):
        self.counters: dict = {}
        self.gauges: dict = {}
        self.timings: dict = {}

    def increment_counter(self, name, value=1):
        self.counters[name] = self.counters.get(name, 0) + value

    def set_gauge(self, name, value):
        self.gauges[name] = value

    def record_timing(self, name, value):
        self.timings.setdefault(name, []).append(value)

    def get_stats(self):
        return {"counters": self.counters, "gauges": self.gauges, "timings": self.timings}


class _StubProviderManager:
    def status(self):
        return {"active": "qwen", "qwen": True, "hf": False, "anthropic": False, "ruflo": True}


class _StubRouterV2:
    def last_route(self):
        return {"backend": "http", "error": None}


class _StubLocalBrain:
    def status(self):
        return {"backend_in_use": "http", "model_name": "qwen2.5", "llama_server_url": "http://127.0.0.1:8000"}


def _make_agent(tmp_root: Path) -> NiblitDevAgent:
    bus = EventBus()
    return NiblitDevAgent(
        core=None,
        runtime_manager=None,
        event_bus=bus,
        telemetry=_StubTelemetry(),
        local_brain=_StubLocalBrain(),
        router_v2=_StubRouterV2(),
        llm_provider_manager=_StubProviderManager(),
        repo_root=str(tmp_root),
    )


def _make_indexer(tmp_root: Path) -> ArchitectureIndexer:
    (tmp_root / "niblit_core.py").write_text("# core\n")
    (tmp_root / "core").mkdir(exist_ok=True)
    (tmp_root / "core" / "event_bus.py").write_text("# bus\n")
    (tmp_root / "modules").mkdir(exist_ok=True)
    (tmp_root / "modules" / "runtime_router_v2.py").write_text("# rr\n")
    (tmp_root / "modules" / "local_brain.py").write_text("# lb\n")
    return ArchitectureIndexer(tmp_root)


# ── 1. DevTaskContract dataclass ──────────────────────────────────────────────


def test_dev_task_contract_defaults():
    c = DevTaskContract(scope="test_scope")
    assert c.approval_state == APPROVAL_PENDING
    assert c.execution_state == EXEC_QUEUED
    assert isinstance(c.task_id, str) and len(c.task_id) > 0
    assert c.runtime_impact.affected is False


def test_dev_task_contract_round_trip():
    c = DevTaskContract(
        scope="core",
        description="touch niblit_core",
        affected_modules=["niblit_core.py"],
        runtime_impact=ImpactAssessment(affected=True, severity="high"),
    )
    d = c.to_dict()
    restored = DevTaskContract.from_dict(d)
    assert restored.scope == "core"
    assert restored.runtime_impact.affected is True
    assert restored.runtime_impact.severity == "high"
    assert restored.affected_modules == ["niblit_core.py"]


# ── 2. PlanningEngine ─────────────────────────────────────────────────────────


def test_planning_engine_produces_contract(tmp_path):
    idx = _make_indexer(tmp_path)
    tel = DevAgentTelemetryHooks(_StubTelemetry())
    engine = PlanningEngine(architecture_indexer=idx, telemetry=tel)

    contract = engine.plan_task(
        scope="runtime",
        description="Modify niblit_core",
        affected_modules=["niblit_core.py"],
    )

    assert contract.scope == "runtime"
    assert contract.execution_state == EXEC_PLANNING
    # niblit_core.py is a runtime-critical path — should raise impact
    assert contract.runtime_impact.affected is True
    assert contract.runtime_impact.severity in {"high", "medium"}
    assert "planning_duration_ms" in contract.metadata


def test_planning_engine_no_affected_modules(tmp_path):
    idx = _make_indexer(tmp_path)
    tel = DevAgentTelemetryHooks(_StubTelemetry())
    engine = PlanningEngine(architecture_indexer=idx, telemetry=tel)

    contract = engine.plan_task(scope="docs", affected_modules=[])
    # No modules → all impacts should be non-affected
    assert contract.runtime_impact.affected is False
    assert contract.provider_impact.affected is False


def test_planning_engine_analyze_scope_returns_context(tmp_path):
    idx = _make_indexer(tmp_path)
    tel = DevAgentTelemetryHooks(_StubTelemetry())
    engine = PlanningEngine(
        architecture_indexer=idx,
        telemetry=tel,
        provider_snapshot={"active_provider": "qwen", "fallback_available": True},
        runtime_snapshot={"deployment_mode": "local", "runtime_topology": {"runtime_mode": "normal"}},
    )

    report = engine.analyze_scope("niblit_core")
    assert report["scope"] == "niblit_core"
    assert "touched_modules" in report
    assert "niblit_core.py" in report["touched_modules"]
    assert report["provider_context"]["active_provider"] == "qwen"


def test_planning_engine_rollback_strategy_none_for_safe_scope(tmp_path):
    idx = _make_indexer(tmp_path)
    tel = DevAgentTelemetryHooks(_StubTelemetry())
    engine = PlanningEngine(architecture_indexer=idx, telemetry=tel)

    contract = engine.plan_task(scope="docs", affected_modules=["README.md"])
    assert contract.rollback_strategy == "none"


def test_planning_engine_rollback_strategy_git_revert_for_core(tmp_path):
    idx = _make_indexer(tmp_path)
    tel = DevAgentTelemetryHooks(_StubTelemetry())
    engine = PlanningEngine(architecture_indexer=idx, telemetry=tel)

    contract = engine.plan_task(scope="core", affected_modules=["niblit_core.py"])
    assert contract.rollback_strategy in {"git_revert", "checkpoint_restore"}


# ── 3. FilesystemGuard ────────────────────────────────────────────────────────


def test_filesystem_guard_write_read(tmp_path):
    guard = FilesystemGuard(repo_root=tmp_path)
    record = guard.write_file("output/test.txt", "hello\n")

    assert (tmp_path / "output" / "test.txt").read_text() == "hello\n"
    assert record["operation"] == "write"
    assert not record["protected"]
    assert guard.changed_files() == ["output/test.txt"]


def test_filesystem_guard_blocks_protected_path(tmp_path):
    guard = FilesystemGuard(repo_root=tmp_path)
    with pytest.raises(FilesystemGuardError):
        guard.write_file("niblit_core.py", "# evil\n")


def test_filesystem_guard_force_allows_protected(tmp_path):
    guard = FilesystemGuard(repo_root=tmp_path)
    (tmp_path / "niblit_core.py").write_text("# original\n")
    record = guard.write_file("niblit_core.py", "# modified\n", force=True)
    assert record["forced"] is True
    assert record["protected"] is True


def test_filesystem_guard_path_traversal_blocked(tmp_path):
    guard = FilesystemGuard(repo_root=tmp_path)
    with pytest.raises(FilesystemGuardError):
        guard.write_file("../../etc/passwd", "pwned")


def test_filesystem_guard_rollback_metadata(tmp_path):
    guard = FilesystemGuard(repo_root=tmp_path)
    guard.write_file("a.txt", "aaa")
    guard.write_file("b.txt", "bbb")
    meta = guard.rollback_metadata()
    assert meta["total_changes"] == 2
    assert set(meta["affected_paths"]) == {"a.txt", "b.txt"}


def test_filesystem_guard_delete_file(tmp_path):
    guard = FilesystemGuard(repo_root=tmp_path)
    (tmp_path / "x.txt").write_text("delete me")
    record = guard.delete_file("x.txt")
    assert record["operation"] == "delete"
    assert not (tmp_path / "x.txt").exists()


def test_filesystem_guard_validate_path(tmp_path):
    guard = FilesystemGuard(repo_root=tmp_path)
    result = guard.validate_path("niblit_core.py")
    assert result["is_protected"] is True

    result2 = guard.validate_path("outputs/log.txt")
    assert result2["is_protected"] is False


# ── 4. EventSubscriber reactive workflow suggestions ─────────────────────────


class _MockEvent:
    """Minimal stand-in for core.event_bus.Event using string type."""

    def __init__(self, event_type_str: str, payload: dict | None = None):
        self.type = _TypeHolder(event_type_str)
        self.payload = payload or {}
        self.source = "test"


class _TypeHolder:
    def __init__(self, value: str):
        self.value = value


def test_event_subscriber_suggests_workflow_on_provider_failure():
    bus = EventBus()
    tel = DevAgentTelemetryHooks(_StubTelemetry())
    sub = EventSubscriber(bus, tel)
    sub.subscribe()

    # Inject a real TASK_COMPLETED event (no reactive trigger) + a mock provider_failure
    bus.publish(Event(type=EventType.TASK_COMPLETED, payload={}, source="test"))

    # Simulate a provider-failure-like event by calling _react directly
    sub._react({"type": "provider_failed", "category": "provider", "source": "test", "payload": {}})

    suggestions = sub.workflow_suggestions()
    assert len(suggestions) >= 1
    assert any(s["workflow"] == "provider_fallback_check" for s in suggestions)


def test_event_subscriber_runtime_degradation_triggers_suggestion():
    bus = EventBus()
    tel = DevAgentTelemetryHooks(_StubTelemetry())
    sub = EventSubscriber(bus, tel)
    sub.subscribe()

    sub._react({"type": "runtime_degradation_warning", "category": "runtime", "source": "test", "payload": {}})

    suggestions = sub.workflow_suggestions()
    assert any(s["workflow"] == "runtime_health_check" for s in suggestions)


def test_event_subscriber_flush_drains_suggestions():
    bus = EventBus()
    tel = DevAgentTelemetryHooks(_StubTelemetry())
    sub = EventSubscriber(bus, tel)
    sub.subscribe()

    sub._react({"type": "provider_error", "category": "provider", "source": "test", "payload": {}})
    out = sub.flush_suggestions()
    assert len(out) >= 1
    assert sub.workflow_suggestions() == []


def test_event_subscriber_recent_events_bounded():
    bus = EventBus()
    tel = DevAgentTelemetryHooks(_StubTelemetry())
    sub = EventSubscriber(bus, tel)
    sub.subscribe()

    for _ in range(10):
        bus.publish(Event(type=EventType.TASK_CREATED, payload={}, source="test"))

    recent = sub.recent_events(5)
    assert len(recent) <= 5


# ── 5. MemoryBridge Phase-2 expansions ────────────────────────────────────────


def test_memory_bridge_architecture_context_valid():
    bridge = MemoryBridge()
    arch = {
        "indexed_at": "2026-01-01T00:00:00+00:00",
        "runtime_modules": ["niblit_core.py", "core/event_bus.py"],
        "deployment_boundaries": ["Dockerfile"],
        "scan_duration_ms": 1.5,
    }
    result = bridge.build_architecture_context(arch)
    assert "valid" in result
    assert "allowed" in result


def test_memory_bridge_topology_snapshot():
    bridge = MemoryBridge()
    rt = {"deployment_mode": "local", "runtime_topology": {"runtime_mode": "normal"}}
    pr = {"active_provider": "qwen", "fallback_available": True}
    result = bridge.build_topology_snapshot(rt, pr)
    assert "valid" in result
    assert "normalized" in result


def test_memory_bridge_event_summary():
    bridge = MemoryBridge()
    metrics = {"events_total": 42, "categories": {"provider": 5}, "workflow_suggestions_total": 2}
    result = bridge.build_event_summary(metrics, [], runtime_snapshot=None)
    assert "valid" in result


def test_memory_bridge_provider_history():
    bridge = MemoryBridge()
    pr = {"active_provider": "qwen", "fallback_available": True, "provider_health": {"qwen": True}}
    result = bridge.build_provider_history(pr)
    assert "valid" in result


# ── 6. Telemetry Phase-2 convenience wrappers ────────────────────────────────


def test_telemetry_hooks_phase2_wrappers_are_no_ops_without_backend():
    tel = DevAgentTelemetryHooks(telemetry=None)
    # Should not raise
    tel.record_task_planned(150.0, affected_modules=3)
    tel.record_architecture_analysis(80.0, touched_modules=5)
    tel.record_execution_approval(approved=True)
    tel.record_rollback_event("task-123")
    tel.record_task_completed(200.0, success=True)


def test_telemetry_hooks_phase2_wrappers_record_to_backend():
    stub = _StubTelemetry()
    tel = DevAgentTelemetryHooks(telemetry=stub)
    tel.record_task_planned(120.0, affected_modules=2)
    tel.record_execution_approval(approved=True)
    tel.record_rollback_event()
    tel.record_task_completed(300.0, success=False)

    assert stub.counters.get("dev_agent_tasks_planned_total", 0) >= 1
    assert stub.counters.get("dev_agent_task_approvals_total", 0) >= 1
    assert stub.counters.get("dev_agent_rollback_events_total", 0) >= 1
    assert stub.counters.get("dev_agent_tasks_failed_total", 0) >= 1


# ── 7. Agent CLI analyze command ─────────────────────────────────────────────


def test_agent_cli_analyze_returns_scope_report(tmp_path):
    _make_indexer(tmp_path)
    agent = _make_agent(tmp_path)

    result = agent.handle_cli("analyze niblit_core")
    assert "NiblitDevAgent Analysis" in result
    assert "niblit_core" in result.lower()
    assert "touched_modules" in result.lower()


def test_agent_cli_analyze_without_arg_uses_default(tmp_path):
    _make_indexer(tmp_path)
    agent = _make_agent(tmp_path)

    result = agent.handle_cli("analyze")
    assert "NiblitDevAgent Analysis" in result


def test_agent_cli_analyze_scope_method(tmp_path):
    _make_indexer(tmp_path)
    agent = _make_agent(tmp_path)

    report = agent.analyze_scope("niblit_core")
    assert "touched_modules" in report
    assert report["scope"] == "niblit_core"


def test_agent_plan_task_returns_contract_dict(tmp_path):
    _make_indexer(tmp_path)
    agent = _make_agent(tmp_path)

    contract_dict = agent.plan_task(
        scope="core",
        description="touch core runtime",
        affected_modules=["niblit_core.py"],
    )
    assert "task_id" in contract_dict
    assert contract_dict["scope"] == "core"
    assert "runtime_impact" in contract_dict
    assert "rollback_strategy" in contract_dict


# ── 8. Graceful no-core behavior ─────────────────────────────────────────────


def test_planning_engine_no_architecture_index(tmp_path):
    """PlanningEngine should call index() on demand even with empty repo."""
    idx = ArchitectureIndexer(tmp_path)  # repo has no known modules
    tel = DevAgentTelemetryHooks(None)
    engine = PlanningEngine(architecture_indexer=idx, telemetry=tel)
    contract = engine.plan_task(scope="empty", affected_modules=[])
    assert isinstance(contract, DevTaskContract)
    assert contract.runtime_impact.affected is False


def test_filesystem_guard_telemetry_is_optional(tmp_path):
    guard = FilesystemGuard(repo_root=tmp_path, telemetry=None)
    record = guard.write_file("safe.txt", "data")
    assert record["operation"] == "write"
