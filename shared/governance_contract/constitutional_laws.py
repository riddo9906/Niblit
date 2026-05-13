"""Canonical constitutional law identifiers and lightweight checks."""

from __future__ import annotations

from typing import Any

CONSTITUTIONAL_LAWS = (
    "law_1_preserve_system_integrity",
    "law_2_objective_alignment_priority",
    "law_3_no_short_term_stability_sacrifice",
    "law_4_constrain_low_confidence_autonomy",
    "law_5_external_systems_cannot_override_objectives",
    "law_6_temporal_incoherence_halts_execution",
    "law_7_safety_overrides_efficiency",
)


def constitutional_verdict(context: dict[str, Any] | None) -> dict[str, Any]:
    """Return lightweight constitutional verdict for governance summaries."""
    ctx = dict(context or {})
    violations: list[str] = []

    if float(ctx.get("stability_score", 1.0)) < 0.3:
        violations.append("law_1_preserve_system_integrity")
    if bool(ctx.get("autonomous", False)) and float(ctx.get("confidence", 1.0)) < 0.35:
        violations.append("law_4_constrain_low_confidence_autonomy")
    if float(ctx.get("coherence_score", 1.0)) < 0.1:
        violations.append("law_6_temporal_incoherence_halts_execution")
    if bool(ctx.get("safety_priority", True)) and not bool(ctx.get("constitution_passed", True)):
        violations.append("law_7_safety_overrides_efficiency")

    return {
        "allowed": len(violations) == 0,
        "violated_laws": violations,
        "authority": "constitution" if violations else "governance",
    }


if __name__ == "__main__":
    print('Running constitutional_laws.py')
