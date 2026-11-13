
"""Read-only acceptance of the existing feed -> rules -> Core analysis path.

Never previews/confirms an order, obtains a human consent token, starts services,
changes configuration or retries a mutation. All memory writes stay at Core.
"""
from pathlib import Path
import hashlib
import json
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from modules.trading_desk import Desk, core_market_analysis
from modules.strategy_manager import assess_observation


def check_market_pipeline(pair=None, *, desk=None, analyze=None, native=None):
    if desk is None:
        # Only existing read methods are used; do not open an order database.
        desk=Desk.__new__(Desk)
        desk.root=ROOT
        desk.transport=None
    analyze=analyze or core_market_analysis
    result={'checked_at':time.time(),'ready_for_analysis':False,'execution_ready':False,
            'orders_sent':0,'services_started':False,
            'execution_limit':'A separately reviewed current human Core ticket and all account/risk checks are still required.'}
    try:
        config=desk.configuration()
        result['configuration']={key:config.get(key) for key in
            ('exchange','strategy','timeframe','dry_run','state')}
        if config.get('dry_run') is not True:
            return {**result,'blocked':'non_live_identity_unverified'}
        pairs=desk.api('whitelist').get('whitelist',[])
        pair=pair or next(iter(pairs),None)
        if pair not in pairs:
            return {**result,'blocked':'no_whitelisted_pair'}
        market=desk.market(pair,config)
        profile=hashlib.sha256(json.dumps([
            str((desk.root/'runtime/trading-desk/freqtrade-research.sqlite3').resolve()),
            config.get('exchange')]).encode()).hexdigest()
        observation={'symbol':pair,'venue':config.get('exchange'),'timeframe':config.get('timeframe'),
            'mode':'dry-run','account_scope':'freqtrade-profile-'+profile,
            'source':market.get('source','freqtrade_analyzed_exchange_candles'),
            'received_at':time.time(),'fresh':market.get('fresh') is True,
            'candles':market.get('candles',[])}
        if native is not None:
            observation['native_strategy']=native(observation,config)
            result['native_strategy']=observation['native_strategy']
        local=assess_observation(observation)
        result['market']={'pair':pair,'fresh':market.get('fresh') is True,
            'candles':len(observation['candles']),'source':observation['source']}
        result['rules']={'signal':local['signal'],'complete':local['assessment_complete'],
            'invoked':len(local['candidates']),'abstain_reason':local.get('abstain_reason')}
        core=analyze(observation)
        result['core']={'state':core.get('state'),'authorization':core.get('authorization'),
            'memory':core.get('memory'),'trace_id':core.get('trace_id'),
            'error_type':core.get('error_type')}
        analysis=core.get('analysis') or {}
        result['ready_for_analysis']=bool(
            market.get('fresh') is True and local['assessment_complete']
            and core.get('state')=='analyzed_by_core'
            and (core.get('authorization') or {}).get('allowed') is True
            and analysis.get('assessment_complete') is True
            and analysis.get('execution_authorized') is False
            and (core.get('memory') or {}).get('queued') is True)
        if native is not None and result['native_strategy'].get('state')!='evaluated':
            result['ready_for_analysis']=False
        if not result['ready_for_analysis']:
            result['blocked']='feed_rule_core_or_memory_gate_incomplete'
        return result
    except Exception as exc:
        return {**result,'blocked':'existing_dependency_unavailable','error_type':type(exc).__name__}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('pair',nargs='?')
    parser.add_argument('--native',action='store_true',help='Evaluate installed stopped dry-run strategy without arming entries')
    args=parser.parse_args()
    from modules.freqtrade_native_analysis import evaluate_native
    report=check_market_pipeline(args.pair,native=evaluate_native if args.native else None)
    print(json.dumps(report,indent=2,allow_nan=False))
    raise SystemExit(0 if report['ready_for_analysis'] else 1)

