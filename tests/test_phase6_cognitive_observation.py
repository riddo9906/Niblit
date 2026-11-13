from datetime import datetime,timezone
import threading
import pytest
from modules.observation_supervisor import ObservationJob,ObservationSupervisor
from modules.memory_laboratory.cognitive import CognitiveMemory
from modules.memory_laboratory.runtime import MemoryRuntime
from test_memory_laboratory_gateway import Backend,gateway


def result(job,now=100):
    return {'account':{'identity':job.account,'terminal_id':job.terminal},
            'symbol':job.symbol,'connected':True,'received_at':now,'fresh':True,
            'execution_authorized':False}


def test_independent_source_failure_and_expiry():
    now=[100.];jobs=[ObservationJob(s,'BTCUSD',s,s,5,10) for s in ('desktop','vps')]
    def fail(job):raise ConnectionError('must not leak credentials')
    service=ObservationSupervisor(jobs,{'desktop':lambda j:result(j),'vps':fail},clock=lambda:now[0])
    service.poll_source('vps');service.poll_source('desktop')
    states={s['source']:s for s in service.status()['jobs']}
    assert states['desktop']['fresh'] and not states['vps']['fresh']
    assert states['vps']['error_type']=='ConnectionError'
    now[0]=111
    assert not service.status()['jobs'][0]['fresh']


@pytest.mark.parametrize('field,value',[('account',{'identity':'wrong','terminal_id':'desktop'}),
    ('symbol','OTHER'),('execution_authorized',True),('received_at',float('nan'))])
def test_wrong_binding_and_authority_never_persist(field,value):
    job=ObservationJob('desktop','BTCUSD','demo','desktop');calls=[]
    service=ObservationSupervisor([job],{'desktop':lambda j:{**result(j),field:value}},sink=lambda *a:calls.append(a),clock=lambda:100)
    service.poll_source('desktop')
    assert not calls and service.status()['jobs'][0]['state']=='unavailable'


def test_no_duplicate_reads_and_recovery():
    now=[100.];job=ObservationJob('desktop','BTCUSD','demo','desktop',5,10);calls=[]
    service=ObservationSupervisor([job],{'desktop':lambda j:result(j,now[0])},sink=lambda *a:calls.append(a),clock=lambda:now[0])
    assert service.poll_source('desktop') and not service.poll_source('desktop')
    now[0]+=5;assert service.poll_source('desktop')
    assert len(calls)==2 and not service.status()['execution_authorized']


def test_blocked_source_cannot_starve_other_or_duplicate_worker():
    entered=threading.Event();release=threading.Event();observed=threading.Event()
    jobs=[ObservationJob(s,'BTCUSD',s,s) for s in ('desktop','vps')]
    def blocked(j):entered.set();release.wait(3);return result(j)
    def desktop(j):observed.set();return result(j)
    service=ObservationSupervisor(jobs,{'vps':blocked,'desktop':desktop},clock=lambda:100)
    assert service.start() and not service.start()
    try:assert entered.wait(1) and observed.wait(1)
    finally:release.set();assert service.stop()


def memory(tmp_path):
    backend=Backend();backend.offline=True
    return CognitiveMemory(MemoryRuntime(gateway(tmp_path,backend)))


def record(m,**extra):
    return m.record(domain='trading',event_id='snapshot-1',source='desktop:demo',
        observed_at='2026-11-12T10:00:00Z',available_at='2026-11-12T10:00:01Z',
        content='Six strategies abstained; this is not a broker fill.',**extra)


def test_canonical_episode_outbox_transaction_and_idempotence(tmp_path):
    m=memory(tmp_path);first=record(m);second=record(m)
    assert first['id']==second['id'] and second['duplicate']
    with m.gateway.db() as db:
        assert db.execute('SELECT count(*) FROM cognitive_episodes_v2').fetchone()[0]==1
        assert db.execute('SELECT count(*) FROM ingestion_outbox').fetchone()[0]==1
    rows=m.retrieve(domain='trading',as_of='2026-11-12T11:00:00Z')
    assert rows[0]['verification']=='unverified' and not rows[0]['execution_authorized']
    assert not m.retrieve(domain='trading',as_of='2026-11-12T10:00:00Z')
    assert not m.retrieve(domain='research',as_of='2026-11-12T11:00:00Z')
    assert not m.retrieve(domain='trading',source='vps:live',as_of='2026-11-12T11:00:00Z')


def test_immutable_conflict_and_restart(tmp_path):
    m=memory(tmp_path);first=record(m)
    with pytest.raises(ValueError):record(m,kind='hypothesis')
    restored=CognitiveMemory(MemoryRuntime(m.gateway))
    assert record(restored)['duplicate']
    assert restored.retrieve(domain='trading',as_of='2026-11-12T11:00:00Z')[0]['id']==first['id']


def test_scoped_access_and_secrets_rollback(tmp_path):
    m=memory(tmp_path);record(m)
    other=CognitiveMemory(MemoryRuntime(m.gateway,scope={'namespace':'other','principal':'other'}))
    assert not other.retrieve(domain='trading',as_of='2026-11-12T11:00:00Z')
    m.gateway.authorize=lambda *a:False
    with pytest.raises(PermissionError):record(m)
    with pytest.raises(PermissionError):m.retrieve(domain='trading',as_of='2026-11-12T11:00:00Z')


