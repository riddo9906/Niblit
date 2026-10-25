"""Exercise actual Core -> strategy -> policy -> durable paper execution."""
import argparse
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import psutil

def call(port,path,payload=None,timeout=75):
    request=Request(f'http://127.0.0.1:{port}{path}',data=json.dumps(payload).encode() if payload is not None else None,headers={'Content-Type':'application/json'})
    with urlopen(request,timeout=timeout) as response: return json.load(response)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--bundle',type=Path); parser.add_argument('--output',type=Path,required=True); parser.add_argument('--steps',type=int,default=520)
    parser.add_argument('--hold-for-ui',action='store_true')
    args=parser.parse_args(); repo=Path(__file__).resolve().parents[1]; out=args.output.resolve(); out.mkdir(parents=True,exist_ok=True)
    bundle=args.bundle.resolve() if args.bundle else None
    env={k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ('TOKEN','API_KEY','SECRET','PASSWORD','CREDENTIAL'))}
    env.update({'PYTHON_DOTENV_DISABLED':'1','HF_HUB_OFFLINE':'1','TRANSFORMERS_OFFLINE':'1','NIBLIT_HEADLESS':'1','NIBLIT_API_AUTOSTART':'1',
        'NIBLIT_API_PORT':'28500','NIBLIT_TRADING_API_PORT':'28100','NIBLIT_STRATEGY_API_PORT':'28150','NIBLIT_PORT':'28080',
        'NIBLIT_CLOUD_SERVER_PRIMARY_PORT':'28080','NIBLIT_CLOUD_SERVER_URL':'http://127.0.0.1:28080','NIBLIT_CLOUD_BASE_URL':'http://127.0.0.1:28080',
        'NIBLIT_MARKET_DATA_PROVIDER':'replay','NIBLIT_MARKET_DATA_TIMEFRAME':'1h','NIBLIT_TRADING_BACKEND':'paper','NIBLIT_TRADING_MODE':'observe',
        'NIBLIT_TRADING_ALLOW_EXECUTION':'false','NIBLIT_FREQTRADE_ALLOW_EXECUTION':'false','NIBLIT_LLM_PROVIDER':'qwen',
        'NIBLIT_LOW_RESOURCE_MODE':'0','NIBLIT_SKIP_INIT_WAIT':'0','NIBLIT_INIT_WAIT_MAX_SECONDS':'120','QDRANT_URL':'http://127.0.0.1:1'})
    paths={'NIBLIT_MEMORY_PATH':'memory.json','NIBLIT_LLM_CHAT_DB_PATH':'chat.sqlite','FUSED_MEMORY_DB_PATH':'fused.sqlite',
        'NIBLIT_UNIFIED_RUNTIME_STATE':'unified.json','NIBLIT_RUNTIME_LOG_FILE':'runtime.jsonl','NIBLIT_PAPER_STATE_FILE':'paper/account.json',
        'NIBLIT_EXECUTION_DB':'paper/executions.sqlite','NIBLIT_TRADING_CONTROL_FILE':'paper/control.json','NIBLIT_REPLAY_STATE_FILE':'paper/replay.json'}
    env.update({key:str(out/value) for key,value in paths.items()})
    env['NIBLIT_REPLAY_DATA_DIR']=str((bundle/'freqtrade/data') if bundle else repo.parent/'freqtrade/user_data/data/binance/futures')
    env['NIBLIT_WORKSPACE_ROOT']=str(out/'workspace'); (out/'workspace').mkdir(exist_ok=True)
    processes=[]; logs=[]; report={'checks':{},'source':'packaged' if bundle else 'source','output':str(out)}
    def launch(name,command,cli=False):
        stream=(out/(name+'.log')).open('w',encoding='utf-8'); logs.append(stream)
        process=subprocess.Popen([str(x) for x in command],cwd=str(out),env=env,stdin=subprocess.PIPE if cli else subprocess.DEVNULL,
            stdout=stream,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        processes.append(process); return process
    def stop(process,graceful=False):
        descendants=psutil.Process(process.pid).children(recursive=True) if process.poll() is None else []
        if graceful and process.poll() is None:
            try: process.communicate(input=b'exit\n',timeout=30)
            except (subprocess.TimeoutExpired,OSError): pass
        for child in reversed(descendants):
            try: child.terminate()
            except psutil.NoSuchProcess: pass
        if process.poll() is None:
            process.terminate()
            try: process.wait(timeout=10)
            except subprocess.TimeoutExpired: process.kill()
        for child in descendants:
            try: child.wait(timeout=10)
            except (psutil.NoSuchProcess,psutil.TimeoutExpired):
                try: child.kill()
                except psutil.NoSuchProcess: pass
    def wait(port,identity=None):
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            try:
                data=call(port,'/health',timeout=2)
                if identity is None or data.get('service')==identity: return data
            except Exception: pass
            time.sleep(.5)
        raise RuntimeError(f'Service {port} did not become ready')
    core_command=[bundle/'niblit.exe','--headless','--cli'] if bundle else [repo/'niblit-env/Scripts/python.exe',repo/'main.py','--headless','--cli']
    lean_command=[bundle/'lean-algos/niblit-lean-algos.exe'] if bundle else [repo.parent/'niblit-lean-algos/.venv/Scripts/python.exe',repo.parent/'niblit-lean-algos/main.py']
    cloud_command=[bundle/'cloud/niblit-cloud.exe'] if bundle else [repo/'dist/testing-20261025-ready/niblit/cloud/niblit-cloud.exe']
    try:
        for port in (28500,28100,28150,28080):
            with socket.socket() as probe: probe.bind(('127.0.0.1',port))
        cloud=launch('cloud',cloud_command); wait(28080)
        lean=launch('runtime',lean_command); wait(28100)
        report['checks']['actual_freqtrade_worker']=wait(28150,'niblit-freqtrade-strategy').get('freqtrade_version') is not None
        core=launch('core',core_command,True); wait(28500,'niblit')
        state=call(28500,'/api/trading/paper/status'); initial=state['account']['balances'][0]['free']
        report['strategy_provenance']={k:state['strategy'][k] for k in ('strategy','dataset','data_sha256','data_start','data_end','cursor','source')}
        call(28500,'/api/trading/paper/control',{'enabled':True})
        request={'action':'enter_long','stake_amount':100,'decision_id':'architecture-entry'}
        entry=call(28500,'/api/trading/paper/decision',request)
        assert entry['success'],entry
        after=call(28500,'/api/trading/paper/status')['account']
        report['checks']['core_to_paper_fill']=entry['execution_state']=='confirmed_open' and after['balances'][0]['used']==100
        report['checks']['cash_and_entry_fee']=math.isclose(after['balances'][0]['free'],initial-100.1,abs_tol=1e-7)
        report['checks']['entry_position_includes_fee']=math.isclose(after['positions'][0]['profit_amount'],-.1,abs_tol=1e-9)
        duplicate=call(28500,'/api/trading/paper/decision',request)
        report['checks']['persistent_idempotency']=duplicate.get('duplicate') is True
        stop(core,True); stop(lean)
        lean=launch('runtime-restart',lean_command); wait(28100)
        core=launch('core-restart',core_command,True); wait(28500,'niblit')
        recovered=call(28500,'/api/trading/paper/status')
        report['checks']['paper_control_recovered']=recovered['mode']=='paper'
        report['checks']['open_position_recovered']=len([p for p in recovered['account']['positions'] if p['status']=='open'])==1
        report['checks']['balance_recovered']=math.isclose(recovered['account']['balances'][0]['free'],initial-100.1,abs_tol=1e-7)
        closed=call(28500,'/api/trading/paper/decision',{'action':'exit_long','stake_amount':100,'decision_id':'architecture-exit'})
        assert closed['success'],closed
        report['checks']['close_and_fees']=closed['execution_state']=='confirmed_closed' and math.isclose(call(28500,'/api/trading/paper/status')['account']['realized_pnl'],-.2,abs_tol=1e-7)
        advice=call(28500,'/api/trading/paper/advice',{'action':'enter_long','stake_amount':100},timeout=60)
        report['checks']['real_local_ai_advice']=type(advice.get('approved')) is bool and advice.get('source')=='local_cloud_model'
        report['ai_advice']=advice
        curve=[]; outcome_counts={}; ai_gate_checked=False
        for index in range(args.steps):
            step=call(28500,'/api/trading/paper/step',{'stake_amount':100,'use_ai':not ai_gate_checked})
            if step['outcome'].get('advice'):
                ai_gate_checked=type(step['outcome']['advice'].get('approved')) is bool
                report['strategy_ai_vote']=step['outcome']['advice']
            status=step['outcome']['status']; outcome_counts[status]=outcome_counts.get(status,0)+1
            curve.append(step['portfolio']['account']['equity'])
            if step['observation']['done']: break
        final=call(28500,'/api/trading/paper/status')
        trades=[p for p in final['account']['positions'] if p['status']=='closed' and p.get('metadata',{}).get('decision_id','').startswith('replay:')]
        report['checks']['strategy_produced_trades']=len(trades)>0
        report['checks']['strategy_ai_gate_exercised']=ai_gate_checked
        report['checks']['ledger_conservation']=math.isclose(final['account']['equity'],final['account']['initial_capital']+final['account']['realized_pnl']+sum((p['current_price']-p['entry_price'])*p['quantity'] for p in final['account']['positions'] if p['status']=='open')-sum(p['metadata'].get('entry_fee',0) for p in final['account']['positions'] if p['status']=='open'),abs_tol=1e-6)
        call(28500,'/api/trading/paper/control',{'enabled':False})
        try: call(28500,'/api/trading/paper/decision',{'action':'enter_long','stake_amount':100}); blocked=False
        except HTTPError as exc: blocked=exc.code==409
        report['checks']['observe_blocks_execution']=blocked
        report['outcomes']=outcome_counts; report['closed_strategy_trades']=len(trades)
        report['final_account']=final['account']; report['equity_curve']=curve
        peak=initial; drawdown=0
        for equity in curve:
            peak=max(peak,equity); drawdown=max(drawdown,(peak-equity)/peak)
        report['performance']={'initial_capital':initial,'net_realized_pnl':final['account']['realized_pnl'],
            'equity':final['account']['equity'],'fees':final['account']['fees'],'maximum_drawdown_fraction':drawdown,
            'last_recorded_close':final['strategy']['as_of'],'replayed_candles':len(curve)}
        report['performance_target']={'monthly_net_target':100,'status':'not_forward_validated','test':'historical strategy replay with first eligible signal gated by the real local AI','guaranteed':False}
        if args.hold_for_ui:
            (out/'verification.json').write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
            print('UI verification ready; create release-ui file to stop owned services',flush=True)
            deadline=time.monotonic()+600
            while time.monotonic()<deadline and not (out/'release-ui').exists(): time.sleep(1)
    except Exception as exc:
        report['error']=str(exc)
        if isinstance(exc,HTTPError): report['error_detail']=exc.read().decode(errors='replace')
    finally:
        for process in reversed(processes):
            if process.poll() is None: stop(process,False)
        for stream in logs: stream.close()
        (out/'verification.json').write_text(json.dumps(report,indent=2,default=str),encoding='utf-8')
    print(json.dumps({'checks':report['checks'],'error':report.get('error'),'closed_strategy_trades':report.get('closed_strategy_trades')},indent=2))
    return 0 if not report.get('error') and all(report['checks'].values()) else 1

if __name__=='__main__': raise SystemExit(main())
