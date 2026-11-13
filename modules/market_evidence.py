"""Versioned deterministic observations, never votes, forecasts or order authority."""
import hashlib
import json
import math
from statistics import mean, pstdev

VERSION = 'market-evidence-v1'


def closed_rows(rows, seconds, as_of):
    if not isinstance(as_of,(int,float)) or not math.isfinite(as_of):
        raise ValueError('Finite source clock required')
    result=[]
    for item in rows[-500:]:
        t=float(item['timestamp'])
        if t+seconds>as_of: continue
        row={k:float(item[k]) for k in ('timestamp','open','high','low','close')}
        if any(not math.isfinite(v) or v<=0 for v in row.values()):raise ValueError('Invalid candle')
        if row['low']>min(row['open'],row['close']) or row['high']<max(row['open'],row['close']):
            raise ValueError('Invalid OHLC')
        if result and row['timestamp']<=result[-1]['timestamp']:raise ValueError('Unordered candles')
        row['volume']=item.get('volume')
        result.append(row)
    return result


def recognize(rows, symbol, frame, seconds, as_of, source):
    bars=closed_rows(rows,seconds,as_of)
    material={'schema':VERSION,'symbol':symbol,'timeframe':frame,'source':source,'candles':bars}
    ident=hashlib.sha256(json.dumps(material,sort_keys=True,allow_nan=False).encode()).hexdigest()
    output={'schema_version':VERSION,'snapshot_id':ident,'symbol':symbol,'timeframe':frame,
            'source':source,'patterns':[],'structure':{},'indicators':{},'execution_authorized':False,
            'closed_candles':len(bars),'last_closed_at':bars[-1]['timestamp']+seconds if bars else None}
    output['timestamp_basis']='source_broker_clock_not_independently_verified_utc'
    output['data_quality']={'session_gaps':sum(b['timestamp']-a['timestamp']!=seconds for a,b in zip(bars,bars[1:]))}
    if not bars:return output
    def body(b):return abs(b['close']-b['open'])
    def span(b):return b['high']-b['low']
    def up(b):return b['close']>b['open']
    def add(name,direction,used,explanation,qualifiers=()):
        if any(b['timestamp']-a['timestamp']!=seconds for a,b in zip(used,used[1:])):return
        close=used[-1]['timestamp']+seconds
        output['patterns'].append({'snapshot_id':ident,'symbol':symbol,'timeframe':frame,
            'name':name,'direction':direction,'candle_timestamps':[b['timestamp'] for b in used],
            'candle_close_time':close,'available_at':close,'rule_version':VERSION,
            'confirmation':'closed_candle_rule','qualifiers':list(qualifiers),
            'source_data':used,'explanation':explanation,'confidence':None,
            'uncertainty':'Deterministic shape; predictive reliability not calibrated'})
    a=bars[-1];r=span(a);b=body(a);upper=a['high']-max(a['open'],a['close']);lower=min(a['open'],a['close'])-a['low']
    trend='unknown' if len(bars)<7 else 'up' if bars[-2]['close']>bars[-7]['close'] else 'down'
    if r>0:
        if b<=.1*r:
            variant='dragonfly_doji' if lower>=.6*r else 'gravestone_doji' if upper>=.6*r else 'doji'
            add(variant,'neutral',[a],'Body <= 10% of total range')
        if 0<b<=.35*r and lower>=2*b and upper<=b:
            add('hanging_man' if trend=='up' else 'hammer','bearish' if trend=='up' else 'bullish',[a],
                'Lower wick >= twice body; upper wick <= body',['prior_trend:'+trend])
        if 0<b<=.35*r and upper>=2*b and lower<=b:
            add('shooting_star' if trend=='up' else 'inverted_hammer','bearish' if trend=='up' else 'bullish',[a],
                'Upper wick >= twice body; lower wick <= body',['prior_trend:'+trend])
        if max(upper,lower)>=.65*r and b<=.3*r:
            add('pin_bar','bullish' if lower>upper else 'bearish',[a],'Dominant wick >= 65% of range')
    if len(bars)>=2:
        p=bars[-2];ab=sorted((a['open'],a['close']));pb=sorted((p['open'],p['close']))
        if up(a)!=up(p) and body(a)>0 and body(p)>0:
            if ab[0]<=pb[0] and ab[1]>=pb[1] and body(a)>body(p):
                add('bullish_engulfing' if up(a) else 'bearish_engulfing','bullish' if up(a) else 'bearish',[p,a],'Opposite real body strictly engulfs previous real body')
            if ab[0]>=pb[0] and ab[1]<=pb[1] and body(a)<body(p):
                add('harami','bullish' if up(a) else 'bearish',[p,a],'Opposite smaller real body inside previous body')
        if a['high']<p['high'] and a['low']>p['low']:add('inside_bar','neutral',[p,a],'Range strictly within previous range')
        if a['high']>p['high'] and a['low']<p['low']:add('outside_bar','bullish' if up(a) else 'bearish',[p,a],'Range strictly exceeds previous range')
        tolerance=max(span(p),r)*.05
        if tolerance and not up(a) and up(p) and abs(a['high']-p['high'])<=tolerance:
            add('tweezer_top','bearish',[p,a],'Opposite candles with highs within 5% of maximum range')
        if tolerance and up(a) and not up(p) and abs(a['low']-p['low'])<=tolerance:
            add('tweezer_bottom','bullish',[p,a],'Opposite candles with lows within 5% of maximum range')
    if len(bars)>=3:
        x,y,z=bars[-3:];mid=(x['open']+x['close'])/2
        if body(x)>0 and body(y)<body(x)*.3:
            if not up(x) and up(z) and z['close']>mid and max(y['open'],y['close'])<mid:
                add('morning_star','bullish',[x,y,z],'Small middle body below midpoint; bullish recovery above midpoint',['gap_not_required'])
            if up(x) and not up(z) and z['close']<mid and min(y['open'],y['close'])>mid:
                add('evening_star','bearish',[x,y,z],'Small middle body above midpoint; bearish recovery below midpoint',['gap_not_required'])
        if all(span(v)>0 and body(v)>=.5*span(v) for v in (x,y,z)):
            if all(up(v) for v in (x,y,z)) and x['close']<y['close']<z['close'] and x['open']<=y['open']<=x['close'] and y['open']<=z['open']<=y['close']:
                add('three_white_soldiers','bullish',[x,y,z],'Three strong advancing bodies with opens inside previous body')
            if all(not up(v) for v in (x,y,z)) and x['close']>y['close']>z['close'] and x['close']<=y['open']<=x['open'] and y['close']<=z['open']<=y['open']:
                add('three_black_crows','bearish',[x,y,z],'Three strong declining bodies with opens inside previous body')
    closes=[v['close'] for v in bars]
    if len(bars)>=20:
        recent=bars[-20:];mu=mean(closes[-20:]);sd=pstdev(closes[-20:])
        trs=[max(v['high']-v['low'],abs(v['high']-bars[i-1]['close']),abs(v['low']-bars[i-1]['close'])) for i,v in enumerate(bars) if i]
        diffs=[q-p for p,q in zip(closes,closes[1:])][-14:];gain=mean(max(0,d) for d in diffs);loss=mean(max(0,-d) for d in diffs)
        ema=closes[0]
        for c in closes[1:]:ema=ema+(c-ema)*2/21
        output['indicators']={'sma20':mu,'ema20':ema,'rsi14_sma':100-100/(1+gain/loss) if loss else 100 if gain else 50,
            'atr14_sma':mean(trs[-14:]),'bollinger20':{'middle':mu,'upper':mu+2*sd,'lower':mu-2*sd},
            'method':'SMA RSI/ATR; EMA seeded by first supplied close; not MT5 Wilder parity',
            'volume_kind':'broker_tick_count','updated_at':a['timestamp']+seconds}
        swings=[]
        for i in range(2,len(bars)-2):
            v=bars[i];window=bars[i-2:i+3]
            for kind,key,fn in [('high','high',max),('low','low',min)]:
                if v[key]==fn(w[key] for w in window) and sum(w[key]==v[key] for w in window)==1:
                    swings.append({'kind':kind,'price':v[key],'timestamp':v['timestamp'],
                        'available_at':bars[i+2]['timestamp']+seconds,'confirmation':'two_closed_right_bars'})
        highs=[v for v in swings if v['kind']=='high'];lows=[v for v in swings if v['kind']=='low']
        structure='undetermined'
        if len(highs)>=2 and len(lows)>=2:
            structure='higher_highs_higher_lows' if highs[-1]['price']>highs[-2]['price'] and lows[-1]['price']>lows[-2]['price'] else 'lower_highs_lower_lows' if highs[-1]['price']<highs[-2]['price'] and lows[-1]['price']<lows[-2]['price'] else 'mixed'
        prior=bars[-21:-1];res=max(v['high'] for v in prior);sup=min(v['low'] for v in prior)
        output['structure']={'trend':structure,'swings':swings[-24:],'support':sup,'resistance':res,
            'breakout':'above' if a['close']>res else 'below' if a['close']<sup else 'none',
            'liquidity_sweep_candidate':a['high']>res and a['close']<=res or a['low']<sup and a['close']>=sup,
            'confirmation':'closed_bars_only','predictive_reliability':'unevaluated'}
    return output
