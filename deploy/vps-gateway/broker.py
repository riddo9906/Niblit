"""The only MT5 entry point. Runs in a disposable, deadline-bound process."""
import argparse
from datetime import datetime, timezone
import time
import hashlib
import json
import os
from pathlib import Path


def observe(api, executable, expected=None, since=None):
    path = Path(executable)
    if not path.is_absolute() or path.name.lower() != "terminal64.exe" or not path.is_file():
        raise ValueError("explicit_terminal_required")
    if not api.initialize(str(path), timeout=5000):
        raise RuntimeError(f"mt5_initialize_{api.last_error()[0]}")
    try:
        def identity():
            terminal, account = api.terminal_info(), api.account_info()
            if not terminal or not terminal.connected or account is None:
                raise RuntimeError("broker_disconnected")
            install = os.path.normcase(str(Path(terminal.path).resolve()))
            if install != os.path.normcase(str(path.resolve().parent)) or not terminal.data_path:
                raise RuntimeError("terminal_mismatch")
            if not account.server.upper().startswith("XM") or not account.company:
                raise RuntimeError("xm_identity_required")
            key = install + "|" + os.path.normcase(terminal.data_path)
            return dict(broker=account.company, login=str(account.login), server=account.server,
                        currency=account.currency, terminal_id=hashlib.sha256(key.encode()).hexdigest()[:20],
                        environment={0: "demo", 1: "contest", 2: "live"}.get(account.trade_mode, "unknown")), account

        binding, _ = identity()
        if expected is None:
            return binding
        if binding != expected:
            raise RuntimeError("account_binding_mismatch")
        positions, orders = api.positions_get(), api.orders_get()
        confirmed, account = identity()
        if positions is None or orders is None or account is None:
            raise RuntimeError("incomplete_broker_inventory")
        if confirmed != binding:
            raise RuntimeError("account_changed_during_read")
        finished = time.time()
        since = finished - 86400 if since is None else since
        if not isinstance(since, (int, float)) or not 0 <= since <= finished:
            raise RuntimeError("invalid_history_window")
        start, end = datetime.fromtimestamp(since, timezone.utc), datetime.fromtimestamp(finished, timezone.utc)
        history_orders, history_deals = api.history_orders_get(start, end), api.history_deals_get(start, end)
        if history_orders is None or history_deals is None:
            raise RuntimeError("incomplete_history")
        symbol = api.symbol_info("EURUSD")
        quote = api.symbol_info_tick("EURUSD") if symbol is not None else None
        symbol_fields = {}
        for name in ("name", "trade_contract_size", "trade_tick_size", "trade_tick_value",
                     "trade_tick_value_profit", "trade_tick_value_loss", "volume_min",
                     "volume_max", "volume_step", "trade_stops_level", "trade_freeze_level",
                     "filling_mode", "trade_calc_mode", "point", "digits", "swap_mode",
                     "swap_long", "swap_short", "swap_rollover3days"):
            symbol_fields[name] = getattr(symbol, name, None)
        symbol_fields["available"] = symbol is not None
        symbol_fields["quote"] = {name: getattr(quote, name, None) for name in ("bid", "ask", "time_msc")}
        symbol_fields["margin_calculation"] = None
        symbol_fields["profit_calculation_one_tick"] = None
        if quote is not None and symbol is not None and quote.ask > 0 and symbol.volume_min > 0:
            symbol_fields["margin_calculation"] = api.order_calc_margin(
                api.ORDER_TYPE_BUY, "EURUSD", symbol.volume_min, quote.ask)
            if symbol.trade_tick_size > 0:
                symbol_fields["profit_calculation_one_tick"] = api.order_calc_profit(
                    api.ORDER_TYPE_BUY, "EURUSD", symbol.volume_min, quote.ask,
                    quote.ask + symbol.trade_tick_size)
        final_binding, account = identity()
        if final_binding != binding:
            raise RuntimeError("account_changed_during_read")
        def fields(row, names):
            return {name: getattr(row, name, None) for name in names}
        return {
            "schema_version": "0.2", "observed_at": time.time(), "history_through": finished,
            "history_from": since,
            "history_orders": [fields(row, ("ticket", "position_id", "time_setup_msc",
                "time_done_msc", "symbol", "type", "state", "volume_initial", "volume_current",
                "price_open", "sl", "tp")) for row in history_orders],
            "history_deals": [fields(row, ("ticket", "order", "position_id", "time_msc",
                "symbol", "type", "entry", "volume", "price", "profit", "commission",
                "swap", "fee")) for row in history_deals],
            "balance": getattr(account, "balance", None),
            "free_margin": getattr(account, "margin_free", None),
            "symbol_specification": symbol_fields,
            "leverage": getattr(account, "leverage", None),
            "margin_mode": getattr(account, "margin_mode", None),
            "account_subtype": None, "commission_schedule": None,
            "account": binding, "equity": str(account.equity), "margin": str(account.margin),
            "positions": sorted([dict(ticket=p.ticket, symbol=p.symbol, side=p.type,
                                      volume=str(p.volume), sl=str(p.sl), tp=str(p.tp))
                                 for p in positions], key=lambda row: row["ticket"]),
            "orders": sorted([dict(ticket=o.ticket, symbol=o.symbol, side=o.type,
                                   volume=str(o.volume_current), price=str(o.price_open),
                                   sl=str(o.sl), tp=str(o.tp))
                              for o in orders], key=lambda row: row["ticket"]),
        }
    finally:
        api.shutdown()


