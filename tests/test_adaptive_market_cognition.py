"""Market cognition must not invent volatility state or let a default guess rank results."""
from modules.adaptive_market_cognition import AdaptiveMarketCognitionLayer, _bucket


def _experience(layer, trace_id, **payload):
    # market_regime.forecast finalizes the experience, so one event carries all state.
    return layer.observe_event(
        "market_regime.forecast",
        "test",
        {"trace_id": trace_id, "symbol": "EURUSD", "regime": "bull", "evaluation_score": 0.5, **payload},
    )


def test_missing_volatility_is_unknown_not_low():
    layer = AdaptiveMarketCognitionLayer()
    record = _experience(layer, "no-vol")
    assert record["volatility_regime"] == "unknown"


def test_measured_volatility_still_buckets_normally():
    layer = AdaptiveMarketCognitionLayer()
    assert _experience(layer, "calm", volatility=0.10)["volatility_regime"] == "low"
    assert _experience(layer, "choppy", volatility=0.55)["volatility_regime"] == "medium"
    assert _experience(layer, "wild", volatility=0.90)["volatility_regime"] == "high"


def test_absent_values_are_never_reported_as_a_low_bucket():
    assert _bucket(None) == "unknown"
    assert _bucket("") == "unknown"
    assert _bucket("not-a-number") == "unknown"
    assert _bucket(True) == "unknown"
    assert _bucket(0.0) == "low"


def test_query_without_a_volatility_cue_gives_no_volatility_bonus():
    layer = AdaptiveMarketCognitionLayer()
    _experience(layer, "medium-vol", volatility_regime="medium")
    _experience(layer, "no-vol-data")
    bundle = layer.build_market_retrieval_bundle(query="explain the bull regime", core=None)
    by_trace = {item["trace_id"]: item["similarity"] for item in bundle.similar_markets}
    assert by_trace["medium-vol"] == by_trace["no-vol-data"]


def test_explicit_volatility_cue_still_prefers_the_matching_experience():
    layer = AdaptiveMarketCognitionLayer()
    _experience(layer, "wild", volatility_regime="high")
    _experience(layer, "calm", volatility_regime="low")
    bundle = layer.build_market_retrieval_bundle(query="high volatility breakout", core=None)
    assert bundle.similar_markets[0]["trace_id"] == "wild"
    scores = {item["trace_id"]: item["similarity"] for item in bundle.similar_markets}
    assert scores["wild"] > scores["calm"]
