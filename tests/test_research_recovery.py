import asyncio,json,io,urllib.error,threading
import httpx,pytest
from modules.task_admission import TaskAuthority,AdmissionBusy,AdmissionUncertain,admitted,delegation_headers
from modules.server_manager import ServerManager
from modules.llm_tool_loop import LlmToolLoop,ToolCallError

@pytest.fixture
def authority(tmp_path,monkeypatch):
    a=TaskAuthority(ServerManager(tmp_path/'authority.sqlite'));key=tmp_path/'key';key.write_text('synthetic-test-key-with-at-least-32-chars')
    monkeypatch.setenv('NIBLIT_SHARED_ADMISSION','1');monkeypatch.setenv('NIBLIT_PORTAL_GGUF_KEY_FILE',str(key));monkeypatch.setenv('NIBLIT_MEMORY_LAB_ENABLED','0')
    real=httpx.Client
    def handler(req):
        b=json.loads(req.content)
        try:
            if req.url.path.endswith('acquire'):r=a.acquire(b['owner'])
            else:r=a.finish(b['token'],b.get('uncertain',False))
            return httpx.Response(200,json=r)
        except AdmissionBusy:return httpx.Response(409,json={'error':'busy'})
    monkeypatch.setattr('modules.task_admission.httpx.Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    return a

def test_model_tool_model_keeps_one_parent(authority,monkeypatch):
    a=authority;tokens=[];turns=[]
    class Executor:
        def niblit_status(self):
            assert a.status()['owner']=='core_tool_loop'
            with pytest.raises(AdmissionBusy):a.acquire('portal_chat')
            return {'status':'fixture-only'}
    def cloud(req,timeout):
        token=next(v for k,v in req.header_items() if k.lower()=='x-niblit-task-token');tokens.append(token)
        job=('%032x'%(len(tokens)));a.delegate(token,job);a.delegate(token,job,complete=True)
        turns.append(json.loads(req.data))
        message={'content':'fixture final'} if len(tokens)==2 else {'content':None,'tool_calls':[{'id':'c1','type':'function','function':{'name':'runtime_status','arguments':'{}'}}]}
        return io.BytesIO(json.dumps({'choices':[{'message':message}]}).encode())
    monkeypatch.setattr('modules.llm_tool_loop.urllib.request.urlopen',cloud)
    result=LlmToolLoop(executor=Executor(),max_loop_calls=2).chat([{'role':'user','content':'Read status'}])
    assert result['text']=='fixture final' and result['trace'][0]['tool']=='runtime_status'
    assert len(tokens)==2 and tokens[0]==tokens[1] and a.status()['state']=='idle'
    assert any(m['role']=='tool' for m in turns[1]['messages'])

def test_uncertain_child_cannot_report_success(authority):
    a=authority
    with pytest.raises(AdmissionUncertain):
        with admitted('core_tool_loop'):
            token=delegation_headers()['x-niblit-task-token'];a.delegate(token,'a'*32);a.delegate(token,'a'*32,complete=True,uncertain=True)
    assert a.status()['state']=='quarantined'

def test_cancelled_owner_quarantines(authority):
    with pytest.raises(asyncio.CancelledError):
        with admitted('core_tool_loop'):raise asyncio.CancelledError()
    assert authority.status()['state']=='quarantined'

def test_cloud_outage_is_not_retried(authority,monkeypatch):
    calls=[]
    def fail(*a,**kw):calls.append(True);raise urllib.error.URLError('controlled outage')
    monkeypatch.setattr('modules.llm_tool_loop.urllib.request.urlopen',fail)
    with pytest.raises(ToolCallError):LlmToolLoop().chat([{'role':'user','content':'fixture'}])
    assert len(calls)==1 and authority.status()['state']=='quarantined'

def test_cancelled_async_waiter_does_not_release_running_worker(authority):
    a=authority;started=threading.Event();release=threading.Event();done=threading.Event()
    def worker():
        with admitted('core_tool_loop'):
            started.set();release.wait(5)
        done.set()
    async def exercise():
        task=asyncio.create_task(asyncio.to_thread(worker))
        await asyncio.to_thread(started.wait,2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert a.status()['state']=='active'
        with pytest.raises(AdmissionBusy):a.acquire('portal_chat')
        release.set();assert await asyncio.to_thread(done.wait,2)
    asyncio.run(exercise());assert a.status()['state']=='idle'


@pytest.mark.parametrize('busy_port,busy_model',[(5000,False),(None,True),(None,False)])
def test_existing_recovery_requires_stopped_producers_and_idle_model(tmp_path,monkeypatch,busy_port,busy_model):
    import importlib.util,sys
    from pathlib import Path
    path=Path(__file__).resolve().parents[1]/'scripts/runtime-task-status.py'
    spec=importlib.util.spec_from_file_location('recovery_owner_test',path);recovery=importlib.util.module_from_spec(spec);spec.loader.exec_module(recovery)
    g=ServerManager(tmp_path/'a.sqlite');a=TaskAuthority(g);token=a.acquire('core_inference')['token'];a.delegate(token,'a'*32);a.delegate(token,'a'*32,complete=True,uncertain=True)
    with g.db() as db:db.execute('CREATE TABLE sentinel(value TEXT)');db.execute("INSERT INTO sentinel VALUES('source evidence')")
    monkeypatch.setattr(recovery,'ROOT',tmp_path);monkeypatch.setattr(recovery,'dotenv_values',lambda *args:{'NIBLIT_MEMORY_LAB_LEDGER':str(g.path)})
    private=tmp_path/'runtime/client-portal';private.mkdir(parents=True);(private/'gguf-api-key').write_text('synthetic-test-key-with-at-least-32-chars')
    class Sock:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def settimeout(self,*args):pass
        def connect_ex(self,target):return 0 if target[1] in (busy_port,8766) else 1
    monkeypatch.setattr(recovery.socket,'socket',lambda:Sock())
    class Response:
        def raise_for_status(self):pass
        def json(self):return [{'is_processing':busy_model}]
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,*args,**kwargs):return Response()
    monkeypatch.setattr(recovery.httpx,'Client',Client)
    monkeypatch.setattr(sys,'argv',['runtime-task-status.py','--recover','--confirm-producers-stopped'])
    if busy_port or busy_model:
        with pytest.raises(SystemExit):recovery.main()
        assert a.status()['state']=='quarantined'
    else:
        recovery.main();assert a.status()['state']=='idle'
        assert a.acquire('core_inference')['token']!=token
    with g.db() as db:assert db.execute('SELECT value FROM sentinel').fetchone()[0]=='source evidence'


def test_definite_cloud_rejection_releases_owner_without_retry(authority,monkeypatch):
    calls=[]
    def rejected(*args,**kwargs):
        calls.append(True);raise urllib.error.HTTPError('http://fixture',400,'rejected',{},io.BytesIO(b'context rejected'))
    monkeypatch.setattr('modules.llm_tool_loop.urllib.request.urlopen',rejected)
    with pytest.raises(ToolCallError):LlmToolLoop().chat([{'role':'user','content':'fixture'}])
    assert calls==[True] and authority.status()['state']=='idle'

def test_forced_final_failure_is_not_swallowed(monkeypatch):
    from test_llm_tool_loop import FakeLoop,_tc
    monkeypatch.setenv('NIBLIT_SHARED_ADMISSION','0');monkeypatch.setenv('NIBLIT_MEMORY_LAB_ENABLED','0')
    loop=FakeLoop([{'choices':[{'message':{'content':None,'tool_calls':[_tc('runtime_status')]}}]},ToolCallError('controlled final outage')]);loop.max_loop_calls=1
    with pytest.raises(ToolCallError):loop.chat([{'role':'user','content':'fixture'}])
    assert len(loop.requests)==2

def test_outer_timeout_default_and_operator_override(monkeypatch):
    from niblit_brain import NiblitCloudBrain
    monkeypatch.delenv('NIBLIT_LLAMA_SERVER_TIMEOUT',raising=False)
    assert NiblitCloudBrain().timeout==300
    assert NiblitCloudBrain(timeout=7).timeout==7


def test_request_tool_selection_only_narrows_existing_registry():
    loop=LlmToolLoop()
    assert loop.tool_schemas(['runtime_status'])[0]['function']['name']=='runtime_status'
    for names in (['not_registered'],['runtime_status','runtime_status']):
        with pytest.raises(ToolCallError):loop.tool_schemas(names)
    assert loop.tool_schemas([])==[]

def test_required_choice_is_initial_only(monkeypatch):
    from test_llm_tool_loop import FakeLoop,_tc
    monkeypatch.setenv('NIBLIT_SHARED_ADMISSION','0');monkeypatch.setenv('NIBLIT_MEMORY_LAB_ENABLED','0')
    loop=FakeLoop([{'choices':[{'message':{'tool_calls':[_tc('runtime_status')]}}]},{'choices':[{'message':{'content':'observed'}}]}])
    assert loop.chat([{'role':'user','content':'fixture'}],tool_choice='required')['text']=='observed'
    assert loop.requests[0]['tool_choice']=='required' and loop.requests[1]['tool_choice'] is None


def test_actual_core_handler_cancel_keeps_worker_owned(authority,monkeypatch):
    import server,niblit_brain
    import modules.core_tool_runtime as runtime
    started=threading.Event();release=threading.Event();done=threading.Event()
    class Loop:
        def chat(self,**kwargs):
            with admitted('core_tool_loop'):
                started.set();release.wait(5)
            done.set();return {'text':'fixture','trace':[]}
    monkeypatch.setattr(server,'get_core',lambda:object())
    monkeypatch.setattr(niblit_brain,'get_niblit_cloud_brain',lambda:object())
    monkeypatch.setattr(runtime,'get_governed_tool_loop',lambda *args:Loop())
    async def exercise():
        body=server.InferenceChatBody(enable_tools=True,messages=[{'role':'user','content':'fixture'}])
        task=asyncio.create_task(server.inference_chat(body))
        assert await asyncio.to_thread(started.wait,2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert authority.status()['state']=='active'
        release.set();assert await asyncio.to_thread(done.wait,2)
    asyncio.run(exercise());assert authority.status()['state']=='idle'

@pytest.mark.parametrize('kind,status',[('busy',409),('uncertain',503)])
def test_core_handler_reports_inference_ownership_failure(monkeypatch,kind,status):
    import server,niblit_brain
    import modules.core_tool_runtime as runtime
    class Loop:
        def chat(self,**kwargs):raise AdmissionBusy('fixture busy') if kind=='busy' else AdmissionUncertain('fixture uncertain')
    monkeypatch.setattr(server,'get_core',lambda:object())
    monkeypatch.setattr(niblit_brain,'get_niblit_cloud_brain',lambda:object())
    monkeypatch.setattr(runtime,'get_governed_tool_loop',lambda *args:Loop())
    body=server.InferenceChatBody(enable_tools=True,messages=[{'role':'user','content':'fixture'}])
    response=asyncio.run(server.inference_chat(body));assert response.status_code==status


def test_tool_loop_honors_requested_generation_budget(monkeypatch):
    from test_llm_tool_loop import FakeExecutor,_tc
    from modules.llm_tool_loop import make_runtime_status_tool
    monkeypatch.setenv('NIBLIT_SHARED_ADMISSION','0');monkeypatch.setenv('NIBLIT_MEMORY_LAB_ENABLED','0')
    budgets=[]
    class Loop(LlmToolLoop):
        def _cloud_chat(self,messages,model,**kwargs):
            budgets.append(kwargs['max_tokens'])
            return {'choices':[{'message':{'tool_calls':[_tc('runtime_status')]}}]} if len(budgets)==1 else {'choices':[{'message':{'content':'observed'}}]}
    assert Loop(executor=FakeExecutor()).chat([{'role':'user','content':'fixture'}],max_tokens=128)['text']=='observed'
    assert budgets==[128,128]
    assert make_runtime_status_tool()['function']['parameters']['additionalProperties'] is False


def test_cancel_after_generation_schedules_no_tools_or_more_generations(authority):
    from modules.task_admission import TaskCancelled
    from test_llm_tool_loop import FakeExecutor,_tc
    event=threading.Event();calls=[];executor=FakeExecutor()
    class Loop(LlmToolLoop):
        def _cloud_chat(self,*args,**kwargs):
            calls.append(True);event.set()
            return {'choices':[{'message':{'tool_calls':[_tc('runtime_status')]}}]}
    with pytest.raises(TaskCancelled):Loop(executor=executor).chat([{'role':'user','content':'fixture'}],cancel_event=event)
    assert calls==[True] and executor.status_calls==0 and authority.status()['state']=='idle'

def test_nested_cancellation_reuses_parent_and_keeps_ambiguous_failure(authority):
    from modules.task_admission import TaskCancelled,task_owned
    event=threading.Event()
    @task_owned('core_tool_loop')
    def parent(cancel_event=None):
        event.set();child()
    @task_owned('core_inference')
    def child():pytest.fail('Cancelled nested work must not run')
    with pytest.raises(TaskCancelled):parent(cancel_event=event)
    assert authority.status()['state']=='idle'
