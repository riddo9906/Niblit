#!/usr/bin/env python3
"""Machine-readable mutation manifest for governed execution staging."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agents.niblit_dev_agent.task_contracts import DevTaskContract


@dataclass
class MutationManifest:
    """Structured metadata emitted before staged execution."""

    task_id: str
    affected_files: list[str] = field(default_factory=list)
    affected_runtime_systems: list[str] = field(default_factory=list)
    provider_runtime_implications: str = ""
    deployment_runtime_implications: str = ""
    memory_implications: str = ""
    telemetry_implications: str = ""
    rollback_required: bool = True
    restart_required: bool = False
    risk_classification: str = "low"  # low|medium|high|critical
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "affected_files": list(self.affected_files),
            "affected_runtime_systems": list(self.affected_runtime_systems),
            "provider_runtime_implications": self.provider_runtime_implications,
            "deployment_runtime_implications": self.deployment_runtime_implications,
            "memory_implications": self.memory_implications,
            "telemetry_implications": self.telemetry_implications,
            "rollback_required": self.rollback_required,
            "restart_required": self.restart_required,
            "risk_classification": self.risk_classification,
            "metadata": dict(self.metadata),
        }


def classify_risk(contract: DevTaskContract, affected_files: list[str]) -> str:
    """Classify mutation risk using contract impact severities and touched paths."""
    severities = {
        contract.runtime_impact.severity,
        contract.deployment_impact.severity,
        contract.provider_impact.severity,
        contract.memory_impact.severity,
        contract.telemetry_impact.severity,
    }
    if "critical" in severities:
        return "critical"
    if "high" in severities:
        return "high"
    if "medium" in severities:
        return "medium"
    if any(p.startswith("core/") or p == "niblit_core.py" for p in affected_files):
        return "high"
    return "low"


def build_manifest(
    contract: DevTaskContract,
    *,
    affected_files: list[str],
    affected_runtime_systems: list[str] | None = None,
    restart_required: bool = False,
    metadata: dict[str, Any] | None = None,
) -> MutationManifest:
    """Build a manifest from a planned/staged contract."""
    return MutationManifest(
        task_id=contract.task_id,
        affected_files=list(affected_files),
        affected_runtime_systems=list(affected_runtime_systems or []),
        provider_runtime_implications=contract.provider_impact.details,
        deployment_runtime_implications=contract.deployment_impact.details,
        memory_implications=contract.memory_impact.details,
        telemetry_implications=contract.telemetry_impact.details,
        rollback_required=contract.rollback_strategy != "none",
        restart_required=restart_required,
        risk_classification=classify_risk(contract, affected_files),
        metadata=dict(metadata or {}),
    )
