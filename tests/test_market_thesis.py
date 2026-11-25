"""Market thesis is traceable analysis, never a new execution decision."""
from modules.market_thesis import build_market_thesis


def test_directional_hypothesis_retains_support_and_provenance():
    assessment = {"side": "buy", "assessment_complete": True, "candidates": [
        {"strategy": "trend_v1", "side": "buy"},
        {"strategy": "breakout_v1", "side": "wait"},
    ]}
    original = dict(assessment)
    thesis = build_market_thesis(assessment, {"observation": {
        "symbol": "BTCUSDm", "venue": "mt5", "bar": 1700000000}})
    assert thesis["classification"] == "directional_hypothesis"
    assert thesis["supporting_strategies"] == ["trend_v1"]
    assert thesis["abstaining_strategies"] == ["breakout_v1"]
    assert thesis["provenance"]["symbol"] == "BTCUSDm"
    assert not thesis["execution_authorized"]
    assert assessment == original


def test_opposing_votes_remain_unresolved_and_evidence_is_stable():
    assessment = {"side": "wait", "assessment_complete": True, "candidates": [
        {"strategy": "trend_v1", "side": "sell"},
        {"strategy": "breakout_v1", "side": "buy"},
    ]}
    scope = {"observation": {"symbol": "ETHUSDm", "bar": 1700000000}}
    a = build_market_thesis(assessment, scope)
    b = build_market_thesis(assessment, scope)
    assert a["classification"] == "directional_conflict"
    assert a["vote_counts"] == {"buy": 1, "sell": 1}
    assert a["evidence_id"] == b["evidence_id"]
    assert a["analysis_only"]


def test_failure_is_not_recast_as_high_confidence():
    result = build_market_thesis({"side": "wait", "assessment_complete": False,
        "candidates": [{"strategy": "trend_v1", "side": "wait", "status": "failed"}]},
        {"observation": {"symbol": "SOLUSDm"}})
    assert result["classification"] == "incomplete_evidence"
    assert result["failed_strategies"] == ["trend_v1"]
    assert "no probability" in result["uncertainty"].lower()


def test_freqtrade_without_higher_timeframe_context_has_thesis():
    from unittest.mock import patch
    from modules.strategy_manager import assess_with_context
    mock_votes = {
        "side": "wait",
        "strategy": "auto",
        "assessment_complete": True,
        "candidates": [
            {"strategy": "trend_v1", "side": "wait"},
            {"strategy": "breakout_v1", "side": "wait"},
        ],
    }
    with patch("modules.strategy_manager.assess", return_value=mock_votes):
        result = assess_with_context([{"timestamp": 1795246200}], context=None)
    assert result["side"] == "wait"
    assert result["market_thesis"]["classification"] == "no_qualifying_setup"
    assert result["market_thesis"]["analysis_only"]
    assert result["market_thesis"]["execution_authorized"] is False


def test_same_bar_revised_strategy_measurement_has_distinct_evidence_id():
    from copy import deepcopy
    original = {"side": "buy", "assessment_complete": True, "candidates": [
        {"strategy": "trend_v1", "side": "buy", "evidence": {"close": 100, "rsi14": 61}}
    ]}
    revised = deepcopy(original)
    revised["candidates"][0]["evidence"]["close"] = 105
    scope = {"observation": {"symbol": "BTCUSDm", "venue": "mt5", "bar": 1795253400}}
    first = build_market_thesis(original, scope)
    second = build_market_thesis(revised, scope)
    assert first["schema"] == "niblit.market-thesis/2"
    assert first["evidence_id"] != second["evidence_id"]
    assert first["classification"] == second["classification"]
    assert first["execution_authorized"] is False


def test_same_measurements_and_scope_keep_stable_identity():
    assessment = {"side": "sell", "assessment_complete": True, "candidates": [
        {"strategy": "trend_v1", "side": "sell", "evidence": {"rsi14": 35}}
    ]}
    observation = {"observation": {"symbol": "BTCUSDm", "bar": 1795253400}}
    first = build_market_thesis(assessment, observation)
    second = build_market_thesis(assessment, observation)
    assert first["evidence_id"] == second["evidence_id"]
