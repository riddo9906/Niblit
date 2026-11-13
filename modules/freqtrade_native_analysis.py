"""Read-only invocation of the installed Freqtrade catalog; no bot/exchange/DB."""
import json
import subprocess
from modules.strategy_manager import assess_observation

RUNNER = r"""
import sys,json,hashlib
from pathlib import Path
sys.path.insert(0,'/freqtrade/user_data/strategies')
import fcntl
lock=open('/tmp/niblit-native-analysis.lock','a')
fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
import pandas as pd
from NiblitLabManager import NiblitLabManager
body=json.load(sys.stdin)
strategy=NiblitLabManager({'dry_run':True,'stake_currency':'USDT'})
df=pd.DataFrame(body['candles'])
df['date']=pd.to_datetime(df.pop('timestamp'),unit='s',utc=True)
result=strategy.analyze_ticker(df,{'pair':body['symbol']})
last=result.iloc[-1]
flags={k:bool(pd.notna(last.get(k)) and last.get(k)==1) for k in ('enter_long','enter_short','exit_long','exit_short')}
conflict=flags['enter_long'] and flags['enter_short']
signal='ABSTAIN' if conflict else 'BUY' if flags['enter_long'] else 'SELL' if flags['enter_short'] else 'HOLD'
print(json.dumps({'state':'evaluated','strategy':'NiblitLabManager','signal':signal,'flags':flags,
 'rows':len(result),'timestamp':last['date'].timestamp(),'execution_authorized':False,
 'strategy_sha256':hashlib.sha256(Path('/freqtrade/user_data/strategies/NiblitLabManager.py').read_bytes()).hexdigest()}))
"""

def evaluate_native(observation, config, *, run=subprocess.run):
    base={'state':'unavailable','strategy':config.get('strategy'),'signal':'ABSTAIN','execution_authorized':False}
    if config.get('dry_run') is not True or config.get('state')!='stopped':
        return {**base,'reason':'requires_stopped_dry_run_profile'}
    if config.get('strategy')!='NiblitLabManager' or config.get('timeframe')!=observation.get('timeframe') or observation.get('mode')!='dry-run':
        return {**base,'reason':'unsupported_or_mismatched_profile'}
    assessment=assess_observation(observation)
    if not assessment['assessment_complete']:
        return {**base,'reason':assessment.get('abstain_reason','observation_rejected')}
    try:
        response=run(['docker','exec','-i','freqtrade','python','-c',RUNNER],
            input=json.dumps({'symbol':observation['symbol'],'candles':observation['candles']},allow_nan=False),
            capture_output=True,text=True,timeout=45,check=True)
        report=json.loads(response.stdout)
        if (report.get('state')!='evaluated' or report.get('strategy')!=config['strategy'] or
            report.get('execution_authorized') is not False or report.get('signal') not in ('BUY','SELL','HOLD','ABSTAIN') or
            report.get('rows')!=len(observation['candles']) or report.get('timestamp')!=observation['candles'][-1]['timestamp']):
            raise ValueError('native_analysis_contract_mismatch')
        return report
    except Exception as exc:
        return {**base,'state':'failed','error_type':type(exc).__name__}


class NativeAnalysisCache:
    """One bounded analysis job; polling never queues a backlog or reuses other bars."""
    def __init__(self, evaluate=evaluate_native, ttl=30):
        import threading
        self.evaluate=evaluate
        self.ttl=ttl
        self.lock=threading.Lock()
        self.results={}
        self.active=None

    def snapshot(self, observation, config):
        import hashlib,time,threading,copy
        base={'state':'pending','signal':'ABSTAIN','execution_authorized':False}
        if observation.get('fresh') is not True:
            return {**base,'state':'unavailable','reason':'stale_market'}
        binding={k:v for k,v in observation.items() if k not in ('received_at','native_strategy')}
        key=hashlib.sha256(json.dumps([binding,config],sort_keys=True,allow_nan=False).encode()).hexdigest()
        with self.lock:
            cached=self.results.get(key)
            if cached and time.monotonic()-cached[0]<self.ttl:
                return copy.deepcopy(cached[1])
            if self.active is not None:
                return {**base,'reason':'analysis_in_progress' if self.active==key else 'analysis_busy_no_queue'}
            self.active=key
        obs,cfg=copy.deepcopy(observation),copy.deepcopy(config)
        def work():
            try: result=self.evaluate(obs,cfg)
            except Exception as exc:result={**base,'state':'failed','error_type':type(exc).__name__}
            with self.lock:
                if len(self.results)>=16:self.results.pop(next(iter(self.results)))
                self.results[key]=(time.monotonic(),result)
                self.active=None
        threading.Thread(target=work,name='NativeStrategyAnalysis',daemon=True).start()
        return base
