import hashlib,json
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from modules.permission_manager import PermissionManager
from modules.task_admission import TaskAuthority,AdmissionBusy
from test_memory_laboratory_gateway import Backend,gateway

@pytest.fixture
def control(tmp_path):
    g=gateway(tmp_path,Backend());pm=PermissionManager();pm.path=str(tmp_path/'permissions.json')
    pm.perms={'command.operator.autonomous_learn_start':False,'trading.execute':False}
    (tmp_path/'permissions.json').write_text(json.dumps(pm.perms));authority=TaskAuthority(g)
    return pm,g,authority

def proposed(control):
    pm,g,_=control;ident=pm.propose_learning(g,'SQLite outbox durability','Verify current source evidence without enabling background learning.')
    item=next(x for x in pm.learning_requests(g,'core-a') if x['id']==ident)
    return ident,item

def approved(control):
    ident,item=proposed(control);pm,g,a=control
    pm.decide_learning(g,ident,item['spec_hash'],'approve_once','core-a')
    token=a.acquire('autonomous_step')['token'];pm.bind_learning(g,ident,'core-a',token)
    return ident,token

def test_proposal_allowed_while_start_denied_no_ownership_or_file_changes(control):
    pm,g,a=control;before=open(pm.path,'rb').read();ident,item=proposed(control)
    assert item['state']=='pending' and not pm.check('command.operator.autonomous_learn_start')
    assert a.status()['state']=='idle' and open(pm.path,'rb').read()==before
    assert pm.propose_learning(g,item['spec']['topic'],item['spec']['justification'])==ident
    assert item['spec']['limits']['cycles']==1 and item['spec']['trading_authority'] is False

def test_deny_never_grants_or_runs_and_approval_replay_rejected(control):
    pm,g,a=control;ident,item=proposed(control);pm.decide_learning(g,ident,item['spec_hash'],'deny','core-a')
    with pytest.raises(PermissionError):pm.decide_learning(g,ident,item['spec_hash'],'approve_once','core-a')
    assert a.status()['state']=='idle' and not pm.check('command.operator.autonomous_learn_start')

def test_forged_hash_or_material_change_requires_fresh_approval(control):
    pm,g,_=control;ident,item=proposed(control)
    with pytest.raises(PermissionError):pm.decide_learning(g,ident,'0'*64,'approve_once','core-a')
    altered=item['spec'];altered['limits']['model_calls']=2
    with g.db() as db:db.execute('UPDATE task_authorizations SET spec=? WHERE id=?',(json.dumps(altered),ident))
    with pytest.raises(PermissionError):pm.decide_learning(g,ident,item['spec_hash'],'approve_once','core-a')

def test_scoped_once_grant_has_tool_budget_and_preserves_default_denial(control):
    pm,g,a=control;before=open(pm.path,'rb').read();ident,token=approved(control)
    pm.authorize_learning_stage(g,ident,'core-a',token,'local_gguf')
    with pytest.raises(PermissionError):pm.authorize_learning_stage(g,ident,'core-a',token,'local_gguf')
    for forbidden in ('workspace_write','trading.submit','paid_model','shell.execute'):
        with pytest.raises(PermissionError):pm.authorize_learning_stage(g,ident,'core-a',token,forbidden)
    assert not pm.check('command.operator.autonomous_learn_start') and open(pm.path,'rb').read()==before
    pm.finish_learning(g,ident,'completed',{'model_calls':1,'truth_verified':False})
    with pytest.raises(PermissionError):pm.authorize_learning_stage(g,ident,'core-a',token,'memory.observation')
    a.finish(token)

def test_approval_binding_requires_original_owner_and_cannot_be_consumed_twice(control):
    pm,g,a=control;ident,item=proposed(control);pm.decide_learning(g,ident,item['spec_hash'],'approve_once','core-a')
    with pytest.raises(PermissionError):pm.bind_learning(g,ident,'core-a','x'*40)
    token=a.acquire('core_inference')['token']
    with pytest.raises(PermissionError):pm.bind_learning(g,ident,'core-a',token)
    a.finish(token);token=a.acquire('autonomous_step')['token'];pm.bind_learning(g,ident,'core-a',token)
    with pytest.raises(PermissionError):pm.bind_learning(g,ident,'core-a',token)
    with pytest.raises(PermissionError):pm.authorize_learning_stage(g,ident,'other-runtime',token,'local_gguf')
    pm.finish_learning(g,ident,'failed');a.finish(token)

@pytest.mark.parametrize('terminal',['completed','failed','cancelled','expired','interrupted'])
def test_each_terminal_state_revokes_grant(control,terminal):
    pm,g,a=control;ident,token=approved(control);pm.finish_learning(g,ident,terminal)
    with pytest.raises(PermissionError):pm.authorize_learning_stage(g,ident,'core-a',token,'workspace_read')
    assert a.status()['state']=='active' # PM never clears inference ownership.
    a.finish(token)

