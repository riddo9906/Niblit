
"""Core market integration: real code and temporary ledgers; fake projections only."""
import copy
import json
import sqlite3
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from modules.cognitive_ingress import CognitiveIngress
from modules.execution_graph import ExecutionGraph
from modules.memory_laboratory.runtime import MemoryRuntime
from modules.strategy_manager import assess_observation
from test_memory_laboratory_gateway import Backend, gateway


def observation(direction=1, mode='demo', account='fixture-account'):
    end=int(time.time()//300)*300
    candles=[]
    for i in range(60):
        price=100+direction*i*.1
        candles.append(dict(timestamp=end-(60-i)*300,open=price,close=price,
                            high=price+.01,low=price-.01))
    return dict(symbol='EURUSD',venue='fixture-venue',timeframe='5m',mode=mode,
                account_scope=account,source='fixture-completed-bars',
                received_at=time.time(),fresh=True,candles=candles)


class NoGenericMemory:
    def recall_contract(self, request):
        raise AssertionError('Market analysis must not recall unscoped memory')
    def remember_contract(self, record):
        raise AssertionError('Market analysis must not write unscoped memory')


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    from modules.memory_laboratory import runtime as runtime_module
    from niblit_memory import PersistenceManager
    backend=Backend()
    g=gateway(tmp_path,backend)
    runtime=MemoryRuntime(g)
    monkeypatch.setattr(runtime_module,'runtime_memory',lambda:runtime)
    persistence=PersistenceManager(root_dir=str(tmp_path/'checkpoints'))
    persistence.initialize_runtime_assets()
    ingress=CognitiveIngress(unified_memory=NoGenericMemory(),persistence_manager=persistence)
    return SimpleNamespace(ingress=ingress,gateway=g,runtime=runtime,backend=backend,
                           root=tmp_path,persistence=persistence)


def ingest(pipeline, data, **metadata):
    return pipeline.ingress.ingest('Analyze market observation',source='fixture',
        metadata={'market_observation':data,**metadata})


@pytest.mark.parametrize('direction,signal',[(1,'BUY'),(-1,'SELL'),(0,'HOLD')])
def test_actual_registered_rules_normalize_and_preserve_measurements(direction,signal):
    result=assess_observation(observation(direction))
    assert result['signal']==signal
    assert len(result['candidates'])==6
    assert all(c['invoked'] for c in result['candidates'])
    assert all(c['status']=='succeeded' for c in result['candidates'])
    assert result['execution_authorized'] is False
    assert result['regime']!='unknown'


@pytest.mark.parametrize('change,reason',[
    ('missing','insufficient_or_unbounded_history'),('stale','stale_or_unverified_market'),
    ('claim-fresh-old','stale_or_unverified_market'),
    ('future','invalid_observation_time'),('gap','unordered_or_gapped_history'),
    ('nan','invalid_market_data'),('no-receipt','invalid_market_data'),
    ('wrong-timeframe','unsupported_timeframe'),('live','unsupported_mode')])
def test_bad_observations_abstain_without_invoking_strategies(change,reason):
    data=observation()
    if change=='missing': data.pop('candles')
    if change=='stale': data['fresh']=False
    if change=='claim-fresh-old':
        for bar in data['candles']:bar['timestamp']-=3600
    if change=='future':
        for bar in data['candles']:bar['timestamp']+=3600
    if change=='gap': data['candles'][-1]['timestamp']+=1
    if change=='nan': data['candles'][-1]['close']=float('nan')
    if change=='no-receipt': data.pop('received_at')
    if change=='wrong-timeframe': data['timeframe']='1h'
    if change=='live': data['mode']='live'
    with patch('modules.strategy_manager.evaluate') as evaluate:
        result=assess_observation(data)
    evaluate.assert_not_called()
    assert result['signal']=='ABSTAIN'
    assert result['abstain_reason']==reason


def test_replay_uses_explicit_clock_and_remains_replay():
    data=observation(mode='replay')
    for bar in data['candles']:bar['timestamp']-=86400
    data['as_of']=data['candles'][-1]['timestamp']+305
    data['received_at']=data['as_of']
    assert assess_observation(data)['signal']=='BUY'
    assert assess_observation(data)['observation']['mode']=='replay'


@pytest.mark.parametrize('failure',[False,True])
def test_disagreement_and_partial_failure_keep_all_denominator_members(failure):
    def evaluate(rows,name):
        if failure and name=='breakout_v1':raise RuntimeError('private-error-body')
        return {'strategy':name,'side':'buy' if name=='trend_v1' else 'sell',
                'bar':rows[-1]['timestamp'],'reason':'fixture','evidence':{}}
    with patch('modules.strategy_manager.evaluate',side_effect=evaluate):
        result=assess_observation(observation())
    assert result['signal']=='ABSTAIN'
    assert len(result['candidates'])==6
    if failure:
        assert len(result['strategy_failures'])==1
        assert result['candidates'][1]['status']=='failed'
    else: assert result['abstain_reason']=='strategy_disagreement'
    assert 'private-error-body' not in str(result)



def project_receipts(runtime,receipts):
    # Check durable identities, independently of additional authorized view events.
    for _ in range(6):
        with runtime.gateway.db() as db:
            ready=all(db.execute('SELECT state FROM ingestion_outbox WHERE id=?',(r['id'],)).fetchone()[0]=='complete' for r in receipts)
        if ready:return
        runtime.tick_market_partitions()
    assert ready,'Original immutable receipts did not recover'

def test_ingress_graph_strategy_outbox_projection_and_restart(pipeline,monkeypatch):
    data=observation()
    first=ingest(pipeline,data)
    assert first.forecast_signal=='BUY'
    assert first.metadata['market_analysis']['execution_authorized'] is False
    assert 'validate_risk' in first.steps_run
    receipt=first.metadata['market_memory']
    assert receipt['state']=='queued_to_core'
    second=ingest(pipeline,data)
    assert second.metadata['market_memory']['id']==receipt['id']
    with pipeline.gateway.db() as db:
        assert db.execute("SELECT count(*) FROM ingestion_outbox WHERE json_extract(body,'$.metadata.source_type')='market_analysis'").fetchone()[0]==1
    # Recreate facade before projection: canonical SQLite must retain the event.
    reopened=gateway(pipeline.root,pipeline.backend)
    restarted=MemoryRuntime(reopened)
    project_receipts(restarted,[receipt])
    hits=reopened.retrieve('market analysis',namespace=receipt['namespace'],
        principal='desktop_operator',limit=20)['results']
    assert hits and all(h['verification']=='unverified' for h in hits)
    with reopened.db() as db:
        payloads=[json.loads(db.execute("SELECT payload FROM records WHERE id=?",(h['id'],)).fetchone()[0]) for h in hits]
    assert all(p['source_type']=='market_analysis' for p in payloads)
    assert not reopened.retrieve('market analysis',namespace='desktop',principal='desktop_operator')['results']


@pytest.mark.parametrize('mode,account,symbol',[('paper','fixture-account','EURUSD'),
    ('dry-run','fixture-account','EURUSD'),('demo','other-account','EURUSD'),
    ('demo','fixture-account','GBPUSD')])
def test_market_memory_partitions_isolate_mode_account_and_symbol(pipeline,mode,account,symbol):
    first=ingest(pipeline,observation())
    data=observation(mode=mode,account=account);data['symbol']=symbol
    second=ingest(pipeline,data)
    a=first.metadata['market_memory'];b=second.metadata['market_memory']
    assert a['namespace']!=b['namespace'] and a['id']!=b['id']
    project_receipts(pipeline.runtime,[a,b])
    hits=pipeline.gateway.retrieve('market analysis',namespace=a['namespace'],
        principal='desktop_operator',limit=20)['results']
    assert hits
    with pipeline.gateway.db() as db:
        scopes=[db.execute("SELECT namespace FROM records WHERE id=?",(h['id'],)).fetchone()[0] for h in hits]
    assert all(scope==a['namespace'] for scope in scopes)


def test_core_denial_precedes_specialists_even_without_governance_mode(pipeline,monkeypatch):
    # The real Core authorization rule must honor denial in every routed mode.
    from modules.cognitive_router import CognitiveMode
    mode=CognitiveMode('forecasting',False,True,True,False,intent='forecasting')
    monkeypatch.setattr(pipeline.ingress,'_router',lambda:SimpleNamespace(route=lambda profile:mode))
    with patch('modules.strategy_manager.assess_observation') as assess:
        result=ingest(pipeline,observation(),authorization_denied=True)
    assess.assert_not_called()
    assert result.metadata['authorization']['allowed'] is False
    assert result.metadata['market_analysis']['signal']=='ABSTAIN'
    assert result.metadata['market_analysis']['abstain_reason']=='core_denied'
    assert result.forecast_signal=='HOLD'
    assert result.steps_run==['reflect']


def test_memory_permission_denial_is_explicit_and_never_escalated(pipeline):
    pipeline.gateway.authorize=lambda *args:False
    result=ingest(pipeline,observation())
    assert result.metadata['market_memory']=={'state':'pending','queued':False,'error_type':'PermissionError'}
    with pipeline.gateway.db() as db:
        assert db.execute('SELECT count(*) FROM ingestion_outbox').fetchone()[0]==0


def test_projection_outage_retries_same_immutable_receipt_after_restart(pipeline):
    result=ingest(pipeline,observation())
    receipt=result.metadata['market_memory']
    pipeline.backend.offline=True
    assert pipeline.runtime.tick_market_partitions()['failed']>=1
    with pipeline.gateway.db() as db:
        assert db.execute('SELECT state FROM ingestion_outbox').fetchone()[0]=='pending'
        db.execute('UPDATE ingestion_outbox SET next_attempt=0')
    pipeline.backend.offline=False
    restarted=MemoryRuntime(gateway(pipeline.root,pipeline.backend))
    project_receipts(restarted,[receipt])
    with pipeline.gateway.db() as db:
        rows=db.execute("SELECT id,state FROM ingestion_outbox WHERE json_extract(body,'$.metadata.source_type')='market_analysis'").fetchall()
    assert len(rows)==1 and rows[0]['id']==receipt['id'] and rows[0]['state']=='complete'


def test_http_core_analysis_uses_existing_ingress_without_order_surface(pipeline,monkeypatch):
    import server
    core=object()
    monkeypatch.setattr(server,'get_core',lambda:core)
    def run(text,source,core,metadata):
        return pipeline.ingress.ingest(text,source=source,metadata=metadata).to_dict()
    monkeypatch.setattr(server,'_get_unified_runtime',lambda:SimpleNamespace(run_cognitive_cycle=run))
    client=TestClient(server.app)
    response=client.post('/api/trading/analysis',json={'observation':observation()})
    assert response.status_code==200
    payload=response.json()
    assert payload['metadata']['market_analysis']['signal']=='BUY'
    assert payload['metadata']['market_memory']['queued'] is True
    assert payload['tools_called']==[]
    assert payload['metadata']['market_analysis']['execution_authorized'] is False
    denied=client.post('/api/trading/analysis',json={'observation':observation(),'authorization_denied':True})
    assert denied.json()['metadata']['market_analysis']['abstain_reason']=='core_denied'
    monkeypatch.setattr(server,'get_core',lambda:None)
    assert client.post('/api/trading/analysis',json={'observation':observation()}).status_code==503



def test_actual_desk_feed_reaches_core_http_rules_and_canonical_ledger(pipeline,monkeypatch):
    import httpx
    import server
    import modules.trading_desk as desk_module
    core_client=TestClient(server.app)
    monkeypatch.setattr(server,'get_core',lambda:object())
    monkeypatch.setattr(server,'_get_unified_runtime',lambda:SimpleNamespace(
        run_cognitive_cycle=lambda text,source,core,metadata:
            pipeline.ingress.ingest(text,source=source,metadata=metadata).to_dict()))
    original_client=httpx.Client
    calls=[]
    def core_transport(request):
        calls.append(str(request.url))
        assert request.method=='POST' and request.url.path=='/api/trading/analysis'
        response=core_client.post(request.url.path,json=json.loads(request.content))
        return httpx.Response(response.status_code,json=response.json())
    monkeypatch.setattr(desk_module.httpx,'Client',lambda **kwargs:
        original_client(base_url=kwargs['base_url'],transport=httpx.MockTransport(core_transport)))
    data=observation()
    def exchange(path,payload=None):
        assert payload is None, 'Read-only analysis cannot post to exchange'
        if path=='show_config':
            return {'exchange':'fixture-venue','dry_run':True,'state':'stopped',
                    'strategy':'NiblitLabManager','timeframe':'5m'}
        if path=='whitelist':return {'whitelist':['EURUSD']}
        if path.startswith('pair_candles?'):
            columns=['__date_ts','open','high','low','close']
            return {'timeframe_ms':300000,'columns':columns,'data':[
                [r['timestamp']*1000,r['open'],r['high'],r['low'],r['close']] for r in data['candles']]}
        raise AssertionError(path)
    desk=desk_module.Desk(pipeline.root/'data-only',transport=exchange)
    response=TestClient(desk_module.create_app(desk)).get('/api/freqtrade/research',params={'pair':'EURUSD'})
    assert response.status_code==200
    body=response.json()
    assert len(calls)==1 and calls[0].startswith('http://127.0.0.1:5000/')
    assert body['core_analysis']['state']=='analyzed_by_core'
    assert body['core_analysis']['analysis']['signal']=='BUY'
    assert len(body['core_analysis']['analysis']['candidates'])==6
    assert body['core_analysis']['memory']['queued'] is True
    assert body['execution_active'] is False
    project_receipts(pipeline.runtime,[body['core_analysis']['memory']])


def test_core_forwarder_never_retries_ambiguous_analysis_transport(monkeypatch):
    import httpx
    import modules.trading_desk as desk
    original_client=httpx.Client
    calls=[]
    def unavailable(request):
        calls.append(request)
        raise httpx.ReadTimeout('fixture ambiguous response',request=request)
    monkeypatch.setattr(desk.httpx,'Client',lambda **kwargs:
        original_client(base_url=kwargs['base_url'],transport=httpx.MockTransport(unavailable)))
    result=desk.core_market_analysis(observation())
    assert result=={'state':'pending','error_type':'ReadTimeout','execution_authorized':False}
    assert len(calls)==1


def test_unexpected_specialist_failure_cannot_preserve_caller_supplied_signal():
    from modules.cognitive_router import CognitiveMode
    mode=CognitiveMode('forecasting',False,True,False,False,intent='forecasting')
    with patch('modules.strategy_manager.assess_observation',side_effect=RuntimeError('fixture')):
        result=ExecutionGraph().run('market',mode=mode,context={
            'market_observation':observation(),'authorization':{'allowed':True},
            'forecast_signal':'BUY','market_analysis':{'signal':'BUY','execution_authorized':True}})
    assert result.market_analysis['signal']=='ABSTAIN'
    assert result.market_analysis['execution_authorized'] is False
    assert result.forecast_signal=='HOLD'
    assert any(not r.success for r in result.step_results)


def test_disabled_memory_reports_disabled_without_projection(pipeline,monkeypatch):
    from modules.memory_laboratory import runtime as runtime_module
    monkeypatch.setattr(runtime_module,'runtime_memory',lambda:None)
    assert ingest(pipeline,observation()).metadata['market_memory']=={'state':'disabled','queued':False}


def test_queued_market_permission_revocation_blocks_projection(pipeline):
    receipt=ingest(pipeline,observation()).metadata['market_memory']
    pipeline.gateway.authorize=lambda *args:False
    assert pipeline.runtime.tick_market_partitions()['failed']>=1
    assert not pipeline.backend.points


def test_strategy_policy_versions_get_separate_memory_partitions(pipeline,monkeypatch):
    first=ingest(pipeline,observation()).metadata['market_memory']
    from modules import strategy_manager
    real_assess=strategy_manager.assess_observation
    def changed_policy(data):
        return {**real_assess(data),'policy_version':'future-fixture-policy'}
    monkeypatch.setattr(strategy_manager,'assess_observation',changed_policy)
    second=ingest(pipeline,observation()).metadata['market_memory']
    assert first['namespace']!=second['namespace']

