"""Evidence integrity for market cognition (Task 05).

The layer stores ``risk_score = 0.0`` whenever no risk input was measured. That
numeric contract is fine, but every human- or memory-facing string, confidence
derivation and risk profile must keep "not measured" distinct from "measured
zero". Reflections must also label observation, inference, prediction and
verified outcome instead of presenting derived values as verified facts.
"""
import json
from unittest.mock import patch

from modules.adaptive_market_cognition import AdaptiveMarketCognitionLayer, _clamp

_RISK_FIELDS = ["volatility", "drawdown", "exposure", "concentration_risk", "regime_uncertainty"]


class _FakeCluster:
    def __init__(self):
        self.writes = []

    def write_memory(self, text, memory_type=None, payload=None):
        self.writes.append({"text": text, "memory_type": memory_type, "payload": dict(payload or {})})


def _record(layer, trace_id, **payload):
    """Finalize one episode while capturing what would be written to memory."""
    cluster = _FakeCluster()
    target = "niblit_memory.governed_qdrant_memory.get_governed_qdrant_memory_cluster"
    with patch(target, return_value=cluster):
        record = layer.observe_event(
            "market_regime.forecast",
            "test",
            {"trace_id": trace_id, "symbol": "EURUSD", "regime": "bull", "evaluation_score": 0.5, **payload},
        )
    return record, cluster.writes


def _calm_but_measured(**overrides):
    payload = {
        "volatility": 0.0,
        "drawdown": 0.0,
        "exposure": 0.0,
        "concentration_risk": 0.0,
        "uncertainty": 0.0,
    }
    payload.update(overrides)
    return payload


# --- persistence labels -----------------------------------------------------


def test_persisted_summary_distinguishes_unmeasured_from_measured_zero():
    layer = AdaptiveMarketCognitionLayer()
    missing, missing_writes = _record(layer, "summary-missing")
    calm, calm_writes = _record(layer, "summary-calm", **_calm_but_measured())

    assert missing["risk_score"] == calm["risk_score"] == 0.0
    assert "risk=unmeasured (0/5 risk inputs measured)" in missing_writes[0]["payload"]["summary"]
    assert "risk=0.0000 (measured, 5/5 risk inputs)" in calm_writes[0]["payload"]["summary"]
    assert missing_writes[0]["payload"]["risk_score_measured"] is False
    assert calm_writes[0]["payload"]["risk_score_measured"] is True
    assert missing_writes[0]["payload"]["risk_evidence_state"] == "missing"
    assert calm_writes[0]["payload"]["risk_evidence_state"] == "complete"
    # The reflection memory carries the same labels as the episodic payload.
    assert missing_writes[1]["payload"]["risk_score_measured"] is False
    assert calm_writes[1]["payload"]["risk_score_measured"] is True


def test_partial_evidence_summary_counts_measured_inputs():
    _record_result, writes = _record(
        AdaptiveMarketCognitionLayer(), "summary-partial", volatility=0.0
    )
    payload = writes[0]["payload"]
    assert "risk=0.0000 (partial, 1/5 risk inputs)" in payload["summary"]
    assert payload["risk_evidence_state"] == "partial"
    assert payload["risk_score_measured"] is True


def test_invalid_risk_inputs_stay_unmeasured_in_the_persisted_summary():
    layer = AdaptiveMarketCognitionLayer()
    for index, bad in enumerate(("n/a", True, float("nan"), float("inf"), float("-inf"), [0.2])):
        _record_result, writes = _record(layer, f"summary-invalid-{index}", volatility=bad)
        payload = writes[0]["payload"]
        assert "risk=unmeasured" in payload["summary"], bad
        assert payload["risk_evidence_state"] == "missing", bad
        assert payload["risk_score_measured"] is False, bad
        # Payloads must stay serialisable for Qdrant/KnowledgeDB.
        json.dumps(payload, allow_nan=False)


# --- reflection terminology -------------------------------------------------


