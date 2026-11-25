"""Explainable demo exits. Quotes manage profit; completed bars invalidate a thesis.

No ability to submit orders, alter stops or increase exposure. A saved entry
context is required; old/manual positions are never adopted automatically.
"""
import math
import statistics
from modules.demo_strategy import STRATEGIES,ema,rsi


def assess_exit(position,candles,quote,context):
    hold={'action':'hold','reason':'No exit condition met','execution_eligible':False}
    if not context or context.get('strategy') not in STRATEGIES:
        return {**hold,'reason':'No recorded entry thesis; manual management required'}
    try:
        side=1 if position['type']==0 else -1
        entry=float(position['price_open']);stop=float(context['initial_stop'])
        bid=float(quote['bid']);ask=float(quote['ask'])
        if not quote.get('fresh') or not all(math.isfinite(v) and v>0 for v in (entry,stop,bid,ask)) or ask<bid:raise ValueError()
        if side*(entry-stop)<=0:raise ValueError()
        risk=abs(entry-stop);price=bid if side==1 else ask
        gain=side*(price-entry);spread=ask-bid
        peak=max(float(context.get('peak_price_gain',0)),gain,0.)
        context['peak_price_gain']=peak
        current_r=gain/risk;peak_r=peak/risk
        evidence={'strategy':context['strategy'],'current_R':current_r,'peak_R':peak_r,
                  'gain_in_price':gain,'spread_in_price':spread,'initial_risk_in_price':risk,
                  'cost_limit':'Executable bid/ask used. Commission, swap and slippage may erase a price profit.'}
        # Persistent quote-based giveback check; resets whenever recovery occurs.
        giveback=peak_r>=.75 and peak-gain>=.35*risk and gain>=max(.2*risk,3*spread)
        stamp=float(quote.get('timestamp',0))
        if not giveback:context['giveback_checks']=0
        elif stamp>0 and stamp-context.get('last_giveback_check',0)>=10:
            context['giveback_checks']=context.get('giveback_checks',0)+1
            context['last_giveback_check']=stamp
        reason=None
        if context['giveback_checks']>=2:reason='Profit protection: retraced 0.35R after reaching 0.75R, with at least 0.20R and three spreads remaining'
        if len(candles)>=51:
            rows=candles[-51:]
            if any(b['timestamp']-a['timestamp']!=300 for a,b in zip(rows[:-1],rows[1:])):raise ValueError()
            prices=[float(r['close']) for r in rows]
            if not all(math.isfinite(p) and p>0 for p in prices):raise ValueError()
            strategy=context['strategy']
            if strategy in {'trend_v1','ema_pullback_v1'}:
                invalid=all(side*(prices[i]-(statistics.mean(prices[i-19:i+1]) if strategy=='trend_v1' else ema(prices[:i+1],20)))<0 for i in (49,50))
                if invalid:reason='Entry trend invalidation: two completed closes crossed the strategy mean against the position'
            elif strategy in {'breakout_v1','squeeze_breakout_v1'}:
                boundary=context.get('breakout_level')
                if boundary is not None and all(side*(p-float(boundary))<0 for p in prices[-2:]):
                    reason='Possible failed breakout: two completed closes returned inside the recorded entry boundary'
            elif gain>=max(.35*risk,3*spread):
                if strategy=='bollinger_reversion_v1' and side*(prices[-1]-statistics.mean(prices[-20:]))>=0:
                    reason='Reversion target reached: price returned to the strategy mean with a cost buffer'
                if strategy=='rsi_reversion_v1' and side*(rsi(prices)-50)>=0:
                    reason='RSI reversion target reached: RSI recovered to neutral with a cost buffer'
        return {'action':'close' if reason else 'hold','reason':reason or hold['reason'],
                'evidence':evidence,'execution_eligible':bool(reason),
                'prediction_use':'Advisory only: online predictor has not been validated for position exits',
                'limits':'Experimental demo exit rules; cannot identify every fakeout or guarantee a profitable fill.'}
    except (KeyError,TypeError,ValueError,OverflowError):
        return {**hold,'reason':'Invalid or stale exit evidence; broker stop remains unchanged'}



