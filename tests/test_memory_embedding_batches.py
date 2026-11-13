"""Bounded pinned embeddings preserve public identities and fail atomically."""
import threading,json
from types import SimpleNamespace
import pytest
from modules.memory_laboratory.setup import DedicatedEmbedder,Config,validate_vector
from modules.memory_laboratory.runtime import MemoryRuntime
from test_memory_laboratory_gateway import Backend,gateway

class Array:
    def __init__(self,rows):self.rows=rows
    def tolist(self):return self.rows

class Model:
    def __init__(self):self.calls=[];self.active=0;self.peak=0
    def encode(self,texts,**kw):
        self.calls.append((texts,kw));self.active+=1;self.peak=max(self.peak,self.active)
        __import__("time").sleep(.005)
        rows=[[len(x),1.,2.] for x in texts];self.active-=1
        return Array(rows)


def test_pinned_prefix_bounds_scalar_equivalence_and_serialization(monkeypatch):
    monkeypatch.setenv('NIBLIT_MEMORY_EMBEDDING_BATCH_SIZE','3')
    e=DedicatedEmbedder(Config(url='http://127.0.0.1:6333'));e._model=Model()
    many=e.embed_many(['one','two','three','four'])
    assert len(many)==4 and [len(c[0]) for c in e._model.calls]==[3,1]
    assert e._model.calls[0][0][0]=='passage: one'
    assert many[0]==e.embed('one')
    e.embed('one',query=True);assert e._model.calls[-1][0]==['query: one']
    threads=[threading.Thread(target=e.embed,args=('sample',)) for _ in range(4)]
    for t in threads:t.start()
    for t in threads:t.join()
    assert e._model.peak==1


@pytest.mark.parametrize('bad',[[],[''],['x']*201,['x'*4001]])
def test_adapter_rejects_unbounded_inputs(bad):
    e=DedicatedEmbedder(Config(url='http://127.0.0.1:6333'))
    with pytest.raises(ValueError):e.embed_many(bad)
    assert e._model is None


def test_scalar_fallback_and_batch_ids_dedup_are_identical(tmp_path,monkeypatch):
    monkeypatch.setenv('NIBLIT_MEMORY_EMBEDDING_BATCH_SIZE','2')
    scalar=Backend();g=gateway(tmp_path,scalar);segments=[('same','a:0'),('other','a:1'),('same','a:2')]
    first=g.ingest(segments,source='a',namespace='test',principal='operator')
    class Batch(Backend):
        def __init__(self):super().__init__();self.calls=[]
        def embed_many(self,texts):self.calls.append(texts);return [self.embed(t) for t in texts]
    batch=Batch();g.backend=batch
    second=g.ingest(segments,source='a',namespace='test',principal='operator')
    assert first==second and batch.calls==[['same','other']]
    assert g.last_ingestion_profile['chunks']==3 and g.last_ingestion_profile['unique_chunks']==2
    assert g.last_ingestion_profile['adapter_calls']==1
    with g.db() as db:assert db.execute('SELECT count(*) FROM records').fetchone()[0]==3


@pytest.mark.parametrize('failure',['short','nan','dimension','exception'])
def test_partial_embedding_failure_never_publishes(tmp_path,failure):
    class Bad(Backend):
        def embed_many(self,texts):
            if failure=='short':return []
            if failure=='nan':return [[float('nan'),1.,1.]]*len(texts)
            if failure=='dimension':return [[1.,2.],[1.,2.,3.]]
            raise ConnectionError('controlled batch failure')
    g=gateway(tmp_path,Bad())
    with pytest.raises((ValueError,ConnectionError)):
        g.ingest([('one','x:1'),('two','x:2')],source='x',namespace='test',principal='operator')
    assert not g._embedding_cache
    with g.db() as db:assert db.execute('SELECT count(*) FROM records').fetchone()[0]==0


def test_cancelled_batch_retains_outbox_then_restart_projects(tmp_path):
    stop=threading.Event()
    class Batch(Backend):
        def embed_many(self,texts):stop.set();return [self.embed(t) for t in texts]
    backend=Batch();g=gateway(tmp_path,backend);r=MemoryRuntime(g,scope={'namespace':'test','principal':'operator'});r.stop_event=stop
    ident=r.enqueue(source='evidence',content='one source')
    assert r.tick()['failed']==1
    with g.db() as db:
        assert db.execute('SELECT state FROM ingestion_outbox WHERE id=?',(ident,)).fetchone()[0]=='pending'
        assert db.execute('SELECT count(*) FROM records').fetchone()[0]==0
        db.execute('UPDATE ingestion_outbox SET next_attempt=0')
    backend.embed_many=lambda texts:[backend.embed(t) for t in texts]
    reopened=MemoryRuntime(g,scope=r.scope)
    assert reopened.tick()['completed']==1 and reopened.projection_totals['chunks']==1
    assert reopened.projection_totals['stages']['embedding']>=0


