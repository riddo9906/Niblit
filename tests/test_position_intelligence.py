import copy,json,sqlite3,time
from pathlib import Path
from types import SimpleNamespace
import pytest
from modules.position_intelligence import PositionIntelligence,assess_position,reconcile_position
from test_core_market_pipeline import pipeline,ingest,observation

@pytest.fixture
def setup_position(tmp_path,pipeline):
    root=tmp_path/'Core';root.mkdir()
    ledger=root.parent/'freqtrade/user_data/tradesv3.sqlite';ledger.parent.mkdir(parents=True)
    p=dict(trade_id=1,pair='BTC/USDT:USDT',is_open=True,is_short=False,open_rate=100.,amount=2.,stake_amount=200.,leverage=1.,strategy='NiblitLabManager',enter_tag='niblit_lab:trend_v1:buy',open_timestamp=100000,fee_close=.0002,stop_loss_abs=95.)
    with sqlite3.connect(ledger) as db:
        db.execute('CREATE TABLE trades(id,pair,is_open,open_rate,amount,is_short,strategy,stake_amount,leverage)')
        db.execute('INSERT INTO trades VALUES(?,?,?,?,?,?,?,?,?)',(1,p['pair'],1,100.,2.,0,p['strategy'],200.,1.))
        db.execute('CREATE TABLE orders(id,ft_trade_id,order_id,status,side,filled)')
        db.execute("INSERT INTO orders VALUES(1,1,'fixture-order','closed','buy',2.)")
    data=observation(mode='dry-run');data['symbol']=p['pair']
    market=dict(candles=data['candles'],last=data['candles'][-1],fresh=True,source='fixture',timeframe='5m')
    class Desk:
        def configuration(self):return dict(dry_run=True,state='stopped',exchange='fixture',timeframe='5m')
        def api(self,path,payload=None):
            assert payload is None and path in ('status','trades?limit=100'),'Monitoring attempted a mutation or unreviewed route'
            return {'trades':copy.deepcopy(getattr(self,'history',[]))} if path.startswith('trades') else copy.deepcopy(self.positions)
        def market(self,pair,config):return copy.deepcopy(self.market_value)
    desk=Desk();desk.root=root;desk.positions=[p];desk.market_value=market
    def core(obs):
        e=ingest(pipeline,obs)
        return {'state':'analyzed_by_core','authorization':e.metadata['authorization'],'memory':e.metadata['market_memory'],'analysis':e.metadata['market_analysis']}
    monitor=PositionIntelligence(desk,core,pipeline.gateway)
    return SimpleNamespace(position=p,desk=desk,monitor=monitor,market=market,observation=data,pipeline=pipeline,ledger=ledger,core=core)

def test_discovery_reconciliation_and_real_strategies(setup_position):
    s=setup_position;r=s.monitor.scan()['positions'][0]
    assert r['verified']['state']=='matched_engine_record'
    assert r['verified']['recorded_orders'][0]['status']=='closed'
    assert len(r['strategies']['candidates'])==6 and all(c['invoked'] for c in r['strategies']['candidates'])
    assert r['core']['memory']['queued'] and not r['execution_authorized']
    assert not r['realized_result_verified']

@pytest.mark.parametrize('short,expected',[(False,20),(True,-20)])
def test_unrealized_linear_pnl_not_realized(setup_position,short,expected):
    s=setup_position;p=dict(s.position,is_short=short,leverage=3)
    market=copy.deepcopy(s.market);market['last']['close']=110
    r=assess_position(p,market,s.observation,analysis={'assessment_complete':True,'signal':'HOLD'},reconciliation={'state':'matched_engine_record'})
    assert r['estimated']['unrealized_gross_usdt']==expected
    assert not r['estimated']['realized'] and r['estimated']['costs_included'] is False
    assert r['recorded']['open_rate']==100

