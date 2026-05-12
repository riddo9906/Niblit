from __future__ import annotations

from nibblebots.workflow_governance_helpers import build_workflow_output, classify_drift_risk


def test_classify_drift_risk_levels() -> None:
    assert classify_drift_risk(governance_impact="none", schema_impact="none", runtime_impact="none", federation_impact="none") == "low"
    assert classify_drift_risk(governance_impact="medium", schema_impact="low", runtime_impact="low", federation_impact="low") == "medium"
    assert classify_drift_risk(governance_impact="high", schema_impact="high", runtime_impact="medium", federation_impact="medium") == "high"


def test_build_workflow_output_schema() -> None:
    payload = build_workflow_output(
        workflow_name="niblit-cognitive-orchestrator",
        findings=["missing_concurrency:test.yml"],
        proposals=["add_concurrency:test.yml"],
        governance_impact="medium",
        schema_impact="low",
        runtime_impact="medium",
        federation_impact="low",
        confidence=0.8,
    )
    assert payload["workflow"] == "niblit-cognitive-orchestrator"
    assert payload["drift_risk"] in {"low", "medium", "high"}
    assert isinstance(payload["findings"], list)
    assert isinstance(payload["proposals"], list)


if __name__ == "__main__":
    print('Running test_phase_omega_8_workflow_governance.py')
