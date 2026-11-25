"""Quality scores (DQI, prediction_usefulness) must not invent safety credit.

Task 03: a record that measured no risk inputs still reported full "risk
awareness" inside the decision-quality index, and a record that measured no
regime uncertainty still reported a perfect prediction usefulness of 1.0.
"""
import json

from modules.adaptive_market_cognition import AdaptiveMarketCognitionLayer, _clamp

_RISK_FIELDS = ["volatility", "drawdown", "exposure", "concentration_risk", "regime_uncertainty"]


def _record(layer, trace_id, **payload):
    return layer.observe_event(
        "market_regime.forecast",
        "test",
        {"trace_id": trace_id, "symbol": "EURUSD", "regime": "bull", "evaluation_score": 0.5, **payload},
    )


def _calm_but_measured(**overrides):
    payload = {
        "volatility": 0.02,
        "drawdown": 0.0,
        "exposure": 0.0,
        "concentration_risk": 0.0,
        "uncertainty": 0.0,
    }
    payload.update(overrides)
    return payload


def _documented_dqi(record, risk_awareness):
    """Reconstruct weighted DQI with the risk term supplied independently.

    Policy v2 uses labelled-evidence reasoning rather than reflection length.
    The component is pinned here so the test isolates missing-risk credit.
    """
    reflection_quality = record["dqi_components"]["terms"]["reasoning"]
    retrieval_quality = min(1.0, len(record.get("retrievals", [])) / 6.0)
    signal_quality = _clamp(record.get("signal_state", {}).get("signal_strength"))
    confidence_quality = 1.0 - abs(
        _clamp(record.get("confidence_score")) - _clamp(record.get("evaluation_score"))
    )
    evaluation_quality = _clamp(record.get("evaluation_score"))
    outcome_quality = _clamp(
        record.get("outcome_state", {}).get("quality_score") or record.get("evaluation_score")
    )
    return round(
        min(
            1.0,
            (signal_quality * 0.14)
            + (confidence_quality * 0.17)
            + (reflection_quality * 0.14)
            + (evaluation_quality * 0.18)
            + (risk_awareness * 0.14)
            + (retrieval_quality * 0.1)
            + (outcome_quality * 0.13),
        ),
        4,
    )


def test_missing_risk_evidence_earns_no_dqi_safety_credit():
    layer = AdaptiveMarketCognitionLayer()
    # Pin confidence: Task 05 makes derived confidence evidence-aware, so only an
    # explicitly recorded confidence keeps this a pure risk-term comparison.
    missing = _record(layer, "dqi-missing", confidence=0.5)
    calm = _record(layer, "dqi-calm", confidence=0.5, **_calm_but_measured(volatility=0.0))

    assert missing["risk_state"]["risk_evidence"]["state"] == "missing"
    assert missing["dqi_score"] == _documented_dqi(missing, 0.0)
    # Same evaluation/confidence numbers, so the only difference is the risk term.
    assert round(calm["dqi_score"] - missing["dqi_score"], 4) == 0.14


def test_complete_evidence_retains_the_documented_dqi_baseline():
    record = _record(
        AdaptiveMarketCognitionLayer(),
        "dqi-complete",
        volatility=0.5,
        drawdown=0.2,
        exposure=0.4,
        concentration_risk=0.3,
        uncertainty=0.6,
    )
    assert record["risk_state"]["risk_evidence"]["state"] == "complete"
    assert record["dqi_score"] == _documented_dqi(record, 1.0 - record["risk_score"])


def test_partial_evidence_does_not_receive_complete_risk_credit():
    layer = AdaptiveMarketCognitionLayer()
    partial = _record(layer, "dqi-partial", volatility=0.0)
    calm = _record(layer, "dqi-complete-calm", **_calm_but_measured(volatility=0.0))

    # Both measured a zero risk score, so only the evidence coverage may differ.
    assert partial["risk_score"] == calm["risk_score"] == 0.0
    assert partial["risk_state"]["risk_evidence"]["state"] == "partial"
    partial_entry = layer.status()["dqi_scores"][0]
    calm_entry = layer.status()["dqi_scores"][1]
    assert partial_entry["risk_awareness"] < calm_entry["risk_awareness"]
    assert partial_entry["risk_awareness"] > 0.0
    assert partial["dqi_score"] < calm["dqi_score"]