def test_contradictions_preserved_without_promoting_knowledge(tmp_path):
    m=memory(tmp_path);first=record(m)
    m.record(domain='trading',event_id='revision-2',source='desktop:demo',
        observed_at='2026-11-12T10:02:00Z',available_at='2026-11-12T10:02:01Z',
        content='Later evidence conflicts with the earlier interpretation.',kind='hypothesis',
        logical_type='metacognitive',contradict=[first['id']])
    rows=m.retrieve(domain='trading',as_of='2026-11-12T11:00:00Z')
    assert len(rows)==2 and rows[0]['relationships']['contradict']==[first['id']]
    assert all(r['verification']=='unverified' for r in rows)


def test_real_evidence_sink_reuses_canonical_outbox(tmp_path):
    from modules.cognitive_observation_runtime import episode_sink
    from modules.market_evidence import recognize
    bars=[{'timestamp':1000+i*300,'open':100,'close':101,'high':102,'low':99,'volume':10} for i in range(30)]
    frame=recognize(bars,'BTCUSD','M5',300,10000,{'adapter':'fixture'})
    m=memory(tmp_path);sink=episode_sink(m);job=ObservationJob('desktop','BTCUSD','demo','terminal')
    observed={**result(job,10000),'evidence':{'M5':frame}}
    first=sink(job,observed);second=sink(job,observed)
    assert first['id']==second['id'] and second['duplicate']
    assert len(m.retrieve(domain='trading',as_of='2026-11-12T10:00:00Z'))==1


def test_core_install_is_owned_and_restarts_only_reads(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from modules.cognitive_observation_runtime import install
    monkeypatch.delenv('NIBLIT_VPS_GATEWAY_PROFILE',raising=False)
    core=SimpleNamespace();desktop=SimpleNamespace(observe=lambda *a:{'connected':False})
    config={'schema_version':'observation-supervisor/1','jobs':[
        {'source':'desktop','symbol':'BTCUSD','account':'demo','terminal':'terminal'}]}
    service=install(core,desktop=desktop,memory=memory(tmp_path),config=config)
    try:
        assert install(core,config=config) is service
        assert service.status()['execution_authorized'] is False
    finally:assert service.stop()


def test_enqueue_failure_rolls_back_episode(tmp_path):
    m=memory(tmp_path)
    def fail(**kwargs):raise RuntimeError('outbox write failed')
    m.runtime.enqueue=fail
    with pytest.raises(RuntimeError):record(m)
    with m.gateway.db() as db:
        assert db.execute('SELECT count(*) FROM cognitive_episodes_v2').fetchone()[0]==0


def test_secret_provenance_rejected_before_storage(tmp_path):
    m=memory(tmp_path)
    with pytest.raises(PermissionError):
        m.record(domain='research',event_id='test',source='sk-proj-'+'x'*30,
            observed_at='2026-11-12T10:00:00Z',available_at='2026-11-12T10:00:01Z',content='Safe text')
    with m.gateway.db() as db:
        assert db.execute('SELECT count(*) FROM cognitive_episodes_v2').fetchone()[0]==0


def test_remote_market_reuses_shared_features_and_never_calls_execution():
    from unittest.mock import Mock
    from modules.remote_market_intelligence import RemoteMarketIntelligence
    from modules.strategy_manager import assess_observation
    import time
    now=int(time.time());last=(now//300)*300-300
    bars=[{'timestamp':last-(79-i)*300,'open':100+i,'close':101+i,'high':102+i,'low':99+i} for i in range(80)]
    adapter=Mock();adapter.market.return_value={'connected':True,'symbol':'BTCUSDm',
        'account':{'identity':'demo','terminal_id':'vps','server':'broker','environment':'demo'},
        'quote':{'timestamp':now,'fresh':True},'candles':bars}
    seen=[]
    def core(observation):seen.append(observation);return {'analysis':assess_observation(observation)}
    service=RemoteMarketIntelligence(adapter,core)
    value=service.observe('BTCUSDm','demo','vps')
    assert value['evidence']['M5']['source']['adapter']=='mt5_vps_gateway'
    assert len(value['strategy_comparison']['candidates'])==6 and not value['execution_authorized']
    assert adapter.mock_calls==[__import__('unittest.mock').mock.call.market('BTCUSDm')]
    adapter.market.return_value['account']['terminal_id']='desktop'
    with pytest.raises(ValueError):service.observe('BTCUSDm','demo','vps')
    assert len(seen)==1


@pytest.mark.parametrize('offset,state',[(0,'aligned'),(6,'timestamps_not_aligned')])
def test_cross_source_comparison_requires_aligned_independent_quotes(offset,state):
    jobs=[ObservationJob(s,'BTCUSD',s,s) for s in ('desktop','vps')]
    def collect(j):return {**result(j),'quote':{'bid':100,'ask':101,'timestamp':100+(offset if j.source=='vps' else 0)}}
    observer=ObservationSupervisor(jobs,{'desktop':collect,'vps':collect},clock=lambda:100)
    observer.poll_source('desktop');observer.poll_source('vps')
    comparison=observer.status()['comparisons'][0]
    assert comparison['state']==state and not comparison['execution_authorized']
    if state=='aligned':assert comparison['mid_difference']==0 and comparison['contract_equivalence']=='not_assumed'
