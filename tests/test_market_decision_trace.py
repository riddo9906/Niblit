import copy
from modules.market_decision_trace import decision_trace, outcome_attribution
from modules.market_thesis import build_market_thesis


def assessment():
    d={"side":"buy","strategy":"breakout_v1","bar":1795000000,
       "selection_reason":"Confirmed breakout","assessment_complete":True,
       "policy_version":"conditions-v2",
       "candidates":[
           {"strategy":"breakout_v1","side":"buy","evidence":{"high":120}},
           {"strategy":"ema_pullback_v1","side":"wait","evidence":{"ema":112}},
           {"strategy":"rsi_reversion_v1","side":"sell","evidence":{"rsi":72}},
       ]}
    d["market_thesis"]=build_market_thesis(d,{"observation":{
        "symbol":"ETHUSDm","venue":"mt5","account_scope":"demo-account",
        "timeframe":"5m","mode":"demo","source":"broker-observer","bar":d["bar"]}})
    return d


def test_decision_trace_deterministic_and_account_bound():
    source=assessment()
    previous=copy.deepcopy(source)
    a=decision_trace(source,adapter="mt5",symbol="ETHUSDm",account="demo-account",environment="demo")
    b=decision_trace(source,adapter="mt5",symbol="ETHUSDm",account="demo-account",environment="demo")
    assert a==b
    assert source==previous
    assert len(a["trace_id"])==64
    assert a["selected_strategy"]=="breakout_v1"
    assert a["strategy_votes"][2]["side"]=="sell"
    assert a["market_evidence_id"]==source["market_thesis"]["evidence_id"]
    assert a["counterfactual_outcomes"] is None
    assert a["learning_action"]=="record_only"
    assert a["broker_execution_authorized"] is False
    assert decision_trace(source,adapter="mt5",symbol="ETHUSDm",account="other-account",environment="demo")["trace_id"] != a["trace_id"]


def test_outcome_links_broker_return_not_fabricated_alternatives():
    decision=assessment()
    decision["decision_trace"]=decision_trace(
        decision,adapter="mt5",symbol="ETHUSDm",account="demo-account",environment="demo")
    item=outcome_attribution(
        {"decision":decision}, {"state":"closed","realized_net":-0.56},
        {"net_realized_r":-0.13})
    assert item["trace_id"]==decision["decision_trace"]["trace_id"]
    assert item["realized_net"]==-0.56
    assert item["net_realized_r"]==-0.13
    assert item["competing_strategies"][1]["strategy"]=="rsi_reversion_v1"
    assert item["counterfactual_outcomes"] is None
    assert item["learning_action"]=="record_only"


def test_old_orders_have_explicit_legacy_attribution():
    legacy=outcome_attribution({"decision":{"strategy":"breakout_v1"}},
                               {"state":"closed","realized_net":0.6},
                               {"net_realized_r":0.1})
    assert legacy["trace_id"] is None
    assert legacy["attribution"]=="legacy_order_without_decision_trace"


def test_regime_evidence_becomes_part_of_versioned_decision_trace():
    d=assessment()
    d["regime_evidence"]={"regime":"trend_up","evidence_id":"regime-001"}
    first=decision_trace(d,adapter="mt5",symbol="ETHUSDm",
                         account="demo-account",environment="demo")
    assert first["market_regime"]=="trend_up"
    assert first["regime_evidence_id"]=="regime-001"
    d["regime_evidence"]={"regime":"range","evidence_id":"regime-002"}
    second=decision_trace(d,adapter="mt5",symbol="ETHUSDm",
                          account="demo-account",environment="demo")
    assert first["trace_id"]!=second["trace_id"]
    assert second["broker_execution_authorized"] is False


def test_trace_refuses_unattributed_decision():
    import pytest
    d=assessment()
    d.pop("market_thesis")
    with pytest.raises(ValueError,match="thesis"):
        decision_trace(d,adapter="mt5",symbol="ETHUSDm",account="demo",environment="demo")