def test_incomplete_qdrant_readback_never_acknowledges_batch(tmp_path):
    backend=Backend();original=backend.request
    def partial(method,path,**kw):
        if method=='POST' and path.endswith('/points'):return []
        return original(method,path,**kw)
    backend.request=partial;g=gateway(tmp_path,backend);r=MemoryRuntime(g,scope={'namespace':'test','principal':'operator'})
    ident=r.enqueue(source='bad-readback',content='source evidence')
    assert r.tick()['failed']==1
    with g.db() as db:
        assert db.execute('SELECT state FROM ingestion_outbox WHERE id=?',(ident,)).fetchone()[0]=='pending'
        assert db.execute('SELECT count(*) FROM records WHERE active=1').fetchone()[0]==0


def test_denied_scope_does_not_invoke_batch(tmp_path):
    class B(Backend):
        def embed_many(self,texts):pytest.fail('Embedding happened before authorization')
    g=gateway(tmp_path,B(),allow=False)
    with pytest.raises(PermissionError):g.ingest([('text','x')],source='x',namespace='test',principal='operator')


def test_bounded_cache_is_permission_scope_and_revision_separated(tmp_path,monkeypatch):
    monkeypatch.setenv('NIBLIT_MEMORY_EMBEDDING_CACHE_SIZE','2')
    class B(Backend):
        def __init__(self):super().__init__();self.calls=0
        def embed_many(self,texts):self.calls+=1;return [self.embed(t) for t in texts]
    b=B();g=gateway(tmp_path,b)
    def put(source,scope='test',actor='operator'):
        return g.ingest([('same evidence',source)],source=source,namespace=scope,principal=actor)
    put('one');put('two');assert b.calls==1 and g.last_ingestion_profile['cache_hits']==1
    put('three',scope='other');assert b.calls==2
    put('four',actor='different');assert b.calls==3
    assert len(g._embedding_cache)<=2
    g.authorize=lambda *args:False
    with pytest.raises(PermissionError):put('five')
    assert b.calls==3


def test_cache_disabled_preserves_scalar_baseline(tmp_path,monkeypatch):
    monkeypatch.setenv('NIBLIT_MEMORY_EMBEDDING_CACHE_SIZE','0')
    class B(Backend):
        def __init__(self):super().__init__();self.calls=0
        def embed_many(self,texts):self.calls+=1;return [self.embed(t) for t in texts]
    b=B();g=gateway(tmp_path,b)
    for i in range(2):g.ingest([('same','x')],source='x',namespace='test',principal='operator')
    assert b.calls==2 and not g._embedding_cache


def test_explicitly_unsupported_batch_api_uses_original_scalar(tmp_path):
    class Legacy(Backend):
        def embed_many(self,texts):raise NotImplementedError()
    g=gateway(tmp_path,Legacy())
    assert g.ingest([('text','x')],source='x',namespace='test',principal='operator')['verified']
    assert g.last_ingestion_profile['embedding_mode']=='scalar_fallback'


def test_wal_full_sync_preserves_outbox_and_single_task_owner(tmp_path):
    import sqlite3
    from modules.task_admission import TaskAuthority,AdmissionBusy
    g=gateway(tmp_path,Backend());r=MemoryRuntime(g,scope={'namespace':'test','principal':'operator'})
    with g.db() as db:
        assert db.execute('PRAGMA journal_mode=WAL').fetchone()[0]=='wal'
        assert db.execute('PRAGMA synchronous').fetchone()[0]==2
    reader=sqlite3.connect(g.path);reader.execute('BEGIN');reader.execute('SELECT count(*) FROM ingestion_outbox').fetchone()
    done=threading.Event();failures=[]
    def write():
        try:r.enqueue(source='wal-evidence',content='Original source evidence');done.set()
        except Exception as exc:failures.append(type(exc).__name__)
    t=threading.Thread(target=write);t.start();ready=done.wait(2)
    reader.rollback();reader.close();t.join()
    assert ready and not failures
    first=TaskAuthority(g);second=TaskAuthority(gateway(tmp_path,Backend()))
    token=first.acquire('core_inference')['token']
    with pytest.raises(AdmissionBusy):second.acquire('core_tool_loop')
    assert first.finish(token)['state']=='idle'
    reopened=MemoryRuntime(gateway(tmp_path,Backend()),scope=r.scope)
    assert reopened.tick()['completed']==1
    assert reopened.status()['sqlite_settings']=={'journal_mode':'wal','synchronous':2}


