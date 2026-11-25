import pytest

from modules.market_counterfactual_lab import shadow_compare


TRACE={"trace_id":"trace-001","strategy_votes":[
    {"strategy":"breakout_v1","side":"buy"},
    {"strategy":"ema_pullback_v1","side":"wait"},
    {"strategy":"rsi_reversion_v1","side":"sell"},
]}


def quotes(*,start=1000,step=100,count=7,bid0=100.,incr=0.8):
    return [{"timestamp":start+i*step, "bid":bid0+i*incr,
             "ask":bid0+i*incr+0.2} for i in range(count)]


def compare(q=None,**kwargs):
    return shadow_compare(decision_trace=TRACE,
        observed_bidask=q if q is not None else quotes(),
        decision_at=1000,horizon_seconds=600,quantity=1.,
        stop_distance=3.,cash_per_price_unit=1.,
        round_trip_cost_cash=.25,**kwargs)


def test_all_actual_candidate_votes_are_included():
    result=compare()
    choices=result["alternatives"]
    assert [c["strategy"] for c in choices]==[
        "WAIT","breakout_v1","ema_pullback_v1","rsi_reversion_v1"]
    assert choices[0]["modelled_net_cash"]==0
    assert choices[1]["modelled_net_cash"]>0
    assert choices[3]["modelled_net_cash"]<0
    assert all(c["broker_fill_verified"] is False for c in choices)
    assert result["actual_broker_outcome"] is None
    assert result["learning_action"]=="shadow_only"


def test_spread_is_paid_on_each_assumed_bid_ask_path():
    result=compare()
    buy=result["alternatives"][1]
    sell=result["alternatives"][3]
    assert buy["entry_assumed_price"]==pytest.approx(100.2)
    assert buy["exit_assumed_price"]>=100.
    assert buy["gross_price_gain_per_unit"]==pytest.approx(
        buy["exit_assumed_price"]-buy["entry_assumed_price"])
    assert sell["entry_assumed_price"]==pytest.approx(100.)
    assert sell["counterfactual_r"]<0


def test_unknown_costs_do_not_become_fake_net_profit():
    result=shadow_compare(decision_trace=TRACE,observed_bidask=quotes(),
        decision_at=1000,horizon_seconds=600,quantity=1.,stop_distance=3.)
    buy=result["alternatives"][1]
    assert buy["counterfactual_r"] is not None
    assert buy["modelled_gross_cash"] is None
    assert buy["modelled_net_cash"] is None
    assert not buy["price_costs_complete"]


def test_missing_horizon_and_missing_middle_quote_abstain():
    a=compare(q=quotes(count=3))
    assert not a["quotes_complete"]
    assert a["alternatives"][1]["counterfactual_r"] is None
    b=compare(q=quotes(step=400,count=3))
    assert not b["quotes_complete"]
    assert b["alternatives"][3]["modelled_net_cash"] is None


def test_sampled_stop_gap_fills_at_available_quote_not_imaginary_stop():
    fall=quotes(incr=-1.5)
    result=compare(q=fall)
    buy=result["alternatives"][1]
    assert buy["sampled_exit_reason"]=="sampled_stop_touch"
    assert buy["exit_assumed_price"]<buy["entry_assumed_price"]-3.
    assert "assumptions" in result["fill_model"]


def test_sampled_target_touch():
    up=quotes()
    result=compare(q=up,target_distance=1.2)
    buy=result["alternatives"][1]
    assert buy["sampled_exit_reason"]=="sampled_target_touch"
    assert buy["exit_quote_timestamp"]<1600


def test_no_future_data_can_be_used_in_horizon():
    with_future=quotes()+[{"timestamp":4000,"bid":900.,"ask":901.}]
    assert compare(q=quotes())["alternatives"]==compare(q=with_future)["alternatives"]
    assert compare(q=quotes())["quote_evidence_id"]==compare(q=with_future)["quote_evidence_id"]


def test_quote_integrity_and_cost_validation():
    with pytest.raises(ValueError,match="chronology"):
        compare(q=list(reversed(quotes())))
    invalid=quotes()
    invalid[-1]["ask"]=1
    with pytest.raises(ValueError,match="Crossed"):
        compare(q=invalid)
    with pytest.raises(ValueError,match="Cash"):
        shadow_compare(decision_trace=TRACE, observed_bidask=quotes(),
            decision_at=1000,horizon_seconds=600,quantity=1.,stop_distance=3.,
            round_trip_cost_cash=-.01)


def test_replay_is_deterministic():
    assert compare()==compare()
    assert compare()["execution_authorized"] is False


def test_wait_votes_are_not_forced_into_trades():
    entry=compare()["alternatives"][2]
    assert entry["side"]=="wait"
    assert entry["counterfactual_r"]==0.0
    assert entry["modelled_net_cash"]==0.0
    assert entry["evaluation"]=="no_trade_benchmark"


def test_absent_entry_sample_is_not_modelled_as_fill():
    later=quotes(start=1600,count=1)
    result=compare(q=later)
    assert not result["quotes_complete"]
    assert result["alternatives"][1]["counterfactual_r"] is None
