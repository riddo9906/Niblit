"""R14 demo-only broker-minimum sizing regression tests."""
from modules.core_trading_sessions import scoped_limits


def test_eth_broker_minimum_is_used_when_within_demo_ceiling(monkeypatch):
    monkeypatch.setenv("NIBLIT_AUTO_MAX_LOTS", "0.10")
    snap={"demo_volume_ceiling": .10, "demo_volume_min": .10}
    selected=scoped_limits("mt5",snap)
    assert selected["max_volume"] == .10
    assert selected["risk_fraction"] <= .0025
    assert selected["risk_cash"] <= 25


def test_btc_remains_small_by_default(monkeypatch):
    monkeypatch.setenv("NIBLIT_AUTO_MAX_LOTS", "0.10")
    assert scoped_limits("mt5",{"demo_volume_ceiling":.10,"demo_volume_min":.01})["max_volume"] == .01


def test_broker_minimum_exceeding_ceiling_cannot_be_escalated(monkeypatch):
    monkeypatch.setenv("NIBLIT_AUTO_MAX_LOTS", "0.10")
    selected=scoped_limits("mt5",{"demo_volume_ceiling":.10,"demo_volume_min":.20})
    assert selected["max_volume"] <= .10
