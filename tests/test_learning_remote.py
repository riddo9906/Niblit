import copy,hashlib,json
from unittest.mock import Mock
import pytest
from test_memory_laboratory_gateway import Backend,gateway,recall
from modules.memory_laboratory.runtime import MemoryRuntime
from modules.native_evidence_learning import run_cycle as _run_cycle
from functools import partial
run_cycle=partial(_run_cycle,authorize=lambda operation:None)

class Remote:
    _url='https://approved.example.invalid'
    def __init__(self):self.points={};self.calls=0;self.offline=False
    def canonical_project(self,collection,points,**kw):
        self.calls+=1
        if self.offline:raise ConnectionError('controlled outage')
        for p in points:self.points[p['id']]=copy.deepcopy(p)
        return points
    def canonical_request(self,method,collection,*,body=None,suffix=''):
        return [self.points[i] for i in body['ids'] if i in self.points]

def synthetic(g):
    text='Synthetic v201: the sample envelope color is amber. Not historical private memory.'
    meta={'source_type':'synthetic_acceptance','sensitivity':'public','remote_projection':True,'provenance':{'remote_sync':'synthetic_approved'}}
    return g.ingest([(text,'synthetic://v201/envelope#0')],source='synthetic://v201/envelope',namespace='test',principal='operator',metadata=meta)

def test_remote_original_identity_payload_restart_and_scope(tmp_path,monkeypatch):
    monkeypatch.setenv('NIBLIT_QDRANT_REMOTE_SCOPES','test');backend=Backend();g=gateway(tmp_path,backend);synthetic(g);remote=Remote()
    first=g.project_remote(source='synthetic://v201/envelope',namespace='test',principal='operator',manager=remote)
    assert first['verified']==1 and remote.calls==1
    ident=next(iter(remote.points));assert remote.points[ident]==backend.points[ident]
    reopened=gateway(tmp_path,backend)
    assert reopened.project_remote(source='synthetic://v201/envelope',namespace='test',principal='operator',manager=remote)==first
    assert remote.calls==1
    assert reopened.read_remote([ident],namespace='test',principal='operator',manager=remote)['results']
    assert not reopened.read_remote([ident],namespace='test',principal='other',manager=remote)['results']
    monkeypatch.setenv('NIBLIT_QDRANT_REMOTE_SCOPES','other')
    with pytest.raises(PermissionError):reopened.project_remote(source='synthetic://v201/envelope',namespace='test',principal='operator',manager=remote)

def test_cloud_outage_preserves_local_recall_and_retry(tmp_path,monkeypatch):
    monkeypatch.setenv('NIBLIT_QDRANT_REMOTE_SCOPES','test');g=gateway(tmp_path,Backend());synthetic(g);remote=Remote();remote.offline=True
    with pytest.raises(ConnectionError):g.project_remote(source='synthetic://v201/envelope',namespace='test',principal='operator',manager=remote)
    assert g.retrieve('sample envelope',namespace='test',principal='operator')['results']
    remote.offline=False;assert g.project_remote(source='synthetic://v201/envelope',namespace='test',principal='operator',manager=remote)['verified']==1

def test_private_or_unapproved_history_not_transmitted(tmp_path,monkeypatch):
    monkeypatch.setenv('NIBLIT_QDRANT_REMOTE_SCOPES','test');g=gateway(tmp_path,Backend());g.ingest([('private history','history:0')],source='history',namespace='test',principal='operator');remote=Remote()
    with pytest.raises(PermissionError):g.project_remote(source='history',namespace='test',principal='operator',manager=remote)
    assert remote.calls==0

def test_remote_rechecks_permissions_before_network(tmp_path,monkeypatch):
    monkeypatch.setenv('NIBLIT_QDRANT_REMOTE_SCOPES','test');g=gateway(tmp_path,Backend());synthetic(g);g.authorize=lambda *a:False;remote=Remote()
    with pytest.raises(PermissionError):g.project_remote(source='synthetic://v201/envelope',namespace='test',principal='operator',manager=remote)
    assert remote.calls==0

def test_remote_rejects_altered_readback(tmp_path,monkeypatch):
    monkeypatch.setenv('NIBLIT_QDRANT_REMOTE_SCOPES','test');g=gateway(tmp_path,Backend());synthetic(g);remote=Remote();g.project_remote(source='synthetic://v201/envelope',namespace='test',principal='operator',manager=remote)
    ident=next(iter(remote.points));remote.points[ident]['payload']['access_principals']=['stranger']
    assert not g.read_remote([ident],namespace='test',principal='operator',manager=remote)['results']

