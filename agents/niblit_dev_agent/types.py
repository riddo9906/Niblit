#!/usr/bin/env python3
"""Type definitions for NiblitDevAgent scaffolding (Phase 1 + Phase 2)."""

from __future__ import annotations

from typing import Any, TypedDict


class RuntimeSnapshot(TypedDict, total=False):
    deployment_mode: str
    runtime_topology: dict[str, Any]
    runtime_manager: dict[str, Any]
    event_bus: dict[str, Any]
    telemetry: dict[str, Any]
    local_brain: dict[str, Any]
    active_threads: dict[str, Any]
    loaded_memory_systems: list[str]


class ProviderSnapshot(TypedDict, total=False):
    active_provider: str
    provider_status: dict[str, Any]
    provider_health: dict[str, bool]
    fallback_available: bool
    router_last_route: dict[str, Any]
    backend_metadata: dict[str, Any]


class ArchitectureSummary(TypedDict, total=False):
    indexed_at: str
    scan_duration_ms: float
    runtime_modules: list[str]
    provider_flow: dict[str, Any]
    memory_flow: dict[str, Any]
    deployment_boundaries: list[str]
    event_runtime_systems: list[str]
    runtime_shell_surfaces: list[str]


# ── Phase-2 types ─────────────────────────────────────────────────────────────


class ImpactAssessmentDict(TypedDict, total=False):
    affected: bool
    details: str
    severity: str  # none | low | medium | high | critical


class DevTaskContractDict(TypedDict, total=False):
    task_id: str
    task_type: str
    scope: str
    description: str
    affected_modules: list[str]
    runtime_impact: ImpactAssessmentDict
    deployment_impact: ImpactAssessmentDict
    provider_impact: ImpactAssessmentDict
    memory_impact: ImpactAssessmentDict
    telemetry_impact: ImpactAssessmentDict
    rollback_strategy: str
    approval_state: str
    execution_state: str
    metadata: dict[str, Any]


class ScopeAnalysisReport(TypedDict, total=False):
    scope: str
    analysis_duration_ms: float
    touched_modules: list[str]
    provider_context: dict[str, Any]
    runtime_context: dict[str, Any]
    architecture_summary: dict[str, Any]


class WorkflowSuggestion(TypedDict, total=False):
    trigger: str
    workflow: str
    description: str
    governed_task_type: str
    severity: str
