#!/usr/bin/env python3
"""Lightweight architecture indexing for NiblitDevAgent phase 1."""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ArchitectureIndexer:
    """Creates lightweight structured architecture summaries (no vectorization)."""

    def __init__(self, repo_root: str | Path) -> None:
        self._repo_root = Path(repo_root).resolve()
        self._last_summary: dict[str, Any] = {}

    def _exists(self, relpath: str) -> bool:
        return (self._repo_root / relpath).exists()

    def _module_map(self, paths: list[str]) -> dict[str, bool]:
        return {p: self._exists(p) for p in paths}

    def index(self) -> dict[str, Any]:
        start = time.monotonic()

        runtime_modules = [
            p
            for p in (
                "niblit_core.py",
                "core/runtime_manager.py",
                "core/event_bus.py",
                "core/task_queue.py",
                "core/orchestrator.py",
                "modules/runtime_router_v2.py",
                "modules/local_brain.py",
                "modules/llm_provider_manager.py",
            )
            if self._exists(p)
        ]

        provider_flow = self._module_map(
            [
                "modules/runtime_router_v2.py",
                "modules/local_brain.py",
                "modules/llm_provider_manager.py",
                "modules/ruflo_adapter.py",
            ]
        )

        memory_flow = self._module_map(
            [
                "shared/governance_contract/memory_contracts.py",
                "modules/unified_memory_engine.py",
                "modules/memory_loop.py",
                "modules/vector_memory/qdrant_adapter.py",
                "modules/embedding_engine.py",
            ]
        )

        deployment_boundaries = [
            p
            for p in (
                "Dockerfile",
                "fly.toml",
                "vercel.json",
                "render.yaml",
                "tools/runtime_profiles",
            )
            if self._exists(p)
        ]

        event_runtime_systems = [
            p
            for p in (
                "core/event_bus.py",
                "modules/event_store.py",
                "modules/metrics_observability.py",
            )
            if self._exists(p)
        ]

        runtime_shell_surfaces = [
            p
            for p in ("main.py", "app.py", "server.py", "niblit_dashboard.py", "kivy_app.py")
            if self._exists(p)
        ]

        if self._exists("nodes"):
            try:
                node_files = sum(1 for _ in os.scandir(self._repo_root / "nodes"))
            except Exception:
                node_files = 0
        else:
            node_files = 0

        summary = {
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "scan_duration_ms": round((time.monotonic() - start) * 1000.0, 2),
            "runtime_modules": runtime_modules,
            "provider_flow": provider_flow,
            "memory_flow": memory_flow,
            "deployment_boundaries": deployment_boundaries,
            "event_runtime_systems": event_runtime_systems,
            "runtime_shell_surfaces": runtime_shell_surfaces,
            "runtime_topology": {
                "has_nodes_directory": self._exists("nodes"),
                "node_entries": node_files,
            },
        }
        self._last_summary = summary
        return summary

    def last_summary(self) -> dict[str, Any]:
        return dict(self._last_summary)
