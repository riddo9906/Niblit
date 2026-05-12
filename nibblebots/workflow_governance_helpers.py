"""Workflow governance helper utilities for anti-drift orchestration."""

from __future__ import annotations

from typing import Any


def classify_drift_risk(*, governance_impact: str, schema_impact: str, runtime_impact: str, federation_impact: str) -> str:
    """Classify drift risk from structured impact dimensions."""
    weights = {
        "none": 0,
        "low": 1,
        "medium": 2,
        "high": 3,
    }
    score = sum(
        weights.get(str(v).strip().lower(), 1)
        for v in (governance_impact, schema_impact, runtime_impact, federation_impact)
    )
    if score <= 2:
        return "low"
    if score <= 6:
        return "medium"
    return "high"


def build_workflow_output(
    *,
    workflow_name: str,
    findings: list[str] | None = None,
    proposals: list[str] | None = None,
    governance_impact: str = "low",
    schema_impact: str = "low",
    runtime_impact: str = "low",
    federation_impact: str = "low",
    confidence: float = 0.7,
) -> dict[str, Any]:
    """Return standardized workflow output schema."""
    drift_risk = classify_drift_risk(
        governance_impact=governance_impact,
        schema_impact=schema_impact,
        runtime_impact=runtime_impact,
        federation_impact=federation_impact,
    )
    return {
        "workflow": workflow_name,
        "findings": list(findings or []),
        "proposals": list(proposals or []),
        "drift_risk": drift_risk,
        "governance_alignment": governance_impact,
        "schema_impact": schema_impact,
        "runtime_impact": runtime_impact,
        "federation_impact": federation_impact,
        "architectural_impact": "high" if drift_risk == "high" else "medium" if drift_risk == "medium" else "low",
        "confidence": max(0.0, min(1.0, float(confidence))),
    }


if __name__ == "__main__":
    print('Running workflow_governance_helpers.py')
