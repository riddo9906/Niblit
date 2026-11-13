"""Compare registered demo rules without inventing probabilities or weakening risk.

Specific breakout evidence wins an agreeing tie; opposing directions abstain.
An open position stays with its entry strategy, preventing strategy hopping from
changing the exit thesis. Selection is a deterministic policy, not learned edge.
"""
from modules.demo_strategy import STRATEGIES, evaluate


def assess(candles, requested='auto', held_strategy=None):
    if requested != 'auto' and requested not in STRATEGIES:
        raise ValueError('Unknown strategy selection')
    candidates = []
    failures = []
    for name in STRATEGIES:
        try:
            candidate = evaluate(candles, name)
            if (not isinstance(candidate, dict) or candidate.get('strategy') != name
                    or candidate.get('side') not in ('buy', 'sell', 'wait')):
                raise ValueError('Invalid strategy result contract')
            candidates.append(candidate)
        except Exception as exc:
            # A failed evaluator must not hide opposition or kill the observer.
            # Keep the failure visible without exposing exception payloads.
            failure = {'strategy': name, 'error_type': type(exc).__name__}
            failures.append(failure)
            candidates.append({'strategy': name, 'side': 'wait', 'status': 'failed',
                'reason': 'Strategy assessment unavailable; consensus cannot be established.',
                'error_type': failure['error_type'], 'evidence': {}})
    selected = None
    if failures:
        reason = 'Strategy assessment failed; abstain until all registered rules can be compared.'
    elif held_strategy and held_strategy not in STRATEGIES:
        reason = 'Recorded entry strategy is unavailable; abstain without transferring position ownership.'
    elif held_strategy:
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
            'candidates':candidates,'policy_version':'conditions-v2',
            'assessment_complete':not failures and (not held_strategy or held_strategy in STRATEGIES),
            'strategy_failures':failures,
            'selection_limit':'Rule eligibility is not proof that a strategy will be profitable.'}