@pytest.mark.parametrize('signal,complete,expected',[('BUY',True,'HOLD'),('SELL',True,'EXIT-CANDIDATE'),('ABSTAIN',True,'REVIEW'),('ABSTAIN',False,'ABSTAIN')])
def test_agreement_conflict_failure_assessments(setup_position,signal,complete,expected):
    s=setup_position
    r=assess_position(s.position,s.market,s.observation,analysis={'assessment_complete':complete,'signal':signal,'abstain_reason':'fixture disagreement/failure'},reconciliation={'state':'matched_engine_record'})
    assert r['assessment']==expected and r['execution_authorized'] is False

@pytest.mark.parametrize('change',['stale','missing','mismatch','duplicate'])
def test_invalid_position_or_market_abstains(setup_position,change):
    s=setup_position
    if change=='stale':s.desk.market_value['fresh']=False
    if change=='missing':s.desk.market_value.update(candles=[],last=None,fresh=False)
    if change=='mismatch':s.desk.positions[0]['amount']=3
    if change=='duplicate':s.desk.positions*=2
    r=s.monitor.scan();assert len(r['positions'])==1 and r['positions'][0]['assessment']=='ABSTAIN'
    assert not r['execution_authorized']

def test_provider_failure_does_not_stop_next_position(setup_position):
    s=setup_position;second=dict(s.position,trade_id=2,pair='ETH/USDT:USDT');s.desk.positions.append(second)
    original=s.desk.market
    def market(pair,config):
        if pair.startswith('BTC'):raise ConnectionError('controlled unavailable provider')
        return original(pair,config)
    s.desk.market=market
    r=s.monitor.scan();assert len(r['positions'])==2 and r['positions'][0]['error_type']=='ConnectionError'
    assert r['positions'][1]['strategies']['assessment_complete']

def test_core_denial_overrides_local_recommendation(setup_position):
    s=setup_position;s.monitor.core_analysis=lambda obs:{'state':'denied','authorization':{'allowed':False}}
    r=s.monitor.scan()['positions'][0];assert r['assessment']=='ABSTAIN' and 'Core' in r['reason']

def test_restart_idempotence_and_later_observation(setup_position,monkeypatch):
    s=setup_position;clock=[time.time()];monkeypatch.setattr(time,'time',lambda:clock[0])
    a=s.monitor.scan()['positions'][0];clock[0]+=.1
    restarted=PositionIntelligence(s.desk,s.core,s.pipeline.gateway)
    b=restarted.scan()['positions'][0]
    assert a['core']['memory']['id']==b['core']['memory']['id']
    clock[0]+=300
    for candle in s.desk.market_value['candles']:
        candle['timestamp']+=300
        for key in ('open','high','low','close'):candle[key]+=1
    s.desk.market_value['last']=s.desk.market_value['candles'][-1]
    c=restarted.scan()['positions'][0]
    assert c['subsequent_observation']['realized'] is False
    assert c['core']['memory']['id']!=a['core']['memory']['id']
    assert restarted.scan()['positions'][0]['core']['memory']['id']==c['core']['memory']['id']
    assert sum(s.pipeline.runtime.tick_market_partitions()['completed'] for _ in range(2))>=2

def test_mode_isolation_and_cancellation(setup_position):
    s=setup_position;s.desk.configuration=lambda:dict(dry_run=False)
    assert s.monitor.scan()['state']=='unsupported_execution_mode'
    s.desk.configuration=lambda:dict(dry_run=True,state='stopped',exchange='fixture',timeframe='5m')
    s.monitor.stop();assert s.monitor.scan()['state']=='cancelled'

def test_duplicate_worker_kernel_lock_and_cancel(setup_position):
    s=setup_position
    class Scheduler:
        def __init__(self):self.jobs=[];self.cancelled=[]
        def submit(self,fn,**kwargs):self.jobs.append(fn);return str(len(self.jobs))
        def cancel(self,key):self.cancelled.append(key)
        def prune_completed(self,*a,**kw):pass
    scheduler=Scheduler();other=PositionIntelligence(s.desk,s.core,s.pipeline.gateway)
    assert s.monitor.start(scheduler) and not s.monitor.start(scheduler)
    assert not other.start(scheduler)
    s.monitor.stop();assert scheduler.cancelled
    assert other.start(scheduler);other.stop()

