"""Existing worker recovery/fairness; fake Qdrant only, real SQLite/ingress."""
import json,sqlite3,threading
import pytest
from modules.memory_laboratory.runtime import MemoryRuntime
from test_memory_laboratory_gateway import Backend,gateway
from test_core_market_pipeline import pipeline,ingest,observation

@pytest.fixture
def runtime(tmp_path,monkeypatch):
    monkeypatch.delenv("NIBLIT_MEMORY_SYNC_SOURCE",raising=False)
    return MemoryRuntime(gateway(tmp_path,Backend()),scope={'namespace':'test','principal':'operator'})


def test_phase_fault_does_not_starve_market_or_leak_message(runtime,monkeypatch):
    events=[];failure=[True]
    def general(limit):
        events.append(('general',limit))
        if failure[0]:
            exc=sqlite3.OperationalError('private path/token must not be exposed');exc.sqlite_errorcode=sqlite3.SQLITE_BUSY
            raise exc
        return {'completed':1,'failed':0}
    monkeypatch.setattr(runtime,'tick',general)
    monkeypatch.setattr(runtime,'tick_market_partitions',lambda limit:events.append(('market',limit)) or {'completed':1,'failed':0})
    from modules.memory_laboratory.market import MarketJournal
    monkeypatch.setattr(MarketJournal,'repair_pending',lambda self:events.append(('journal',8)) or 0)
    runtime.run_once()
    assert events==[('general',4),('market',8),('journal',8)]
    error=runtime.phase_status['general_projection']['error']
    assert error=={'error_type':'OperationalError','sqlite_errorcode':5,'sqlite_errorname':'SQLITE_BUSY'}
    assert 'private' not in json.dumps(runtime.status())
    assert runtime.source_error is None  # projection fault is not a source fault
    failure[0]=False;events.clear();runtime.run_once()
    assert events==[('general',4),('market',8),('general',28),('journal',8)]
    state=runtime.phase_status['general_projection']
    assert state['state']=='ok' and 'error' not in state and state['last_error']['sqlite_errorcode']==5
    assert state['recovered_at']


def test_legacy_sync_failure_recovers_without_blocking_projection(runtime,monkeypatch):
    monkeypatch.setenv('NIBLIT_MEMORY_SYNC_SOURCE','fixture.json');fail=[True];calls=[]
    def sync(path):
        if fail[0]:raise sqlite3.OperationalError('sensitive details')
        return 0  # unchanged valid source is a successful check
    monkeypatch.setattr(runtime,'sync_knowledge_file',sync)
    monkeypatch.setattr(runtime,'tick',lambda limit:calls.append(limit) or {'completed':0,'failed':0})
    monkeypatch.setattr(runtime,'tick_market_partitions',lambda limit:{'completed':0,'failed':0})
    runtime.run_once();assert runtime.source_error=='OperationalError' and calls==[4,28]
    fail[0]=False;runtime._last_sync=-1e10;runtime.run_once()
    assert runtime.source_error is None and runtime.phase_status['knowledge_sync']['state']=='ok'
    assert runtime.phase_status['knowledge_sync']['last_error']['error_type']=='OperationalError'


def test_market_failure_does_not_disable_general_memory(runtime,monkeypatch):
    calls=[];monkeypatch.setattr(runtime,'tick',lambda limit:calls.append(limit) or {'completed':0,'failed':0})
    def unavailable(limit):raise ConnectionError('private endpoint')
    monkeypatch.setattr(runtime,'tick_market_partitions',unavailable)
    runtime.run_once()
    assert calls==[4,28] and runtime.phase_status['market_partitions']['state']=='error'
    assert runtime.phase_status['market_journal']['state']=='ok'


def test_cancellation_stops_followup_phases(runtime,monkeypatch):
    calls=[]
    def tick(limit):calls.append(limit);runtime.stop_event.set();return {'completed':0,'failed':0}
    monkeypatch.setattr(runtime,'tick',tick)
    monkeypatch.setattr(runtime,'tick_market_partitions',lambda limit:pytest.fail('Cancelled follow-up'))
    runtime.run_once();assert calls==[4]


def test_atomic_start_does_not_create_duplicate_workers(runtime,monkeypatch):
    entered=threading.Event();release=threading.Event();calls=[]
    def run():calls.append(1);entered.set();release.wait(5)
    monkeypatch.setattr(runtime,'run_once',run)
    starts=[threading.Thread(target=runtime.start) for _ in range(8)]
    for t in starts:t.start()
    for t in starts:t.join()
    assert entered.wait(4) and calls==[1]
    runtime.stop_event.set();release.set();runtime.stop()


def test_real_market_episode_served_before_general_tail(pipeline,monkeypatch):
    monkeypatch.delenv("NIBLIT_MEMORY_SYNC_SOURCE",raising=False)
    r=pipeline.runtime;g=pipeline.gateway
    for i in range(6):r.enqueue(source=f'fixture-general-{i}',content=f'General fact {i}')
    receipt=ingest(pipeline,observation()).metadata['market_memory']
    original=r.tick_market_partitions;seen=[]
    def market(limit):
        with g.db() as db:
            count=db.execute("SELECT count(*) FROM ingestion_outbox WHERE state='complete' AND coalesce(json_extract(body,'$.metadata.source_type'),'')<>'chart_annotation_delta' AND json_extract(body,'$.namespace')='desktop'").fetchone()[0]
        seen.append(count)
        return original(limit)
    r.tick_market_partitions=market;r.run_once()
    assert seen==[4]
    with g.db() as db:
        assert db.execute('SELECT state FROM ingestion_outbox WHERE id=?',(receipt['id'],)).fetchone()[0]=='complete'
        assert db.execute("SELECT count(*) FROM ingestion_outbox WHERE state='complete' AND coalesce(json_extract(body,'$.metadata.source_type'),'')<>'chart_annotation_delta'").fetchone()[0]==7
    # Both the original market episode and its derived chart delta share this worker.
    with g.db() as db:
        assert db.execute("SELECT count(*) FROM ingestion_outbox WHERE state='complete' AND json_extract(body,'$.metadata.source_type')='chart_annotation_delta'").fetchone()[0]==1
    assert r.phase_status['market_partitions']['result']['completed']==2


def test_unchanged_snapshot_performs_no_writes_and_rechecks_permission(runtime,tmp_path):
    source=tmp_path/'snapshot.json'
    source.write_text(json.dumps({'facts':[{'key':f'fact-{i}','value':{'content':f'Evidence {i}'}} for i in range(300)]}))
    assert runtime.sync_knowledge_file(source)==300
    # A new file mtime with identical facts emulates a normal Core snapshot save.
    source.write_text(source.read_text())
    from contextlib import contextmanager
    original=runtime.gateway.db;statements=[]
    @contextmanager
    def watched():
        with original() as db:
            db.set_trace_callback(statements.append)
            yield db
    runtime.gateway.db=watched
    runtime.sync_knowledge_file(source)
    assert not any(x.lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) for x in statements)
    runtime.gateway.authorize=lambda *args:False
    with pytest.raises(PermissionError):runtime.enqueue_fact({'key':'fact-1','value':{'content':'Evidence 1'}})