def existing_terminal(executable):
    """Require one already-running terminal in this Python user's Windows session."""
    import ctypes
    from ctypes import wintypes
    kernel, psapi = ctypes.WinDLL("kernel32", use_last_error=True), ctypes.WinDLL("psapi", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                 wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    psapi.EnumProcesses.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD,
                                   ctypes.POINTER(wintypes.DWORD)]
    ids = (wintypes.DWORD * 8192)()
    size = wintypes.DWORD()
    if not psapi.EnumProcesses(ids, ctypes.sizeof(ids), ctypes.byref(size)) or size.value >= ctypes.sizeof(ids):
        raise RuntimeError("terminal_process_inventory_unavailable")
    current_session = wintypes.DWORD()
    if not kernel.ProcessIdToSessionId(os.getpid(), ctypes.byref(current_session)):
        raise RuntimeError("terminal_process_inventory_unavailable")
    matches = []
    expected = os.path.normcase(str(Path(executable).resolve()))
    for pid in ids[:size.value // ctypes.sizeof(wintypes.DWORD)]:
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            continue
        try:
            buffer, length = ctypes.create_unicode_buffer(32768), wintypes.DWORD(32768)
            if kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
                if os.path.normcase(buffer.value) == expected:
                    session = wintypes.DWORD()
                    if not kernel.ProcessIdToSessionId(pid, ctypes.byref(session)) or session.value != current_session.value:
                        raise RuntimeError("terminal_session_mismatch")
                    matches.append(pid)
        finally:
            kernel.CloseHandle(handle)
    if len(matches) != 1:
        raise RuntimeError("terminal_unavailable_or_duplicated")
    return matches[0]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("terminal")
    parser.add_argument("--bound", action="store_true")
    args = parser.parse_args()
    try:
        import sys
        process_id = existing_terminal(args.terminal)
        import MetaTrader5
        request = json.load(sys.stdin) if args.bound else None
        print(json.dumps(observe(MetaTrader5, args.terminal,
            request["account"] if request else None, request.get("since") if request else None),
            allow_nan=False))
    except Exception as exc:
        # Only emit controlled failure codes, never exception arguments from the SDK.
        code = str(exc) if type(exc) is RuntimeError and str(exc).startswith((
            "mt5_initialize_", "broker_disconnected", "terminal_mismatch", "xm_identity_required",
            "account_binding_mismatch", "incomplete_broker_inventory", "account_changed_during_read",
            "incomplete_history", "invalid_history_window", "terminal_process_inventory_unavailable",
            "terminal_session_mismatch", "terminal_unavailable_or_duplicated"
        )) else "broker_probe_failed"
        print(json.dumps({"error": code}))