def assess_observation(observation, *, now=None):
    """Validate a point-in-time M5 observation and reuse the existing registry.

    Input is evidence, never an execution grant. Replay uses an explicit replay
    clock and stays labeled. Account scope is a non-secret producer identifier,
    not proof of broker authentication.
    """
    import hashlib
    import json
    import math
    import time

    result = {'signal': 'ABSTAIN', 'side': 'wait', 'execution_authorized': False,
              'analysis_only': True, 'candidates': [], 'assessment_complete': False,
              'regime': 'unknown', 'policy_version': 'observation-v1'}
    if not isinstance(observation, dict):
        return {**result, 'abstain_reason': 'missing_observation'}
    identity = {key: observation.get(key) for key in
                ('symbol', 'venue', 'timeframe', 'mode', 'account_scope', 'source')}
    result['observation'] = identity
    if not all(isinstance(value, str) and 0 < len(value) <= 160 for value in identity.values()):
        return {**result, 'abstain_reason': 'missing_market_identity'}
    if identity['mode'] not in ('observe', 'paper', 'demo', 'dry-run', 'replay'):
        return {**result, 'abstain_reason': 'unsupported_mode'}
    if identity['timeframe'] != '5m':
        return {**result, 'abstain_reason': 'unsupported_timeframe'}
    candles = observation.get('candles')
    if not isinstance(candles, list) or not 51 <= len(candles) <= 500:
        return {**result, 'abstain_reason': 'insufficient_or_unbounded_history'}
    try:
        rows = []
        for candle in candles:
            row = {}
            for key in ('timestamp', 'open', 'high', 'low', 'close'):
                value = candle[key]
                if isinstance(value, bool):
                    raise ValueError('Boolean candle value')
                row[key] = float(value)
                if not math.isfinite(row[key]) or row[key] <= 0:
                    raise ValueError('Invalid candle value')
            if row['low'] > min(row['open'], row['close']) or row['high'] < max(row['open'], row['close']):
                raise ValueError('Inconsistent OHLC')
            rows.append(row)
        if any(b['timestamp']-a['timestamp'] != 300 for a,b in zip(rows, rows[1:])):
            return {**result, 'abstain_reason': 'unordered_or_gapped_history'}
        wall_clock = time.time() if now is None else now
        clock = observation.get('as_of') if identity['mode'] == 'replay' else wall_clock
        received = observation.get('received_at')
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or
               not math.isfinite(value) for value in (clock, received)):
            raise ValueError('Explicit finite UTC epoch timestamps required')
        # Replay cannot claim observations or receipts from a future wall clock.
        completed_at = rows[-1]['timestamp'] + 300
        age = clock-completed_at
        if clock > wall_clock+5 or received > clock+5 or received < completed_at:
            return {**result, 'abstain_reason': 'invalid_observation_time'}
        if observation.get('fresh') is not True or not 0 <= age <= 600:
            return {**result, 'abstain_reason': 'stale_or_unverified_market'}
    except (KeyError, TypeError, ValueError, OverflowError):
        return {**result, 'abstain_reason': 'invalid_market_data'}

    evidence = observation.get('market_evidence')
    comparison = (assess_with_context(rows,observation.get('market_context'))
                  if isinstance(evidence,dict) else assess(rows))
    if isinstance(evidence,dict):
        snapshot_id=evidence.get('M5',{}).get('snapshot_id')
        for candidate in comparison['candidates']:
            candidate['snapshot_id']=snapshot_id
            candidate['evidence_policy']='shared_observations_advisory_no_extra_vote'
    result.update(comparison)
    result['execution_authorized'] = False
    result['analysis_only'] = True
    result['observation'] = {**identity, 'bar': rows[-1]['timestamp'],
                             'completed_at': completed_at, 'received_at': received,
                             'as_of': clock, 'age_seconds': age}
    # Evidence is retained even when a registered evaluator failed.
    for candidate in result['candidates']:
        candidate['invoked'] = True
        candidate['status'] = ('failed' if candidate.get('status') == 'failed'
                               else 'succeeded' if candidate.get('bar') is not None else 'abstained')
        candidate['eligible'] = candidate['status'] == 'succeeded' and candidate['side'] in ('buy', 'sell')
    if not result['assessment_complete']:
        result.update(signal='ABSTAIN', abstain_reason='incomplete_strategy_comparison')
    elif result['side'] in ('buy', 'sell'):
        result['signal'] = result['side'].upper()
    else:
        directions = {c['side'] for c in result['candidates'] if c['side'] in ('buy', 'sell')}
        result['signal'] = 'ABSTAIN' if len(directions) > 1 else 'HOLD'
        result['abstain_reason'] = 'strategy_disagreement' if len(directions) > 1 else 'no_qualifying_setup'
    evidence = next((c.get('evidence', {}) for c in result['candidates'] if c.get('evidence')), {})
    if evidence:
        result['regime'] = ('range' if evidence.get('flat_regime') else
                            'trend_up' if evidence.get('mean20', 0) > evidence.get('mean50', 0) else 'trend_down')
        result['regime_basis'] = 'Existing rule mean/flat-regime measurements; not a calibrated forecast.'
    material = {'identity': identity, 'candles': rows, 'comparison': comparison}
    result['observation_id'] = hashlib.sha256(json.dumps(material, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return result


# Each rule retains its existing M5 trigger. Context is advisory until a
# separately evaluated policy assigns it a veto or confirmation role.
CONTEXT_TIMEFRAMES = {
    'trend_v1': ('M15', 'H1', 'H4', 'D1'),
    'breakout_v1': ('M15', 'M30', 'H1', 'H4'),
    'rsi_reversion_v1': ('M1', 'M15', 'H1'),
    'bollinger_reversion_v1': ('M15', 'H1', 'D1'),
    'ema_pullback_v1': ('M1', 'M15', 'H1', 'H4'),
    'squeeze_breakout_v1': ('M15', 'M30', 'H4', 'W1'),
}


def assess_with_context(candles, context=None):
    """Attach point-in-time context to the six votes without adding votes."""
    decision = assess(candles, 'auto')
    if not context:
        return decision
    for candidate in decision['candidates']:
        frames = CONTEXT_TIMEFRAMES[candidate['strategy']]
        candidate['context'] = {
            frame: context.get(frame, {'status': 'missing'}) for frame in frames
        }
        candidate['execution_timeframe'] = 'M5'
        candidate['context_policy'] = 'advisory'
        opposing = {'buy': 'down', 'sell': 'up'}.get(candidate['side'])
        candidate['context_contradictions'] = [
            frame for frame in frames
            if opposing and context.get(frame, {}).get('trend') == opposing
        ]
    return decision


def replay_context(native_bars, decision_times):
    """Replay closed native bars in the supplied broker clock, without fills."""
    from modules.mt5_bridge import TIMEFRAME_SECONDS, summarize_completed
    for as_of in decision_times:
        # Filter before validating so later malformed rows cannot affect history.
        closed = {
            frame: [row for row in native_bars.get(frame, ())
                    if row['time'] + seconds <= as_of]
            for frame, seconds in TIMEFRAME_SECONDS.items()
        }
        context = {frame:summarize_completed(rows,frame,as_of) for frame, rows in closed.items()}
        execution = [{'timestamp':row['time'], **{k:row[k] for k in ('open','high','low','close')}}
                     for row in closed['M5'][-200:]]
        decision = assess_with_context(execution,context)
        recent = execution[-51:]
        if (len(recent) < 51 or context['M5']['status'] != 'ready'
                or any(b['timestamp']-a['timestamp'] != 300 for a,b in zip(recent,recent[1:]))):
            decision.update(side='wait',assessment_complete=False,
                            selection_reason='Incomplete replay M5 evidence')
        yield {'as_of':as_of,'input_m5_timestamps':[row['timestamp'] for row in execution],
               'context':context,'assessment':decision,'execution_enabled':False}
