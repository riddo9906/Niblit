#!/usr/bin/env python3
"""Governance-aligned memory read bridge for NiblitDevAgent (Phase 2)."""

from __future__ import annotations

from typing import Any

from shared.governance_contract.memory_contracts import (
    governed_recall_allowed,
    validate_memory_payload,
)


class MemoryBridge:
    """Read-only memory bridge aligned with governance memory contracts."""

    def __init__(self, authority: str = "niblit_dev_agent") -> None:
        self._authority = authority

    def build_runtime_context(
        self,
        runtime_snapshot: dict[str, Any],
        architecture_summary: dict[str, Any],
        provider_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        memory_payload = {
            "memory_type": "semantic_memory",
            "summary": "NiblitDevAgent runtime context snapshot",
            "content_text": (
                "runtime="
                f"{runtime_snapshot.get('deployment_mode', 'unknown')} "
                f"providers={provider_snapshot.get('active_provider', 'unknown')}"
            ),
            "indexing": {
                "tags": ["niblit_dev_agent", "runtime", "phase1"],
                "keywords": ["runtime", "provider", "architecture"],
            },
            "telemetry": {
                "runtime_mode": runtime_snapshot.get("runtime_topology", {}).get("runtime_mode", "normal"),
                "authority": self._authority,
            },
            "metadata": {
                "runtime_snapshot": runtime_snapshot,
                "architecture_summary": architecture_summary,
                "provider_snapshot": provider_snapshot,
            },
        }
        return self._validate_and_check(memory_payload)

    # ── Phase-2 read-focused expansions ───────────────────────────────────────

    def build_architecture_context(
        self,
        architecture_summary: dict[str, Any],
        runtime_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a governed memory payload from an architecture summary."""
        memory_payload = {
            "memory_type": "runtime_memory",
            "summary": "NiblitDevAgent architecture index snapshot",
            "content_text": (
                f"indexed_at={architecture_summary.get('indexed_at', 'unknown')} "
                f"modules={len(architecture_summary.get('runtime_modules', []))} "
                f"deployment_boundaries={len(architecture_summary.get('deployment_boundaries', []))}"
            ),
            "indexing": {
                "tags": ["niblit_dev_agent", "architecture", "phase2"],
                "keywords": ["architecture", "modules", "runtime_topology"],
            },
            "telemetry": {
                "runtime_mode": (runtime_snapshot or {})
                .get("runtime_topology", {})
                .get("runtime_mode", "normal"),
                "authority": self._authority,
            },
            "metadata": {
                "architecture_summary": architecture_summary,
                "runtime_snapshot": runtime_snapshot or {},
            },
        }
        return self._validate_and_check(memory_payload)

    def build_topology_snapshot(
        self,
        runtime_snapshot: dict[str, Any],
        provider_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """Build a governed memory payload for topology state observation."""
        topo = runtime_snapshot.get("runtime_topology", {})
        memory_payload = {
            "memory_type": "runtime_memory",
            "summary": "NiblitDevAgent topology state observation",
            "content_text": (
                f"deployment_mode={runtime_snapshot.get('deployment_mode', 'unknown')} "
                f"runtime_mode={topo.get('runtime_mode', 'normal')} "
                f"event_bus={topo.get('event_bus_available', False)} "
                f"provider={provider_snapshot.get('active_provider', 'unknown')}"
            ),
            "indexing": {
                "tags": ["niblit_dev_agent", "topology", "phase2"],
                "keywords": ["topology", "deployment", "provider"],
            },
            "telemetry": {
                "runtime_mode": topo.get("runtime_mode", "normal"),
                "authority": self._authority,
            },
            "metadata": {
                "runtime_snapshot": runtime_snapshot,
                "provider_snapshot": provider_snapshot,
            },
        }
        return self._validate_and_check(memory_payload)

    def build_event_summary(
        self,
        event_metrics: dict[str, Any],
        workflow_suggestions: list[dict[str, Any]],
        runtime_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a governed memory payload summarising event bus observations."""
        memory_payload = {
            "memory_type": "episodic_memory",
            "summary": "NiblitDevAgent event bus observation summary",
            "content_text": (
                f"events_total={event_metrics.get('events_total', 0)} "
                f"workflow_suggestions={event_metrics.get('workflow_suggestions_total', 0)} "
                f"categories={list(event_metrics.get('categories', {}).keys())}"
            ),
            "indexing": {
                "tags": ["niblit_dev_agent", "events", "phase2"],
                "keywords": ["event_bus", "workflow", "telemetry"],
            },
            "telemetry": {
                "runtime_mode": (runtime_snapshot or {})
                .get("runtime_topology", {})
                .get("runtime_mode", "normal"),
                "authority": self._authority,
            },
            "metadata": {
                "event_metrics": event_metrics,
                "workflow_suggestions": workflow_suggestions[:20],
            },
        }
        return self._validate_and_check(memory_payload)

    def build_provider_history(
        self,
        provider_snapshot: dict[str, Any],
        runtime_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a governed memory payload from a provider state observation."""
        memory_payload = {
            "memory_type": "runtime_memory",
            "summary": "NiblitDevAgent provider state observation",
            "content_text": (
                f"active={provider_snapshot.get('active_provider', 'unknown')} "
                f"fallback={provider_snapshot.get('fallback_available', False)} "
                f"health={list(provider_snapshot.get('provider_health', {}).keys())}"
            ),
            "indexing": {
                "tags": ["niblit_dev_agent", "provider", "phase2"],
                "keywords": ["provider", "health", "fallback"],
            },
            "telemetry": {
                "runtime_mode": (runtime_snapshot or {})
                .get("runtime_topology", {})
                .get("runtime_mode", "normal"),
                "authority": self._authority,
            },
            "metadata": {
                "provider_snapshot": provider_snapshot,
            },
        }
        return self._validate_and_check(memory_payload)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _validate_and_check(self, memory_payload: dict[str, Any]) -> dict[str, Any]:
        validated = validate_memory_payload(memory_payload)
        normalized = validated.get("normalized", {})
        allowed = governed_recall_allowed(
            normalized,
            runtime_mode=str(normalized.get("runtime_mode", "normal")),
            governance_state=str(normalized.get("governance_state", "active")),
        )
        return {
            "valid": bool(validated.get("valid")),
            "issues": list(validated.get("issues", [])),
            "allowed": bool(allowed),
            "authority": self._authority,
            "normalized": normalized,
        }
