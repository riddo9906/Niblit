"""Deterministic funded preflight. A PASS never grants broker authority."""
from decimal import Decimal, InvalidOperation


def decimal(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError('Required finite decimal')
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError('Required finite decimal') from exc
    if not result.is_finite():
        raise ValueError('Required finite decimal')
    return result


BINDING = ('broker', 'terminal_id', 'login', 'server', 'environment', 'currency')
MAXIMUMS = {
    'risk_cash': 'max_risk_cash', 'risk_fraction': 'max_risk_fraction',
    'realized_loss': 'max_realized_loss', 'equity_loss': 'max_equity_loss',
    'drawdown': 'max_drawdown', 'positions_after': 'max_positions',
    'aggregate_risk': 'max_aggregate_risk', 'symbol_exposure': 'max_symbol_exposure',
    'correlated_exposure': 'max_correlated_exposure',
    'margin_fraction': 'max_margin_fraction', 'spread_points': 'max_spread_points',
    'slippage_points': 'max_slippage_points', 'consecutive_losses': 'max_consecutive_losses',
    'daily_entries_after': 'max_daily_entries', 'orders_in_window_after': 'max_order_frequency',
    'volume': 'max_volume',
}
MINIMUMS = {'free_margin_after': 'min_free_margin', 'net_reward_risk': 'min_net_reward_risk'}
BREACHES = {
    'emergency_stop': 'EMERGENCY_STOP',
    'uncertain_delivery': 'RECONCILIATION_REQUIRED',
    'duplicate_risk': 'RECONCILIATION_REQUIRED',
    'unreconciled_position': 'RECONCILIATION_REQUIRED',
    'protection_failure': 'RECONCILIATION_REQUIRED',
    'repeated_rejections': 'ENTRY_SUSPENDED',
}


def evaluate(policy, evidence, *, now, breaker='NORMAL'):
    """Evaluate trusted Core inputs using account-currency decimals."""
    reasons = []
    if not policy:
        return {'decision':'REJECT','reasons':['policy_missing'],'execution_enabled':False,
                'account':evidence.get('account', {}),'symbol':evidence.get('symbol'),
                'strategy':evidence.get('strategy'),'action':evidence.get('action'),'evaluated_at':now}
    binding = evidence.get('account', {})
    expected = policy.get('account', {})
    if (binding.get('environment') != 'live' or not evidence.get('identity_verified') or
            any(not binding.get(key) or binding[key] != expected.get(key) for key in BINDING)):
        reasons.append('account_binding_mismatch')
    if not policy.get('version') or not policy.get('authorization_id'):
        reasons.append('unversioned_authorization')
    try:
        if not decimal(policy.get('starts')) <= decimal(now) < decimal(policy.get('expires')):
            reasons.append('outside_authorization_window')
    except ValueError:
        reasons.append('invalid_authorization_window')
    if policy.get('revoked') is not False:
        reasons.append('authorization_revoked_or_unknown')
    if evidence.get('symbol') not in policy.get('symbols', ()) or evidence.get('strategy') not in policy.get('strategies', ()):
        reasons.append('outside_strategy_or_symbol_scope')
    if evidence.get('action') != 'open':
        reasons.append('action_not_supported')
    for flag in ('connected','quote_fresh','contract_verified','protective_stop',
                 'consensus_complete','context_eligible','costs_complete'):
        if evidence.get(flag) is not True:
            reasons.append(flag+'_required')
    for flag in BREACHES:
        if evidence.get(flag) is not False:
            reasons.append(flag+'_not_clear')
    if breaker != 'NORMAL':
        reasons.append('breaker_'+breaker.lower())
    limits = policy.get('limits', {})
    measured = {}
    for rule, keys in (('maximum', MAXIMUMS), ('minimum', MINIMUMS)):
        for field, limit in keys.items():
            try:
                value, threshold = decimal(evidence.get(field)), decimal(limits.get(limit))
                if threshold < 0 or (rule == 'maximum' and value < 0):
                    raise ValueError('Invalid signed quantity')
                measured[field] = str(value)
                if (rule == 'maximum' and value > threshold) or (rule == 'minimum' and value < threshold):
                    reasons.append(limit+'_breach')
            except ValueError:
                reasons.append(field+'_unverified')
    return {'decision':'REJECT' if reasons else 'PASS','reasons':reasons,
            'account':binding,'policy_version':policy.get('version'),
            'authorization_id':policy.get('authorization_id'),'symbol':evidence.get('symbol'),
            'strategy':evidence.get('strategy'),'action':evidence.get('action'),
            'evaluated_at':now,'measurements':measured,'execution_enabled':False}


def breaker_after(current, evidence, decision):
    """Critical states latch. Monitoring never clears an unresolved incident."""
    triggered = [state for flag, state in BREACHES.items() if evidence.get(flag) is True]
    if current == 'EMERGENCY_STOP' or 'EMERGENCY_STOP' in triggered:
        return 'EMERGENCY_STOP'
    if current == 'RECONCILIATION_REQUIRED' or 'RECONCILIATION_REQUIRED' in triggered:
        return 'RECONCILIATION_REQUIRED'
    if current == 'RECOVERY_PENDING':
        return current
    return 'ENTRY_SUSPENDED' if decision['reasons'] else 'NORMAL'


def net_costs(gross_target, gross_stop, *, volume, currency, schedule, now):
    """Normalize explicitly bounded charges; unknowns never become zero."""
    unknown = {'status':'UNKNOWN','costs_complete':False,'net_target':None,'net_stop':None}
    if not schedule or schedule.get('currency') != currency or not schedule.get('source'):
        return unknown
    try:
        if not decimal(schedule['verified_at']) <= decimal(now) < decimal(schedule['expires']):
            return {**unknown,'status':'STALE'}
        lots = decimal(volume)
        target, stop = decimal(gross_target), decimal(gross_stop)
        commission = max(decimal(schedule['minimum_commission']),
                         decimal(schedule['round_trip_per_lot'])*lots)
        financing = decimal(schedule['financing_upper_bound'])
        slippage = decimal(schedule['slippage_upper_bound'])
        if lots <= 0 or stop >= 0 or min(commission, financing, slippage,
                                       decimal(schedule['minimum_commission']),
                                       decimal(schedule['round_trip_per_lot'])) < 0:
            return unknown
    except (ValueError, KeyError):
        return unknown
    total = commission+financing+slippage
    return {'status':'ESTIMATED','costs_complete':True,'currency':currency,
            'commission':str(commission),'financing':str(financing),'slippage':str(slippage),
            'net_target':str(target-total),'net_stop':str(stop-total),
            'net_reward_risk':str((target-total)/(-stop+total)),
            'source':schedule['source'],'version':schedule.get('version')}
