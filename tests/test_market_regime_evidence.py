import math
import pytest
from modules.market_regime_evidence import observe_regime, _one_timeframe, _rsi, _atr_adx


def bars(step=300, n=75, trend=0.0, start=1_800_000_000):
    start=start-start%step
    result=[]
    for i in range(n):
        price=100.0+i*trend+(.18*math.sin(i*.33) if trend == 0 else 0)
        result.append({"timestamp":start+i*step,"open":price,
                       "high":price+.3,"low":price-.3,"close":price+.08})
    return result


def view(candles=None, **kwargs):
    candles = candles if candles is not None else bars()
    return observe_regime(symbol="ETHUSDm",account="demo-01",
        cutoff=candles[-1]["timestamp"]+300+20,
        candles_by_timeframe={"M5":candles},**kwargs)


def test_constant_prices_has_finite_indicators_and_no_fake_probabilities():
    candles=bars()
    result=view(candles)
    assert result["schema"]=="niblit.market-regime-evidence/1"
    assert result["regime"] in {"range","compression","uncertain"}
    feature=result["timeframes"]["M5"]["features"]
    assert 0<=feature["rsi14"]<=100
    assert feature["atr14"]>0
    assert feature["bollinger_width_fraction"]>=0
    assert result["probability"] is None
    assert result["expected_profit"] is None
    assert result["execution_authorized"] is False


def test_trend_or_breakout_is_hypothesis_not_buy_signal():
    result=view(bars(trend=.22))
    assert result["regime"] in {"trend_up","breakout_candidate"}
    assert result["timeframes"]["M5"]["features"]["plus_di14"]>0
    assert result["learning_action"]=="record_only"
    assert "side" not in result


def test_completed_timeframe_lookahead_rejected():
    candles=bars()
    bad_cutoff=candles[-1]["timestamp"]+299
    with pytest.raises(ValueError,match="Unclosed"):
        observe_regime(symbol="ETHUSDm",account="demo-01",
                       cutoff=bad_cutoff,candles_by_timeframe={"M5":candles})
    higher=bars(step=3600)
    with pytest.raises(ValueError,match="Unclosed"):
        observe_regime(symbol="ETHUSDm",account="demo-01",
            cutoff=higher[-1]["timestamp"]+1800,
            candles_by_timeframe={"H1":higher})


def test_multi_timeframe_is_separately_validated():
    five=bars()
    hour=bars(step=3600,start=five[0]["timestamp"]-3600*75)
    cutoff=max(five[-1]["timestamp"]+300,hour[-1]["timestamp"]+3600)+20
    result=observe_regime(symbol="ETHUSDm",account="demo-01",cutoff=cutoff,
                          candles_by_timeframe={"M5":five,"H1":hour})
    assert result["timeframes"]["H1"]["bars"]==75
    assert result["timeframes"]["M15"]["status"]=="missing"
    assert "H1" not in result["reasons"][-1]


def test_gap_detection_and_bad_ohlc():
    candles=bars()
    with pytest.raises(ValueError,match="gapped"):
        view(candles[:30]+candles[31:])
    bad=[dict(c) for c in candles]
    bad[-1]["high"]=1.0
    with pytest.raises(ValueError,match="OHLC"):
        view(bad)


def test_stale_quote_is_not_a_fresh_spread_measurement():
    candles=bars()
    cutoff=candles[-1]["timestamp"]+320
    result=observe_regime(symbol="ETHUSDm",account="demo",cutoff=cutoff,
                          candles_by_timeframe={"M5":candles},
                          quote={"bid":100.0,"ask":100.5,"timestamp":cutoff-500,"fresh":True})
    assert result["spread"] is None
    assert any("stale" in x for x in result["reasons"])


def test_wide_spread_classifies_unstable():
    candles=bars()
    cutoff=candles[-1]["timestamp"]+320
    result=observe_regime(symbol="ETHUSDm",account="demo",cutoff=cutoff,
                          candles_by_timeframe={"M5":candles},
                          quote={"bid":100.0,"ask":100.5,"timestamp":cutoff-1,"fresh":True})
    assert result["regime"]=="unstable"
    assert result["spread"]==pytest.approx(.5)


def test_regime_transition_is_evidence_only():
    result=view(previous={"regime":"trend_up"})
    assert result["transition"]["from"]=="trend_up"
    assert result["transition"]["to"]==result["regime"]
    assert result["transition"]["changed"] is (result["regime"]!="trend_up")


def test_missing_history_is_uncertain():
    result=observe_regime(symbol="ETHUSDm",account="demo",cutoff=1_800_000_000,
                          candles_by_timeframe={})
    assert result["regime"]=="uncertain"
    assert result["timeframes"]["M5"]["status"]=="missing"


def test_known_constant_rsi_and_no_adx_direction():
    closes=[100.]*30
    assert _rsi(closes)==50
    candles=bars(trend=0)
    atr,adx,pdi,mdi=_atr_adx(candles)
    assert atr>0 and adx is not None
    assert math.isfinite(pdi) and math.isfinite(mdi)


def test_invalid_numeric_and_future_quotes_are_not_silently_used():
    candles=bars()
    bad=[dict(c) for c in candles]
    bad[30]["close"]=float("nan")
    with pytest.raises(ValueError):
        view(bad)
    cutoff=candles[-1]["timestamp"]+320
    result=observe_regime(symbol="ETHUSDm",account="demo",cutoff=cutoff,
                          candles_by_timeframe={"M5":candles},
                          quote={"bid":100.,"ask":100.1,"timestamp":cutoff+2,"fresh":True})
    assert result["spread"] is None


def test_explicit_unfresh_quote_cannot_be_labelled_current_trend():
    candles=bars(trend=.22)
    cutoff=candles[-1]["timestamp"]+320
    result=observe_regime(symbol="ETHUSDm",account="demo",cutoff=cutoff,
                          candles_by_timeframe={"M5":candles},
                          quote={"fresh":False,"reason":"MT5 delayed"})
    assert result["regime"]=="uncertain"
    assert result["market_data_current"] is False
    assert result["timeframes"]["M5"]["features"]["adx14"] is not None
    assert any("freshness" in x for x in result["reasons"])


def test_stale_completed_bar_forces_uncertain_current_market():
    candles=bars(trend=.2)
    cutoff=candles[-1]["timestamp"]+1500
    result=observe_regime(symbol="ETHUSDm",account="demo",cutoff=cutoff,
                          candles_by_timeframe={"M5":candles})
    assert result["regime"]=="uncertain"
    assert result["market_data_current"] is False
    assert any("stale" in x for x in result["reasons"])


def test_same_input_produces_identical_record():
    candles=bars(trend=.07)
    assert view(candles)==view(candles)
