"""Missing risk evidence must never be reported as a measured low risk state."""
import json

from modules.adaptive_market_cognition import AdaptiveMarketCognitionLayer, _bucket

_ALL_RISK_FIELDS = ["volatility", "drawdown", "exposure", "concentration_risk", "regime_uncertainty"]


def _record(layer, trace_id, **payload):
    # market_regime.forecast finalizes the experience, so one event carries all state.
    return layer.observe_event(
        "market_regime.forecast",
        "test",
        {"trace_id": trace_id, "symbol": "EURUSD", "regime": "bull", "evaluation_score": 0.5, **payload},
    )


def _calm_but_measured():
    return {
        "volatility": 0.02,
        "drawdown": 0.0,
        "exposure": 0.0,
        "concentration_risk": 0.0,
        "uncertainty": 0.0,
    }


def test_missing_risk_evidence_is_unknown_not_low():
    record = _record(AdaptiveMarketCognitionLayer(), "missing-risk")
    assert record["volatility_regime"] == "unknown"
    assert record["risk_state"]["volatility_state"] == "unknown"
    assert record["risk_state"]["drawdown_state"] == "unknown"
    assert record["risk_state"]["exposure_state"] == "unknown"
    assert record["risk_state"]["concentration_state"] == "unknown"
    assert record["risk_state"]["risk_evidence"] == {"state": "missing", "missing": _ALL_RISK_FIELDS}
    # The numeric contract is preserved: risk_score stays a float, it just claims no evidence.
    assert isinstance(record["risk_score"], float)
    assert record["risk_score"] == 0.0


def test_measured_zero_volatility_remains_low():
    record = _record(AdaptiveMarketCognitionLayer(), "measured-zero", volatility=0.0)
    assert record["volatility_regime"] == "low"
    assert record["risk_state"]["volatility_state"] == "low"
    evidence = record["risk_state"]["risk_evidence"]
    assert evidence["state"] == "partial"
    assert "volatility" not in evidence["missing"]
    assert record["risk_score"] == 0.0


def test_measured_volatility_buckets_and_scores_increase():
    layer = AdaptiveMarketCognitionLayer()
    calm = _record(layer, "calm", volatility=0.10)
    choppy = _record(layer, "choppy", volatility=0.55)
    wild = _record(layer, "wild", volatility=0.90)
    assert [row["risk_state"]["volatility_state"] for row in (calm, choppy, wild)] == ["low", "medium", "high"]
    assert calm["risk_score"] < choppy["risk_score"] < wild["risk_score"]
    # Only volatility is measured, so the score is that measurement, not a diluted sum.
    assert wild["risk_score"] == 0.9


def test_invalid_risk_values_are_unknown_and_never_low_or_high():
    layer = AdaptiveMarketCognitionLayer()
    for index, bad in enumerate(("n/a", True, float("nan"), float("inf"), [0.2])):
        record = _record(layer, f"invalid-{index}", volatility=bad, drawdown=None)
        assert record["risk_state"]["volatility_state"] == "unknown", bad
        assert record["risk_state"]["drawdown_state"] == "unknown", bad
        assert record["volatility_regime"] == "unknown", bad
        assert record["risk_score"] == 0.0, bad
        # Unknown evidence must stay JSON-serialisable for Qdrant/KnowledgeDB payloads.
        json.dumps(record["risk_state"], allow_nan=False)


def test_bucket_treats_non_finite_and_non_numeric_values_as_unknown():
    assert _bucket(float("nan")) == "unknown"
    assert _bucket(float("inf")) == "unknown"
    assert _bucket(float("-inf")) == "unknown"
    assert _bucket(None) == "unknown"
    assert _bucket(True) == "unknown"
    assert _bucket("not-a-number") == "unknown"
    assert _bucket(0.0) == "low"
    assert _bucket("0.80") == "high"


def test_complete_evidence_keeps_the_documented_weighted_score():
    record = _record(
        AdaptiveMarketCognitionLayer(),
        "complete",
        volatility=0.5,
        drawdown=0.2,
        exposure=0.4,
        concentration_risk=0.3,
        uncertainty=0.6,
    )
    expected = round(
        (0.5 * 0.28) + (0.2 * 0.22) + (0.4 * 0.18) + (0.3 * 0.17) + (0.6 * 0.15),
        4,
    )
    assert record["risk_score"] == expected
    assert record["risk_state"]["risk_evidence"] == {"state": "complete", "missing": []}
    assert record["risk_state"]["regime_uncertainty"] == 0.6


def test_partial_evidence_does_not_treat_missing_fields_as_zero_risk():
    record = _record(
        AdaptiveMarketCognitionLayer(),
        "partial",
        volatility=0.9,
        drawdown=0.0,
    )
    evidence = record["risk_state"]["risk_evidence"]
    assert evidence["state"] == "partial"
    assert evidence["missing"] == ["exposure", "concentration_risk", "regime_uncertainty"]
    # drawdown=0.0 is a real measurement, so it is not listed as missing anywhere.
    assert record["risk_state"]["drawdown_state"] == "low"


def test_explicit_nested_risk_state_is_not_overwritten_by_absent_fields():
    record = _record(
        AdaptiveMarketCognitionLayer(),
        "nested",
        risk_state={"volatility": 0.85, "drawdown": 0.0},
    )
    assert record["risk_state"]["volatility_state"] == "high"
    assert record["risk_state"]["drawdown_state"] == "low"
    assert record["risk_state"]["volatility"] == 0.85


def test_unknown_risk_earns_no_safety_credit_in_retrieval():
    layer = AdaptiveMarketCognitionLayer()
    _record(layer, "known-calm", **_calm_but_measured())
    _record(layer, "no-risk-data")
    bundle = layer.build_market_retrieval_bundle(query="explain the bull regime", core=None)
    scores = {item["trace_id"]: item["similarity"] for item in bundle.similar_markets}
    assert scores["known-calm"] > scores["no-risk-data"]


def test_unknown_risk_profile_is_reported_as_unknown():
    layer = AdaptiveMarketCognitionLayer()
    _record(layer, "no-risk")
    bundle = layer.build_market_retrieval_bundle(query="bull regime view", core=None)
    assert bundle.risk_profile["risk_evidence_state"] == "unknown"
    assert bundle.risk_profile["volatility_state"] == "unknown"
    assert "risk_evidence_state" in bundle.context


def test_persisted_market_fact_marks_unknown_volatility():
    layer = AdaptiveMarketCognitionLayer()
    _record(layer, "persist")

    class _Db:
        def __init__(self):
            self.facts = []

        def add_fact(self, key, value, tags=None):
            self.facts.append((key, value, tags))

    class _Core:
        def __init__(self):
            self.db = _Db()

    core = _Core()
    layer.status(core=core)
    assert core.db.facts
    _key, value, tags = core.db.facts[-1]
    assert "volatility=unknown" in value
    assert "unknown" in tags