def test_reflection_labels_observed_inferred_predicted_and_verified_sections():
    record, _writes = _record(AdaptiveMarketCognitionLayer(), "reflection-sections", confidence=0.4)
    reflection = record["reflection"]
    for section in ("observed=[", "inferred=[", "predicted=[", "verified_outcome=["):
        assert section in reflection
    assert "signal_coherence=not directly measured" in reflection
    assert "regime_context=bull (assumed from event, unverified)" in reflection
    assert "verified_outcome=[none recorded" in reflection
    # The old wording asserted outcomes that were never verified.
    assert "worked=" not in reflection
    assert "assumption_correct=" not in reflection


def test_reflection_reports_the_derived_confidence_the_episode_carries():
    record, _writes = _record(AdaptiveMarketCognitionLayer(), "reflection-derived")
    # The reflection is built after derivation, so it cannot report the 0.0
    # placeholder as if it were the observed confidence.
    assert record["confidence_score"] > 0.0
    assert f"confidence_score={record['confidence_score']}" in record["reflection"]
    gap = round(record["confidence_score"] - record["evaluation_score"], 4)
    assert f"confidence_calibration={gap:+.4f}" in record["reflection"]


def test_reflection_reports_recorded_scenarios_as_unverified_predictions():
    record, _writes = _record(
        AdaptiveMarketCognitionLayer(),
        "reflection-scenario",
        scenario_probabilities={"bull": 0.6, "bear": 0.4},
    )
    assert "predicted=[p(bull=0.6000, bear=0.4000) (recorded forecast, unverified)]" in record["reflection"]


def test_reflection_reports_measured_risk_with_its_evidence_not_as_awareness():
    record, _writes = _record(AdaptiveMarketCognitionLayer(), "reflection-calm", **_calm_but_measured())
    reflection = record["reflection"]
    assert "risk=0.0000 (measured, 5/5 risk inputs)" in reflection
    assert "risk_awareness=0.0" not in reflection
    # The decision-quality index is not available when the reflection is built.
    assert "risk_awareness" not in reflection


def test_reflection_reports_unmeasured_risk_as_unmeasured():
    record, _writes = _record(AdaptiveMarketCognitionLayer(), "reflection-missing")
    reflection = record["reflection"]
    assert "risk_inputs_measured=0/5 (missing)" in reflection
    assert "risk=unmeasured (0/5 risk inputs measured)" in reflection
    assert "risk=0.0" not in reflection


def test_reflection_only_marks_outcomes_the_caller_supplied_as_verified():
    layer = AdaptiveMarketCognitionLayer()
    verified, _writes = _record(
        layer, "reflection-verified", outcome_verified=True, realized_outcome="target hit"
    )
    assert "verified_outcome=[target hit (verified)]" in verified["reflection"]

    unmarked, _writes = _record(layer, "reflection-unmarked", realized_outcome="target hit")
    assert "verification unmarked" in unmarked["reflection"]


# --- confidence -------------------------------------------------------------


def test_unmeasured_risk_confidence_is_lower_than_measured_zero_risk():
    layer = AdaptiveMarketCognitionLayer()
    missing, _ = _record(layer, "confidence-missing")
    calm, _ = _record(layer, "confidence-calm", **_calm_but_measured())

    assert calm["confidence_score"] == 0.525
    # No invented observation, but no free pass either: absent evidence costs confidence.
    assert 0.0 < missing["confidence_score"] < calm["confidence_score"]


def test_partial_evidence_confidence_sits_between_missing_and_complete():
    layer = AdaptiveMarketCognitionLayer()
    missing, _ = _record(layer, "confidence-none")
    partial, _ = _record(layer, "confidence-partial", volatility=0.0)
    complete, _ = _record(layer, "confidence-complete", **_calm_but_measured())

    assert missing["confidence_score"] < partial["confidence_score"] < complete["confidence_score"]


def test_measured_risk_still_lowers_derived_confidence():
    layer = AdaptiveMarketCognitionLayer()
    calm, _ = _record(layer, "confidence-risk-calm", **_calm_but_measured())
    risky, _ = _record(
        layer,
        "confidence-risk-high",
        volatility=1.0,
        drawdown=1.0,
        exposure=1.0,
        concentration_risk=1.0,
        uncertainty=1.0,
    )
    assert risky["risk_score"] == 1.0
    assert risky["confidence_score"] < calm["confidence_score"]


