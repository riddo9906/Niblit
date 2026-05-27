#!/usr/bin/env python3
"""Focused Phase 3 tests for governed execution staging."""

from __future__ import annotations

from pathlib import Path

import pytest

from agents.niblit_dev_agent.agent import NiblitDevAgent
from agents.niblit_dev_agent.approval_manager import ApprovalManager
from agents.niblit_dev_agent.event_subscriber import EventSubscriber
from agents.niblit_dev_agent.filesystem_guard import FilesystemGuard
from agents.niblit_dev_agent.governed_executor import GovernedExecutor
from agents.niblit_dev_agent.rollback_manager import RollbackManager
from agents.niblit_dev_agent.task_contracts import DevTaskContract
from agents.niblit_dev_agent.telemetry_hooks import DevAgentTelemetryHooks
from core.event_bus import EventBus
from core.runtime_manager import RuntimeManager


class _StubTelemetry:
    def __init__(self):
        self.counters = {}
        self.gauges = {}
        self.timings = {}

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


def _create_min_repo(root: Path) -> None:
    (root / "niblit_core.py").write_text("# core\n", encoding="utf-8")
    (root / "core").mkdir(exist_ok=True)
    (root / "core" / "event_bus.py").write_text("# bus\n", encoding="utf-8")
    (root / "modules").mkdir(exist_ok=True)
    (root / "modules" / "runtime_router_v2.py").write_text("# rr\n", encoding="utf-8")


def _make_agent(tmp_path: Path, runtime_manager: RuntimeManager | None = None) -> NiblitDevAgent:
    _create_min_repo(tmp_path)
    return NiblitDevAgent(
        core=None,
        runtime_manager=runtime_manager,
        event_bus=getattr(runtime_manager, "event_bus", EventBus()),
        telemetry=_StubTelemetry(),
        local_brain=_StubLocalBrain(),
        router_v2=_StubRouterV2(),
        llm_provider_manager=_StubProviderManager(),
        repo_root=str(tmp_path),
    )


def test_approval_manager_requires_explicit_ack():
    am = ApprovalManager()
    contract = DevTaskContract(scope="safe", affected_modules=["safe.txt"])
    am.stage_task(
        contract,
        staged_plan={"plan_id": contract.task_id, "changes": []},
        mutation_manifest={"task_id": contract.task_id},
    )
    with pytest.raises(ValueError):
        am.approve_task(
            contract.task_id,
            approver="tester",
            runtime_risk_acknowledged=False,
            rollback_confirmed=True,
        )


def test_filesystem_guard_stage_preview_and_scope(tmp_path):
    guard = FilesystemGuard(repo_root=tmp_path)
    plan_id = "p1"
    guard.stage_write(plan_id, "safe.txt", "hello")
    preview = guard.staged_plan(plan_id)
    assert len(preview["changes"]) == 1
    scope_ok = guard.validate_execution_scope(plan_id, ["safe.txt"])
    assert scope_ok["valid"] is True


def test_filesystem_guard_prepare_rollback_snapshot(tmp_path):
    (tmp_path / "safe.txt").write_text("before", encoding="utf-8")
    guard = FilesystemGuard(repo_root=tmp_path)
    guard.stage_write("p1", "safe.txt", "after")
    snapshot = guard.prepare_rollback_snapshot("p1")
    assert snapshot["files"]["safe.txt"]["content"] == "before"


def test_rollback_manager_diff_aware(tmp_path):
    rm = RollbackManager(repo_root=tmp_path)
    task_id = "t1"
    rm.capture_pre_execution_snapshot(
        task_id,
        files={"safe.txt": {"exists": True, "content": "before", "sha256": "abc"}},
        mutation_manifest={"task_id": task_id},
    )
    plan = rm.build_staged_rollback_plan(task_id, staged_changes=[{"relpath": "safe.txt"}])
    assert plan["deterministic"] is True
    diff = rm.build_diff_aware_restoration(task_id, post_change_hashes={"safe.txt": "def"})
    assert diff["drift"]["safe.txt"]["changed"] is True


def test_governed_executor_runs_only_approved(tmp_path):
    guard = FilesystemGuard(repo_root=tmp_path)
    rollback = RollbackManager(repo_root=tmp_path)
    approval = ApprovalManager()
    telemetry = DevAgentTelemetryHooks(_StubTelemetry())
    executor = GovernedExecutor(
        approval_manager=approval,
        filesystem_guard=guard,
        rollback_manager=rollback,
        telemetry=telemetry,
        event_bus=EventBus(),
    )
    contract = DevTaskContract(scope="safe", affected_modules=["safe.txt"])
    guard.stage_write(contract.task_id, "safe.txt", "hello")
    manifest = guard.mutation_manifest(plan_id=contract.task_id, contract=contract)
    approval.stage_task(
        contract,
        staged_plan={"plan_id": contract.task_id, **guard.staged_plan(contract.task_id)},
        mutation_manifest=manifest,
    )

    with pytest.raises(ValueError):
        executor.execute_approved_task(contract.task_id)

    approval.approve_task(
        contract.task_id,
        approver="tester",
        runtime_risk_acknowledged=True,
        rollback_confirmed=True,
    )
    result = executor.execute_approved_task(contract.task_id)
    assert result["task_id"] == contract.task_id
    assert (tmp_path / "safe.txt").read_text(encoding="utf-8") == "hello"


def test_event_subscriber_outputs_staged_approval_proposal():
    sub = EventSubscriber(EventBus(), DevAgentTelemetryHooks(_StubTelemetry()))
    sub._react({"type": "provider_failed", "payload": {}, "source": "test", "category": "provider"})
    suggestions = sub.workflow_suggestions()
    assert suggestions
    assert suggestions[0]["approval_required"] is True
    assert "staged_execution_plan" in suggestions[0]


def test_agent_cli_approve_requires_flags(tmp_path):
    agent = _make_agent(tmp_path, runtime_manager=None)
    staged = agent.stage_task(
        scope="safe",
        description="write safe file",
        affected_modules=["safe.txt"],
        staged_mutations=[{"operation": "write", "relpath": "safe.txt", "content": "ok"}],
    )
    task_id = staged["task_id"]
    response = agent.handle_cli(f"approve {task_id}")
    assert "explicit acknowledgements required" in response.lower()


def test_agent_cli_approve_executes_via_runtime_manager(tmp_path):
    runtime_manager = RuntimeManager()
    try:
        agent = _make_agent(tmp_path, runtime_manager=runtime_manager)
        runtime_manager.register_agent("dev_agent_execute", agent.handle)

        staged = agent.stage_task(
            scope="safe",
            description="write safe file",
            affected_modules=["safe.txt"],
            staged_mutations=[{"operation": "write", "relpath": "safe.txt", "content": "ok"}],
        )
        task_id = staged["task_id"]
        response = agent.handle_cli(
            f"approve {task_id} --ack-risk --confirm-rollback"
        )
        assert "approval" in response.lower()
        assert (tmp_path / "safe.txt").read_text(encoding="utf-8") == "ok"
    finally:
        runtime_manager.stop_loop()
