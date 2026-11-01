import json
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from modules.server_manager import ServerManager, create_app
from modules.portal_tools import ResearchTools
from modules.portal_model import reply


def setup(tmp_path):
    manager=ServerManager(tmp_path/'portal.sqlite',responder=lambda h,c:'ordinary reply')
    manager.add_user('owner','long-test-password','admin')
    manager.add_user('guest','long-test-password','operator')
    return manager,ResearchTools(manager,{'name':'owner','role':'admin'},'shared',1)


def test_boundaries_and_inert_proposals(tmp_path):
    manager,tools=setup(tmp_path)
    assert 'modules/portal_model.py' in tools.invoke('source_list',{})['files']
    assert tools.invoke('source_read',{'path':'../../.env'}).get('error')
    result=tools.invoke('proposal_save',{'title':'Small draft','rationale':'Evidence needed','patch':'print(1)','validation':'Run isolated tests'})
    assert result['applied'] is False
    with manager.db() as db:
        assert db.execute('SELECT count(*) FROM improvement_proposals').fetchone()[0]==1
        assert [r[0] for r in db.execute('SELECT state FROM tool_events ORDER BY id')]==['complete','failed','complete']
    with pytest.raises(ValueError,match='budget'):tools.invoke('source_list',{})
    fresh=ResearchTools(manager,{'name':'owner','role':'admin'},'shared',2)
    assert fresh.invoke('docs_read',{'document':'http://127.0.0.1:8000/.env'}).get('error')
    with pytest.raises(ValueError):fresh.invoke('shell',{'command':'whoami'})
    with pytest.raises(ValueError):fresh.invoke('source_read',{'path':123})


def test_owner_checks_and_workspace_isolation(tmp_path):
    manager,tools=setup(tmp_path)
    app=create_app(manager,'http://testserver')
    def login(name):
        c=TestClient(app);r=c.post('/api/login',json={'username':name,'password':'long-test-password'},headers={'Origin':'http://testserver'})
        return c,{'Origin':'http://testserver','X-CSRF-Token':r.json()['csrf']}
    owner,oh=login('owner');guest,gh=login('guest')
    assert guest.post('/api/messages',json={'content':'read source','use_tools':True},headers=gh).status_code==403
    assert guest.get('/api/tool-activity').status_code==403
    assert TestClient(app).get('/api/tool-activity').status_code==401
    tools.invoke('source_list',{})
    assert len(owner.get('/api/tool-activity').json()['events'])==1
    manager.workspaces.set_plan({'name':'owner'},'guest','personal')
    wid=manager.workspaces.create({'name':'guest','role':'operator'},'Private')['id']
    assert owner.get('/api/tool-activity?workspace='+wid).status_code==404
    with manager.db() as db:db.execute("UPDATE users SET active=0 WHERE name='owner'")
    with pytest.raises(ValueError,match='active administrator'):tools.invoke('source_list',{})


def test_model_observation_loop_and_invalid_request_stop(monkeypatch,tmp_path):
    manager,tools=setup(tmp_path)
    monkeypatch.setenv('NIBLIT_PORTAL_MODEL_BACKEND','ollama')
    client=Mock()
    responses=[]
    for decision in [{'tool':'source_list','arguments':{}},{'answer':'The published source is inspectable; no changes applied.'}]:
        response=Mock();response.json.return_value={'message':{'content':'```json\n'+json.dumps(decision)+'\n```'}};responses.append(response)
    client.post.side_effect=responses
    factory=Mock();factory.return_value.__enter__=Mock(return_value=client);factory.return_value.__exit__=Mock(return_value=False)
    monkeypatch.setattr('modules.portal_model.httpx.Client',factory)
    assert 'no changes applied' in reply([],'Inspect available source',tools=tools)
    messages=client.post.call_args.kwargs['json']['messages']
    assert 'modules/portal_model.py' in messages[-1]['content']
    assert 'source_list' in messages[-2]['content']
    client.post.side_effect=None
    client.post.return_value.json.return_value={'message':{'content':'{"tool":"shell","arguments":{}}'}}
    assert 'invalid or disallowed' in reply([],'execute shell',tools=tools)
    assert client.post.call_count==3


def test_repeated_model_call_synthesizes_without_reexecuting(monkeypatch,tmp_path):
    manager,tools=setup(tmp_path)
    monkeypatch.setenv('NIBLIT_PORTAL_MODEL_BACKEND','ollama')
    responses=[]
    for text in ['{"tool":"source_list","arguments":{}}']*2+['Source inspected; no changes applied.']:
        r=Mock();r.json.return_value={'message':{'content':text}};responses.append(r)
    client=Mock();client.post.side_effect=responses
    factory=Mock();factory.return_value.__enter__=Mock(return_value=client);factory.return_value.__exit__=Mock(return_value=False)
    monkeypatch.setattr('modules.portal_model.httpx.Client',factory)
    assert reply([],'Inspect source',tools=tools)=='Source inspected; no changes applied.'
    assert tools.calls==1
    assert 'format' not in client.post.call_args.kwargs['json']


def test_invalid_followup_summarizes_existing_evidence(monkeypatch,tmp_path):
    manager,tools=setup(tmp_path)
    monkeypatch.setenv('NIBLIT_PORTAL_MODEL_BACKEND','ollama')
    responses=[]
    for text in ['{"tool":"source_list","arguments":{}}','{"invalid":true}','The source catalog contains the portal modules.']:
        r=Mock();r.json.return_value={'message':{'content':text}};responses.append(r)
    client=Mock();client.post.side_effect=responses
    factory=Mock();factory.return_value.__enter__=Mock(return_value=client);factory.return_value.__exit__=Mock(return_value=False)
    monkeypatch.setattr('modules.portal_model.httpx.Client',factory)
    assert 'source catalog' in reply([],'Inspect source',tools=tools)
    assert tools.calls==1
