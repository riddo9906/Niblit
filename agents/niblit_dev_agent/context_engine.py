#!/usr/bin/env python3
"""Context aggregation engine for NiblitDevAgent."""

from __future__ import annotations

from typing import Any

from agents.niblit_dev_agent.architecture_indexer import ArchitectureIndexer
from agents.niblit_dev_agent.memory_bridge import MemoryBridge
from agents.niblit_dev_agent.provider_awareness import ProviderAwareness
from agents.niblit_dev_agent.runtime_awareness import RuntimeAwareness
from agents.niblit_dev_agent.telemetry_hooks import DevAgentTelemetryHooks


class ContextEngine:
    """Builds consolidated runtime/provider/architecture context snapshots."""

    def __init__(
        self,
        runtime_awareness: RuntimeAwareness,
        provider_awareness: ProviderAwareness,
        architecture_indexer: ArchitectureIndexer,
        memory_bridge: MemoryBridge,
        telemetry: DevAgentTelemetryHooks,
    ) -> None:
        self._runtime_awareness = runtime_awareness
        self._provider_awareness = provider_awareness
        self._architecture_indexer = architecture_indexer
        self._memory_bridge = memory_bridge
        self._telemetry = telemetry

    def build_context(self) -> dict[str, Any]:
        with self._telemetry.timed("dev_agent_runtime_scan_ms"):
            runtime = self._runtime_awareness.get_runtime_snapshot()

        with self._telemetry.timed("dev_agent_provider_scan_ms"):
            providers = self._provider_awareness.get_provider_snapshot()

        with self._telemetry.timed("dev_agent_architecture_index_ms"):
            architecture = self._architecture_indexer.index()

        memory_context = self._memory_bridge.build_runtime_context(
            runtime_snapshot=runtime,
            architecture_summary=architecture,
            provider_snapshot=providers,
        )

        return {
            "runtime": runtime,
            "providers": providers,
            "architecture": architecture,
            "memory_context": memory_context,
        }
