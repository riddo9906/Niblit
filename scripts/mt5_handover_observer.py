"""MT5 read-only position handover observation from r12 to isolated r13.

No trading, login, account selection, settings, modification, order_send,
position close, external Core POST, or database mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_json(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            obj = json.loads(value)
            return obj if isinstance(obj, dict) else {}
        except ValueError:
            return {}
    return {}


def core_snapshot(base, *, opener=urlopen):
    u = urlsplit(base)
    if (u.scheme != "http" or u.hostname != "127.0.0.1" or u.port != 5200
            or u.username or u.password or u.path not in ("", "/")
            or u.query or u.fragment):
        raise ValueError("Only the known local r12 Core endpoint is accepted")
    with opener("http://127.0.0.1:5200/api/trading/sessions", timeout=15) as response:
        data = json.load(response)
    if not isinstance(data, dict) or not isinstance(data.get("orders"), list):
        raise ValueError("Unverifiable Core order response")
    return data


def broker_binding(api, account, terminal):
    from modules.mt5_bridge import MT5Bridge
    return MT5Bridge.account_record(MT5Bridge(), api, account, terminal)


def inspect(api, core):
    report = {
        "state": "unavailable", "read_only": True, "execution_authorized": False,
        "trading_ownership_transferred": False, "position_claims": [],
        "unresolved_other_account_records": 0, "blockers": [],
    }
    if not api.initialize():
        report["blockers"].append("Native terminal initialization failed")
        return report
    try:
        account, terminal = api.account_info(), api.terminal_info()
        positions, pending = api.positions_get(), api.orders_get()
        if (account is None or terminal is None or positions is None or pending is None
                or not getattr(terminal, "connected", False)):
            report["blockers"].append("Broker readback unavailable")
            return report
        binding = broker_binding(api, account, terminal)
        current = (core.get("mt5_accounts") or {}).get("active") or {}
        binding_keys = ("identity", "environment", "terminal_id")
        same_binding = all(current.get(k) == binding.get(k) for k in binding_keys)
        if binding["environment"] != "demo" or not same_binding:
            report["blockers"].append("Demo account/terminal binding differs from r12")
        live_orders = []
        other_unknown = []
        for row in core["orders"]:
            if not isinstance(row, dict) or row.get("adapter") != "mt5":
                continue
            if row.get("state") not in {"open", "unknown", "sending", "partial"}:
                continue
            if row.get("account") != binding["identity"]:
                if row.get("state") in {"unknown", "sending", "partial"}:
                    other_unknown.append(row)
                continue
            live_orders.append(row)
        report["unresolved_other_account_records"] = len(other_unknown)
        matched_order_ids = set()
        for position in positions:
            ticket = str(position.ticket)
            identifier = str(getattr(position, "identifier", "") or "")
            matches = []
            for row in live_orders:
                if row.get("state") != "open" or row.get("symbol") != position.symbol:
                    continue
                result = parse_json(row.get("result"))
                if str(result.get("position_id")) == ticket and str(result.get("position_identifier")) == identifier:
                    matches.append(row)
            if len(matches) == 1:
                matched_order_ids.add(matches[0]["id"])
            # A ticket-number match is necessary but not enough to demonstrate
            # that the originating broker deal belongs to the recorded Core ticket.
            deal_history = api.history_deals_get(position=int(identifier)) if identifier.isdigit() else None
            order_history = api.history_orders_get(position=int(identifier)) if identifier.isdigit() else None
            history_available = deal_history is not None and order_history is not None
            entries = [d for d in (deal_history or ())
                       if getattr(d, "symbol", None) == position.symbol
                       and str(getattr(d, "position_id", "")) == identifier
                       and getattr(d, "entry", None) == 0]
            prepared = parse_json(matches[0].get("payload")).get("prepared") if len(matches) == 1 else None
            prepared = prepared if isinstance(prepared, dict) else {}
            ticket_token = prepared.get("ticket")
            expected_comment = ("niblit_" + ticket_token[:12]
                                if isinstance(ticket_token, str) and len(ticket_token) == 32
                                else None)
            attributed = [
                d for d in entries
                if expected_comment is not None
                and getattr(d, "magic", None) == 29102026
                and getattr(d, "comment", None) == expected_comment
                and abs(float(getattr(d, "volume", 0)) - float(position.volume)) < 1e-8
            ]
            linked_orders = [o for o in (order_history or ())
                             if getattr(o, "symbol", None) == position.symbol
                             and getattr(o, "magic", None) == 29102026
                             and getattr(o, "comment", None) == expected_comment]
            receipt = bool(history_available and len(entries) == 1 and len(attributed) == 1
                           and len(linked_orders) == 1
                           and str(getattr(attributed[0], "order", "")) ==
                           str(getattr(linked_orders[0], "ticket", ""))
                           and str(getattr(linked_orders[0], "ticket", "")) == ticket)
            protected = bool(position.sl and position.tp)
            claim = {
                "ticket": ticket, "position_identifier": identifier, "symbol": position.symbol,
                "volume": float(position.volume), "protected": protected,
                "matching_core_order_count": len(matches),
                "native_deal_history_available": history_available,
                "native_open_deal_receipt_found": receipt,
                "account_binding_verified": same_binding,
                "observation_eligible": same_binding and len(matches) == 1 and receipt,
                "exit_execution_authorized": False,
            }
            report["position_claims"].append(claim)
            if not claim["observation_eligible"]:
                report["blockers"].append("Position lacks complete account-scoped receipt: " + ticket)
            if not protected:
                report["blockers"].append("Broker protective levels missing: " + ticket)
        # Verify that the same account remains attached after native history queries.
        after_account, after_terminal = api.account_info(), api.terminal_info()
        if (after_account is None or after_terminal is None or
                broker_binding(api, after_account, after_terminal) != binding or
                not getattr(after_terminal, 'connected', False)):
            report["blockers"].append("MT5 account or terminal changed during readback")
            for claim in report["position_claims"]:
                claim["observation_eligible"] = False
        for row in live_orders:
            if row.get("id") not in matched_order_ids:
                report["blockers"].append("Unmatched current-account Core claim: " + row.get("state", "unknown"))
        if pending:
            report["blockers"].append("Unreconciled native pending orders")
        report.update(
            state="observed",
            account_mode=binding["environment"],
            account_binding_verified=same_binding,
            broker_position_count=len(positions),
            broker_pending_order_count=len(pending),
            current_account_core_claims=len(live_orders),
            observation_handover_eligible=not report["blockers"],
        )
        return report
    finally:
        api.shutdown()


def persist_snapshot(dest, result):
    """Write only within approved isolated r13/r14 observation data roots."""
    approved_roots = (
        Path(r"D:\NiblitAIOS\data\r13-observe-20261121").resolve(),
        Path(r"D:\NiblitAIOS\data\r14-observe-20261121").resolve(),
        Path(r"D:\NiblitAIOS\data\r14-demo-eth-20261121").resolve(),
    )
    path = Path(dest).resolve()
    if not any(path.is_relative_to(root) for root in approved_roots) or path.suffix != ".json":
        raise ValueError("Observer output must remain inside an approved isolated observation data root")
    path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    fd, tmp = tempfile.mkstemp(prefix="handover-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, allow_nan=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def load_pinned_core_snapshot(path):
    """Read only an operator-exported original receipt, never imported authority."""
    expected = Path(
        r"D:\NiblitAIOS\data\r14-demo-eth-20261121\r12-original-btc-evidence.json"
    ).resolve()
    path = path.resolve()
    if path != expected or path.is_symlink() or path.stat().st_size > 65536:
        raise ValueError("Only the pinned original BTC evidence snapshot is accepted")
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or not isinstance(data.get("orders"), list)
            or len(data["orders"]) != 1
            or data["orders"][0].get("symbol") != "BTCUSDm"
            or data["orders"][0].get("state") != "open"
            or not isinstance(data.get("mt5_accounts"), dict)):
        raise ValueError("Invalid original broker-position evidence snapshot")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-url", default="http://127.0.0.1:5200")
    parser.add_argument("--core-snapshot", type=Path, default=None,
                        help="Use the pinned original Core evidence without contacting the old process")
    parser.add_argument("--output", type=Path, default=Path(r"D:\NiblitAIOS\data\r14-observe-20261121\mt5-handover-latest.json"))
    parser.add_argument("--watch", action="store_true", help="Continue independent read-only observation until interrupted")
    parser.add_argument("--interval", type=int, default=20)
    args = parser.parse_args(argv)
    if args.watch and not 10 <= args.interval <= 300:
        parser.error("Interval must be 10–300 seconds")
    import MetaTrader5 as mt5
    while True:
        try:
            core = (load_pinned_core_snapshot(args.core_snapshot) if args.core_snapshot
                    else core_snapshot(args.core_url))
            result = inspect(mt5, core)
        except Exception as exc:
            result = {"state": "unavailable", "error_type": type(exc).__name__,
                      "execution_authorized": False, "trading_ownership_transferred": False,
                      "blockers": ["Read-only evidence unavailable"]}
        # Re-evaluate the original recorded entry thesis only for positions
        # whose read-only broker/Core reconciliation was accepted. Advisory
        # never grants an exit lease or submits an order.
        if result.get("observation_handover_eligible") and result.get("position_claims"):
            try:
                from scripts.mt5_active_exit_advisory import evaluate as exit_advisory
                symbol = result["position_claims"][0]["symbol"]
                advisory = (exit_advisory(mt5, args.core_url, symbol, snapshot=core)
                            if args.core_snapshot else exit_advisory(mt5, args.core_url, symbol))
                result["exit_advisory"] = {
                    "status": advisory.get("status"),
                    "orders_submitted": 0,
                    "execution_authorized": False,
                    "advisories": advisory.get("advisories", []),
                }
            except Exception as exc:
                result["exit_advisory"] = {"status": "unavailable", "error_type": type(exc).__name__,
                                           "execution_authorized": False, "orders_submitted": 0}
        # The old Core has not emitted a durable ownership-release receipt.
        # Review is intentionally separate from observation eligibility and is
        # never a broker execution permit, even with complete receipt evidence.
        from modules.mt5_adoption_lease import review_handover
        result["adoption_review"] = review_handover(
            result, prior_owner_released=False)
        result["checked_at_unix"] = time.time()
        persist_snapshot(args.output, result)
        print(json.dumps(result, indent=2, allow_nan=False), flush=True)
        if not args.watch:
            return 0 if result["state"] == "observed" else 2
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
