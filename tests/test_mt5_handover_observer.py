"""No-order regression suite for account-scoped MT5 handover observer."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import mt5_handover_observer as audit


class FakeBroker:
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_REAL = 2

    def __init__(self, *, changed=False, history=True, positions=True, pending=False):
        self.changed, self.history, self.has_positions, self.pending = changed, history, positions, pending
        self.account_calls = 0
        self.shutdown_called = False
        self.order_calls = 0

    def initialize(self):
        return True

    def account_info(self):
        self.account_calls += 1
        return SimpleNamespace(trade_mode=0, login=2 if self.changed and self.account_calls >= 2 else 1,
                               server="Demo", company="Broker")

    def terminal_info(self):
        return SimpleNamespace(connected=True, path=r"C:\MT5", data_path=r"C:\MT5\data")

    def positions_get(self):
        return ([SimpleNamespace(ticket=123, identifier=123, symbol="BTCUSDm", volume=.01,
                                 sl=11, tp=12)] if self.has_positions else [])

    def orders_get(self):
        return [SimpleNamespace(ticket=777)] if self.pending else []

    def history_deals_get(self, *, position):
        return ([SimpleNamespace(position_id=123, symbol="BTCUSDm", entry=0,
                                 magic=29102026, comment="niblit_" + "a" * 12,
                                 volume=.01, order=123)] if self.history else None)

    def history_orders_get(self, *, position):
        return ([SimpleNamespace(ticket=123, position_id=123, symbol="BTCUSDm",
                                 magic=29102026, comment="niblit_" + "a" * 12)]
                if self.history else None)

    def shutdown(self):
        self.shutdown_called = True

    def order_send(self, *args, **kwargs):
        self.order_calls += 1
        raise AssertionError("No order sends permitted")


def core(*, duplicate=False, cross_account_unknown=True, ticket=123):
    order = {"id": "a", "adapter": "mt5", "account": "acct1", "state": "open",
             "symbol": "BTCUSDm", "payload": {"prepared": {"ticket": "a" * 32}},
             "result": json.dumps({"position_id": ticket,
                                   "position_identifier": ticket})}
    orders = [order]
    if duplicate:
        orders.append({**order, "id": "b"})
    if cross_account_unknown:
        orders.append({"id": "c", "adapter": "mt5", "account": "acct2", "state": "unknown",
                       "symbol": "EURUSD", "result": '{"reason": "Original ticket unavailable"}'})
    return {"mt5_accounts": {"active": {"identity": "acct1", "environment": "demo",
                                        "terminal_id": "terminal1"}}, "orders": orders}


@pytest.fixture(autouse=True)
def fake_binding(monkeypatch):
    monkeypatch.setattr(audit, "broker_binding",
                        lambda api, account, term: {
                            "identity": "acct" + str(account.login),
                            "environment": "demo", "terminal_id": "terminal1"})


def test_exact_account_and_historical_receipt_enables_observation_not_execution():
    api = FakeBroker()
    r = audit.inspect(api, core())
    assert r["observation_handover_eligible"] is True
    assert r["trading_ownership_transferred"] is False
    assert r["execution_authorized"] is False
    assert r["unresolved_other_account_records"] == 1
    assert r["position_claims"][0]["observation_eligible"]
    assert api.order_calls == 0 and api.shutdown_called


def test_mismatched_account_never_adopted():
    r = audit.inspect(FakeBroker(), {"mt5_accounts": {"active": {"identity": "wrong"}},
                                     "orders": core()["orders"]})
    assert not r["observation_handover_eligible"]


def test_duplicate_receipts_cannot_mint_claim():
    r = audit.inspect(FakeBroker(), core(duplicate=True))
    assert not r["observation_handover_eligible"]
    assert r["position_claims"][0]["matching_core_order_count"] == 2


def test_native_history_unavailable_cannot_be_claimed():
    r = audit.inspect(FakeBroker(history=False), core())
    assert not r["observation_handover_eligible"]
    assert not r["position_claims"][0]["native_open_deal_receipt_found"]


def test_account_switch_detected_after_readback():
    r = audit.inspect(FakeBroker(changed=True), core())
    assert not r["observation_handover_eligible"]
    assert not r["position_claims"][0]["observation_eligible"]


def test_pending_order_blocks_handover():
    r = audit.inspect(FakeBroker(pending=True), core())
    assert not r["observation_handover_eligible"]


def test_nonmatching_ticket_blocks_handover():
    r = audit.inspect(FakeBroker(), core(ticket=200))
    assert not r["observation_handover_eligible"]


def test_unrelated_unknown_account_does_not_block_scoped_observation():
    r = audit.inspect(FakeBroker(), core(cross_account_unknown=True))
    assert r["unresolved_other_account_records"] == 1
    assert r["observation_handover_eligible"]


def test_missing_broker_position_blocks_open_core_claim():
    r = audit.inspect(FakeBroker(positions=False), core())
    assert not r["observation_handover_eligible"]


def test_output_path_cannot_escape_isolated_r13_root(tmp_path):
    with pytest.raises(ValueError):
        audit.persist_snapshot(tmp_path / "fake.json", {"state": "observed"})


def test_core_url_does_not_accept_remote_host():
    with pytest.raises(ValueError):
        audit.core_snapshot("http://example.com:5200")


def test_matching_ticket_but_wrong_original_core_token_blocks_observation():
    record = core()
    record["orders"][0]["payload"]["prepared"]["ticket"] = "b" * 32
    r = audit.inspect(FakeBroker(), record)
    assert not r["observation_handover_eligible"]
    assert not r["position_claims"][0]["native_open_deal_receipt_found"]


def test_matching_ticket_but_wrong_native_magic_blocks_observation():
    class WrongMagic(FakeBroker):
        def history_deals_get(self, *, position):
            return [SimpleNamespace(position_id=123, symbol="BTCUSDm", entry=0,
                                    magic=0, comment="niblit_" + "a" * 12,
                                    volume=.01, order=123)]
    r = audit.inspect(WrongMagic(), core())
    assert not r["observation_handover_eligible"]


def test_matching_ticket_but_wrong_native_volume_blocks_observation():
    class WrongVolume(FakeBroker):
        def history_deals_get(self, *, position):
            return [SimpleNamespace(position_id=123, symbol="BTCUSDm", entry=0,
                                    magic=29102026, comment="niblit_" + "a" * 12,
                                    volume=.02, order=123)]
    r = audit.inspect(WrongVolume(), core())
    assert not r["observation_handover_eligible"]


def test_broker_order_history_mismatch_blocks_observation():
    class WrongOrder(FakeBroker):
        def history_orders_get(self, *, position):
            return [SimpleNamespace(ticket=999, position_id=123, symbol="BTCUSDm",
                                    magic=29102026, comment="niblit_" + "a" * 12)]
    r = audit.inspect(WrongOrder(), core())
    assert not r["observation_handover_eligible"]
