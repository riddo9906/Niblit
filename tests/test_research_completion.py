import json
import threading
import pytest
from test_governed_learning import learning
from test_public_source_learning import public_request, QUOTE
from modules.research_contracts import source_identity, attributed_claims, validate_comparison_proposal, render_source_comparison


def catalog():
    return attributed_claims([
        {'id':'microsoft-claim','value':'After a physical count, use the Adjust Inventory action to record the inventory quantity.',
         'citation':'https://learn.microsoft.com/en-us/dynamics365/business-central/inventory-how-count-adjust-reclassify'},
        {'id':'odoo-claim','value':'Inventory adjustments reconcile recorded inventory counts with actual warehouse counts.',
         'citation':'https://raw.githubusercontent.com/odoo/documentation/18.0/content/inventory.rst'}])


def test_exact_source_binding_and_vendor_scope():
    c=catalog()
    proposal={'claims':[{'claim_id':x['claim_id'],'source_id':x['source_id']} for x in c]}
    result=validate_comparison_proposal(proposal,c)
    assert result['valid']
    assert validate_comparison_proposal({'claims':['E1','E2']},c)['valid']
    assert not validate_comparison_proposal({'claims':['E9']},c)['valid']
    text=render_source_comparison(c,result)
    assert 'Microsoft / Dynamics 365 Business Central' in text
    assert 'For Odoo, that named action is UNKNOWN' in text
    assert 'Supported similarity' in text
    proposal['claims'][0]['source_id']=c[1]['source_id']
    result=validate_comparison_proposal(proposal,c)
    assert not result['valid'] and result['reason']=='claim_source_mismatch'
    assert 'partial answer' in render_source_comparison(c,result)


def test_generated_conclusions_and_invented_references_rejected():
    c=catalog()
    assert not validate_comparison_proposal({'claims':[],'conclusion':'Both vendors use Adjust Inventory'},c)['valid']
    assert not validate_comparison_proposal({'claims':[{'claim_id':'made-up','source_id':c[0]['source_id']}]},c)['valid']
    assert source_identity('https://raw.githubusercontent.com/attacker/documentation/18.0/test')['publisher']=='UNKNOWN'


def test_unknown_research_scope_never_falls_into_unchecked_generation(monkeypatch):
    import server
    from types import SimpleNamespace
    def forbidden(*args,**kwargs):raise AssertionError('model must not infer missing source scope')
    monkeypatch.setattr(server,'_niblit_local_completion',forbidden)
    evidence={'tools_executed':[{'result':json.dumps({'facts':[{'id':'unknown',
        'value':'A claimed procedure without a recognized publisher.', 'citation':'https://unknown.example/source'}]})}]}
    response=server._validated_learning_answer('Compare procedures',evidence,SimpleNamespace(add_exchange=lambda *args:True))
    assert 'UNKNOWN' in response['reply'] and response['niblit_model']['generation_performed'] is False


