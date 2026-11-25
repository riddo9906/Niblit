import copy
import pytest
from modules.strategy_performance_shadow import shadow_rank


def record(name, n, value, account="demo-A", **kw):
    r={"broker_deal_group_id":f"{name}-{n}-{account}","account":account,
       "symbol":"ETHUSDm","timeframe":"M5","regime":"trend_up",
       "closed_at":n if n<=40 else 1000+n,
       "entry_strategy":name,"net_realized_r":value,
       "broker_verified":True,"all_fees_included":True,"actual_fill":True}
    r.update(kw)
    return r


def data():
    rows=[]
    for i in range(1,31):
        rows.append(record("breakout_v1",i,.2 if i%4 else -.1))
        rows.append(record("mean_reversion_v1",i,-.1 if i%4 else .1))
    for i in range(41,51):
        rows.append(record("breakout_v1",i,.3 if i%4 else -.1))
        rows.append(record("mean_reversion_v1",i,-.15 if i%4 else .1))
    return rows


def rank(rows=None):
    return shadow_rank(outcomes=data() if rows is None else rows,
                       account="demo-A",symbol="ETHUSDm",timeframe="M5",
                       regime="trend_up",evaluated_at=2000,train_before=1000)


def test_broker_verified_outcomes_rank_in_shadow_only():
    result=rank()
    assert result["schema"]=="niblit.strategy-performance-shadow/1"
    assert result["counted_verified_records"]==80
    assert result["shadow_leader"]=="breakout_v1"
    assert result["learning_action"]=="rank_only"
    assert result["selection_authority"]=="none"
    assert result["promotion_authorized"] is False
    for s in result["strategies"]:
        assert s["train"]["n"]==30
        assert s["validation"]["n"]==10
        assert s["evidence_gate"]=="eligible_for_shadow_comparison"
        assert s["shadow_rank_score"] is not None


def test_missing_validation_or_training_stays_unranked():
    result=rank(data()[:35])
    assert result["shadow_leader"] is None
    assert any(s["evidence_gate"]=="insufficient_broker_outcomes" for s in result["strategies"])


def test_unverified_and_fee_unknown_excluded_without_fabrication():
    rows=data()
    rows[0]["all_fees_included"]=False
    rows[1]["actual_fill"]=False
    result=rank(rows)
    assert result["excluded"]["unverified_or_cost_unknown"]==2
    assert result["shadow_leader"] is None


def test_account_and_regime_never_crosstrain():
    rows=data()
    rows.extend(record("breakout_v1",i,200,account="different-A") for i in range(51,60))
    rows.append(record("breakout_v1",61,200,regime="range"))
    result=rank(rows)
    assert result["counted_verified_records"]==80
    assert result["excluded"]["out_of_scope"]==10
    assert result["shadow_leader"]=="breakout_v1"


def test_future_outcome_cannot_affect_rank():
    baseline=rank()
    future=record("breakout_v1",999,-999,closed_at=2500)
    updated=rank(data()+[future])
    assert updated["excluded"]["future_at_evaluation"]==1
    assert updated["shadow_leader"]==baseline["shadow_leader"]
    assert updated["strategies"]==baseline["strategies"]


def test_duplicate_broker_trade_rejected():
    rows=data()
    with pytest.raises(ValueError,match="Duplicate"):
        rank(rows+[copy.deepcopy(rows[0])])


def test_future_training_cutoff_rejected():
    with pytest.raises(ValueError,match="boundary"):
        shadow_rank(outcomes=data(),account="demo-A",symbol="ETHUSDm",
                    timeframe="M5",regime="trend_up",evaluated_at=900,train_before=1000)


def test_no_data_never_promotes_candidate():
    result=rank([])
    assert result["strategies"]==[]
    assert result["shadow_leader"] is None
    assert result["promotion_authorized"] is False


def test_outcome_is_reproducible():
    assert rank()==rank()
