"""Deterministic observed-price trade diagnostics, not entry/exit decisions.

MFE/MAE are *sampled* mark-to-market excursions. They cannot describe unseen
intra-candle spikes and are not realized broker P&L. Call with the broker's
executable bid for longs and ask for shorts; do not use candle close or mid.
"""
import math


def _number(value, name, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError("Invalid " + name)
    value = float(value)
    if positive and value <= 0:
        raise ValueError("Invalid " + name)
    return value


def observed_excursion(*, side, entry, initial_stop, mark, prior=None):
    """One reproducible price observation, with previous observed extrema.

    'r' is raw executable-price movement divided by initial stop distance.
    Fee, swap, funding, and slippage are excluded, intentionally.
    """
    if side not in ("buy", "sell"):
        raise ValueError("A directional position is required")
    entry = _number(entry, "entry", True)
    stop = _number(initial_stop, "initial stop", True)
    mark = _number(mark, "executable mark", True)
    direction = 1 if side == "buy" else -1
    if direction * (entry - stop) <= 0:
        raise ValueError("Initial stop is on the wrong side of entry")
    price_risk = abs(entry - stop)
    now_r = direction * (mark - entry) / price_risk
    seen = prior or {}
    if not isinstance(seen, dict):
        raise ValueError("Prior excursion record must be a dict")
    prev_favorable = _number(seen.get("mfe_r", 0), "prior favorable excursion")
    prev_adverse = _number(seen.get("mae_r", 0), "prior adverse excursion")
    if prev_favorable < 0 or prev_adverse > 0:
        raise ValueError("Prior excursion extrema are invalid")
    mfe_r = max(prev_favorable, now_r, 0.)
    mae_r = min(prev_adverse, now_r, 0.)
    return {
        "schema": "niblit.observed-trade-excursion/1",
        "side": side,
        "entry": entry,
        "initial_stop": stop,
        "executable_mark": mark,
        "initial_stop_distance": price_risk,
        "current_r": now_r,
        "mfe_r": mfe_r,
        "mae_r": mae_r,
        "retracement_from_peak_r": max(0., mfe_r - now_r),
        "gross_price_only": True,
        "realized_profit": None,
        "measurement": "sampled executable quotes; no unsampled candle extrema",
    }


def summarise_closed(*, entry_risk_cash, realized_net, prior=None):
    """Net realized R uses signed broker profit and original cash stop risk."""
    cash_risk = _number(entry_risk_cash, "initial cash stop risk", True)
    net = _number(realized_net, "broker realized net")
    summary = {
        "schema": "niblit.realized-trade-outcome/1",
        "net_cash": net,
        "initial_risk_cash": cash_risk,
        "net_realized_r": net / cash_risk,
        "broker_reconciled": True,
    }
    if prior is not None:
        if not isinstance(prior, dict):
            raise ValueError("Prior excursion must be a dict")
        summary.update(observed_mfe_r=_number(prior.get("mfe_r"), "MFE"),
                       observed_mae_r=_number(prior.get("mae_r"), "MAE"))
    return summary
