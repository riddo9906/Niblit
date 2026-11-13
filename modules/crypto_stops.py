"""Deterministic Exness DEMO protection from native completed M5 bars.

Signal eligibility stays in the six-strategy manager. This module cannot send,
modify, authorize or resize orders. An unaffordable stop is rejected, not tightened.
"""
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
import math

VERSION='crypto-atr-structure/1'
RULES={
 'crypto_default':(2.,10),
 'trend_v1':(2.5,10),
 'breakout_v1':(2.,10),
 'rsi_reversion_v1':(2.,5),
 'bollinger_reversion_v1':(2.,5),
 'ema_pullback_v1':(2.,10),
 'squeeze_breakout_v1':(2.5,10),
}
SPEC_FIELDS=('point','trade_tick_size','trade_stops_level','trade_freeze_level','digits',
             'currency_base','currency_profit','trade_mode')


def policy():
    return {'version':VERSION,'timeframe':'M5','atr_period':14,'spread_multiple':3.,
            'structure_buffer_atr':.25,'reward_multiple':2.,'maximum_stop_fraction':.05,
            'strategy_rules':{k:{'atr_multiple':v[0],'structure_bars':v[1]} for k,v in RULES.items()}}


def finite(value,name,positive=False):
    if type(value) not in (int,float) or not math.isfinite(value) or (positive and value<=0):
        raise ValueError('Unverified crypto '+name)
    return float(value)


def grid(value,tick,digits,up=False):
    step=Decimal(str(tick));rounding=ROUND_CEILING if up else ROUND_FLOOR
    price=(Decimal(str(value))/step).to_integral_value(rounding=rounding)*step
    return float(price.quantize(Decimal(1).scaleb(-digits),rounding=rounding))


def specification(spec):
    if spec.get('currency_base') not in ('BTC','ETH') or spec.get('currency_profit')!='USD' or spec.get('trade_mode')!=4:
        raise ValueError('Fully tradable USD crypto specification required')
    point=finite(spec.get('point'),'point',True);tick=finite(spec.get('trade_tick_size'),'tick size',True)
    digits=spec.get('digits')
    if type(digits) is not int or not 0<=digits<=12 or tick<point or abs(tick/point-round(tick/point))>1e-6:
        raise ValueError('Invalid crypto price grid')
    stops,freeze=spec.get('trade_stops_level'),spec.get('trade_freeze_level')
    if any(type(x) is not int or x<0 for x in (stops,freeze)):
        raise ValueError('Unknown broker stop/freeze distances')
    return point,tick,digits,max(stops,freeze)*point


def levels(rows,spec,quote,side,strategy='crypto_default'):
    if strategy not in RULES or side not in ('buy','sell'):
        raise ValueError('Known crypto strategy and direction required')
    point,tick,digits,broker_min=specification(spec)
    bid=finite(quote.get('bid'),'bid',True);ask=finite(quote.get('ask'),'ask',True)
    now=finite(quote.get('timestamp'),'broker tick time',True)
    if ask<bid:raise ValueError('Crossed crypto quote')
    if rows is None or not 30<=len(rows)<=500:raise ValueError('Insufficient completed crypto history')
    bars=[]
    for row in rows:
        # Native MT5 records use time; Core-normalized records use timestamp.
        try:at=int(row['time'])
        except (KeyError,ValueError,IndexError):at=int(row['timestamp'])
        o,h,l,c=(float(row[k]) for k in ('open','high','low','close'))
        if at<=0 or not all(math.isfinite(v) and v>0 for v in (o,h,l,c)) or l>min(o,c) or h<max(o,c):
            raise ValueError('Invalid crypto OHLC history')
        bars.append((at,o,h,l,c))
    if any(b[0]-a[0]!=300 for a,b in zip(bars,bars[1:])):
        raise ValueError('Gapped or unordered crypto history')
    if not 300<=now-bars[-1][0]<=620:
        raise ValueError('Crypto completed history is stale or contains a forming/future bar')
    tr=[max(b[2]-b[3],abs(b[2]-a[4]),abs(b[3]-a[4])) for a,b in zip(bars,bars[1:])]
    atr=sum(tr[:14])/14
    for value in tr[14:]:atr=(13*atr+value)/14
    finite(atr,'ATR',True)
    multiple,lookback=RULES[strategy];spread=ask-bid
    buffer=max(.25*atr,2*tick)
    minimum=max(multiple*atr,3*spread,broker_min+2*tick)
    entry=ask if side=='buy' else bid
    if side=='buy':
        anchor=min(b[3] for b in bars[-lookback:])
        stop=grid(min(bid-minimum,anchor-buffer),tick,digits)
        risk=entry-stop;target=grid(entry+2*risk,tick,digits,up=True)
    else:
        anchor=max(b[2] for b in bars[-lookback:])
        stop=grid(max(ask+minimum,anchor+buffer),tick,digits,up=True)
        risk=stop-entry;target=grid(entry-2*risk,tick,digits)
    if not 0<risk<=entry*.05 or target<=0:
        raise ValueError('Crypto structural stop exceeds distance ceiling; no tighter fallback')
    return {'version':VERSION,'strategy':strategy,'side':side,'atr':atr,'atr_period':14,
            'atr_multiple':multiple,'structure_bars':lookback,'structure_anchor':anchor,
            'structure_buffer':buffer,'spread':spread,'broker_minimum_distance':broker_min,
            'stop_loss':stop,'take_profit':target,'reviewed_entry':entry,'stop_distance':risk,
            'gross_reward_multiple':abs(target-entry)/risk,'last_completed_bar':bars[-1][0],
            'source':'mt5_native_completed_M5_Wilder_TR14_and_recent_structure',
            'stop_modifications_enabled':False}


def fixed_levels(protection,spec,quote,side):
    """Revalidate reviewed levels on a fresh quote; never widen or move them."""
    _,tick,digits,broker_min=specification(spec)
    if protection.get('version')!=VERSION or protection.get('side')!=side or protection.get('strategy') not in RULES:
        raise ValueError('Reviewed crypto protection policy changed')
    bid=finite(quote.get('bid'),'bid',True);ask=finite(quote.get('ask'),'ask',True)
    if ask<bid:raise ValueError('Crossed crypto quote')
    stop=finite(protection.get('stop_loss'),'reviewed stop',True)
    target=finite(protection.get('take_profit'),'reviewed target',True)
    if any(abs(v/tick-round(v/tick))>1e-6 for v in (stop,target)):
        raise ValueError('Reviewed protection no longer matches broker grid')
    gap=max(broker_min+2*tick,3*(ask-bid))
    entry=ask if side=='buy' else bid
    valid=stop<=bid-gap and target>=bid+broker_min if side=='buy' else stop>=ask+gap and target<=ask-broker_min
    risk=abs(entry-stop);reward=(target-entry) if side=='buy' else (entry-target)
    if not valid or not 0<risk<=entry*.05 or reward/risk<1.8:
        raise ValueError('Reviewed crypto levels invalid at current quote; fresh review required')
    return {**protection,'stop_distance':risk,'current_entry':entry,'current_gross_reward_multiple':reward/risk}


def from_mt5(api,symbol,info,quote,side,strategy='crypto_default'):
    rows=api.copy_rates_from_pos(symbol,api.TIMEFRAME_M5,1,64)
    return levels(rows,{k:getattr(info,k,None) for k in SPEC_FIELDS},quote,side,strategy)
