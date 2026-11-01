"""Deterministic, inspectable demo hypotheses. No paid models or live-order path.

Signals use completed M5 bars. These hand-authored rules are experiments, not
discovered profitable strategies; results must include costs and unseen periods.
"""
import math
import statistics

STRATEGIES = {
    'trend_v1': '20/50 mean trend with a five-bar momentum confirmation',
    'breakout_v1': 'Close beyond the previous 20-bar high or low',
    'rsi_reversion_v1': 'Cutler RSI(14) recovery through 30/70 in a flat 20/50 mean regime',
    'bollinger_reversion_v1': 'Return inside a two-deviation 20-bar band in a flat regime',
    'ema_pullback_v1': 'Price recrosses EMA(20) in the direction of EMA(50)',
    'squeeze_breakout_v1': '20-bar range breakout after contracting return volatility',
}

REFERENCES = {
    'strategy_families':'https://www.quantconnect.com/docs/v2/writing-algorithms/strategy-library',
    'predictive_validation':'https://www.freqtrade.io/en/stable/freqai/',
    'lookahead':'https://www.freqtrade.io/en/stable/lookahead-analysis/',
}

def ema(values, period):
    value=values[0]
    for price in values[1:]: value += 2/(period+1)*(price-value)
    return value

def rsi(values, period=14):
    deltas=[b-a for a,b in zip(values[-period-1:-1],values[-period:])]
    gain=sum(max(x,0) for x in deltas)/period
    loss=sum(max(-x,0) for x in deltas)/period
    return 50. if gain==loss==0 else 100. if loss==0 else 100-100/(1+gain/loss)

def evaluate(candles, strategy):
    if strategy not in STRATEGIES:
        raise ValueError('Unknown strategy')
    result = {'strategy': strategy, 'origin': 'Human-authored Niblit baseline v1',
              'rule': STRATEGIES[strategy], 'side': 'wait', 'evidence': {},
              'profitability': 'Unproven; reward/risk is not a probability or a profit forecast.',
              'invalidation': 'Stop loss, opposing signal, or changed market regime; gaps can exceed stops.'}
    result['references']=REFERENCES
    result['validation']='Experimental demo rule. Documentation describes the family, not profitability of these exact parameters.'
    result['hypothesis'] = ('Trend persistence after price and momentum agree.' if strategy=='trend_v1'
                            else 'A close outside the prior range may precede continuation.')
    if strategy in ('rsi_reversion_v1','bollinger_reversion_v1'):
        result['hypothesis']='An extreme deviation recovering in a flat regime may revert toward its mean; a new trend can invalidate this.'
    elif strategy=='ema_pullback_v1':
        result['hypothesis']='A pullback recross in an established mean trend may resume that trend; whipsaws invalidate this.'
    elif strategy=='squeeze_breakout_v1':
        result['hypothesis']='Contracting volatility followed by a range break may precede expansion; false breakouts invalidate this.'
    result['risk_reward'] = 'Broker ticket targets twice its stop distance before costs. Break-even needs more than one-third wins at exact 2:1 fills; costs and gaps increase the requirement.'
    if len(candles) < 51:
        return {**result, 'reason': 'Need at least 51 completed candles'}
    rows = candles[-51:]
    values = [float(r[k]) for r in rows for k in ('open','high','low','close','timestamp')]
    if not all(math.isfinite(v) and v > 0 for v in values):
        raise ValueError('Invalid candle values')
    if any(r['low']>min(r['open'],r['close']) or r['high']<max(r['open'],r['close']) for r in rows):
        raise ValueError('Inconsistent OHLC prices')
    if any(rows[i]['timestamp'] >= rows[i+1]['timestamp'] or
           rows[i+1]['timestamp']-rows[i]['timestamp'] != 300 for i in range(50)):
        return {**result, 'reason': 'M5 history has a gap or unordered timestamps'}
    close = rows[-1]['close']
    fast = sum(r['close'] for r in rows[-20:])/20
    slow = sum(r['close'] for r in rows[-50:])/50
    prior_high = max(r['high'] for r in rows[-21:-1])
    prior_low = min(r['low'] for r in rows[-21:-1])
    prices=[r['close'] for r in rows]
    deviation=statistics.pstdev(prices[-20:])
    previous_mean=statistics.mean(prices[-21:-1])
    previous_dev=statistics.pstdev(prices[-21:-1])
    current_rsi, prior_rsi=rsi(prices),rsi(prices[:-1])
    ema20,ema50=ema(prices,20),ema(prices,50)
    old_ema20=ema(prices[:-1],20)
    flat=abs(fast-slow)<=max(deviation*.5,close*.00001)
    returns=[b/a-1 for a,b in zip(prices[:-1],prices[1:])]
    compressed=statistics.pstdev(returns[-11:-1])<statistics.pstdev(returns[-31:-11])*.75
    if strategy == 'trend_v1':
        side = 'buy' if close > fast > slow and close > rows[-6]['close'] else 'sell' if close < fast < slow and close < rows[-6]['close'] else 'wait'
    elif strategy == 'breakout_v1':
        side = 'buy' if close > prior_high else 'sell' if close < prior_low else 'wait'
    elif strategy == 'rsi_reversion_v1':
        side='buy' if flat and prior_rsi<30<=current_rsi else 'sell' if flat and prior_rsi>70>=current_rsi else 'wait'
    elif strategy == 'bollinger_reversion_v1':
        side='buy' if flat and prices[-2]<previous_mean-2*previous_dev and close>=fast-2*deviation else 'sell' if flat and prices[-2]>previous_mean+2*previous_dev and close<=fast+2*deviation else 'wait'
    elif strategy == 'ema_pullback_v1':
        side='buy' if ema20>ema50 and prices[-2]<=old_ema20 and close>ema20 else 'sell' if ema20<ema50 and prices[-2]>=old_ema20 and close<ema20 else 'wait'
    else:
        side='buy' if compressed and close>prior_high else 'sell' if compressed and close<prior_low else 'wait'
    conditions={
        'trend_v1':{'long':[close>fast,fast>slow,close>prices[-6]],'short':[close<fast,fast<slow,close<prices[-6]]},
        'breakout_v1':{'long':[close>prior_high],'short':[close<prior_low]},
        'rsi_reversion_v1':{'long':[flat,prior_rsi<30<=current_rsi],'short':[flat,prior_rsi>70>=current_rsi]},
        'bollinger_reversion_v1':{'long':[flat,prices[-2]<previous_mean-2*previous_dev,close>=fast-2*deviation],
                                  'short':[flat,prices[-2]>previous_mean+2*previous_dev,close<=fast+2*deviation]},
        'ema_pullback_v1':{'long':[ema20>ema50,prices[-2]<=old_ema20,close>ema20],'short':[ema20<ema50,prices[-2]>=old_ema20,close<ema20]},
        'squeeze_breakout_v1':{'long':[compressed,close>prior_high],'short':[compressed,close<prior_low]},
    }[strategy]
    return {**result, 'side': side, 'bar': rows[-1]['timestamp'],'conditions':conditions,
            'evidence': {'close': close, 'mean20': fast, 'mean50': slow,
                         'prior20_high': prior_high, 'prior20_low': prior_low,
                         'rsi14':current_rsi,'previous_rsi14':prior_rsi,'ema20':ema20,'ema50':ema50,
                         'flat_regime':flat,'volatility_compressed':compressed,'band_deviation':deviation},
            'reason': f'{side.upper()}: {STRATEGIES[strategy]}. See measured values; WAIT means no qualifying setup.'}

