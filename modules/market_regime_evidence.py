"""Point-in-time market regime evidence: no signals, no broker actions.

All data must be completed bars. Categories are uncalibrated hypotheses,
not profitable-trading probabilities.
"""
from __future__ import annotations
import math
import statistics
import hashlib
import json
from collections.abc import Mapping

SECONDS = {"M5": 300, "M15": 900, "H1": 3600, "H4": 14400}
REGIMES = {"trend_up", "trend_down", "range", "compression",
           "breakout_candidate", "unstable", "uncertain"}


def _finite(value, *, positive=False):
    if type(value) not in (float, int) or not math.isfinite(value):
        raise ValueError("Invalid numeric market evidence")
    number = float(value)
    if positive and number <= 0:
        raise ValueError("Nonpositive market price")
    return number


def _ema(series, length):
    if len(series) < length:
        return None
    alpha = 2 / (length + 1)
    out = statistics.mean(series[:length])
    for value in series[length:]:
        out = alpha * value + (1 - alpha) * out
    return out


def _rsi(closes, period=14):
    if len(closes) <= period:
        return None
    delta = [b-a for a,b in zip(closes[-period-1:-1], closes[-period:])]
    ups = sum(max(0, v) for v in delta) / period
    downs = sum(max(0, -v) for v in delta) / period
    return 50.0 if ups == 0 and downs == 0 else 100.0 if downs == 0 else 100 - 100 / (1 + ups / downs)


def _atr_adx(rows, period=14):
    if len(rows) < period + 1:
        return None, None, None, None
    trs, pdms, mdms = [], [], []
    for prev, bar in zip(rows[:-1], rows[1:]):
        high, low, close0 = bar["high"], bar["low"], prev["close"]
        trs.append(max(high-low, abs(high-close0), abs(low-close0)))
        up = high-prev["high"]
        down = prev["low"]-low
        pdms.append(up if up > down and up > 0 else 0.)
        mdms.append(down if down > up and down > 0 else 0.)
    def wilder(values):
        smoothed = sum(values[:period])
        output = [smoothed]
        for v in values[period:]:
            smoothed = smoothed - smoothed / period + v
            output.append(smoothed)
        return output
    wtr, wp, wm = wilder(trs), wilder(pdms), wilder(mdms)
    dx=[]
    for a,b,c in zip(wtr,wp,wm):
        plus = 100*b/a if a else 0.
        minus = 100*c/a if a else 0.
        dx.append(100*abs(plus-minus)/(plus+minus) if plus+minus else 0.)
    adx = statistics.mean(dx[-period:]) if len(dx) >= period else None
    return wtr[-1] / period, adx, (100*wp[-1]/wtr[-1] if wtr[-1] else 0.), (100*wm[-1]/wtr[-1] if wtr[-1] else 0.)


def _one_timeframe(name, candles, cutoff):
    sec = SECONDS[name]
    if not isinstance(candles, (list, tuple)):
        raise ValueError("Candles must be a list")
    rows=[]
    for original in candles:
        if not isinstance(original, Mapping):
            raise ValueError("Invalid bar structure")
        ts = _finite(original.get("timestamp"), positive=True)
        if ts != int(ts) or int(ts) % sec:
            raise ValueError("Bar timestamp does not align to timeframe start")
        if ts + sec > cutoff:
            raise ValueError("Unclosed or future bar in evidence")
        values={k:_finite(original.get(k),positive=True) for k in ("open","high","low","close")}
        if values["high"] < max(values["open"], values["close"]) or values["low"] > min(values["open"],values["close"]) or values["low"] > values["high"]:
            raise ValueError("Invalid OHLC range")
        rows.append({"timestamp": int(ts),**values})
    if any(b["timestamp"] <= a["timestamp"] for a,b in zip(rows, rows[1:])):
        raise ValueError("Non-increasing bar timestamps")
    gaps=[b["timestamp"]-a["timestamp"] for a,b in zip(rows, rows[1:])]
    if any(d != sec for d in gaps):
        raise ValueError("Missing or gapped bars")
    if not rows:
        return {"timeframe":name,"bars":0,"features":{},"status":"missing"}
    closes=[r["close"] for r in rows]
    ema20=_ema(closes,20)
    ema50=_ema(closes,50)
    atr,adx,pdi,mdi=_atr_adx(rows)
    width=None
    if len(closes)>=20:
        mean=statistics.mean(closes[-20:])
        sigma=statistics.pstdev(closes[-20:])
        width=4*sigma/mean
    high20=max(r["high"] for r in rows[-21:-1]) if len(rows)>20 else None
    low20=min(r["low"] for r in rows[-21:-1]) if len(rows)>20 else None
    returns=[math.log(b/a) for a,b in zip(closes[-21:-1],closes[-20:])] if len(closes)>=21 else []
    features={
        "latest_close":closes[-1], "ema20":ema20, "ema50":ema50,
        "ema20_slope":(ema20-_ema(closes[:-5],20))/closes[-1] if ema20 is not None and len(closes)>=25 else None,
        "rsi14":_rsi(closes), "atr14":atr, "atr_price_fraction":atr/closes[-1] if atr is not None else None,
        "adx14":adx,"plus_di14":pdi,"minus_di14":mdi,
        "bollinger_width_fraction":width,
        "prior20_high":high20,"prior20_low":low20,
        "prior20_range_fraction":(high20-low20)/closes[-1] if high20 is not None else None,
        "realized_log_return_volatility":statistics.pstdev(returns) if len(returns)>=2 else None,
        "last_close_above_range":closes[-1]>high20 if high20 is not None else None,
        "last_close_below_range":closes[-1]<low20 if low20 is not None else None,
    }
    return {"timeframe":name,"bars":len(rows),
            "first_bar":rows[0]["timestamp"],"last_bar":rows[-1]["timestamp"],
            "last_completed_at":rows[-1]["timestamp"]+sec,
            "status":"complete" if len(rows)>=50 else "insufficient_history",
            "features":features}


