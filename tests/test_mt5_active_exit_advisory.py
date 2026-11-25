"""Read-only active exit advisory boundary tests, no real MT5 calls."""
import io
import json
from types import SimpleNamespace

from scripts.mt5_active_exit_advisory import evaluate, saved_context


class BrokerDouble:
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_REAL = 2
    def __init__(self, mode=0):
        self.mode = mode
        self.closed = False
        self.order_calls = 0
    def initialize(self):
        return True
    def account_info(self):
        return SimpleNamespace(trade_mode=self.mode)
    def terminal_info(self):
        return SimpleNamespace(connected=True)
    def positions_get(self):
        return [SimpleNamespace(ticket=123, symbol="BTCUSDm", type=0,
                                price_open=100, profit=0)]
    def shutdown(self):
        self.closed = True
    def order_send(self, *_args, **_kwargs):
        self.order_calls += 1
        raise AssertionError("Order transport must not be called")


def test_live_account_remains_observation_only():
    api = BrokerDouble(mode=2)
    result = evaluate(api, "http://127.0.0.1:5200", "BTCUSDm")
    assert result["status"] == "observation_only"
    assert result["execution_authorized"] is False
    assert api.closed and api.order_calls == 0


def test_no_core_context_does_not_guess_entry(monkeypatch):
    from scripts import mt5_active_exit_advisory as target
    monkeypatch.setattr(target, "saved_context", lambda *_args: (None, "missing"))
    api = BrokerDouble()
    result = evaluate(api, "http://127.0.0.1:5200", "BTCUSDm")
    assert result["advisories"][0]["advice"] == "ABSTAIN"
    assert result["orders_submitted"] == 0
    assert api.order_calls == 0


def test_core_context_requires_exact_ticket_and_unique_record(monkeypatch):
    from scripts import mt5_active_exit_advisory as target
    def fake_open(url, timeout):
        assert url == "http://127.0.0.1:5200/api/trading/sessions"
        return io.BytesIO(json.dumps({"orders": [
            {"adapter": "mt5", "symbol": "BTCUSDm", "state": "open",
             "result": {"position_id": "123"},
             "payload": {"context": {"strategy": "breakout_v1", "initial_stop": 90}}},
            {"adapter": "mt5", "symbol": "ETHUSDm", "state": "open",
             "result": {"position_id": "555"}, "payload": {"context": {}}},
        ]}).encode())
    monkeypatch.setattr(target, "urlopen", fake_open)
    context, reason = saved_context("http://127.0.0.1:5200", 123, "BTCUSDm")
    assert reason is None and context["strategy"] == "breakout_v1"
    assert saved_context("http://127.0.0.1:5200", 124, "BTCUSDm")[0] is None
    assert saved_context("http://remote.example", 123, "BTCUSDm")[1] == "invalid_local_core_url"


def test_saved_snapshot_requires_unique_broker_ticket_and_never_calls_http(monkeypatch):
    from scripts import mt5_active_exit_advisory as target
    monkeypatch.setattr(target, "urlopen", lambda *_a, **_k: (_ for _ in ()).throw(
        AssertionError("Snapshot mode must not contact prior Core")))
    snapshot={"orders":[{
        "adapter":"mt5","symbol":"BTCUSDm","state":"open",
        "result":{"position_id":"123"},
        "payload":{"context":{"strategy":"breakout_v1","initial_stop":90}}
    }]}
    entry, error=saved_context("http://127.0.0.1:5999", 123, "BTCUSDm", snapshot=snapshot)
    assert error is None and entry["strategy"]=="breakout_v1"
    assert saved_context("http://127.0.0.1:5999", 124, "BTCUSDm", snapshot=snapshot)[0] is None
    snapshot["orders"].append(dict(snapshot["orders"][0]))
    assert saved_context("http://127.0.0.1:5999", 123, "BTCUSDm", snapshot=snapshot)[0] is None