def assess_reversal(position, candles, quote, context, *, observed_profit=None):
    """Evidence-based early-profit exit evaluation; no order submission.

    Uses only completed consecutive M5 closes and executable bid/ask. A
    candidate needs meaningful positive gross R, retracement from observed
    peak, and two independent classes of deterioration evidence. Confirmation
    is per completed bar, not repeated worker ticks on the same bar.
    """
    hold = {"action": "hold", "reason": "No confirmed profitable reversal",
            "execution_eligible": False, "policy": "early-reversal-v1",
            "prediction": "rule_based_reversal_risk_not_probability"}
    try:
        if not isinstance(context, dict) or context.get("strategy") not in STRATEGIES:
            return hold
        direction = 1 if position["type"] == 0 else -1
        entry = float(position["price_open"])
        initial_stop = float(context["initial_stop"])
        bid, ask = float(quote["bid"]), float(quote["ask"])
        if not quote.get("fresh") or not all(math.isfinite(x) and x > 0 for x in
                   (entry, initial_stop, bid, ask)) or ask < bid:
            return hold
        if direction * (entry - initial_stop) <= 0:
            return hold
        risk = abs(entry - initial_stop)
        spread = ask - bid
        mark = bid if direction == 1 else ask
        price_gain = direction * (mark - entry)
        current_r = price_gain / risk
        peak_r = max(0., float(context.get("peak_price_gain", 0)) / risk, current_r)
        if not math.isfinite(peak_r):
            return hold
        # The early-profit rule requires a broker-measured positive floating
        # result; missing, malformed or unmeasured profit is not evidence.
        if (type(observed_profit) not in (float, int)
                or not math.isfinite(observed_profit) or observed_profit <= 0):
            return {**hold, "reason": "Broker positive floating result is unavailable or unverified"}
        if len(candles) < 51:
            return hold
        rows = candles[-51:]
        if any(b["timestamp"] - a["timestamp"] != 300 for a, b in zip(rows, rows[1:])):
            return hold
        closes = [float(r["close"]) for r in rows]
        if not all(math.isfinite(p) and p > 0 for p in closes):
            return hold
        last_bar = int(rows[-1]["timestamp"])
        quote_stamp = float(quote.get("timestamp", 0))
        # Candle timestamps may denote completion in broker snapshots.
        # Never confirm from future-dated or more-than-one-bar-old evidence.
        if (not math.isfinite(quote_stamp) or quote_stamp <= 0
                or quote_stamp < last_bar or quote_stamp >= last_bar + 600):
            return {**hold, "reason": "Latest completed bar is not contemporaneous with the quote"}
        if (current_r < .25 or peak_r < .65 or peak_r - current_r < .20
                or price_gain < 4 * spread):
            context["reversal_consecutive_bars"] = 0
            return {**hold, "reason": "Insufficient retained profit, excursion or retracement",
                    "evidence": {"current_r": current_r, "peak_r": peak_r,
                                 "retracement_r": peak_r - current_r}}
        # Deterioration classes: short-horizon price momentum, relation to
        # trend mean, and recovery of RSI away from the prior extreme.
        momentum = direction * (closes[-1] - closes[-4]) < 0
        mean20 = statistics.mean(closes[-20:])
        mean_cross = direction * (closes[-1] - mean20) < 0
        prior_rsi = rsi(closes[:-1])
        latest_rsi = rsi(closes)
        rsi_reversal = direction * (latest_rsi - prior_rsi) < -4 and (
            prior_rsi >= 55 if direction == 1 else prior_rsi <= 45)
        reasons = [name for name, yes in (
            ("three_bar_counter_momentum", momentum),
            ("against_20_bar_mean", mean_cross),
            ("rsi_counter_move", rsi_reversal)) if yes]
        score = len(reasons)
        last_checked = context.get("reversal_last_bar")
        previous = int(context.get("reversal_consecutive_bars", 0))
        if last_checked is None or last_bar > int(last_checked):
            contiguous = last_checked is not None and last_bar - int(last_checked) == 300
            context["reversal_last_bar"] = last_bar
            context["reversal_consecutive_bars"] = (previous + 1 if contiguous else 1) if score >= 2 else 0
        count = int(context.get("reversal_consecutive_bars", 0))
        report = {"current_r": current_r, "peak_r": peak_r,
                  "retracement_r": peak_r-current_r, "rsi": latest_rsi,
                  "prior_rsi": prior_rsi, "mean20": mean20, "score": score,
                  "signals": reasons, "confirmed_bars": count, "bar": last_bar,
                  "gross_price_gain": price_gain,
                  "observed_profit": observed_profit,
                  "fees_excluded": True}
        # Three simultaneous signals can justify one completed bar; two
        # weaker signals must persist across two distinct completed bars.
        exit_qualified = score == 3 or (score >= 2 and count >= 2)
        if not exit_qualified:
            return {**hold, "evidence": report}
        return {"action": "close", "reason": "Profitable reversal evidence: " + ", ".join(reasons),
                "execution_eligible": True, "policy": "early-reversal-v1",
                "prediction": "rule_based_reversal_risk_not_probability",
                "evidence": report,
                "limitations": "No future-price forecast; gaps, spreads and fees can change realized outcome"}
    except (KeyError, TypeError, ValueError, OverflowError, ZeroDivisionError):
        return hold
