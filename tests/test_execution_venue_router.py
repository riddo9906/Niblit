import pytest

from modules.execution_venue_router import VenueBinding, resolve_route, route_difference

HASH = "a" * 64


def binding(env="demo", account="demo-100"):
    return VenueBinding("mt5", env, account, "BTCUSDm", "BTC/USD",
                        "USD", "mt5:exness-trial:terminal-1")


def test_demo_and_live_share_route_schema_not_account_identity():
    decision = {"side": "sell", "symbol": "BTCUSDm", "venue": "mt5"}
    demo = resolve_route(binding(), decision, risk_profile="demo-risk/1",
                         feed_identity="mt5:BTCUSDm:M5:bar-100", plan_hash=HASH)
    funded = resolve_route(binding("live", "live-200"), decision,
                           risk_profile="funded-risk/1",
                           feed_identity="mt5:BTCUSDm:M5:bar-100", plan_hash=HASH)
    assert demo == resolve_route(binding(), decision, risk_profile="demo-risk/1",
                                 feed_identity="mt5:BTCUSDm:M5:bar-100", plan_hash=HASH)
    assert demo["route_hash"] != funded["route_hash"]
    assert demo["execution_stage"] == funded["execution_stage"] == "ROUTE_DESCRIPTION"
    assert demo["broker_order_id"] is funded["broker_order_id"] is None
    assert set(route_difference(demo, funded)) == {"environment", "account", "risk_profile"}


def test_freqtrade_exchange_context_is_explicit_and_isolated():
    dry = VenueBinding("freqtrade", "dry-run", "coremanaged-sim", "ETH/USDT:USDT",
                       "ETH/USDT", "USDT", "freqtrade:binance:isolated-config-sha")
    route = resolve_route(dry, {"side": "short", "symbol": dry.symbol},
                          risk_profile="freqtrade-risk/1",
                          feed_identity="binance:5m:bar-1", plan_hash=HASH)
    assert route["side"] == "sell"
    assert route["environment"] == "dry-run"
    assert route["identity"].startswith("freqtrade:")


@pytest.mark.parametrize("decision", [
    {"side": "wait", "symbol": "BTCUSDm"},
    {"side": "buy", "symbol": "EURUSD"},
    {"side": "buy", "symbol": "BTCUSDm", "venue": "freqtrade"},
])
def test_bad_or_nontrade_decisions_do_not_emit_routes(decision):
    with pytest.raises(ValueError):
        resolve_route(binding(), decision, risk_profile="risk/1",
                      feed_identity="feed/1", plan_hash=HASH)


@pytest.mark.parametrize("kwargs", [
    {"adapter": "mt5", "environment": "dry-run"},
    {"adapter": "freqtrade", "environment": "demo"},
    {"adapter": "mt5", "environment": "live", "identity": "wrong"},
])
def test_exact_venue_environment_identity_contract(kwargs):
    args = {"adapter": "mt5", "environment": "demo", "account": "demo-1",
            "symbol": "BTCUSDm", "instrument": "BTC/USD", "currency": "USD",
            "identity": "mt5:server:terminal"}
    args.update(kwargs)
    with pytest.raises(ValueError):
        VenueBinding(**args)
