#!/usr/bin/env python3
"""Type definitions for NiblitDevAgent phase-1 scaffolding."""

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
