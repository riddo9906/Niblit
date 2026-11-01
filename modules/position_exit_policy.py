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