def test_expiry_refuses_new_generation_but_existing_ack_can_finish(control):
    pm,g,a=control;ident,token=approved(control);a.delegate(token,'a'*32)
    with g.db() as db:db.execute('UPDATE task_authorizations SET expires=0 WHERE id=?',(ident,))
    with pytest.raises(AdmissionBusy):a.delegate(token,'b'*32)
    with pytest.raises(PermissionError):pm.authorize_learning_stage(g,ident,'core-a',token,'memory.observation')
    assert a.delegate(token,'a'*32,complete=True)['state']=='complete'
    assert next(x for x in pm.learning_requests(g,'core-a') if x['id']==ident)['state']=='expired'
    a.finish(token)

def test_cancellation_wins_over_late_provider_success(control):
    pm,g,a=control;ident,token=approved(control);pm.finish_learning(g,ident,'cancelled');pm.finish_learning(g,ident,'completed',{'answer':'late'})
    assert next(x for x in pm.learning_requests(g,'core-a') if x['id']==ident)['state']=='cancelled'
    with pytest.raises(AdmissionBusy):a.delegate(token,'c'*32)
    a.finish(token)

def test_restart_retains_pending_but_revokes_old_runtime_grant(control):
    pm,g,a=control;ident,token=approved(control);pending=pm.propose_learning(g,'Task cancellation ownership','Review acknowledged delivery boundaries.')
    rows=pm.learning_requests(g,'core-b');states={x['id']:x['state'] for x in rows}
    assert states[ident]=='interrupted' and states[pending]=='pending'
    assert a.status()['state']=='active';a.finish(token)

def test_unapproved_native_cycle_performs_no_recall_research_model_or_write(monkeypatch):
    from modules.native_evidence_learning import run_cycle
    monkeypatch.setenv('NIBLIT_NATIVE_LOCAL_TRANSPORT','local_gguf');g=Mock();infer=Mock();research=Mock()
    result=run_cycle(0,stopped=lambda:False,gateway=g,infer=infer,research=research)
    assert result['state']=='awaiting_approval';g.retrieve.assert_not_called();g.ingest.assert_not_called();infer.assert_not_called();research.assert_not_called()

def test_core_approval_route_rejects_foreign_origin_wrong_nonce_and_replay(control,monkeypatch):
    import server
    from fastapi.testclient import TestClient
    pm,g,a=control;ident,item=proposed(control);engine=Mock();engine.start.return_value=True
    monkeypatch.setattr(server,'_learning_control',(pm,g,'core-a','operator-session-nonce'))
    monkeypatch.setattr(server,'get_core',lambda:SimpleNamespace(autonomous_engine=engine))
    client=TestClient(server.app);url=f'/api/learning/proposals/{ident}/decision';body={'spec_hash':item['spec_hash'],'decision':'approve_once'}
    assert client.post(url,json=body,headers={'origin':'https://untrusted.invalid','x-niblit-operator-nonce':'operator-session-nonce'}).status_code==403
    assert client.post(url,json=body,headers={'origin':'http://localhost:5173','x-niblit-operator-nonce':'forged'}).status_code==403
    engine.start.assert_not_called()
    headers={'origin':'http://localhost:5173','x-niblit-operator-nonce':'operator-session-nonce'}
    response=client.post(url,json=body,headers=headers);assert response.status_code==200 and response.json()['cycles']==1
    assert engine.start.call_args.kwargs['max_cycles']==1 and not pm.check('command.operator.autonomous_learn_start')
    assert client.post(url,json=body,headers=headers).status_code==403
    assert engine.start.call_count==1

def test_bg_status_observes_bindings_without_invoking_engines(monkeypatch):
    import server
    from fastapi.testclient import TestClient
    teacher=Mock();trainer=Mock();core=SimpleNamespace(self_teacher=teacher,brain=SimpleNamespace(brain_trainer=trainer),autonomous_engine=None)
    monkeypatch.setattr(server,'get_core',lambda:core);monkeypatch.setattr(server,'_get_unified_runtime',lambda:None)
    result=TestClient(server.app).get('/api/bg_status').json()
    assert result['learning_components']['self_teacher']['bound'] and result['learning_components']['brain_trainer']['bound']
    assert not teacher.mock_calls and not trainer.mock_calls


