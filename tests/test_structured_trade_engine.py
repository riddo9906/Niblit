"""The structured engine is pure and can never reach a broker transport."""
import copy
import pytest

from modules.structured_trade_engine import plan_mt5_crypto, validated_m5, lot_grid

AS_OF = 1800000000
BASE = AS_OF - 65 * 300
CANDLES = [
    {"timestamp": BASE + i * 300,
     "open": 60000 - 20 * i + 4,
     "high": 60000 - 20 * i + 12,
     "low": 60000 - 20 * i - 15,
     "close": 60000 - 20 * i}
    for i in range(65)
]
SPEC = {"currency_base": "BTC", "currency_profit": "USD", "trade_mode": 4,
        "point": 0.01, "trade_tick_size": 0.01, "digits": 2,
        "trade_stops_level": 0, "trade_freeze_level": 0,
        "volume_min": 0.01, "volume_max": 10.0, "volume_step": 0.01}
QUOTE = {"bid": CANDLES[-1]["close"] - 1,
         "ask": CANDLES[-1]["close"] + 5,
         "timestamp": AS_OF, "fresh": True}


def make(**overrides):
    arguments = dict(symbol="BTCUSDm", candles=copy.deepcopy(CANDLES),
                     quote=copy.deepcopy(QUOTE), spec=copy.deepcopy(SPEC),
                     equity=10000, risk_fraction=.0025, risk_cash=25,
                     max_volume=.10, loss_per_lot=200, as_of=AS_OF)
    arguments.update(overrides)
    return plan_mt5_crypto(**arguments)


def test_pure_deterministic_trade_plan_has_structure_and_no_permission():
    original = copy.deepcopy(CANDLES)
    first, second = make(), make()
    assert first == second
    assert first["status"] == "DRAFT_ONLY"
    assert first["side"] == "sell"
    assert first["strategy"] == "breakout_v1"
    assert first["execution_authorized"] is False
    assert first["order_sent"] is False
    assert first["plan"]["protection_version"] == "crypto-atr-structure/1"
    assert first["plan"]["costs_complete"] is False
    assert first["plan"]["atr"] > 0
    assert first["plan"]["reward_multiple"] >= 1.8
    assert first["plan"]["gross_stop_risk"] <= first["risk_budget"]
    assert first["plan"]["volume"] == .1
    assert CANDLES == original


def test_broker_minimum_lot_abstains_when_risk_too_high():
    result = make(loss_per_lot=10000)
    assert result["status"] == "NO_TRADE"
    assert result["plan"] is None
    assert "minimum lot" in result["decision_reason"]


@pytest.mark.parametrize("change", [
    lambda a: a["candles"][-1].update(timestamp=a["candles"][-2]["timestamp"]),
    lambda a: a["candles"][-1].update(high=1),
    lambda a: a.update(as_of=AS_OF + 1000),
    lambda a: a["quote"].update(fresh=False),
    lambda a: a["quote"].update(timestamp=AS_OF - 25),
    lambda a: a["spec"].update(currency_profit="EUR"),
    lambda a: a["spec"].update(volume_step=0),
])
def test_malformed_or_unverified_inputs_cannot_make_trade_plan(change):
    a = dict(symbol="BTCUSDm", candles=copy.deepcopy(CANDLES),
             quote=copy.deepcopy(QUOTE), spec=copy.deepcopy(SPEC),
             equity=10000, risk_fraction=.0025, risk_cash=25,
             max_volume=.10, loss_per_lot=200, as_of=AS_OF)
    change(a)
    with pytest.raises(ValueError):
        plan_mt5_crypto(**a)


def test_volume_rounding_floor_on_broker_grid():
    assert lot_grid(.01, .01, 1, .067) == .06
    assert lot_grid(.01, .01, 1, .009) is None
    assert lot_grid(.02, .02, 1, .061) == .06
    with pytest.raises(ValueError):
        lot_grid(.01, 0, 1, .1)


def test_completed_candles_cannot_contain_forming_bar():
    rows = copy.deepcopy(CANDLES)
    rows.append({"timestamp": AS_OF, "open": 1, "high": 2, "low": 1, "close": 1})
    with pytest.raises(ValueError):
        validated_m5(rows, AS_OF)



def test_core_mt5_demo_crypto_preflight_uses_atr_structure_not_spread_formula(tmp_path):
    """Exercise actual DemoOrders broker-double preview; no external order call."""
    from modules.trading_session_selftest import fixture
    from modules.core_trading_sessions import configured_limits
    f = fixture(tmp_path)
    api = f.api
    api.symbol = "BTCUSDm"
    api.info.name = "BTCUSDm"
    api.info.currency_base = "BTC"
    api.info.currency_profit = "USD"
    api.info.trade_contract_size = 1.0
    api.info.point = .01
    api.info.trade_tick_size = .01
    api.info.trade_stops_level = 0
    api.info.trade_freeze_level = 0
    api.info.digits = 2
    api.info.volume_min = .01
    api.info.volume_step = .01
    api.price = 59010.
    api.rates = [
        dict(time=api.bar - (59-i)*300,
             open=59600-10*i+3, high=59600-10*i+12,
             low=59600-10*i-12, close=59600-10*i,
             tick_volume=20)
        for i in range(60)
    ]
    f.orders.crypto_stops = True
    f.bridge.snapshot("BTCUSDm")
    f.bridge.snapshot("BTCUSDm")
    s = f.service.adapters["mt5"].snapshot("BTCUSDm")
    s["entry_strategy"] = "trend_v1"
    draft = f.service.adapters["mt5"].draft_entry(
        s, "sell", configured_limits() | {"max_volume": .01})
    assert draft["protection"]["version"] == "crypto-atr-structure/1"
    assert draft["protection"]["strategy"] == "trend_v1"
    assert draft["protection"]["atr"] > 0
    assert draft["stop_loss"] > api.price
    assert draft["take_profit"] < api.price
    assert draft["protection"]["stop_distance"] > 2.0
    assert draft["intent"]["volume"] == .01
    record = draft["structured_plan"]
    assert record["schema"] == "niblit.execution-plan/1"
    assert record["strategy"] == "trend_v1"
    assert record["source"] == "mt5_native_completed_M5_Wilder_TR14_and_recent_structure"
    assert record["stop_loss"] == draft["stop_loss"]
    assert record["take_profit"] == draft["take_profit"]
    assert len(record["record_hash"]) == 64
    assert record["execution_authorized"] is False
    route = draft["execution_route"]
    assert route["schema"] == "niblit.execution-route/1"
    assert route["source_plan_hash"] == record["record_hash"]
    assert route["account"] == s["account"]
    assert route["environment"] == "demo"
    assert route["execution_stage"] == "ROUTE_DESCRIPTION"
    assert route["broker_order_id"] is None
    assert len(route["route_hash"]) == 64
    assert api.sent == []
    f.service.shutdown()
