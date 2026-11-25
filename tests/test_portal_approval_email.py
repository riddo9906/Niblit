"""Portal email review requires a separate authenticated administrator decision."""
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from modules.server_manager import ServerManager,create_app
from modules import portal_notifications as notices


def fixture_portal(tmp_path,monkeypatch):
    monkeypatch.delenv('NIBLIT_PORTAL_REMOTE_ORIGIN',raising=False)
    manager=ServerManager(tmp_path/'portal.sqlite')
    manager.add_user('the_owner','secure-owner-password-123','admin')
    return manager,TestClient(create_app(manager,origin='http://127.0.0.1:8768'),
                              base_url='http://127.0.0.1:8768')


def test_pending_signup_email_and_admin_review_flow(tmp_path,monkeypatch):
    manager,client=fixture_portal(tmp_path,monkeypatch)
    notices_sent=[]
    monkeypatch.setattr(notices,'send_registration_notice',lambda name:notices_sent.append(name))
    username='unique.client_42'
    payload={'username':username,'password':'unique-strong-client-pass',
             'shared_workspace_acknowledged':True}
    result=client.post('/api/signup',json=payload,headers={'Origin':'http://127.0.0.1:8768'})
    assert result.status_code==202
    assert notices_sent==[username]
    with manager.db() as db:
        account=db.execute('SELECT active FROM users WHERE name=?',(username,)).fetchone()
        state=db.execute('SELECT state FROM signup_notifications WHERE name=?',(username,)).fetchone()
        assert account['active']==0
        assert state['state']=='sent'
    assert client.post('/api/login',json={'username':username,'password':payload['password']},
                       headers={'Origin':'http://127.0.0.1:8768'}).status_code==401
    admin=client.post('/api/login',json={'username':'the_owner',
                    'password':'secure-owner-password-123'},
                    headers={'Origin':'http://127.0.0.1:8768'})
    assert admin.status_code==200
    csrf=admin.json()['csrf']
    assert client.post('/api/admin/approve/'+username,
                       headers={'Origin':'http://127.0.0.1:8768'}).status_code==403
    assert client.post('/api/admin/approve/'+username,
                       headers={'Origin':'http://127.0.0.1:8768',
                                'X-CSRF-Token':csrf}).status_code==200
    client.post('/api/logout',json={},headers={'Origin':'http://127.0.0.1:8768',
                                          'X-CSRF-Token':csrf})
    auth=client.post('/api/login',json={'username':username,'password':payload['password']},
                     headers={'Origin':'http://127.0.0.1:8768'})
    assert auth.status_code==200
    session=client.get('/api/session').json()
    assert session['user']['name']==username
    assert len(session['user']['account_id'])==32
    assert session['user']['account_id']!=manager.db().__class__.__name__


def test_email_failure_queues_approval_for_admin_resend(tmp_path,monkeypatch):
    manager,client=fixture_portal(tmp_path,monkeypatch)
    def unavailable(name):raise RuntimeError('not configured')
    monkeypatch.setattr(notices,'send_registration_notice',unavailable)
    r=client.post('/api/signup',json={'username':'pendinguser','password':'strong-pass-12121212',
        'shared_workspace_acknowledged':True},headers={'Origin':'http://127.0.0.1:8768'})
    assert r.status_code==202
    with manager.db() as db:
        state=db.execute('SELECT state,attempts FROM signup_notifications WHERE name=?',('pendinguser',)).fetchone()
    assert state['state']=='pending' and state['attempts']==1
    assert client.post('/api/admin/notify/pendinguser',
        headers={'Origin':'http://127.0.0.1:8768'}).status_code==401
    auth=client.post('/api/login',json={'username':'the_owner',
        'password':'secure-owner-password-123'},headers={'Origin':'http://127.0.0.1:8768'})
    sent=[]
    monkeypatch.setattr(notices,'send_registration_notice',lambda name:sent.append(name))
    r=client.post('/api/admin/notify/pendinguser',headers={
        'Origin':'http://127.0.0.1:8768','X-CSRF-Token':auth.json()['csrf']})
    assert r.status_code==200 and sent==['pendinguser']


def test_approval_review_url_needs_trusted_origin(monkeypatch):
    monkeypatch.setenv('NIBLIT_PORTAL_REVIEW_ORIGIN','https://niblit.example')
    assert notices.review_url('alice.bob')=='https://niblit.example/admin?review=alice.bob'
    for bad in ('http://remote.example','https://example.org/attack',
                'https://someone@remote.example','https://example.org?x=1'):
        monkeypatch.setenv('NIBLIT_PORTAL_REVIEW_ORIGIN',bad)
        with pytest.raises(ValueError):notices.review_url('x')


def test_password_change_revokes_existing_sessions(tmp_path,monkeypatch):
    manager,client=fixture_portal(tmp_path,monkeypatch)
    a=client.post('/api/login',json={'username':'the_owner',
                   'password':'secure-owner-password-123'},
                   headers={'Origin':'http://127.0.0.1:8768'})
    csrf=a.json()['csrf']
    response=client.post('/api/account/password',json={
        'current_password':'secure-owner-password-123','new_password':'new-very-strong-password-123'},
        headers={'Origin':'http://127.0.0.1:8768','X-CSRF-Token':csrf})
    assert response.status_code==200
    assert client.get('/api/session').status_code==401
    assert client.post('/api/login',json={'username':'the_owner',
        'password':'new-very-strong-password-123'},
        headers={'Origin':'http://127.0.0.1:8768'}).status_code==200
