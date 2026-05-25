#!/usr/bin/env python3
"""Architecture-aware planning engine for NiblitDevAgent governed tasks."""

from __future__ import annotations

import time
from typing import Any

from agents.niblit_dev_agent.architecture_indexer import ArchitectureIndexer
from agents.niblit_dev_agent.task_contracts import (
    APPROVAL_PENDING,
    EXEC_PLANNING,
    DevTaskContract,
    ImpactAssessment,
)
from agents.niblit_dev_agent.telemetry_hooks import DevAgentTelemetryHooks

# Paths that, if touched, bump deployment impact to at least "medium"
_DEPLOYMENT_SENSITIVE: frozenset[str] = frozenset({
    "Dockerfile",
    "fly.toml",
    "vercel.json",
    "render.yaml",
    "tools/runtime_profiles",
    ".env",
    "requirements.txt",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
})

# Paths that, if touched, bump provider impact to at least "medium"
_PROVIDER_SENSITIVE: frozenset[str] = frozenset({
    "modules/runtime_router_v2.py",
    "modules/local_brain.py",
    "modules/llm_provider_manager.py",
    "modules/ruflo_adapter.py",
    "modules/hf_brain.py",
})

# Paths that, if touched, bump memory impact to at least "medium"
_MEMORY_SENSITIVE: frozenset[str] = frozenset({
    "shared/governance_contract/memory_contracts.py",
    "modules/unified_memory_engine.py",
    "modules/memory_loop.py",
    "modules/vector_memory",
    "modules/embedding_engine.py",
})

# Core runtime paths — any change is "high" risk
_RUNTIME_CRITICAL: frozenset[str] = frozenset({
    "niblit_core.py",
    "core/runtime_manager.py",
    "core/event_bus.py",
    "core/task_queue.py",
    "core/orchestrator.py",
})

# Telemetry / observability paths
_TELEMETRY_SENSITIVE: frozenset[str] = frozenset({
    "modules/metrics_observability.py",
    "modules/event_store.py",
    "core/event_bus.py",
})


