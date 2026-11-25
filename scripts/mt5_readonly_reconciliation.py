"""Read-only MT5 position/ledger reconciliation. Never sends, modifies, or closes orders."""
import argparse
import json
import sqlite3
import sys
from pathlib import Path


def ledger_evidence(path):
    """Return ticket evidence without creating or changing the SQLite database."""
    if path is None:
        return {"state": "not_configured", "tickets": []}
    path = Path(path).resolve()
    if not path.is_file():
        return {"state": "missing", "tickets": []}
    try:
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=3) as con:
            rows = con.execute(
                "SELECT state, result FROM mt5_tickets WHERE state IN ('placed','sending','unknown')"
            ).fetchall()
        tickets = []
        for state, raw in rows:
            try:
                result = json.loads(raw or "{}")
                if not isinstance(result, dict):
                    result = {}
            except (TypeError, ValueError):
                result = {}
            ticket = result.get("position_id")
            if ticket is None:
                ticket = result.get("position_ticket")
            tickets.append({"state": state, "position_id": str(ticket) if ticket is not None else None})
        return {"state": "available", "tickets": tickets}
    except (OSError, sqlite3.Error) as exc:
        return {"state": "unavailable", "error_type": type(exc).__name__, "tickets": []}


def core_evidence(url):
    """Read existing Core session records without activation or order endpoints."""
    from urllib.parse import urlsplit
    from urllib.request import urlopen
    addr = urlsplit(url)
    if addr.scheme != "http" or addr.hostname != "127.0.0.1" or addr.username or addr.password or addr.path or addr.query or addr.fragment:
        return {"state": "invalid_local_core_url", "orders": []}
    try:
        with urlopen(url.rstrip("/") + "/api/trading/sessions", timeout=10) as response:
            result = json.load(response)
        orders = []
        for order in result.get("orders", []):
            if order.get("adapter") != "mt5" or order.get("state") not in ("open", "unknown"):
                continue
            details = order.get("result")
            if isinstance(details, str):
                try:
                    details = json.loads(details)
                except (TypeError, ValueError):
                    details = {}
            details = details if isinstance(details, dict) else {}
            pos = details.get("position_id")
            orders.append({"state": order["state"], "symbol": order.get("symbol"),
                           "position_id": str(pos) if pos is not None else None})
        return {"state": "available", "orders": orders}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return {"state": "unavailable", "error_type": type(exc).__name__, "orders": []}


def inspect(api, ledger_path=None):
    """Attach to an existing terminal and read positions. Do not submit order calls."""
    evidence = ledger_evidence(ledger_path)
    if not api.initialize():
        return {"state": "terminal_unavailable", "execution_authorized": False,
                "ledger": evidence, "positions": [], "ready_for_live": False}
    try:
        account = api.account_info()
        terminal = api.terminal_info()
        positions = api.positions_get()
        pending = api.orders_get()
        if account is None or terminal is None or positions is None or pending is None:
            return {"state": "broker_readback_unavailable", "execution_authorized": False,
                    "ledger": evidence, "positions": [], "ready_for_live": False}
        mode = ("demo" if account.trade_mode == api.ACCOUNT_TRADE_MODE_DEMO else
                "live" if account.trade_mode == api.ACCOUNT_TRADE_MODE_REAL else "other")
        ids = {str(p.ticket) for p in positions}
        reconciliation = []
        for record in evidence["tickets"]:
            ticket = record["position_id"]
            reconciliation.append({**record, "current_broker_ticket_match": ticket in ids if ticket else False})
        matched_ids = {r["position_id"] for r in reconciliation if r["current_broker_ticket_match"]}
        observations = [
            {"ticket": str(p.ticket), "symbol": p.symbol, "volume": p.volume,
             "has_stop_loss": bool(p.sl), "has_take_profit": bool(p.tp),
             "matched_to_supplied_ledger": str(p.ticket) in matched_ids}
            for p in positions
        ]
        unresolved = [r for r in reconciliation if not r["current_broker_ticket_match"]]
        return {"state": "observed", "account_mode": mode,
                "terminal_connected": bool(terminal.connected),
                "account_trading_allowed": bool(account.trade_allowed),
                "positions": observations, "pending_order_count": len(pending),
                "ledger": {**evidence, "reconciliation": reconciliation},
                "unresolved_ledger_count": len(unresolved),
                "execution_authorized": False, "ready_for_live": False,
                "limitations": "Read-only snapshot. No broker ownership, fill, history, or lifecycle proof; unmatched tickets require independent historical reconciliation."}
    finally:
        api.shutdown()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ledger", type=Path, help="Existing MT5 ticket ledger (opened SQLite read-only)")
    p.add_argument("--core-url", help="Local Core URL, e.g. http://127.0.0.1:5200 (GET only)")
    args = p.parse_args(argv)
    import MetaTrader5 as mt5
    result = inspect(mt5, args.ledger)
    if args.core_url:
        core = core_evidence(args.core_url)
        result["core"] = core
        for position in result["positions"]:
            position["core_ticket_number_match"] = any(
                order["state"] == "open" and order["symbol"] == position["symbol"]
                and order["position_id"] == position["ticket"]
                for order in core["orders"])
            position["broker_account_binding_verified"] = False
        result["unresolved_core_records"] = [
            order for order in core["orders"]
            if not any(order["state"] == "open" and order["symbol"] == position["symbol"]
                       and order["position_id"] == position["ticket"]
                       for position in result["positions"])
        ]
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["state"] == "observed" else 2


if __name__ == "__main__":
    sys.exit(main())