def test_measured_zero_regime_uncertainty_is_a_real_measurement():
    record = _record(
        AdaptiveMarketCognitionLayer(),
        "uncertainty-zero",
        volatility=0.1,
        uncertainty=0.0,
    )
    assert record["metaevaluation"]["prediction_usefulness"] == 1.0
    assert record["metaevaluation"]["prediction_usefulness_evidence"] == "measured"


def test_unmeasured_regime_uncertainty_is_not_reported_as_useful():
    record = _record(AdaptiveMarketCognitionLayer(), "uncertainty-missing", volatility=0.1)
    assert "regime_uncertainty" in record["risk_state"]["risk_evidence"]["missing"]
    assert record["metaevaluation"]["prediction_usefulness"] is None
    assert record["metaevaluation"]["prediction_usefulness_evidence"] == "unmeasured"
    # Null is honest and still serialisable for persistence.
    json.dumps(record["metaevaluation"], allow_nan=False)


def test_non_finite_regime_uncertainty_is_unmeasured_not_perfect():
    layer = AdaptiveMarketCognitionLayer()
    for index, bad in enumerate((float("nan"), float("inf"), float("-inf"), "n/a", True)):
        record = _record(layer, f"uncertainty-bad-{index}", volatility=0.1, uncertainty=bad)
        assert record["risk_state"]["regime_uncertainty"] == 0.0, bad
        assert record["metaevaluation"]["prediction_usefulness"] is None, bad
        assert record["metaevaluation"]["prediction_usefulness_evidence"] == "unmeasured", bad


def test_dqi_history_matches_the_computed_score_and_evidence_state():
    layer = AdaptiveMarketCognitionLayer()
    missing = _record(layer, "hist-missing")
    partial = _record(layer, "hist-partial", volatility=0.0)
    complete = _record(
        layer,
        "hist-complete",
        volatility=0.0,
        drawdown=0.0,
        exposure=0.0,
        concentration_risk=0.0,
        uncertainty=0.0,
    )
    entries = layer.status()["dqi_scores"]
    assert [entry["latest"] for entry in entries] == [
        missing["dqi_score"],
        partial["dqi_score"],
        complete["dqi_score"],
    ]
    assert [entry["risk_awareness_state"] for entry in entries] == ["missing", "partial", "complete"]
    assert [entry["risk_awareness_measured"] for entry in entries] == [False, True, True]
    # Missing evidence earns 0.0, not the 1.0 that a zero risk score used to imply.
    # The recorded value is the weighted credit the DQI actually applied (max 0.14).
    assert entries[0]["risk_awareness"] == 0.0
    assert entries[2]["risk_awareness"] == round((1.0 - complete["risk_score"]) * 0.14, 4)
    assert entries[0]["risk_evidence_coverage"] == 0.0
    assert entries[2]["risk_evidence_coverage"] == 1.0
    assert entries[1]["risk_awareness"] < entries[2]["risk_awareness"]


def test_dqi_and_metaevaluation_telemetry_is_json_serialisable():
    layer = AdaptiveMarketCognitionLayer()
    _record(layer, "json-missing")
    _record(layer, "json-partial", volatility=0.8)
    _record(layer, "json-complete", **_calm_but_measured())
    status = layer.status()
    json.dumps(status, allow_nan=False)
    json.dumps(layer.render_command("market intelligence dqi"), allow_nan=False)
    for entry in status["dqi_scores"]:
        assert 0.0 <= entry["latest"] <= 1.0
        assert 0.0 <= entry["risk_awareness"] <= 1.0


def test_dqi_stays_bounded_for_extreme_complete_evidence():
    record = _record(
        AdaptiveMarketCognitionLayer(),
        "extreme",
        volatility=5.0,
        drawdown=-2.0,
        exposure=1.0,
        concentration_risk=1.0,
        uncertainty=1.0,
        signal_strength=1.0,
        quality_score=1.0,
    )
    assert 0.0 <= record["dqi_score"] <= 1.0
    assert record["risk_state"]["risk_evidence"]["state"] == "complete"
