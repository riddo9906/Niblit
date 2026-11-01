from concurrent.futures import ThreadPoolExecutor
import threading
import pytest
from fastapi.testclient import TestClient
from modules.server_manager import ServerManager,create_app

def test_shared_session_and_revocation(tmp_path):
    manager=ServerManager(tmp_path/'portal.sqlite',responder=lambda history,text:'Shared reply: '+text)
    manager.add_user('owner','long-test-password','admin')
    manager.add_user('guest','long-test-password','operator')
    manager.add_user('reader','long-test-password','viewer')
    app=create_app(manager,'http://testserver')
    owner,guest,reader=[TestClient(app) for _ in range(3)]
    def login(client,name):
        r=client.post('/api/login',json={'username':name,'password':'long-test-password'},headers={'Origin':'http://testserver'})
        assert r.status_code==200
        return {'Origin':'http://testserver','X-CSRF-Token':r.json()['csrf']}
    oh,gh,rh=login(owner,'owner'),login(guest,'guest'),login(reader,'reader')
    assert guest.post('/api/messages',json={'content':'hello'},headers=gh).status_code==200
    assert reader.get('/api/session').json()['messages'][-1]['content']=='Shared reply: hello'
    assert reader.post('/api/messages',json={'content':'no'},headers=rh).status_code==403
    assert guest.get('/api/admin').status_code==403
    assert guest.post('/api/messages',json={'content':'no'},headers={'Origin':'https://evil.test'}).status_code==403
    assert guest.post('/api/messages',json={'content':'no'},headers={'Origin':'http://testserver'}).status_code==403
    assert owner.post('/api/admin/revoke/guest',json={},headers=oh).status_code==200
    assert guest.get('/api/session').status_code==401
    assert ServerManager(tmp_path/'portal.sqlite').history()[-1]['content']=='Shared reply: hello'

def test_serialization_failure_expiry_and_lockout(tmp_path):
    entered,release=threading.Event(),threading.Event()
    def respond(history,text):
        entered.set();release.wait(3);return 'done'
    manager=ServerManager(tmp_path/'portal.sqlite',responder=respond)
    manager.add_user('user','long-test-password','operator')
    token,_=manager.login('user','long-test-password')
    user=manager.identity(token)
    with ThreadPoolExecutor() as pool:
        first=pool.submit(manager.submit,user,'one');assert entered.wait(2)
        with pytest.raises(Exception) as e:manager.submit(user,'two')
        assert e.value.status_code==409
        release.set();first.result()
    with manager.db() as db:db.execute('UPDATE logins SET expires=0')
    with pytest.raises(Exception) as e:manager.identity(token)
    assert e.value.status_code==401
    for _ in range(5):
        with pytest.raises(Exception):manager.login('user','wrong')
    with pytest.raises(Exception) as e:manager.login('user','long-test-password')
    assert e.value.status_code==429

def test_failed_model_is_durable_and_not_retried(tmp_path):
    calls=[]
    def broken(history,text):
        calls.append(text)
        raise RuntimeError('private backend details')
    manager=ServerManager(tmp_path/'portal.sqlite',responder=broken)
    manager.add_user('user','long-test-password','operator')
    token,_=manager.login('user','long-test-password')
    with pytest.raises(Exception) as e:
        manager.submit(manager.identity(token),'test')
    assert e.value.status_code==503
    assert 'private backend details' not in e.value.detail
    assert calls==['test']
    assert manager.history()[0]['state']=='failed'
    assert len(ServerManager(tmp_path/'portal.sqlite').history())==1

def test_signup_requires_admin_approval_and_cannot_replace_account(tmp_path):
    manager=ServerManager(tmp_path/'portal.sqlite')
    manager.add_user('owner','long-test-password','admin')
    app=create_app(manager,'http://testserver')
    client=TestClient(app)
    origin={'Origin':'http://testserver'}
    body={'username':'new-client','password':'long-new-password','shared_workspace_acknowledged':True}
    assert client.post('/api/signup',json=body,headers=origin).status_code==202
    assert client.post('/api/session',json={}).status_code==403
    assert client.post('/api/login',json={'username':'new-client','password':body['password']},headers=origin).status_code==401
    assert client.post('/api/admin/approve/new-client',json={},headers=origin).status_code==401
    r=client.post('/api/login',json={'username':'owner','password':'long-test-password'},headers=origin)
    headers={**origin,'X-CSRF-Token':r.json()['csrf']}
    assert client.post('/api/admin/approve/new-client',json={},headers=headers).status_code==200
    guest=TestClient(app)
    r=guest.post('/api/login',json={'username':'new-client','password':body['password']},headers=origin)
    assert r.status_code==200
    assert guest.get('/api/session').json()['user']['role']=='viewer'
    assert client.post('/api/admin/revoke/new-client',json={},headers=headers).status_code==200
    body['password']='replacement-password'
    assert guest.post('/api/signup',json=body,headers=origin).status_code==202
    assert client.post('/api/admin/approve/new-client',json={},headers=headers).status_code==400
    assert guest.post('/api/login',json={'username':'new-client','password':body['password']},headers=origin).status_code==401
    assert guest.get('/api/session').status_code==401
