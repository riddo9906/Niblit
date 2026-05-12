"""Anti-drift and contract validation helpers."""

from __future__ import annotations

from typing import Any

from .advisor_protocol import normalize_advisor_votes
from .compatibility_matrix import validate_compatibility
from .event_constants import CANONICAL_EVENTS
from .runtime_modes import normalize_runtime_mode
from .schema_v2 import SCHEMA_V2_REQUIRED_FIELDS, ensure_schema_v2


def validate_runtime_contract(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Validate schema/runtime/governance/advisor contract consistency."""
    env = ensure_schema_v2(payload)
    issues: list[str] = []

    for field in SCHEMA_V2_REQUIRED_FIELDS:
        if field not in env:
            issues.append(f"missing:{field}")

    runtime_mode = normalize_runtime_mode((env.get("runtime") or {}).get("mode"))
    governance_mode = normalize_runtime_mode((env.get("governance") or {}).get("governance_mode"))
    if runtime_mode != governance_mode:
        issues.append("mode_mismatch:runtime_vs_governance")

    if not isinstance(normalize_advisor_votes(env), dict):
        issues.append("advisor_protocol_invalid")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "normalized": env,
        "runtime_mode": runtime_mode,
        "governance_mode": governance_mode,
    }


def anti_drift_report(
    *,
    contract: dict[str, Any] | None,
    compatibility: dict[str, Any] | None,
    observed_events: list[str] | None = None,
) -> dict[str, Any]:
    """Return semantic drift assessment for governance orchestration workflows."""
    contract_check = validate_runtime_contract(contract)
    compat_check = validate_compatibility(compatibility)

    observed = set(observed_events or [])
    unknown_events = sorted(list(observed - CANONICAL_EVENTS))

    drift_factors: list[str] = []
    if not contract_check["valid"]:
        drift_factors.append("runtime_contract_invalid")
    if not compat_check["compatible"]:
        drift_factors.append("compatibility_mismatch")
    if unknown_events:
        drift_factors.append("unknown_events_detected")

    if len(drift_factors) == 0:
        drift_risk = "low"
    elif len(drift_factors) == 1:
        drift_risk = "medium"
    else:
        drift_risk = "high"

    return {
        "drift_risk": drift_risk,
        "drift_factors": drift_factors,
        "unknown_events": unknown_events,
        "contract": contract_check,
        "compatibility": compat_check,
    }


if __name__ == "__main__":
    print('Running validators.py')
