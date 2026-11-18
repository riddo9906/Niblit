import json
from types import SimpleNamespace
import pytest

from modules.core_tool_runtime import build_governed_tool_loop
from modules import permission_manager
from test_memory_laboratory_gateway import Backend, gateway


@pytest.fixture
def learning(tmp_path, monkeypatch):
    from modules.memory_laboratory import context
    path=tmp_path/'permissions.json'
    path.write_text(json.dumps({'command.run_learning':True}))
    monkeypatch.setattr(permission_manager,'PERM_FILE',str(path))
    monkeypatch.setenv('NIBLIT_WORKSPACE_ROOT',str(tmp_path))
    monkeypatch.setenv('NIBLIT_MEMORY_LAB_NAMESPACE','test')
    monkeypatch.setenv('NIBLIT_MEMORY_LAB_PRINCIPAL','operator')
    backend=Backend();g=gateway(tmp_path,backend)
    monkeypatch.setattr(context,'runtime_gateway',lambda:g)
    loop=build_governed_tool_loop(lambda:None)
    source=tmp_path/'package.json';source.write_text(json.dumps({'name':'niblit','version':'1.0.0'}))
    request={'objective':'Investigate package name and version','subject':'niblit.package',
             'permitted_actions':['recall','read_workspace','store_observations'],
             'sources':[{'kind':'workspace_json','path':'package.json','fields':['name','version']}],
             'max_seconds':10,'max_research_calls':1,'max_accepted_records':2}
    return loop,g,request,source,path,backend


def invoke(learning):
    loop,g,request,*_=learning
    result=loop.invoke('run_learning',request)
    assert result['status']=='success',result
    return result['result']


def test_real_files_recall_accept_repeat_and_conflict(learning):
    first=invoke(learning)
    assert len(first['accepted'])==2 and first['model_calls']==0
    assert first['prior_evidence_ids']==[]
    second=invoke(learning)
    assert len(second['prior_evidence_ids'])==2
    assert all(x['status']=='repeated' and x['occurrences']==2 for x in second['accepted'])
    assert second['knowledge_changed'] is False and second['knowledge_gaps']==[]
    assert second['acquisition_reason']=='revalidate_current_source'
    loop,g,request,source,*_=learning
    source.write_text(json.dumps({'name':'niblit','version':'9.0.0'}))
    third=invoke(learning)
    assert any(isinstance(x,dict) and x['status']=='conflict' for x in third['unresolved'])
    with g.db() as db:
        assert db.execute("SELECT count(*) FROM records WHERE active=1").fetchone()[0]==2
        assert db.execute("SELECT count(*) FROM audit WHERE action='learning.completed'").fetchone()[0]==3
    recalled=g.retrieve('package version',namespace='test',principal='operator')
    assert any('1.0.0' in h['content'] for h in recalled['results'])
    assert not any('9.0.0' in h['content'] for h in recalled['results'])
    exact=g.learning_facts('niblit.package',namespace='test',principal='operator')
    assert {f['field']:f['value'] for f in exact['facts']}=={'name':'niblit','version':'1.0.0'}
    assert not g.learning_facts('unknown.subject',namespace='test',principal='operator')['facts']
    assert not g.learning_facts('niblit.package',namespace='foreign',principal='operator')['facts']


def test_operator_denial_prevents_acquisition(learning):
    loop,g,request,source,path,_=learning
    path.write_text('{}')
    assert loop.invoke('run_learning',request)['status']=='authorization_required'
    with g.db() as db:assert db.execute('SELECT count(*) FROM records').fetchone()[0]==0


def test_memory_denial_is_not_success(learning):
    loop,g,request,*_=learning
    g.authorize=lambda *args:False
    assert loop.invoke('run_learning',request)['status']=='authorization_required'


@pytest.mark.parametrize('text,reason',[
    ('{"name":"a","name":"b"}','malformed_or_unsupported_source_json'),
    ('{"name":NaN}','malformed_or_unsupported_source_json'),
    ('{"generated":true,"name":"niblit"}','generated_material_not_independent_evidence'),
    ('{"source_type":"reflection","name":"niblit"}','generated_material_not_independent_evidence'),
    ('{"provenance":{"generated":true},"name":"niblit"}','generated_material_not_independent_evidence'),
])
def test_unsupported_source_never_becomes_knowledge(learning,text,reason):
    learning[3].write_text(text)
    result=invoke(learning)
    assert not result['accepted'] and result['rejected'][0]['reason']==reason


def test_budgets_and_filesystem_fail_closed(learning):
    request=learning[2]
    request['max_research_calls']=0
    assert invoke(learning)['research_calls']==0
    request['max_research_calls']=1
    request['sources'][0]['path']='../package.json'
    assert not invoke(learning)['accepted']
    request['max_accepted_records']=1000
    assert learning[0].invoke('run_learning',request)['status']=='rejected'


def test_projection_failure_is_not_reported_as_learning(learning):
    learning[-1].offline=True
    result=invoke(learning)
    assert not result['accepted'] and result['unresolved']
