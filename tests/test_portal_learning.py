import json
import time

from fastapi.testclient import TestClient
from modules.server_manager import ServerManager,create_app


def owner(tmp_path,monkeypatch):
    monkeypatch.setenv('NIBLIT_PORTAL_LOCAL_LEARNING','1')
    monkeypatch.setenv('NIBLIT_PORTAL_ORIGIN','http://127.0.0.1:8769')
    m=ServerManager(tmp_path/'portal.sqlite');m.add_user('owner','long-test-password','admin')
    return m


def test_one_feedback_loop_and_no_queue(tmp_path,monkeypatch):
    m=owner(tmp_path,monkeypatch);calls=[]
    monkeypatch.setattr(m.tutor,'recall',lambda q:([{'id':'e1','content':'Evidence','citation':'knowledge://e1','verification':'unverified'}],[]))
    monkeypatch.setattr('modules.portal_model.reply',lambda h,c:calls.append(c) or 'Evidence supports this claim [1].')
    monkeypatch.setattr(m.tutor,'remember',lambda *a:{'stored':True,'verification':'unverified','category':'episodic'})
    m.turn_lock.acquire()
    assert m.tutor.tick('owner')=='busy'
    assert calls==[]
    assert m.tutor.status('owner')['cycles']==[]
    m.turn_lock.release()
    assert m.tutor.tick('owner')=='candidate_for_review'
    assert len(calls)==1
    with m.db() as db:
        row=db.execute('SELECT * FROM learning_candidates').fetchone()
        assert row['verification']=='unverified'
        assert db.execute('SELECT count(*) FROM messages').fetchone()[0]==0
    report=m.tutor.status('owner')['cycles'][0]
    assert json.loads(report['assessment'])['truth_verified'] is False
    assert m.turn_lock.acquire(blocking=False)
    m.turn_lock.release()


def test_gap_and_dependency_failure_never_generate_or_retry(tmp_path,monkeypatch):
    m=owner(tmp_path,monkeypatch)
    monkeypatch.setattr(m.tutor,'recall',lambda q:([],[]))
    monkeypatch.setattr('modules.portal_model.reply',lambda *a:(_ for _ in ()).throw(AssertionError('No evidence means no inference')))
    assert m.tutor.tick('owner')=='knowledge_gap'
    def failed(q):raise ConnectionError('private service unavailable')
    monkeypatch.setattr(m.tutor,'recall',failed)
    assert m.tutor.tick('owner')=='unavailable'
    with m.db() as db:assert db.execute('SELECT count(*) FROM learning_candidates').fetchone()[0]==0


def test_local_only_owner_only_idle_and_restart_disarmed(tmp_path,monkeypatch):
    m=owner(tmp_path,monkeypatch);m.add_user('guest','long-test-password','operator')
    c=TestClient(create_app(m,'http://testserver'))
    r=c.post('/api/login',json={'username':'guest','password':'long-test-password'},headers={'Origin':'http://testserver'})
    h={'Origin':'http://testserver','X-CSRF-Token':r.json()['csrf']}
    assert c.get('/api/learning').status_code==403
    assert c.post('/api/learning/start',json={},headers=h).status_code==403
    assert m.tutor.start('owner')['state']=='waiting_for_idle'
    assert m.tutor.status('owner')['cycles']==[]
    m.tutor.stop();m.tutor.thread.join(timeout=3)
    assert not m.tutor.thread.is_alive()
    assert ServerManager(m.path).tutor.state['state']=='stopped'
    monkeypatch.setenv('NIBLIT_PORTAL_ORIGIN','https://portal.enginehsd.site')
    assert m.tutor.enabled() is False
