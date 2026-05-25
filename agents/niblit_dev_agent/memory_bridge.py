#!/usr/bin/env python3
"""Governance-aligned memory read bridge for NiblitDevAgent."""

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
        validated = validate_memory_payload(memory_payload)
        normalized = validated.get("normalized", {})
        allowed = governed_recall_allowed(
            normalized,
            runtime_mode=str(normalized.get("runtime_mode", "normal")),
            governance_state=str(normalized.get("governance_state", "active")),
            authority=self._authority,
        )
        return {
            "valid": bool(validated.get("valid")),
            "issues": list(validated.get("issues", [])),
            "allowed": bool(allowed.get("allowed", False)),
            "authority": allowed.get("authority"),
            "normalized": normalized,
        }