def test_scheduler_prunes_only_owned_completed_history():
    from aios_scheduler import AIOSScheduler
    s=AIOSScheduler()
    for _ in range(5):
        key=s.submit(lambda:None,label='position-observation');s._tasks[key].completed=True
    kept=s.submit(lambda:None,label='other')
    assert s.prune_completed('position-observation',keep=2)==3 and kept in s._tasks


def test_future_high_priority_job_does_not_starve_ready_observation():
    from aios_scheduler import AIOSScheduler
    scheduler=AIOSScheduler()
    future=scheduler.submit(lambda:None,priority=0,delay_secs=3600)
    ready=scheduler.submit(lambda:None,priority=7,label='position-observation')
    assert scheduler._pop_ready_task().task_id==ready
    assert scheduler._tasks[future].completed is False


def test_confirmed_simulated_close_persists_once_and_is_not_live_profit(setup_position):
    s=setup_position;s.monitor.scan()
    closed=dict(s.position,is_open=False,close_timestamp=200000,close_rate=110.,profit_abs=20.,realized_profit=20.)
    s.desk.positions=[];s.desk.history=[closed]
    with sqlite3.connect(s.ledger) as db:
        db.execute('UPDATE trades SET is_open=0 WHERE id=1')
        db.execute("INSERT INTO orders VALUES(2,1,'fixture-exit','closed','sell',2.)")
    result=s.monitor.scan()['closed_outcomes']['events'][0]
    assert result['verification']=='engine_confirmed_simulated_close'
    assert not result['live_broker_result_verified'] and result['memory']['queued']
    restarted=PositionIntelligence(s.desk,s.core,s.pipeline.gateway)
    again=restarted.scan()['closed_outcomes']['events'][0]
    assert again['cached'] and again['memory']['id']==result['memory']['id']

def test_monitor_exception_clears_previous_account_snapshot(setup_position):
    s=setup_position;s.monitor.scan()
    def unavailable():raise ConnectionError('controlled engine outage')
    s.desk.configuration=unavailable
    result=s.monitor.scan();assert result['state']=='unavailable' and result['positions']==[]


def test_account_profile_isolation(setup_position):
    s=setup_position
    config=s.desk.root.parent/'freqtrade/user_data/config.json'
    config.write_text('{"dry_run":true,"profile":"A"}')
    a=s.monitor.scan()['positions'][0]
    config.write_text('{"dry_run":true,"profile":"B"}')
    b=s.monitor.scan()['positions'][0]
    assert a['scope']['account_scope']!=b['scope']['account_scope']
    assert a['core']['memory']['namespace']!=b['core']['memory']['namespace']
    assert b['subsequent_observation'] is None


def test_cooperative_cancel_during_provider_preserves_worker_lock(setup_position):
    import threading
    s=setup_position;entered=threading.Event();release=threading.Event()
    class Scheduler:
        def __init__(self):self.jobs=[]
        def submit(self,fn,**kw):self.jobs.append(fn);return str(len(self.jobs))
        def cancel(self,key):pass
        def prune_completed(self,*a,**kw):pass
    scheduler=Scheduler();calls=[];original=s.desk.market
    def blocked(pair,config):
        entered.set();assert release.wait(5);return original(pair,config)
    s.desk.market=blocked;s.monitor.core_analysis=lambda obs:calls.append(obs)
    assert s.monitor.start(scheduler)
    scheduler.jobs[0]();assert entered.wait(5)
    scheduler.jobs[0]()  # single-flight: does not launch another pass
    s.monitor.stop()
    other=PositionIntelligence(s.desk,s.core,s.pipeline.gateway)
    assert not other.start(scheduler)
    release.set()
    import time
    deadline=time.monotonic()+5
    while s.monitor.tick_lock.locked() and time.monotonic()<deadline:time.sleep(.01)
    assert not calls and len(scheduler.jobs)==1
    assert other.start(scheduler);other.stop()