def test_small_event_group_batches_embedding_and_keeps_source_ids(tmp_path):
    class B(Backend):
        def __init__(self):super().__init__();self.batches=[]
        def embed_many(self,texts):self.batches.append(list(texts));return [self.embed(t) for t in texts]
    b=B();g=gateway(tmp_path,b);r=MemoryRuntime(g,scope={'namespace':'test','principal':'operator'})
    ids=[r.enqueue(source=f'source-{i}',content=f'evidence {i}') for i in range(4)]
    assert r.tick(4)['completed']==4 and b.batches==[[f'evidence {i}' for i in range(4)]]
    with g.db() as db:
        assert all(db.execute('SELECT state FROM ingestion_outbox WHERE id=?',(x,)).fetchone()[0]=='complete' for x in ids)
        assert db.execute('SELECT count(*) FROM records WHERE active=1').fetchone()[0]==4
    assert r.projection_totals['adapter_calls']==1 and r.projection_totals['prefetch_generated']==4


def test_partial_group_failure_acks_only_verified_event_then_restarts(tmp_path):
    class B(Backend):
        def __init__(self):super().__init__();self.writes=0;self.fail=True
        def embed_many(self,texts):return [self.embed(t) for t in texts]
        def request(self,method,path,**kw):
            if method=='PUT':
                self.writes+=1
                if self.fail:
                    partial=dict(kw);partial['json']={'points':kw['json']['points'][:1]}
                    super().request(method,path,**partial)
                    raise ConnectionError('ambiguous partial group outage')
            return super().request(method,path,**kw)
    b=B();g=gateway(tmp_path,b);r=MemoryRuntime(g,scope={'namespace':'test','principal':'operator'})
    ids=[r.enqueue(source=str(i),content=f'evidence {i}') for i in range(4)]
    result=r.tick(4);assert result['completed']==0 and result['failed']==4
    with g.db() as db:
        assert [db.execute('SELECT state FROM ingestion_outbox WHERE id=?',(x,)).fetchone()[0] for x in ids]==['pending']*4
        db.execute("UPDATE ingestion_outbox SET next_attempt=0 WHERE state='pending'")
    b.fail=False;reopened=MemoryRuntime(g,scope=r.scope)
    assert reopened.tick(4)['completed']==4
    with g.db() as db:assert db.execute('SELECT count(*) FROM records WHERE active=1').fetchone()[0]==4


def test_prefetch_rejects_scope_mix_without_embedding(tmp_path):
    class B(Backend):
        def embed_many(self,texts):pytest.fail('Mixed tenant input reached embedder')
    g=gateway(tmp_path,B())
    bodies=[dict(namespace='test',principal='operator',source=str(i),content='evidence',category='semantic') for i in range(2)]
    bodies[1]['namespace']='other'
    with pytest.raises(ValueError):g.prime_small_events(bodies)


def test_large_event_stays_alone_and_lease_replacement_is_not_overwritten(tmp_path):
    b=Backend();g=gateway(tmp_path,b);r=MemoryRuntime(g,scope={'namespace':'test','principal':'operator'})
    big=r.enqueue(source='big',content='a'*1500);small=r.enqueue(source='small',content='small evidence')
    assert r.tick(1)['completed']==1
    with g.db() as db:assert db.execute('SELECT state FROM ingestion_outbox WHERE id=?',(small,)).fetchone()[0]=='pending'
    original=b.request
    def changed(method,path,**kw):
        result=original(method,path,**kw)
        if method=='PUT':
            with g.db() as db:db.execute('UPDATE ingestion_outbox SET next_attempt=next_attempt+1 WHERE id=?',(small,))
        return result
    b.request=changed
    assert r.tick(1)['completed']==0
    with g.db() as db:assert db.execute('SELECT state FROM ingestion_outbox WHERE id=?',(small,)).fetchone()[0]=='processing'


