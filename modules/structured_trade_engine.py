"""Deterministic, side-effect-free trading decision contract (paper planning only).

Inputs are verified market/broker snapshots and explicit numerical assumptions.
No connector, credential, model, API, memory, state mutation or order placement.
Market outcomes cannot be predicted reliably; only rule-based scenarios are emitted.
"""
import hashlib
import json
import math
from decimal import Decimal, ROUND_FLOOR

from modules.strategy_manager import assess_with_context
from modules.crypto_stops import levels as crypto_levels, SPEC_FIELDS

VERSION = "structured-execution-plan/1"


def finite(value, name, *, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or (positive and value <= 0):
        raise ValueError("Invalid " + name)
    return float(value)


def validated_m5(candles, as_of):
    """Only completed, continuous 5-minute bars. No future or forming candles."""
    now = finite(as_of, "as_of", positive=True)
    if not isinstance(candles, list) or not 51 <= len(candles) <= 500:
        raise ValueError("Need 51-500 completed M5 candles")
    rows = []
    for c in candles:
        t = finite(c.get("timestamp"), "bar time", positive=True)
        if t != int(t):
            raise ValueError("Nonintegral bar time")
        item = {"timestamp": int(t)}
        for k in ("open", "high", "low", "close"):
            item[k] = finite(c.get(k), k, positive=True)
        if item["low"] > min(item["open"], item["close"]) or item["high"] < max(item["open"], item["close"]):
            raise ValueError("Invalid OHLC")
        rows.append(item)
    if any(b["timestamp"] - a["timestamp"] != 300 for a, b in zip(rows, rows[1:])):
        raise ValueError("M5 gaps or unordered history")
    age = now - (rows[-1]["timestamp"] + 300)
    if not 0 <= age <= 300:
        raise ValueError("Future, forming or stale completed bar")
    return rows


def lot_grid(minimum, step, maximum, ceiling):
    """Broker-grid volume rounding always rounds down, never exceeds risk."""
    lo = Decimal(str(finite(minimum, "minimum lot", positive=True)))
    inc = Decimal(str(finite(step, "lot step", positive=True)))
    hi = min(Decimal(str(finite(maximum, "maximum lot", positive=True))),
             Decimal(str(finite(ceiling, "risk size ceiling", positive=True))))
    if hi < lo:
        return None
    return float(lo + ((hi - lo) / inc).to_integral_value(rounding=ROUND_FLOOR) * inc)


def plan_mt5_crypto(*, symbol, candles, quote, spec, equity, risk_fraction,
                    risk_cash, max_volume, loss_per_lot, as_of, context=None):
    """Plan BTC/USD or ETH/USD demo trades; never grants or executes them.

    loss_per_lot is a venue-calculated loss to the *same* candidate stop,
    including the correct account-currency conversion. Callers must obtain it
    from broker order_calc_profit, not assume USD price delta equals exposure.
    """
    if type(symbol) is not str or not symbol:
        raise ValueError("Symbol required")
    bars = validated_m5(candles, as_of)
    if not isinstance(spec, dict) or not isinstance(quote, dict):
        raise ValueError("Broker specification and quote required")
    bid = finite(quote.get("bid"), "bid", positive=True)
    ask = finite(quote.get("ask"), "ask", positive=True)
    if ask < bid or quote.get("fresh") is not True:
        raise ValueError("Verified fresh executable quote required")
    if not 0 <= finite(as_of, "clock") - finite(quote.get("timestamp"), "quote time", positive=True) <= 15:
        raise ValueError("Quote timestamp is stale or future-dated")
    capital = finite(equity, "equity", positive=True)
    fraction = finite(risk_fraction, "risk fraction", positive=True)
    if fraction > 1:
        raise ValueError("Risk fraction exceeds 100 percent")
    budget = min(capital * fraction, finite(risk_cash, "cash cap", positive=True))
    assessment = assess_with_context(bars, context)
    decision = assessment["side"]
    result = {"version": VERSION, "symbol": symbol, "timeframe": "M5", "bar": bars[-1]["timestamp"],
              "side": decision, "strategy": assessment["strategy"],
              "candidate_directions": {name: [v["strategy"] for v in assessment["candidates"]
                                              if v["side"] == name] for name in ("buy", "sell", "wait")},
              "decision_reason": assessment["selection_reason"], "risk_budget": budget,
              "execution_authorized": False, "order_sent": False,
              "forecast_kind": "conditional_rules_not_calibrated_prediction",
              "status": "NO_TRADE", "plan": None}
    if not assessment["assessment_complete"] or decision not in ("buy", "sell"):
        return result
    if spec.get("currency_profit") != "USD" or spec.get("currency_base") not in ("BTC", "ETH"):
        raise ValueError("USD BTC/ETH broker specification required")
    if spec.get("currency_base") not in symbol.upper():
        raise ValueError("Symbol does not match broker specification")
    # crypto_levels validates completed market structure, ATR, broker stop grid
    # and deterministic reward-to-risk; it cannot submit or modify orders.
    native = [{"time": b["timestamp"], **{k: b[k] for k in ("open", "high", "low", "close")}} for b in bars]
    protection = crypto_levels(native, {k: spec.get(k) for k in SPEC_FIELDS},
                               {"bid": bid, "ask": ask, "timestamp": quote["timestamp"]},
                               decision, assessment["strategy"])
    per_lot = finite(loss_per_lot, "broker loss per lot", positive=True)
    # A broker-derived 1-lot stop valuation is mandatory. If unavailable,
    # caller must not guess and no volume is emitted.
    quantity = lot_grid(spec.get("volume_min"), spec.get("volume_step"),
                        spec.get("volume_max"), min(finite(max_volume, "lot limit", positive=True),
                        budget / per_lot))
    if quantity is None:
        return {**result, "decision_reason": "Broker minimum lot exceeds the validated stop-risk budget"}
    gross_loss = quantity * per_lot
    if gross_loss > budget + 1e-8:
        raise ValueError("Sizing exceeded risk budget")
    plan = {"entry_reference": ask if decision == "buy" else bid,
            "stop_loss": protection["stop_loss"], "take_profit": protection["take_profit"],
            "volume": quantity, "gross_stop_risk": gross_loss,
            "stop_distance": protection["stop_distance"],
            "atr": protection["atr"], "structure_anchor": protection["structure_anchor"],
            "reward_multiple": protection["gross_reward_multiple"],
            "protection_version": protection["version"],
            "costs_complete": False,
            "binding_note": "Reprice, broker-value, cost-model and revalidate at order preview and execution"}
    material = {"version": VERSION, "symbol": symbol, "bar": bars[-1]["timestamp"],
                "quote": {"bid": bid, "ask": ask, "timestamp": quote["timestamp"]},
                "assessment": assessment, "plan": plan, "risk_budget": budget}
    return {**result, "status": "DRAFT_ONLY", "plan": plan,
            "plan_hash": hashlib.sha256(json.dumps(material, sort_keys=True,
                                                  allow_nan=False).encode()).hexdigest()}



def execution_plan_record(*, snapshot, review, intent, risk_budget):
    """Describe a broker-reviewed plan deterministically without authorizing it.

    Core persists this beside the durable claim. No broker calls, state writes,
    mutable policy flags or adaptive model behavior are introduced.
    """
    if not isinstance(snapshot, dict) or not isinstance(review, dict) or not isinstance(intent, dict):
        raise ValueError("Structured plan needs broker and strategy evidence")
    protect = review.get("protection")
    if not isinstance(protect, dict) or protect.get("version") != "crypto-atr-structure/1":
        raise ValueError("Structured crypto protection evidence required")
    data = {
        "schema": "niblit.execution-plan/1",
        "venue": "mt5",
        "account": snapshot["account"],
        "symbol": snapshot["symbol"],
        "side": intent["side"],
        "strategy": intent.get("strategy") or "crypto_default",
        "bar": protect["last_completed_bar"],
        "protection_version": protect["version"],
        "source": protect["source"],
        "atr": finite(protect["atr"], "ATR", positive=True),
        "structure_anchor": finite(protect["structure_anchor"], "structure", positive=True),
        "reviewed_entry": finite(review["price"], "reviewed entry", positive=True),
        "stop_loss": finite(review["stop_loss"], "stop", positive=True),
        "take_profit": finite(review["take_profit"], "target", positive=True),
        "volume": finite(intent["volume"], "volume", positive=True),
        "gross_stop_risk": finite(review["estimated_stop_risk"], "gross stop loss", positive=True),
        "risk_budget": finite(risk_budget, "risk budget", positive=True),
        "purpose": "deterministic_replay_and_order_attribution",
        "execution_authorized": False,
    }
    encoded = json.dumps(data, allow_nan=False, sort_keys=True, separators=(",", ":"))
    return {**data, "record_hash": hashlib.sha256(encoded.encode("utf-8")).hexdigest()}
