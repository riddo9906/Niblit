"""Read-only exit-cognition report for an existing MT5 demo position.

This utility never opens, closes, edits or authorizes a trade. It evaluates a
copy of the saved Core entry thesis against native completed M5 candles and
current executable quote; it does not write the mutated evaluator context.
"""
import argparse
import json
import math
import sys
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def decoded(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def saved_context(core_url, ticket, symbol, *, snapshot=None):
    if snapshot is None:
        addr = urlsplit(core_url)
        if (addr.scheme != "http" or addr.hostname != "127.0.0.1"
                or addr.username or addr.password or addr.path or addr.query or addr.fragment):
            return None, "invalid_local_core_url"
    try:
        if snapshot is None:
            with urlopen(core_url + "/api/trading/sessions", timeout=10) as response:
                status = json.load(response)
        else:
            status = snapshot
        if not isinstance(status, dict) or not isinstance(status.get("orders"), list):
            return None, "core_status_unavailable"
        matched = []
        for record in status["orders"]:
            if record.get("adapter") != "mt5" or record.get("state") != "open" or record.get("symbol") != symbol:
                continue
            result = decoded(record.get("result"))
            if str(result.get("position_id")) == str(ticket):
                matched.append(decoded(record.get("payload")).get("context"))
        if len(matched) != 1 or not isinstance(matched[0], dict):
            return None, "unique_core_entry_context_not_found"
        return dict(matched[0]), None
    except (OSError, ValueError, TypeError, KeyError):
        return None, "core_status_unavailable"


def evaluate(api, core_url, symbol, *, snapshot=None):
    report = {"status": "unavailable", "execution_authorized": False,
              "orders_submitted": 0, "advisories": []}
    if not api.initialize():
        return {**report, "reason": "MT5 terminal unavailable"}
    try:
        account = api.account_info()
        terminal = api.terminal_info()
        positions = api.positions_get()
        if not account or not terminal or positions is None or not terminal.connected:
            return {**report, "reason": "Broker readback unavailable"}
        if account.trade_mode != api.ACCOUNT_TRADE_MODE_DEMO:
            return {**report, "status": "observation_only", "reason": "Only demo account evaluation was validated"}
        from modules.position_exit_policy import assess_exit, assess_reversal
        for p in positions:
            if p.symbol != symbol:
                continue
            entry, error = (saved_context(core_url, p.ticket, symbol) if snapshot is None
                            else saved_context(core_url, p.ticket, symbol, snapshot=snapshot))
            item = {"ticket": str(p.ticket), "symbol": symbol, "entry_thesis_verified": entry is not None,
                    "execution_authorized": False, "advice": "ABSTAIN", "reason": error}
            if entry is None:
                report["advisories"].append(item)
                continue
            tick = api.symbol_info_tick(symbol)
            rates = api.copy_rates_from_pos(symbol, api.TIMEFRAME_M5, 1, 51)
            if tick is None or rates is None or len(rates) != 51:
                item["reason"] = "Native quote or completed bars unavailable"
                report["advisories"].append(item)
                continue
            candles = [{"timestamp": int(r["time"]), "close": float(r["close"])} for r in rates]
            quote = {"bid": float(tick.bid), "ask": float(tick.ask),
                     "timestamp": int(tick.time), "fresh": int(tick.time) > 0 and int(tick.time) >= candles[-1]["timestamp"]
                     and int(tick.time) - candles[-1]["timestamp"] < 600}
            native_position = {"type": int(p.type), "price_open": float(p.price_open)}
            # Both policies mutate ONLY private copies; never persist simulated peak data.
            exit_report = assess_exit(native_position, candles, quote, dict(entry))
            reversal_report = assess_reversal(native_position, candles, quote, dict(entry),
                                               observed_profit=float(p.profit))
            recommendations = [r for r in (exit_report, reversal_report) if r.get("action") == "close"]
            item.update(advice="EXIT_CANDIDATE" if recommendations else "HOLD_OR_ABSTAIN",
                        reason="Read-only market assessment, not trade authorization",
                        entry_strategy=entry.get("strategy"), quote_fresh=quote["fresh"],
                        exit_policy=exit_report, reversal_policy=reversal_report)
            report["advisories"].append(item)
        return {**report, "status": "observed", "account_mode": "demo",
                "position_count": len(positions),
                "limitations": "Gross R and floating broker profit are observations, not guaranteed net proceeds. No lifecycle ownership or order authority established."}
    finally:
        api.shutdown()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTCUSDm")
    parser.add_argument("--core-url", default="http://127.0.0.1:5200")
    args = parser.parse_args(argv)
    import MetaTrader5 as mt5
    result = evaluate(mt5, args.core_url, args.symbol)
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0 if result["status"] == "observed" else 2


if __name__ == "__main__":
    sys.exit(main())
