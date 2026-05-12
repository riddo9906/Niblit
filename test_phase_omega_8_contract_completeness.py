"""Phase Ω.8 governance contract completeness tests.

Covers: normalize_telemetry, normalize_replay_metadata, constitutional_verdict,
anti_drift_report, and advisor protocol normalization — completing the
targeted Phase 5 validation surface for the canonical governance/orchestration
authority contract.
"""
from __future__ import annotations

from shared.governance_contract import (
    anti_drift_report,
    normalize_advisor_votes,
    normalize_replay_metadata,
    normalize_telemetry,
)
from shared.governance_contract.constitutional_laws import constitutional_verdict

# ── telemetry normalization ───────────────────────────────────────────────────

def test_normalize_telemetry_defaults() -> None:
    tel = normalize_telemetry({})
    assert tel["runtime_mode"] == "normal"
    assert tel["governance_mode"] == "normal"
    assert 0.0 <= tel["coherence_score"] <= 1.0
    assert 0.0 <= tel["coherence_drift"] <= 1.0
    assert tel["source"] == "unknown"


def test_normalize_telemetry_clamping() -> None:
    tel = normalize_telemetry({"coherence_score": 2.0, "coherence_drift": -0.5, "runtime_health": 99.0})
    assert tel["coherence_score"] == 1.0
    assert tel["coherence_drift"] == 0.0
    assert tel["runtime_health"] == 1.0


def test_normalize_telemetry_passthrough() -> None:
    tel = normalize_telemetry({
        "runtime_mode": "survival",
        "governance_mode": "lockdown",
        "epoch_id": 42,
        "source": "cloud",
        "model_trust": 0.75,
    })
    assert tel["runtime_mode"] == "survival"
    assert tel["governance_mode"] == "lockdown"
    assert tel["epoch_id"] == 42
    assert tel["source"] == "cloud"
    assert tel["model_trust"] == 0.75


# ── replay metadata normalization ─────────────────────────────────────────────

def test_normalize_replay_metadata_defaults() -> None:
    meta = normalize_replay_metadata({})
    assert isinstance(meta["trace_id"], str)
    assert meta["trace_id"].startswith("trace-")
    assert isinstance(meta["decision_lineage"], list)
    assert isinstance(meta["confidence_evolution"], list)
    assert isinstance(meta["causal_references"], list)


def test_normalize_replay_metadata_passthrough() -> None:
    meta = normalize_replay_metadata({
        "trace_id": "t-abc",
        "decision_lineage": ["step1", "step2"],
        "confidence_evolution": [0.6, 0.7, 0.8],
        "causal_references": ["ref1"],
        "governance_replay": {"mode_at_decision": "cautious"},
    })
    assert meta["trace_id"] == "t-abc"
    assert meta["decision_lineage"] == ["step1", "step2"]
    assert meta["confidence_evolution"] == [0.6, 0.7, 0.8]
    assert meta["causal_references"] == ["ref1"]
    assert meta["governance_replay"]["mode_at_decision"] == "cautious"


def test_normalize_replay_metadata_causal_trace_id_alias() -> None:
    meta = normalize_replay_metadata({"causal_trace_id": "causal-xyz"})
    assert meta["trace_id"] == "causal-xyz"


def test_normalize_replay_metadata_memory_reference_ids_alias() -> None:
    meta = normalize_replay_metadata({"memory_reference_ids": ["m1", "m2"]})
    assert meta["causal_references"] == ["m1", "m2"]


# ── constitutional verdict ────────────────────────────────────────────────────

def test_constitutional_verdict_allowed_by_default() -> None:
    verdict = constitutional_verdict({})
    assert verdict["allowed"] is True
    assert verdict["violated_laws"] == []


def test_constitutional_verdict_low_stability_blocks() -> None:
    verdict = constitutional_verdict({"stability_score": 0.1})
    assert not verdict["allowed"]
    assert "law_1_preserve_system_integrity" in verdict["violated_laws"]


def test_constitutional_verdict_low_coherence_blocks() -> None:
    verdict = constitutional_verdict({"coherence_score": 0.05})
    assert not verdict["allowed"]
    assert "law_6_temporal_incoherence_halts_execution" in verdict["violated_laws"]


def test_constitutional_verdict_low_confidence_autonomous_blocks() -> None:
    verdict = constitutional_verdict({"autonomous": True, "confidence": 0.2})
    assert not verdict["allowed"]
    assert "law_4_constrain_low_confidence_autonomy" in verdict["violated_laws"]


def test_constitutional_verdict_authority_field() -> None:
    good = constitutional_verdict({"stability_score": 1.0})
    bad = constitutional_verdict({"stability_score": 0.1})
    assert good["authority"] == "governance"
    assert bad["authority"] == "constitution"


# ── anti-drift report ─────────────────────────────────────────────────────────

def test_anti_drift_report_low_risk_clean_state() -> None:
    report = anti_drift_report(contract=None, compatibility=None)
    assert report["drift_risk"] == "low"
    assert report["drift_factors"] == []


def test_anti_drift_report_unknown_events_detected() -> None:
    report = anti_drift_report(
        contract=None,
        compatibility=None,
        observed_events=["completely.unknown.event"],
    )
    assert "unknown_events_detected" in report["drift_factors"]
    assert "completely.unknown.event" in report["unknown_events"]


def test_anti_drift_report_compat_mismatch_raises_risk() -> None:
    mismatch_compat = {
        "schema_version": "99.x",
        "event_contract_version": "omega-7",
        "governance_contract_version": "1.x",
        "advisor_protocol_version": "2.x",
        "runtime_mode_contract": "2026.05",
    }
    report = anti_drift_report(contract=None, compatibility=mismatch_compat)
    assert "compatibility_mismatch" in report["drift_factors"]
    assert report["drift_risk"] in {"medium", "high"}


def test_anti_drift_report_multiple_factors_yield_high_risk() -> None:
    mismatch_compat = {"schema_version": "99.x"}
    report = anti_drift_report(
        contract=None,
        compatibility=mismatch_compat,
        observed_events=["completely.unknown.event"],
    )
    assert report["drift_risk"] == "high"


# ── advisor protocol normalization ────────────────────────────────────────────

def test_normalize_advisor_votes_empty() -> None:
    result = normalize_advisor_votes({})
    assert isinstance(result, dict)
    assert result == {}


def test_normalize_advisor_votes_passthrough() -> None:
    env = {
        "advisors": {
            "votes": {
                "advisor_1": {"direction": "BUY", "confidence": 0.8},
            }
        }
    }
    result = normalize_advisor_votes(env)
    assert "advisor_1" in result
    assert result["advisor_1"]["direction"] == "BUY"
    assert 0.0 <= result["advisor_1"]["confidence"] <= 1.0


def test_validate_runtime_contract_non_dict_advisors_flagged() -> None:
    """Envelope with a non-dict 'advisors' field should trigger advisor_protocol_invalid."""
    from shared.governance_contract import validate_runtime_contract
    env = {"advisors": "invalid_advisors_string"}
    check = validate_runtime_contract(env)
    assert "advisor_protocol_invalid" in check["issues"]


if __name__ == "__main__":
    print("Running test_phase_omega_8_contract_completeness.py")
