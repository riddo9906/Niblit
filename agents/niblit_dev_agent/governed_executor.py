#!/usr/bin/env python3
"""Controlled execution runner for approved staged development tasks."""

from __future__ import annotations

import time
from typing import Any

from agents.niblit_dev_agent.approval_manager import ApprovalManager
from agents.niblit_dev_agent.filesystem_guard import FilesystemGuard
from agents.niblit_dev_agent.rollback_manager import RollbackManager
from agents.niblit_dev_agent.task_contracts import DevTaskContract
from agents.niblit_dev_agent.telemetry_hooks import DevAgentTelemetryHooks
from core.event_bus import Event, EventBus, EventType


class GovernedExecutor:
    """Executes only explicitly approved staged tasks."""

    def __init__(
        self,
        *,
        approval_manager: ApprovalManager,
        filesystem_guard: FilesystemGuard,
        rollback_manager: RollbackManager,
        telemetry: DevAgentTelemetryHooks,
        event_bus: EventBus | None = None,
    ) -> None:
        self._approval_manager = approval_manager
        self._filesystem_guard = filesystem_guard
        self._rollback_manager = rollback_manager
        self._telemetry = telemetry
        self._event_bus = event_bus

    def execute_approved_task(self, task_id: str) -> dict[str, Any]:
        """Execute a staged task after approval checks and rollback prep."""
        record = self._approval_manager.get_approved(task_id)
        if record is None:
            raise ValueError(f"Task is not approved: {task_id}")
        if not record.get("runtime_risk_acknowledged") or not record.get("rollback_confirmed"):
            raise ValueError("Approval missing risk acknowledgement or rollback confirmation.")

        contract = DevTaskContract.from_dict(record["contract"])
        staged_plan = dict(record.get("staged_plan", {}))
        manifest = dict(record.get("mutation_manifest", {}))

        self._approval_manager.begin_execution(task_id)
        start = time.monotonic()
        self._emit(
            EventType.PLAN_GENERATED,
            {"task_id": task_id, "stage": "execution_started", "manifest": manifest},
        )

        # Snapshot before mutation
        snapshot = self._filesystem_guard.prepare_rollback_snapshot(
            staged_plan.get("plan_id", "default")
        )
        self._rollback_manager.capture_pre_execution_snapshot(
            task_id,
            files=snapshot.get("files", {}),
            mutation_manifest=manifest,
        )

        # Runtime safety boundary: staged files must remain inside contract scope
        scope_check = self._filesystem_guard.validate_execution_scope(
            staged_plan.get("plan_id", "default"),
            allowed_modules=list(contract.affected_modules),
        )
        if not scope_check.get("valid", False):
            self._approval_manager.complete_execution(
                task_id,
                success=False,
                result={"error": "execution_scope_validation_failed", **scope_check},
            )
            self._emit(
                EventType.TASK_FAILED,
                {"task_id": task_id, "reason": "execution_scope_validation_failed"},
            )
            raise ValueError(f"Execution scope validation failed: {scope_check}")

        execution_result = self._filesystem_guard.execute_staged_plan(
            staged_plan.get("plan_id", "default"),
            force=bool(record.get("approval_metadata", {}).get("allow_protected_writes", False)),
        )
        post_hashes = {
            r["relpath"]: r.get("post_hash")
            for r in execution_result.get("applied_changes", [])
        }
        rollback_plan = self._rollback_manager.build_staged_rollback_plan(
            task_id,
            staged_changes=execution_result.get("applied_changes", []),
        )
        diff_aware = self._rollback_manager.build_diff_aware_restoration(
            task_id, post_change_hashes=post_hashes
        )

        duration_ms = (time.monotonic() - start) * 1000.0
        self._telemetry.record_task_completed(duration_ms, success=True)
        self._approval_manager.complete_execution(
            task_id,
            success=True,
            result={
                "execution_result": execution_result,
                "rollback_plan": rollback_plan,
                "diff_aware": diff_aware,
            },
        )
        self._emit(
            EventType.TASK_COMPLETED,
            {"task_id": task_id, "duration_ms": round(duration_ms, 2)},
        )
        return {
            "task_id": task_id,
            "execution_result": execution_result,
            "rollback_plan": rollback_plan,
            "diff_aware": diff_aware,
            "duration_ms": round(duration_ms, 2),
        }

    def _emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        if self._event_bus is None:
            return
        self._event_bus.publish(
            Event(type=event_type, payload=payload, source="niblit_dev_agent.governed_executor")
        )