@pytest.mark.parametrize('failure',[False,True])
def test_original_ale_worker_consumes_one_approval_and_revokes(control,monkeypatch,failure):
    from contextlib import contextmanager
    from test_ale_lifecycle import engine
    from modules import task_admission as admission
    pm,g,a=control;ident,item=proposed(control);pm.decide_learning(g,ident,item['spec_hash'],'approve_once','core-a')
    e=engine();e._cycle_count=0;e.startup_delay=0;e.poll_interval=1;e.self_teacher=None;e.brain_trainer=None
    monkeypatch.setenv('NIBLIT_ALE_LOCAL_SAFE','1')
    @contextmanager
    def lease(owner):
        token=a.acquire(owner)['token'];marker=admission._lease.set(token)
        try:yield
        finally:a.finish(token);admission._lease.reset(marker)
    monkeypatch.setattr(admission,'admitted',lease)
    calls=[]
    def study(*args,**kw):
        kw['authorize']('local_gguf');calls.append(kw['topic'])
        if failure:raise RuntimeError('controlled native step failure')
        return {'state':'candidate_for_review','model_calls':1,'truth_verified':False}
    monkeypatch.setattr('modules.native_evidence_learning.run_cycle',study)
    assert e.start(max_cycles=1,task_authorization=(pm,g,ident,'core-a'));e.learning_thread.join(5)
    assert not e.learning_thread.is_alive() and calls==[item['spec']['topic']]
    assert a.status()['state']=='idle' and not pm.check('command.operator.autonomous_learn_start')
    assert next(x for x in pm.learning_requests(g,'core-a') if x['id']==ident)['state']==('failed' if failure else 'completed')


def test_existing_ale_busy_admission_revokes_unused_approval(control,monkeypatch):
    from contextlib import contextmanager
    from test_ale_lifecycle import engine
    pm,g,a=control;ident,item=proposed(control);pm.decide_learning(g,ident,item['spec_hash'],'approve_once','core-a')
    busy=a.acquire('core_inference')['token'];e=engine();e._cycle_count=0;e.startup_delay=0;e.poll_interval=1;e.self_teacher=None;e.brain_trainer=None
    monkeypatch.setenv('NIBLIT_ALE_LOCAL_SAFE','1')
    @contextmanager
    def lease(owner):
        a.acquire(owner);yield
    monkeypatch.setattr('modules.task_admission.admitted',lease)
    study=Mock();monkeypatch.setattr('modules.native_evidence_learning.run_cycle',study)
    assert e.start(max_cycles=1,task_authorization=(pm,g,ident,'core-a'));e.learning_thread.join(5)
    assert next(x for x in pm.learning_requests(g,'core-a') if x['id']==ident)['state']=='failed'
    assert a.status()['owner']=='core_inference';study.assert_not_called();a.finish(busy)



def test_single_generation_budget_is_enforced_at_original_cloud_delegation(control):
    pm,g,a=control;ident,token=approved(control);a.delegate(token,'e'*32);a.delegate(token,'e'*32,complete=True)
    with pytest.raises(AdmissionBusy,match='budget exhausted'):a.delegate(token,'f'*32)
    pm.finish_learning(g,ident,'completed');a.finish(token)


def test_denied_opportunity_is_not_repeated_without_explicit_renewal(control):
    pm,g,_=control;ident,item=proposed(control);pm.decide_learning(g,ident,item['spec_hash'],'deny','core-a')
    assert pm.propose_learning(g,item['spec']['topic'],item['spec']['justification'])==ident
    assert pm.propose_learning(g,item['spec']['topic'],item['spec']['justification'],renew=True)!=ident


def test_sync_background_learning_keeps_queue_and_only_prepares_proposal():
    import ast,logging,threading
    from pathlib import Path
    tree=ast.parse((Path(__file__).parents[1]/'niblit_core.py').read_text(encoding='utf-8'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='NiblitCore')
    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_auto_research_loop')
    namespace={'log':logging.getLogger('approval-test')};exec(compile(ast.Module(body=[method],type_ignores=[]),'original_core_learning_loop','exec'),namespace)
    researcher=Mock();db=Mock();db.get_learning_queue.return_value=[{'topic':'SQLite durability','status':'queued'}]
    obj=SimpleNamespace(running=True,_shutdown_event=threading.Event(),autonomous_engine=None,db=db,researcher=researcher,config=SimpleNamespace(research_queue_limit=3),_prepare_queued_learning=Mock())
    def stop(seconds):obj.running=False;return False
    obj._sleep_with_shutdown=stop
    namespace['_auto_research_loop'](obj)
    obj._prepare_queued_learning.assert_called_once_with('SQLite durability');researcher.search.assert_not_called()
    assert not db.store_research.called



def test_idea_generator_construction_does_not_start_learning_and_manual_plan_still_works():
    from modules.self_idea_generator import SelfIdeaGenerator
    db=Mock();obj=SelfIdeaGenerator(db=db)
    assert obj._thread is None and not obj.running
    assert 'Implementation plan' in obj.generate_plan('source-grounded review')
    db.add_fact.assert_called_once()


def test_core_initialization_constructs_learning_components_without_autostart():
    import ast
    from pathlib import Path
    tree=ast.parse((Path(__file__).parents[1]/'niblit_core.py').read_text(encoding='utf-8'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='NiblitCore')
    init=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_init_learning_systems')
    starts=[n for n in ast.walk(init) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='start' and isinstance(n.func.value,ast.Attribute) and n.func.value.attr in ('background_trainer','slsa_engine')]
    assert starts==[]
