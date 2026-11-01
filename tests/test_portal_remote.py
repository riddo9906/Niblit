from fastapi.testclient import TestClient
import pytest
from modules.server_manager import ServerManager,create_app
from modules.portal_remote import remote_origin


def test_remote_client_keeps_auth_csrf_and_local_capability_boundary(tmp_path,monkeypatch):
    public='https://niblit-api.enginehsd.site'
    monkeypatch.setenv('NIBLIT_PORTAL_REMOTE_ORIGIN',public)
    m=ServerManager(tmp_path/'portal.sqlite',responder=lambda h,c:'local answer')
    m.add_user('owner','long-test-password','admin')
    app=create_app(m,'http://127.0.0.1:8769')
    c=TestClient(app,base_url=public)
    assert c.get('/api/session').status_code==401
    response=c.post('/api/login',json={'username':'owner','password':'long-test-password'},headers={'Origin':public})
    assert response.status_code==200
    cookie=response.headers['set-cookie'].lower()
    assert 'secure' in cookie and 'httponly' in cookie and 'samesite=strict' in cookie
    headers={'Origin':public,'X-CSRF-Token':response.json()['csrf']}
    assert c.get('/api/session').json()['remote_client'] is True
    assert c.post('/api/messages',json={'content':'hello'},headers=headers).status_code==200
    assert c.post('/api/messages',json={'content':'tools','use_tools':True},headers=headers).status_code==403
    assert c.post('/api/messages',json={'content':'cross-site'},headers={**headers,'Origin':'https://evil.example'}).status_code==403
    assert c.post('/api/messages',json={'content':'no csrf'},headers={'Origin':public}).status_code==403
    for path in ['/admin','/api/admin','/api/learning','/api/tool-activity','/api/mt5/snapshot','/api/local-tutor/recall']:
        assert c.get(path,headers={'X-Forwarded-Host':'127.0.0.1:8769'}).status_code==403
    local=TestClient(app,base_url='http://127.0.0.1:8769')
    assert local.get('/admin').status_code==200


def test_remote_is_off_by_default_and_origin_is_explicit(tmp_path,monkeypatch):
    monkeypatch.delenv('NIBLIT_PORTAL_REMOTE_ORIGIN',raising=False)
    c=TestClient(create_app(ServerManager(tmp_path/'portal.sqlite')),base_url='https://remote.example')
    assert c.get('/').status_code==400
    for value in ['http://api.example','https://user:secret@api.example','https://localhost','https://api.example/path','https://api.example?key=value']:
        with pytest.raises(ValueError):remote_origin(value)
    assert remote_origin('') is None