def test_real_executor_cancellation_preserves_commit_and_owner(learning,monkeypatch):
    from modules import core_tool_runtime as runtime
    request=public_request(learning,monkeypatch)
    request['sources'].append({'kind':'public_web','url':'https://docs.example.org/second'})
    request['max_research_calls']=2
    request['max_accepted_records']=4
    monkeypatch.setattr(runtime,'_LEARNING_JOBS',{})
    loop,g,*_=learning
    session='owner-session-'+'a'*40
    job=runtime.begin_learning_job('test-research-job-0001',session)
    original=loop.invoke;entered=threading.Event();release=threading.Event();calls=[]
    def controlled(name,args):
        if name=='web_fetch':
            calls.append(args['url'])
            if len(calls)==2:
                entered.set();assert release.wait(5)
        return original(name,args)
    monkeypatch.setattr(loop,'invoke',controlled)
    outcome={}
    def run():
        with runtime.learning_job_context(job):outcome.update(loop.invoke('run_learning',request))
        job.finish(outcome['result'])
    worker=threading.Thread(target=run);worker.start()
    assert entered.wait(5)
    with pytest.raises(PermissionError):runtime.learning_job_status(job.job_id,'other-session-'+'b'*40,cancel=True)
    assert not job.cancelled.is_set()
    runtime.learning_job_status(job.job_id,session,cancel=True)
    assert not job.done.is_set()  # In-flight I/O has not drained; no false acknowledgment.
    release.set();worker.join(5)
    assert not worker.is_alive()
    assert job.done.is_set() and job.public()['status']=='cancelled'
    result=outcome['result']
    assert result['status']=='cancelled' and result['new_records']==1
    assert len(calls)==2
    assert len(g.learning_facts(request['subject'],namespace='test',principal='operator')['facts'])==1
    with g.db() as db:
        assert db.execute("SELECT count(*) FROM audit WHERE action='learning.cancelled'").fetchone()[0]==1
    with pytest.raises(ValueError):runtime.begin_learning_job(job.job_id,session)
    # A process restart can read terminal history without resuming work.
    monkeypatch.setattr(runtime,'_LEARNING_JOBS',{})
    assert runtime.learning_job_status(job.job_id,session)[1]['status']=='cancelled'


def test_cancel_before_first_research_tool(learning,monkeypatch):
    from modules import core_tool_runtime as runtime
    request=public_request(learning,monkeypatch)
    monkeypatch.setattr(runtime,'_LEARNING_JOBS',{})
    session='session-'+'x'*48;job=runtime.begin_learning_job('test-cancel-before-start',session)
    job.request_cancel('test_before_start')
    with runtime.learning_job_context(job):result=learning[0].invoke('run_learning',request)['result']
    job.finish(result)
    assert result['status']=='cancelled' and not result['accepted']
    assert not job.calls and result['research_calls']==0


def test_permission_revocation_stops_new_stages_but_owner_can_cancel(learning,monkeypatch):
    from modules import core_tool_runtime as runtime
    public_request(learning,monkeypatch)
    monkeypatch.setattr(runtime,'_LEARNING_JOBS',{})
    session='revoked-'+'x'*48;job=runtime.begin_learning_job('test-revocation-job-01',session)
    learning[4].write_text('{}')
    assert job.stage('tool:web_fetch') is False
    assert job.cancelled.is_set() and not job.calls
    runtime.learning_job_status(job.job_id,session,cancel=True)
    job.finish({'status':'cancelled','accepted':[]})


def test_buffered_request_disconnect_is_forwarded_without_polling():
    import asyncio
    from server import ResearchDisconnectMiddleware
    async def scenario():
        incoming=asyncio.Queue();observed=asyncio.Event()
        await incoming.put({'type':'http.request','body':b'{}','more_body':False})
        async def application(scope,receive,send):
            assert (await receive())['type']=='http.request'
            observed.set()
            await scope['niblit.research_disconnect'].wait()
        middleware=ResearchDisconnectMiddleware(application)
        task=asyncio.create_task(middleware({'type':'http','path':'/chat','method':'POST'},incoming.get,lambda message:None))
        await observed.wait();await incoming.put({'type':'http.disconnect'})
        await asyncio.wait_for(task,1)
    asyncio.run(scenario())


def test_deadline_after_inflight_io_does_not_accept_late_findings(learning,monkeypatch):
    import time
    request=public_request(learning,monkeypatch);request['max_seconds']=1
    loop,g,*_=learning;original=loop.invoke
    def delayed(name,args):
        if name=='web_fetch':time.sleep(1.1)
        return original(name,args)
    monkeypatch.setattr(loop,'invoke',delayed)
    result=loop.invoke('run_learning',request)['result']
    assert result['status']=='timed_out' and not result['accepted']
    with g.db() as db:
        assert db.execute("SELECT count(*) FROM audit WHERE action='learning.timed_out'").fetchone()[0]==1
