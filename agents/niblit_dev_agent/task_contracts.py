#!/usr/bin/env python3
"""Task contracts for NiblitDevAgent runtime integration."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

# ── Task-type identifiers ─────────────────────────────────────────────────────

DEV_AGENT_TASK_TYPE = "dev_agent_inspect"
DEV_AGENT_ANALYZE_TASK_TYPE = "dev_agent_analyze"

# ── CLI action identifiers ─────────────────────────────────────────────────────

CLI_STATUS = "status"
CLI_RUNTIME = "runtime"
CLI_PROVIDERS = "providers"
CLI_ARCHITECTURE = "architecture"
CLI_ANALYZE = "analyze"

VALID_CLI_ACTIONS = {
    CLI_STATUS,
    CLI_RUNTIME,
    CLI_PROVIDERS,
    CLI_ARCHITECTURE,
    CLI_ANALYZE,
}

# ── Approval / execution states ───────────────────────────────────────────────

APPROVAL_PENDING = "pending"
APPROVAL_APPROVED = "approved"
APPROVAL_DENIED = "denied"

EXEC_QUEUED = "queued"
EXEC_PLANNING = "planning"
EXEC_APPROVED = "approved"
EXEC_EXECUTING = "executing"
EXEC_COMPLETED = "completed"
EXEC_ROLLED_BACK = "rolled_back"
EXEC_FAILED = "failed"

# ── Governed DevTaskContract ──────────────────────────────────────────────────


@dataclass
class ImpactAssessment:
    """Runtime-consequence evaluation for a single system boundary."""

    affected: bool = False
    details: str = ""
    severity: str = "none"  # none | low | medium | high | critical


@dataclass
class DevTaskContract:
    """Governed development task descriptor.

    All tasks must carry a contract before they may progress past EXEC_QUEUED.
    The planner populates the impact fields from architecture and runtime data;
    a human operator (or governance chain) then sets approval_state.
    """

    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    task_type: str = "analysis"
    scope: str = ""
    description: str = ""
    affected_modules: list[str] = field(default_factory=list)

    # ── Impact assessments (populated by PlanningEngine) ─────────────────────
    runtime_impact: ImpactAssessment = field(default_factory=ImpactAssessment)
    deployment_impact: ImpactAssessment = field(default_factory=ImpactAssessment)
    provider_impact: ImpactAssessment = field(default_factory=ImpactAssessment)
    memory_impact: ImpactAssessment = field(default_factory=ImpactAssessment)
    telemetry_impact: ImpactAssessment = field(default_factory=ImpactAssessment)

    # ── Governance fields ─────────────────────────────────────────────────────
    rollback_strategy: str = "none"
    approval_state: str = APPROVAL_PENDING
    execution_state: str = EXEC_QUEUED

    # ── Optional metadata ─────────────────────────────────────────────────────
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "scope": self.scope,
            "description": self.description,
            "affected_modules": list(self.affected_modules),
            "runtime_impact": {
                "affected": self.runtime_impact.affected,
                "details": self.runtime_impact.details,
                "severity": self.runtime_impact.severity,
            },
            "deployment_impact": {
                "affected": self.deployment_impact.affected,
                "details": self.deployment_impact.details,
                "severity": self.deployment_impact.severity,
            },
            "provider_impact": {
                "affected": self.provider_impact.affected,
                "details": self.provider_impact.details,
                "severity": self.provider_impact.severity,
            },
            "memory_impact": {
                "affected": self.memory_impact.affected,
                "details": self.memory_impact.details,
                "severity": self.memory_impact.severity,
            },
            "telemetry_impact": {
                "affected": self.telemetry_impact.affected,
                "details": self.telemetry_impact.details,
                "severity": self.telemetry_impact.severity,
            },
            "rollback_strategy": self.rollback_strategy,
            "approval_state": self.approval_state,
            "execution_state": self.execution_state,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DevTaskContract:
        def _impact(d: dict[str, Any]) -> ImpactAssessment:
            return ImpactAssessment(
                affected=bool(d.get("affected", False)),
                details=str(d.get("details", "")),
                severity=str(d.get("severity", "none")),
            )

        return cls(
            task_id=str(data.get("task_id", str(uuid.uuid4()))),
            task_type=str(data.get("task_type", "analysis")),
            scope=str(data.get("scope", "")),
            description=str(data.get("description", "")),
            affected_modules=list(data.get("affected_modules", [])),
            runtime_impact=_impact(data.get("runtime_impact", {})),
            deployment_impact=_impact(data.get("deployment_impact", {})),
            provider_impact=_impact(data.get("provider_impact", {})),
            memory_impact=_impact(data.get("memory_impact", {})),
            telemetry_impact=_impact(data.get("telemetry_impact", {})),
            rollback_strategy=str(data.get("rollback_strategy", "none")),
            approval_state=str(data.get("approval_state", APPROVAL_PENDING)),
            execution_state=str(data.get("execution_state", EXEC_QUEUED)),
            metadata=dict(data.get("metadata", {})),
        )