class PlanningEngine:
    """Reasons about runtime consequences before a governed task executes.

    The engine inspects the current architecture index, provider topology, and
    deployment boundaries to produce a fully-populated :class:`DevTaskContract`
    that carries per-system impact assessments.
    """

    def __init__(
        self,
        architecture_indexer: ArchitectureIndexer,
        telemetry: DevAgentTelemetryHooks,
        provider_snapshot: dict[str, Any] | None = None,
        runtime_snapshot: dict[str, Any] | None = None,
    ) -> None:
        self._indexer = architecture_indexer
        self._telemetry = telemetry
        self._provider_snapshot: dict[str, Any] = provider_snapshot or {}
        self._runtime_snapshot: dict[str, Any] = runtime_snapshot or {}

    def update_snapshots(
        self,
        provider_snapshot: dict[str, Any] | None = None,
        runtime_snapshot: dict[str, Any] | None = None,
    ) -> None:
        if provider_snapshot is not None:
            self._provider_snapshot = provider_snapshot
        if runtime_snapshot is not None:
            self._runtime_snapshot = runtime_snapshot

    # ── Public entry point ────────────────────────────────────────────────────

    def plan_task(
        self,
        scope: str,
        description: str = "",
        affected_modules: list[str] | None = None,
        task_type: str = "analysis",
    ) -> DevTaskContract:
        """Return a contract describing runtime consequences of *scope*.

        Args:
            scope:            Short human label for the work area.
            description:      Optional longer description of intent.
            affected_modules: Caller-provided list of paths/modules involved.
            task_type:        One of the task-type constants.

        Returns:
            A :class:`DevTaskContract` in state EXEC_PLANNING.
        """
        start = time.monotonic()

        arch = self._indexer.last_summary() or self._indexer.index()
        modules = list(affected_modules or [])

        contract = DevTaskContract(
            task_type=task_type,
            scope=scope,
            description=description,
            affected_modules=modules,
            approval_state=APPROVAL_PENDING,
            execution_state=EXEC_PLANNING,
        )

        contract.runtime_impact = self._assess_runtime(modules, arch)
        contract.deployment_impact = self._assess_deployment(modules, arch)
        contract.provider_impact = self._assess_provider(modules, arch)
        contract.memory_impact = self._assess_memory(modules, arch)
        contract.telemetry_impact = self._assess_telemetry(modules, arch)
        contract.rollback_strategy = self._rollback_strategy(contract)

        contract.metadata["planning_duration_ms"] = round(
            (time.monotonic() - start) * 1000.0, 2
        )
        contract.metadata["architecture_indexed_at"] = arch.get("indexed_at", "")

        elapsed_ms = (time.monotonic() - start) * 1000.0
        self._telemetry.record_timing("dev_agent_plan_task_ms", elapsed_ms)
        self._telemetry.increment("dev_agent_tasks_planned_total", 1)
        self._telemetry.gauge(
            "dev_agent_plan_affected_modules",
            float(len(modules)),
        )

        return contract

    def analyze_scope(self, scope: str) -> dict[str, Any]:
        """Return a structured report on what runtime systems a scope touches."""
        start = time.monotonic()
        arch = self._indexer.last_summary() or self._indexer.index()

        # Determine which tracked paths scope overlaps with
        all_tracked = set(arch.get("runtime_modules", []))
        for paths in (
            arch.get("provider_flow", {}).keys(),
            arch.get("memory_flow", {}).keys(),
            arch.get("event_runtime_systems", []),
            arch.get("runtime_shell_surfaces", []),
        ):
            all_tracked.update(paths)

        scope_lower = scope.lower()
        touched = sorted(p for p in all_tracked if scope_lower in p.lower())

        provider_mode = self._provider_snapshot.get("active_provider", "unknown")
        fallback = self._provider_snapshot.get("fallback_available", False)
        runtime_mode = self._runtime_snapshot.get("runtime_topology", {}).get(
            "runtime_mode", "normal"
        )
        deployment_mode = self._runtime_snapshot.get("deployment_mode", "unknown")

        elapsed_ms = (time.monotonic() - start) * 1000.0
        self._telemetry.record_timing("dev_agent_analyze_scope_ms", elapsed_ms)
        self._telemetry.increment("dev_agent_scope_analyses_total", 1)

        return {
            "scope": scope,
            "analysis_duration_ms": round(elapsed_ms, 2),
            "touched_modules": touched,
            "provider_context": {
                "active_provider": provider_mode,
                "fallback_available": fallback,
            },
            "runtime_context": {
                "runtime_mode": runtime_mode,
                "deployment_mode": deployment_mode,
                "event_bus_available": self._runtime_snapshot.get(
                    "runtime_topology", {}
                ).get("event_bus_available", False),
                "local_brain_available": self._runtime_snapshot.get(
                    "runtime_topology", {}
                ).get("local_brain_available", False),
            },
            "architecture_summary": {
                "runtime_modules_count": len(arch.get("runtime_modules", [])),
                "deployment_boundaries_count": len(
                    arch.get("deployment_boundaries", [])
                ),
                "event_runtime_systems_count": len(
                    arch.get("event_runtime_systems", [])
                ),
            },
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _overlap(modules: list[str], sensitive: frozenset[str]) -> list[str]:
        return [m for m in modules if any(s in m or m in s for s in sensitive)]

    def _assess_runtime(
        self, modules: list[str], arch: dict[str, Any]
    ) -> ImpactAssessment:
        hits = self._overlap(modules, _RUNTIME_CRITICAL)
        if hits:
            return ImpactAssessment(
                affected=True,
                details=f"Critical runtime paths: {', '.join(hits)}",
                severity="high",
            )
        rt_modules = set(arch.get("runtime_modules", []))
        indirect = [m for m in modules if m in rt_modules]
        if indirect:
            return ImpactAssessment(
                affected=True,
                details=f"Runtime modules touched: {', '.join(indirect)}",
                severity="medium",
            )
        return ImpactAssessment(affected=False, severity="none")

    def _assess_deployment(
        self, modules: list[str], arch: dict[str, Any]
    ) -> ImpactAssessment:
        boundaries = set(arch.get("deployment_boundaries", []))
        hits = self._overlap(modules, _DEPLOYMENT_SENSITIVE)
        if hits or any(m in boundaries for m in modules):
            return ImpactAssessment(
                affected=True,
                details=f"Deployment-sensitive paths: {', '.join(hits or ['inferred'])}",
                severity="medium",
            )
        return ImpactAssessment(affected=False, severity="none")

    def _assess_provider(
        self, modules: list[str], arch: dict[str, Any]
    ) -> ImpactAssessment:
        hits = self._overlap(modules, _PROVIDER_SENSITIVE)
        if hits:
            active = self._provider_snapshot.get("active_provider", "unknown")
            fallback = self._provider_snapshot.get("fallback_available", False)
            details = (
                f"Provider paths affected: {', '.join(hits)}. "
                f"Active: {active}. Fallback: {fallback}."
            )
            return ImpactAssessment(affected=True, details=details, severity="high")
        provider_flow = set(arch.get("provider_flow", {}).keys())
        indirect = [m for m in modules if m in provider_flow]
        if indirect:
            return ImpactAssessment(
                affected=True,
                details=f"Provider flow modules: {', '.join(indirect)}",
                severity="medium",
            )
        return ImpactAssessment(affected=False, severity="none")

    def _assess_memory(
        self, modules: list[str], arch: dict[str, Any]
    ) -> ImpactAssessment:
        hits = self._overlap(modules, _MEMORY_SENSITIVE)
        if hits:
            return ImpactAssessment(
                affected=True,
                details=f"Memory-sensitive paths: {', '.join(hits)}",
                severity="high",
            )
        memory_flow = set(arch.get("memory_flow", {}).keys())
        indirect = [m for m in modules if m in memory_flow]
        if indirect:
            return ImpactAssessment(
                affected=True,
                details=f"Memory flow modules: {', '.join(indirect)}",
                severity="medium",
            )
        return ImpactAssessment(affected=False, severity="none")

    def _assess_telemetry(
        self, modules: list[str], arch: dict[str, Any]
    ) -> ImpactAssessment:
        hits = self._overlap(modules, _TELEMETRY_SENSITIVE)
        event_systems = set(arch.get("event_runtime_systems", []))
        indirect = [m for m in modules if m in event_systems]
        if hits or indirect:
            return ImpactAssessment(
                affected=True,
                details=f"Telemetry/event paths: {', '.join(hits + indirect)}",
                severity="low",
            )
        return ImpactAssessment(affected=False, severity="none")

    @staticmethod
    def _rollback_strategy(contract: DevTaskContract) -> str:
        severities = {
            c.severity
            for c in (
                contract.runtime_impact,
                contract.deployment_impact,
                contract.provider_impact,
                contract.memory_impact,
                contract.telemetry_impact,
            )
            if c.affected
        }
        if "critical" in severities or "high" in severities:
            return "git_revert"
        if "medium" in severities:
            return "checkpoint_restore"
        if "low" in severities:
            return "manual_review"
        return "none"