def observe_regime(*, symbol, account, cutoff, candles_by_timeframe,
                   quote=None, previous=None):
    """Classify primary M5 context from completed multi-timeframe broker bars."""
    if not symbol or not account:
        raise ValueError("Account and symbol required")
    decision_time=_finite(cutoff,positive=True)
    if not isinstance(candles_by_timeframe, Mapping):
        raise ValueError("Timeframe mapping required")
    if set(candles_by_timeframe)-SECONDS.keys():
        raise ValueError("Unsupported timeframe")
    frames={name:_one_timeframe(name,candles_by_timeframe.get(name,[]),decision_time)
            for name in SECONDS}
    primary=frames["M5"]
    f=primary["features"]
    reasons=[]
    label="uncertain"
    spread=None
    quote_usable=True
    if quote is not None:
        if not isinstance(quote, Mapping):
            raise ValueError("Quote must be structured broker evidence")
        if quote.get("fresh") is not True:
            quote_usable=False
            reasons.append("Broker quote freshness is unverified or false")
        else:
            bid=_finite(quote.get("bid"),positive=True)
            ask=_finite(quote.get("ask"),positive=True)
            stamp=_finite(quote.get("timestamp"),positive=True)
            if ask<bid:
                raise ValueError("Crossed spread")
            if stamp>decision_time or decision_time-stamp>60:
                quote_usable=False
                reasons.append("Quote is stale or future-dated")
            else:
                spread=ask-bid
    m5_stale=(primary.get("last_completed_at") is not None and
              decision_time-primary["last_completed_at"]>600)
    if primary["status"]!="complete":
        reasons.append("Insufficient complete M5 history")
    elif m5_stale:
        reasons.append("Latest completed M5 candle is stale")
    elif not quote_usable:
        reasons.append("Current-market regime unavailable without a fresh broker quote")
    else:
        atr=f["atr14"]
        width=f["bollinger_width_fraction"]
        adx=f["adx14"]
        vol=f["atr_price_fraction"]
        high_spread=spread is not None and atr is not None and atr>0 and spread/atr>=.30
        if high_spread or (vol is not None and vol>=.035):
            label="unstable"
            reasons.append("High transaction spread versus ATR or unusually high normalized ATR")
        elif width is not None and width<.007 and (adx is None or adx<22):
            label="compression"
            reasons.append("Narrow 20-bar Bollinger width with limited directional strength")
        elif f["last_close_above_range"] or f["last_close_below_range"]:
            label="breakout_candidate"
            reasons.append("Completed M5 close exceeded the prior 20-bar range")
        elif adx is not None and adx>=25 and f["ema20"] is not None and f["ema50"] is not None:
            if f["ema20"]>f["ema50"] and f["plus_di14"]>f["minus_di14"] and f["ema20_slope"]>0:
                label="trend_up"
                reasons.append("ADX, +DI, EMA alignment and rising EMA slope agree")
            elif f["ema20"]<f["ema50"] and f["minus_di14"]>f["plus_di14"] and f["ema20_slope"]<0:
                label="trend_down"
                reasons.append("ADX, -DI, EMA alignment and falling EMA slope agree")
        if label=="uncertain" and adx is not None and adx<22:
            label="range"
            reasons.append("Weak ADX suggests non-directional price regime")
        if not reasons:
            reasons.append("Indicators disagree or lack calibrated evidence")
    missing=[name for name,row in frames.items() if row["status"]=="missing"]
    if missing:
        reasons.append("Missing higher-timeframe context: "+",".join(missing))
    prev_label=previous.get("regime") if isinstance(previous, Mapping) else None
    transition={"from":prev_label,"to":label,
                "changed":bool(prev_label in REGIMES and prev_label!=label)}
    record = {
        "schema":"niblit.market-regime-evidence/1",
        "scope":{"symbol":symbol,"account":account,"cutoff":decision_time},
        "timeframes":frames,"regime":label,"transition":transition,
        "reasons":reasons,"uncertainty":"uncalibrated_rule_evidence",
        "spread":spread,
        "market_data_current":(primary["status"]=="complete" and not m5_stale and quote_usable),
        "execution_authorized":False,
        "learning_action":"record_only",
        "expected_profit":None,"probability":None,
    }
    encoded=json.dumps(record,sort_keys=True,allow_nan=False,separators=(",", ":"))
    record["evidence_id"]=hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return record