def test_chunk_aware_fairness_serves_all_oldest_scopes_without_drops(tmp_path):
    from modules.memory_laboratory.gateway import market_namespace
    g=gateway(tmp_path,Backend());parent=MemoryRuntime(g)
    ids=[]
    for symbol in ('A','B','C'):
        ns=g.register_market_partition('desktop',[symbol,'fixture','5m','dry-run','account'],{'policy':'fixture'},'desktop_operator')
        child=MemoryRuntime(g,scope={'namespace':ns,'principal':'desktop_operator'})
        ids.append(child.enqueue(source=symbol,content='a'*50000,metadata={'source_type':'market_analysis','parent_namespace':'desktop'}))
    for expected in ids:
        result=parent.tick_market_partitions(8)
        assert result['completed']==1 and result['estimated_chunks_serviced']==50
        with g.db() as db:assert db.execute('SELECT state FROM ingestion_outbox WHERE id=?',(expected,)).fetchone()[0]=='complete'
    with g.db() as db:assert db.execute("SELECT count(*) FROM ingestion_outbox WHERE state='complete'").fetchone()[0]==3


def test_idle_wal_handle_retains_log_without_transaction_or_durability_change(tmp_path):
    from pathlib import Path
    g=gateway(tmp_path,Backend())
    with g.db() as db:db.execute('PRAGMA journal_mode=WAL')
    r=MemoryRuntime(g,scope={'namespace':'test','principal':'operator'})
    r.enqueue(source='persisted',content='canonical evidence')
    assert g._wal_anchor is not None and not g._wal_anchor.in_transaction
    assert Path(str(g.path)+'-wal').exists()
    with g.db() as db:
        assert db.execute('PRAGMA synchronous').fetchone()[0]==2
        result=db.execute('PRAGMA wal_checkpoint(PASSIVE)').fetchone()
        assert result[0]==0 and result[1]==result[2]
    assert r.tick()['completed']==1
    backup=tmp_path/'wal-backup.sqlite3';r.backup(backup)
    import sqlite3
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT state FROM ingestion_outbox WHERE source='persisted'").fetchone()[0]=='complete'
    g.close();assert g._wal_anchor is None


def test_group_publication_matches_original_identities_and_bounds(tmp_path):
    bodies=[dict(namespace='test',principal='operator',source=str(i),content=f'evidence {i}',category='semantic') for i in range(4)]
    g=gateway(tmp_path/'batch',Backend());reference=gateway(tmp_path/'single',Backend())
    result=g.ingest_small_events(bodies)
    for body,receipt in zip(bodies,result['results']):
        original=dict(body);text=original.pop('content')
        expected=reference.ingest([(text,body['source']+'#offset=0')],**original)
        assert receipt['ids']==expected['ids'] and receipt['collection']==expected['collection'] and receipt['version']==expected['version']
    with pytest.raises(ValueError):g.ingest_small_events(bodies+[bodies[0]])
    with pytest.raises(ValueError):g.ingest_small_events([bodies[0],bodies[0]])
    bodies[1]['namespace']='other'
    with pytest.raises(ValueError):g.ingest_small_events(bodies)


def test_group_cancel_before_activation_keeps_every_event_unacknowledged(tmp_path):
    flag=threading.Event()
    class B(Backend):
        def request(self,method,path,**kw):
            result=super().request(method,path,**kw)
            if method=='PUT':flag.set()
            return result
    g=gateway(tmp_path,B());r=MemoryRuntime(g,scope={'namespace':'test','principal':'operator'})
    for i in range(4):r.enqueue(source=str(i),content=f'evidence {i}')
    r.stop_event=flag
    assert r.tick(4)['completed']==0
    with g.db() as db:
        assert db.execute("SELECT count(*) FROM ingestion_outbox WHERE state='complete'").fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM records WHERE active=1').fetchone()[0]==0


def test_transaction_local_lexical_lookup_preserves_duplicates_and_reinsertion(tmp_path):
    g=gateway(tmp_path,Backend())
    with g.db() as db:
        db.execute('BEGIN IMMEDIATE')
        db.executemany('INSERT INTO lexical(id,content) VALUES(?,?)',[('same','first'),('same','second'),('other','preserved')])
        g._prepare_lexical_rowids(db)
        g._delete_lexical(db,'same')
        assert db.execute("SELECT count(*) FROM lexical WHERE id='same'").fetchone()[0]==0
        g._insert_lexical(db,'same','replacement')
        assert db.execute('SELECT rid FROM lexical_rowids WHERE id=?',('same',)).fetchone()[0]==db.execute("SELECT rowid FROM lexical WHERE id='same'").fetchone()[0]
        g._delete_lexical(db,'same')
        assert db.execute('SELECT id FROM lexical').fetchall()[0][0]=='other'
    with g.db() as db:
        assert db.execute("SELECT count(*) FROM sqlite_temp_master WHERE name='lexical_rowids'").fetchone()[0]==0
        assert db.execute("SELECT count(*) FROM sqlite_master WHERE name='lexical_rowids'").fetchone()[0]==0
