"""Canonical compatibility metadata and validation matrix."""

from __future__ import annotations

from typing import Any

CANONICAL_COMPATIBILITY = {
    "schema_version": "2.x",
    "event_contract_version": "omega-7",
    "governance_contract_version": "1.x",
    "advisor_protocol_version": "2.x",
    "runtime_mode_contract": "2026.05",
}


def compatibility_metadata(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    meta = dict(CANONICAL_COMPATIBILITY)
    meta.update(dict(overrides or {}))
    return meta


def validate_compatibility(payload: dict[str, Any] | None) -> dict[str, Any]:
    incoming = dict(payload or {})
    expected = compatibility_metadata()
    mismatches: dict[str, dict[str, str]] = {}

    for key, expected_value in expected.items():
        got = str(incoming.get(key, "")).strip()
        if got and got != expected_value:
            mismatches[key] = {"expected": str(expected_value), "received": got}

    return {
        "compatible": len(mismatches) == 0,
        "mismatches": mismatches,
        "expected": expected,
    }


if __name__ == "__main__":
    print('Running compatibility_matrix.py')
