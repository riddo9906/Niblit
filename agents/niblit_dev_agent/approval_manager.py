#!/usr/bin/env python3
"""Approval workflow manager for governed execution staging."""

from __future__ import annotations

import time
from typing import Any

from agents.niblit_dev_agent.task_contracts import (
    APPROVAL_APPROVED,
    APPROVAL_DENIED,
    APPROVAL_PENDING,
    EXEC_APPROVED,
    EXEC_COMPLETED,
    EXEC_EXECUTING,
    EXEC_FAILED,
    EXEC_STAGED,
    DevTaskContract,
)
from agents.niblit_dev_agent.telemetry_hooks import DevAgentTelemetryHooks


class ApprovalManager:
    """Tracks pending/approved/rejected tasks and staged execution metadata."""

    def __init__(self, telemetry: DevAgentTelemetryHooks | None = None) -> None:
        self._telemetry = telemetry
        self._pending: dict[str, dict[str, Any]] = {}
        self._approved: dict[str, dict[str, Any]] = {}
        self._rejected: dict[str, dict[str, Any]] = {}
        self._executions: dict[str, dict[str, Any]] = {}

    def stage_task(
        self,
        contract: DevTaskContract,
        *,
        staged_plan: dict[str, Any],
        mutation_manifest: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register a task in pending approval state with staging details."""
        contract.execution_state = EXEC_STAGED
        contract.approval_state = APPROVAL_PENDING
        record = {
            "task_id": contract.task_id,
            "contract": contract.to_dict(),
            "staged_plan": dict(staged_plan),
            "mutation_manifest": dict(mutation_manifest),
            "approval_metadata": {},
            "runtime_risk_acknowledged": False,
            "rollback_confirmed": False,
            "staged_at": time.time(),
            "metadata": dict(metadata or {}),
        }
        self._pending[contract.task_id] = record
        if self._telemetry:
            self._telemetry.increment("dev_agent_approval_pending_total", 1)
        return record

    def approve_task(
        self,
        task_id: str,
        *,
        approver: str,
        runtime_risk_acknowledged: bool,
        rollback_confirmed: bool,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Approve a staged task only when explicit acknowledgements are present."""
        record = self._pending.get(task_id)
        if record is None:
            raise ValueError(f"Unknown pending task_id: {task_id}")
        if not runtime_risk_acknowledged or not rollback_confirmed:
            raise ValueError(
                "Explicit approval requires runtime risk acknowledgement and rollback confirmation."
            )

        contract = DevTaskContract.from_dict(record["contract"])
        contract.approval_state = APPROVAL_APPROVED
        contract.execution_state = EXEC_APPROVED
        record["contract"] = contract.to_dict()
        record["approval_metadata"] = {
            "approver": approver,
            "approved_at": time.time(),
            "runtime_risk_acknowledged": runtime_risk_acknowledged,
            "rollback_confirmed": rollback_confirmed,
            **dict(metadata or {}),
        }
        record["runtime_risk_acknowledged"] = True
        record["rollback_confirmed"] = True
        self._approved[task_id] = record
        self._pending.pop(task_id, None)
        if self._telemetry:
            self._telemetry.record_execution_approval(True)
        return record

    def reject_task(
        self,
        task_id: str,
        *,
        reviewer: str,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Reject a pending task with an explicit reason."""
        record = self._pending.get(task_id)
        if record is None:
            raise ValueError(f"Unknown pending task_id: {task_id}")
        contract = DevTaskContract.from_dict(record["contract"])
        contract.approval_state = APPROVAL_DENIED
        contract.execution_state = EXEC_FAILED
        record["contract"] = contract.to_dict()
        record["approval_metadata"] = {
            "reviewer": reviewer,
            "rejected_at": time.time(),
            "reason": reason,
            **dict(metadata or {}),
        }
        self._rejected[task_id] = record
        self._pending.pop(task_id, None)
        if self._telemetry:
            self._telemetry.record_execution_approval(False)
        return record

    def begin_execution(self, task_id: str) -> dict[str, Any]:
        """Mark an approved task as executing."""
        record = self._approved.get(task_id)
        if record is None:
            raise ValueError(f"Task is not approved: {task_id}")
        contract = DevTaskContract.from_dict(record["contract"])
        contract.execution_state = EXEC_EXECUTING
        record["contract"] = contract.to_dict()
        self._executions[task_id] = {
            "started_at": time.time(),
            "status": EXEC_EXECUTING,
        }
        return record

    def complete_execution(
        self, task_id: str, *, success: bool, result: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Finalize execution status for approved task."""
        record = self._approved.get(task_id)
        if record is None:
            raise ValueError(f"Task is not approved: {task_id}")
        contract = DevTaskContract.from_dict(record["contract"])
        contract.execution_state = EXEC_COMPLETED if success else EXEC_FAILED
        record["contract"] = contract.to_dict()
        execution = self._executions.get(task_id, {})
        execution.update(
            {
                "completed_at": time.time(),
                "status": contract.execution_state,
                "result": dict(result or {}),
            }
        )
        self._executions[task_id] = execution
        return record

    def is_approved(self, task_id: str) -> bool:
        return task_id in self._approved

    def get_approved(self, task_id: str) -> dict[str, Any] | None:
        return self._approved.get(task_id)

    def get_pending(self, task_id: str) -> dict[str, Any] | None:
        return self._pending.get(task_id)

    def list_pending(self) -> list[dict[str, Any]]:
        return list(self._pending.values())

    def list_approved(self) -> list[dict[str, Any]]:
        return list(self._approved.values())

    def list_rejected(self) -> list[dict[str, Any]]:
        return list(self._rejected.values())