def test_existing_manager_schema_and_unscoped_export_guards(tmp_path):
    from modules.hybrid_qdrant_manager import HybridQdrantManager
    from modules.config.qdrant_config import QdrantConfig
    m=HybridQdrantManager(QdrantConfig(url='https://approved.example.invalid',api_key='not-a-real-secret',collection='niblit',prefix='niblit'))
    m._embed=Mock(side_effect=AssertionError('No remote embedding/download'))
    assert m.upsert('private history',{},'legacy') is False
    assert m.insert('private history',{'vector':[1,2,3]}) is False
    assert m.query('private question','legacy')==[]
    g=gateway(tmp_path,Backend());synthetic(g);p=next(iter(g.backend.points.values()));collection=g.config.collection('semantic',3)
    m.canonical_request=Mock(return_value={'config':{'params':{'vectors':{'size':7,'distance':'Cosine'}}}})
    with pytest.raises(ValueError,match='schema incompatible'):m.canonical_project(collection,[p],dimension=3,distance='Cosine')
    assert m.canonical_request.call_count==1

def test_remote_outbox_original_worker_retries_without_local_rollback(tmp_path,monkeypatch):
    monkeypatch.setenv('NIBLIT_QDRANT_REMOTE_SCOPES','test');g=gateway(tmp_path,Backend());r=MemoryRuntime(g,scope={'namespace':'test','principal':'operator'});remote=Remote()
    monkeypatch.setattr('modules.hybrid_qdrant_manager.get_hybrid_manager',lambda:remote)
    ident=r.enqueue(source='synthetic://v201/envelope',content='Synthetic amber envelope',metadata={'source_type':'synthetic_acceptance','sensitivity':'public','remote_projection':True,'provenance':{'remote_sync':'synthetic_approved'}})
    assert r.tick()['completed']==1
    remote.offline=True;assert r.tick_remote()['failed']==1
    with g.db() as db:
        assert db.execute('SELECT state FROM ingestion_outbox WHERE id=?',(ident,)).fetchone()[0]=='complete'
        db.execute('UPDATE remote_projection_outbox SET next_attempt=0')
    remote.offline=False;assert MemoryRuntime(g,scope=r.scope).tick_remote()['verified']==1
    assert r.tick_remote()['verified']==0

def test_gap_research_local_reasoning_teacher_and_source_only_trainer(monkeypatch):
    monkeypatch.setenv('NIBLIT_NATIVE_LOCAL_TRANSPORT','local_gguf');g=Mock();g.retrieve.return_value={'results':[],'issues':[]};infer=Mock(return_value='The source describes a durable outbox [1].');teacher=Mock();teacher.assess_evidence.return_value={'truth_verified':False};trainer=Mock()
    text='A canonical SQLite outbox retains source evidence.';source={'id':'source1','content':text,'citation':'workspace://runtime.py','source_type':'workspace_read','source_hash':hashlib.sha256(text.encode()).hexdigest()}
    report=run_cycle(0,stopped=lambda:False,gateway=g,infer=infer,research=lambda q:[source],teacher=teacher,trainer=trainer)
    assert report['state']=='candidate_for_review' and report['research_performed'] and report['trainer_source_observations']==1
    assert not report['truth_verified'] and not report['weights_trained']
    assert 'SOURCE OBSERVATION' in trainer.ingest_research.call_args.args[1]
    assert infer.call_args.kwargs['max_tokens']==256

def test_cancellation_after_research_blocks_model_and_memory(monkeypatch):
    monkeypatch.setenv('NIBLIT_NATIVE_LOCAL_TRANSPORT','local_gguf');g=Mock();g.retrieve.return_value={'results':[],'issues':[]};stop=[False];infer=Mock()
    def research(topic):stop[0]=True;return []
    report=run_cycle(0,stopped=lambda:stop[0],gateway=g,infer=infer,research=research)
    assert report['state']=='stopped_after_research';infer.assert_not_called();g.ingest.assert_not_called()

def test_selfteacher_review_does_not_promote_candidate():
    from modules.self_teacher import SelfTeacher
    db=Mock();db.get_fact.return_value=None;teacher=SelfTeacher(db=db)
    result=teacher.assess_evidence({'topic':'SQLite durability','citation_check':True})
    assert not result['truth_verified'] and len(teacher._review_queue)==1
    assert all(x.args[0]=='self_teacher:review_queue' for x in db.add_fact.call_args_list)