def test_invalid_confidence_and_risk_inputs_yield_finite_confidence():
    record, _writes = _record(
        AdaptiveMarketCognitionLayer(),
        "confidence-invalid",
        confidence=float("nan"),
        volatility=float("inf"),
        uncertainty="n/a",
    )
    confidence = record["confidence_score"]
    assert isinstance(confidence, float)
    assert 0.0 <= confidence <= 1.0
    json.dumps(record["metaevaluation"], allow_nan=False)
    json.dumps(record["risk_state"], allow_nan=False)


# --- DQI consistency --------------------------------------------------------


def test_dqi_policy_and_evidence_state_agree_across_record_history_status_and_memory():
    layer = AdaptiveMarketCognitionLayer()
    record, writes = _record(layer, "dqi-consistency", volatility=0.4)
    status = layer.status()
    history = status["dqi_scores"][-1]

    assert record["dqi_policy"] == history["dqi_policy"] == status["dqi_policy"] == AdaptiveMarketCognitionLayer._DQI_POLICY
    assert history["latest"] == record["dqi_score"]
    assert history["risk_awareness_state"] == "partial"
    assert history["risk_awareness_measured"] is True
    for write in writes:
        payload = write["payload"]
        assert payload["dqi_policy"] == AdaptiveMarketCognitionLayer._DQI_POLICY
        assert payload["dqi_score"] == record["dqi_score"]
        assert payload["risk_evidence_state"] == "partial"
        assert payload["risk_score_measured"] is True

    snapshot = layer._dqi_snapshot(status["dqi_scores"], [])
    assert snapshot["policy"] == AdaptiveMarketCognitionLayer._DQI_POLICY
    assert snapshot["latest_risk_awareness_state"] == "partial"
    assert snapshot["latest_risk_awareness_measured"] is True
    assert snapshot["latest"] == round(record["dqi_score"], 4)


def test_coherence_projection_stays_independent_of_a_low_dqi():
    layer = AdaptiveMarketCognitionLayer()
    record, writes = _record(layer, "coherence-floor", evaluation_score=0.0, confidence=0.0)

    assert record["dqi_score"] < 0.3
    payload = writes[0]["payload"]
    # The constitutional admissibility floor applies to coherence, not the DQI.
    assert payload["coherence_score"] == 0.3
    assert payload["dqi_score"] == record["dqi_score"]
    assert payload["coherence_score"] != payload["dqi_score"]


def test_dqi_snapshot_reports_a_recorded_zero_instead_of_substituting_the_average():
    layer = AdaptiveMarketCognitionLayer()
    snapshot = layer._dqi_snapshot(
        [
            {"latest": 0.8, "risk_awareness_state": "complete", "risk_awareness_measured": True},
            {"latest": 0.0, "risk_awareness_state": "missing", "risk_awareness_measured": False},
        ],
        [],
    )
    assert snapshot["latest"] == 0.0
    assert snapshot["recent_average"] == 0.4
    assert snapshot["latest_risk_awareness_state"] == "missing"
    assert snapshot["latest_risk_awareness_measured"] is False


def test_retrieval_risk_profile_ignores_records_with_no_risk_evidence():
    layer = AdaptiveMarketCognitionLayer()
    _record(
        layer,
        "profile-measured",
        volatility=0.9,
        drawdown=0.9,
        exposure=0.9,
        concentration_risk=0.9,
        uncertainty=0.9,
    )
    _record(layer, "profile-unmeasured")

    bundle = layer.build_market_retrieval_bundle(query="bull regime view", core=None)
    profile = bundle.risk_profile
    # The unmeasured record's 0.0 placeholder must not average the risk down.
    assert profile["risk_score"] == 0.9
    assert profile["risk_inputs_measured"] == 1
    assert profile["experiences_considered"] == 2
    assert profile["risk_evidence_state"] == "partial"
    json.dumps(bundle.to_payload(), allow_nan=False)


def test_unknown_risk_labels_are_bounded_and_clamped():
    # Guards the public numeric contract while labels do the explaining.
    assert _clamp(None) == 0.0
    assert _clamp(float("nan")) == 0.0
    assert _clamp(2.0) == 1.0
