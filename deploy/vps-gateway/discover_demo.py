"""Read-only candidate binding discovery; run in the MT5 interactive Windows session."""
import argparse
import hashlib
import json
from pathlib import Path
from broker import existing_terminal
from modules.mt5_bridge import MT5Bridge
from demo_execution import load_demo_config

def discover(api,terminal,symbols):
    existing_terminal(str(terminal))
    if not api.initialize(str(terminal),timeout=5000):raise RuntimeError('Bounded MT5 IPC initialization failed')
    a,t=api.account_info(),api.terminal_info()
    if a is None or t is None or not t.connected or a.trade_mode!=api.ACCOUNT_TRADE_MODE_DEMO:
        raise PermissionError('Connected SDK-verified DEMO account required; live/unknown rejected')
    binding=MT5Bridge().account_record(api,a,t)
    if any(api.symbol_info(symbol) is None for symbol in symbols):raise ValueError('Requested broker symbol unavailable')
    a2,t2=api.account_info(),api.terminal_info()
    if a2 is None or t2 is None or not t2.connected or a2.trade_mode!=api.ACCOUNT_TRADE_MODE_DEMO or MT5Bridge().account_record(api,a2,t2)!=binding:
        raise PermissionError('Account changed during discovery')
    return {'terminal':str(terminal),'account':binding,'symbols':symbols}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--terminal',required=True,type=Path)
    parser.add_argument('--symbol',required=True,action='append')
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError('Preserve existing configuration; choose a new candidate output')
    import MetaTrader5 as api
    cfg=discover(api,args.terminal,args.symbol)
    # Output is a candidate only; it never changes gateway startup, credentials or account.
    with args.output.open('x',encoding='utf-8') as f:json.dump(cfg,f,indent=2)
    try:load_demo_config(args.output)
    except Exception:
        raise ValueError('Candidate written but validation failed; do not activate it')
    print(json.dumps({'candidate':str(args.output),'gateway_id':hashlib.sha256(json.dumps(cfg,sort_keys=True).encode()).hexdigest(),'account':cfg['account'],'activated':False,'orders_sent':0}))
if __name__=='__main__':main()
