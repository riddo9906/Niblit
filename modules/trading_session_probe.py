"""Explicit, non-delivering broker checks for the packaged executable.

This command never constructs Core sessions, grants permission, creates a ticket,
confirms an order, starts an engine or sends an order. Credentials stay local.
"""
import argparse
import json
import time
from pathlib import Path


def check(root,mt5_symbol='EURUSD',freqtrade_symbol='BTC/USDT:USDT'):
    from modules.mt5_bridge import MT5Bridge
    from modules.mt5_orders import DemoOrders
    from modules.trading_desk import Desk
    from modules.trading_session_adapters import MT5SessionAdapter,FreqtradeSessionAdapter
    from modules.core_trading_sessions import CoreTradingSessions
    root=Path(root).resolve()
    if not (root/'niblit_core.py').is_file():raise ValueError('Select the existing private runtime source root')
    out={'checked_at':time.time(),'broker_orders':0,'sessions_activated':0,
         'scope':'Read-only provider observations and MT5 order_check only; no preview/confirm/order_send'}
    validator=CoreTradingSessions.__new__(CoreTradingSessions);validator.clock=time.time
    try:
        bridge=MT5Bridge();orders=DemoOrders.__new__(DemoOrders);orders.bridge=bridge
        orders.path=root/'runtime/trading-desk/mt5-orders.sqlite3'
        adapter=MT5SessionAdapter(bridge,orders)
        for attempt in range(4):
            s=adapter.snapshot(mt5_symbol)
            if s['quote'].get('fresh'):break
            time.sleep(1)
        validator.validate_snapshot(s,mt5_symbol)
        out['mt5']={'observations_valid':True,'account':s['account'],'environment':s['environment'],
            'symbol':s['symbol'],'candles':len(s['candles']),'positions':len(s['positions']),
            'fresh':s['quote']['fresh'],'execution_blockers':['Explicit bounded activation required']}
        if orders.path.is_file():
            try:
                r=orders.inspect({'action':'open','symbol':mt5_symbol,'side':'buy','volume':.01,
                    'account_identity':s['account'],'position_ticket':None,'max_stop_risk':min(25.,s['equity']*.0025)})
                out['mt5']['non_delivering_preflight']={'accepted':True,**{k:r.get(k) for k in
                    ('volume','estimated_stop_risk','stop_loss','take_profit','margin_after','mode')}}
            except Exception as exc:
                out['mt5']['non_delivering_preflight']={'accepted':False,'error_type':type(exc).__name__}
                out['mt5']['execution_blockers'].append('Native non-delivering preflight did not pass')
        else:out['mt5']['preflight']='Original ticket ledger absent; no file created'
    except Exception as exc:
        out['mt5']={'observations_valid':False,'error_type':type(exc).__name__,'reason':str(exc)[:180]}
    try:
        desk=Desk.__new__(Desk);desk.root=root;desk.transport=None;desk.market_rules=None
        s=FreqtradeSessionAdapter(desk).snapshot(freqtrade_symbol)
        validator.validate_snapshot(s,freqtrade_symbol)
        blockers=['Explicit bounded activation required']
        if s['configuration'].get('strategy')!='NiblitCoreManaged':blockers.append('Core-managed native strategy must be selected before a session')
        if s['configuration']['state']!='running':blockers.append('Native engine is stopped')
        if len(s['positions'])>=s['configuration']['max_open_trades']:blockers.append('All configured position slots occupied')
        if s['protections'].get('fee') is None:blockers.append('Native fee is unreported; explicit verified fee required')
        out['freqtrade']={'observations_valid':True,'account':s['account'],'environment':s['environment'],
            'symbol':s['symbol'],'candles':len(s['candles']),'positions':len(s['positions']),
            'engine_state':s['configuration']['state'],'fresh':s['quote']['fresh'],
            'native_protections':s['protections'],'execution_blockers':blockers}
    except Exception as exc:
        out['freqtrade']={'observations_valid':False,'error_type':type(exc).__name__,'reason':str(exc)[:180]}
    return out


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_root',type=Path)
    parser.add_argument('--mt5-symbol',default='EURUSD')
    parser.add_argument('--freqtrade-symbol',default='BTC/USDT:USDT')
    args=parser.parse_args(argv)
    report=check(args.source_root,args.mt5_symbol,args.freqtrade_symbol)
    print(json.dumps(report,indent=2,allow_nan=False))
    return 0 if all(report.get(k,{}).get('observations_valid') for k in ('mt5','freqtrade')) else 1
