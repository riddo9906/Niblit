import json,time,subprocess
from types import SimpleNamespace
import pytest
from modules.freqtrade_native_analysis import evaluate_native
from test_market_pipeline_readiness import check,fixture_desk,analyzed
CFG=dict(dry_run=True,state="stopped",strategy="NiblitLabManager",timeframe="5m")
def observation():
    end=int(time.time()//300)*300
    return dict(symbol="BTC/USDT:USDT",venue="binance",timeframe="5m",mode="dry-run",account_scope="test",source="fixture",fresh=True,received_at=time.time(),candles=[dict(timestamp=end-(60-i)*300,open=100,high=102,low=99,close=101,volume=1) for i in range(60)])
@pytest.mark.parametrize("signal",["BUY","SELL","HOLD","ABSTAIN"])
def test_native_contract_never_grants_permission(signal):
    obs=observation();calls=[]
    def run(args,**kw):
        calls.append(args);assert args[:5]==['docker','exec','-i','freqtrade','python']
        assert json.loads(kw['input'])['candles']==obs['candles']
        return SimpleNamespace(stdout=json.dumps(dict(state='evaluated',strategy='NiblitLabManager',signal=signal,rows=60,timestamp=obs['candles'][-1]['timestamp'],execution_authorized=False)))
    result=evaluate_native(obs,CFG,run=run)
    assert result['signal']==signal and result['execution_authorized'] is False and len(calls)==1
@pytest.mark.parametrize('change',[dict(dry_run=False),dict(state='running'),dict(strategy='Other'),dict(timeframe='1h')])
def test_denied_profile_never_invokes(change):
    def forbidden(*a,**kw):pytest.fail('Unexpected invocation')
    assert evaluate_native(observation(),dict(CFG,**change),run=forbidden)['signal']=='ABSTAIN'
def test_invalid_and_stale_data_do_not_invoke():
    def forbidden(*a,**kw):pytest.fail('Unexpected invocation')
    for obs in ({},dict(observation(),fresh=False)):
        assert evaluate_native(obs,CFG,run=forbidden)['state']=='unavailable'
@pytest.mark.parametrize('kind',['timeout','json','identity','authority'])
def test_failure_is_visible_without_retry(kind):
    obs=observation();calls=[]
    def run(*a,**kw):
        calls.append(True)
        if kind=='timeout':raise subprocess.TimeoutExpired('docker',45)
        if kind=='json':return SimpleNamespace(stdout='not json')
        return SimpleNamespace(stdout=json.dumps(dict(state='evaluated',strategy='NiblitLabManager',signal='BUY',rows=60,timestamp=obs['candles'][-1]['timestamp']-(300 if kind=='identity' else 0),execution_authorized=kind=='authority')))
    result=evaluate_native(obs,CFG,run=run)
    assert result['state']=='failed' and result['signal']=='ABSTAIN' and len(calls)==1
def test_native_failure_keeps_core_observation(tmp_path):
    seen=[]
    def core(obs):seen.append(obs);return analyzed(obs)
    result=check.check_market_pipeline(desk=fixture_desk(tmp_path),analyze=core,native=lambda *a:dict(state='failed',signal='ABSTAIN',execution_authorized=False))
    assert seen[0]['native_strategy']['state']=='failed'
    assert result['core']['state']=='analyzed_by_core' and not result['ready_for_analysis']
    assert result['rules']['invoked']==6 and result['orders_sent']==0


def test_dashboard_cache_single_flight_and_identity():
    import threading,time
    from modules.freqtrade_native_analysis import NativeAnalysisCache
    started=threading.Event();release=threading.Event();calls=[]
    def evaluate(obs,cfg):
        calls.append(obs['symbol']);started.set();release.wait(5)
        return dict(state='evaluated',signal='HOLD',execution_authorized=False)
    cache=NativeAnalysisCache(evaluate);obs=observation()
    assert cache.snapshot(obs,CFG)['state']=='pending'
    assert started.wait(2)
    for _ in range(5):assert cache.snapshot(obs,CFG)['state']=='pending'
    assert cache.snapshot(dict(obs,symbol='ETH/USDT:USDT'),CFG)['reason']=='analysis_busy_no_queue'
    assert len(calls)==1
    release.set()
    for _ in range(100):
        if cache.active is None:break
        time.sleep(.01)
    result=cache.snapshot(dict(obs,received_at=time.time()),CFG)
    assert result['state']=='evaluated' and len(calls)==1
    result['signal']='BUY'
    assert cache.snapshot(obs,CFG)['signal']=='HOLD'
    assert cache.snapshot(dict(obs,fresh=False),CFG)['state']=='unavailable'

def test_dashboard_native_evidence_reaches_core_without_changing_votes(tmp_path):
    desk=fixture_desk(tmp_path);desk.path=tmp_path/"orders.sqlite3";seen=[]
    from modules.freqtrade_research import FreqtradeResearch
    def core(obs):seen.append(obs);return analyzed(obs)
    report=FreqtradeResearch(desk,core_analysis=core,native_analysis=lambda *a:dict(state='evaluated',signal='SELL',execution_authorized=False)).snapshot('BTC/USDT')
    assert report['native_analysis']['signal']=='SELL'
    assert seen[0]['native_strategy']==report['native_analysis']
    assert len(report['manager']['candidates'])==6 and report['execution_active'] is False
