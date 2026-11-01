"""Compare registered demo rules without inventing probabilities or weakening risk.

Specific breakout evidence wins an agreeing tie; opposing directions abstain.
An open position stays with its entry strategy, preventing strategy hopping from
changing the exit thesis. Selection is a deterministic policy, not learned edge.
"""
from modules.demo_strategy import STRATEGIES, evaluate


def assess(candles, requested='auto', held_strategy=None):
    if requested != 'auto' and requested not in STRATEGIES:
        raise ValueError('Unknown strategy selection')
    candidates = [evaluate(candles, name) for name in STRATEGIES]
    selected = None
    if held_strategy:
        selected = next((d for d in candidates if d['strategy']==held_strategy), None)
        reason = 'Existing position retains its recorded entry strategy and exit rules.'
    elif requested != 'auto':
        selected = next(d for d in candidates if d['strategy']==requested)
        reason = 'Pinned strategy; alternatives are observed but cannot replace it.'
    else:
        eligible = [d for d in candidates if d['side'] in ('buy','sell')]
        directions = {d['side'] for d in eligible}
        if len(directions) > 1:
            reason = 'Strategies disagree on direction; abstain rather than guess.'
        elif eligible:
            selected = next((d for d in eligible if d['strategy']=='breakout_v1'), eligible[0])
            if len(eligible)==1:
                reason='Only this strategy currently meets its entry conditions.'
            elif selected['strategy']=='breakout_v1':
                reason='A completed range breakout is the more specific agreeing setup.'
            else:
                names=', '.join(d['strategy'] for d in eligible)
                reason=f"Eligible rules agree on {selected['side']}: {names}. Registry priority selects {selected['strategy']}; this is not a profitability ranking."
        else:
            reason = 'No strategy currently meets its entry conditions; continue observing.'
    if selected is None:
        selected = {'strategy':'auto','side':'wait','reason':reason,'evidence':{},
                    'bar':candles[-1]['timestamp'] if candles else None,
                    'profitability':'No validated profitability forecast.'}
    return {**selected, 'selection_reason':reason, 'selection_mode':requested,
            'candidates':candidates,'policy_version':'conditions-v1',
            'selection_limit':'Rule eligibility is not proof that a strategy will be profitable.'}