def risk_budget(equity):
    """Grow only the absolute budget with equity, never the risk percentage.

    The existing broker controller independently caps lots, risk and margin.
    If minimum broker volume is too risky, skip rather than round risk upward.
    """
    if not math.isfinite(equity) or equity <= 0:
        raise ValueError('Invalid demo equity')
    return min(25., equity * .0025)

def position_volume(equity, risk_at_centilot, minimum, step):
    """Round down to broker steps; skip when minimum lot exceeds the budget."""
    if not all(math.isfinite(v) and v > 0 for v in (risk_at_centilot, minimum, step)):
        raise ValueError('Missing broker sizing inputs')
    ceiling = min(.01, .01*risk_budget(equity)/risk_at_centilot)
    if ceiling < minimum-1e-10:
        return None
    return round(minimum+math.floor((ceiling-minimum+1e-10)/step)*step, 8)

EVENT_LESSONS = [
    {'topic':'Interest rates', 'mechanism':'Rate surprises change relative yields, borrowing costs and currency demand.',
     'uncertainty':'The surprise versus expectations matters; higher rates do not always strengthen a currency.'},
    {'topic':'War and supply shocks', 'mechanism':'Supply disruption can affect energy prices, inflation expectations and risk appetite.',
     'uncertainty':'Exposure, inventories, policy responses and prior pricing can reverse the initial reaction.'},
    {'topic':'Politics and fiscal policy', 'mechanism':'Elections, tariffs and budgets can change expected cash flows, trade and risk premia.',
     'uncertainty':'Headlines are not causal proof. Separate announcement time, market reaction and later interpretation.'},
]
