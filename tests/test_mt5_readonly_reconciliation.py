"""Tests for read-only terminal reconciliation; no broker SDK or order transport."""
import json
import sqlite3
from types import SimpleNamespace

from scripts.mt5_readonly_reconciliation import inspect, ledger_evidence


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_REAL = 2

    def __init__(self, mode=0, positions=(), pending=(), online=True):
        self.mode = mode
        self.positions = positions
        self.pending = pending
        self.online = online
        self.shutdown_called = False

    def initialize(self):
        return self.online

    def account_info(self):
        return SimpleNamespace(trade_mode=self.mode, trade_allowed=True)

    def terminal_info(self):
        return SimpleNamespace(connected=True)

    def positions_get(self):
        return self.positions

    def orders_get(self):
        return self.pending

    def shutdown(self):
        self.shutdown_called = True


def position(ticket=123):
    return SimpleNamespace(ticket=ticket, symbol="BTCUSDm", volume=.01, sl=10.0, tp=20.0)


def test_live_account_remains_readonly():
    api = FakeMT5(mode=2, positions=[position()])
    result = inspect(api)
    assert result["account_mode"] == "live"
    assert result["ready_for_live"] is False
    assert result["execution_authorized"] is False
    assert api.shutdown_called


def test_demo_position_without_ledger_does_not_claim_ownership():
    result = inspect(FakeMT5(positions=[position()]))
    assert result["positions"][0]["matched_to_supplied_ledger"] is False


def test_unavailable_terminal_is_not_ready():
    result = inspect(FakeMT5(online=False))
    assert result["state"] == "terminal_unavailable"
    assert not result["ready_for_live"]


def test_ledger_is_opened_readonly_and_matches_exact_ticket(tmp_path):
    ledger = tmp_path / "tickets.sqlite3"
    with sqlite3.connect(ledger) as con:
        con.execute("CREATE TABLE mt5_tickets(id TEXT, created REAL, state TEXT, body TEXT, result TEXT)")
        con.execute("INSERT INTO mt5_tickets VALUES(?,?,?,?,?)",
                    ("a", 1., "placed", "{}", json.dumps({"position_id": 123})))
        con.execute("INSERT INTO mt5_tickets VALUES(?,?,?,?,?)",
                    ("b", 2., "unknown", "{}", json.dumps({"position_id": 999})))
    result = inspect(FakeMT5(positions=[position()]), ledger)
    assert result["positions"][0]["matched_to_supplied_ledger"] is True
    assert result["unresolved_ledger_count"] == 1
    assert ledger_evidence(ledger)["state"] == "available"


def test_missing_ledger_never_created(tmp_path):
    missing = tmp_path / "absent.sqlite3"
    result = inspect(FakeMT5(), missing)
    assert result["ledger"]["state"] == "missing"
    assert not missing.exists()


def test_core_evidence_is_localhost_only(monkeypatch):
    import urllib.request
    from scripts.mt5_readonly_reconciliation import core_evidence
    def forbidden(*args, **kwargs):
        raise AssertionError("Network should not be reached")
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    assert core_evidence("http://example.com")["state"] == "invalid_local_core_url"
    assert core_evidence("http://127.0.0.1:5200/other")["state"] == "invalid_local_core_url"


def test_core_open_and_unknown_records_readonly(monkeypatch):
    import io
    import urllib.request
    from scripts.mt5_readonly_reconciliation import core_evidence
    visited = []
    def fake_open(url, timeout):
        visited.append(url)
        return io.BytesIO(json.dumps({"orders": [
            {"adapter": "mt5", "state": "open", "symbol": "BTCUSDm",
             "result": json.dumps({"position_id": 123})},
            {"adapter": "mt5", "state": "unknown", "symbol": "EURUSD", "result": {}},
            {"adapter": "freqtrade", "state": "open", "symbol": "BTC/USDT:USDT",
             "result": {"position_id": 20}}
        ]}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", fake_open)
    result = core_evidence("http://127.0.0.1:5200")
    assert result["state"] == "available"
    assert len(result["orders"]) == 2
    assert result["orders"][0]["position_id"] == "123"
    assert visited == ["http://127.0.0.1:5200/api/trading/sessions"]
