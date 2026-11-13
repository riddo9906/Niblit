import pytest
from modules.task_admission import TaskAuthority,AdmissionBusy
from modules.server_manager import ServerManager

def test_child_restart_and_replay(tmp_path):
    g=ServerManager(tmp_path/'a.sqlite');a=TaskAuthority(g);token=a.acquire('core_inference')['token']
    a.delegate(token,'a'*32);b=TaskAuthority(ServerManager(g.path))
    with pytest.raises(AdmissionBusy):b.delegate(token,'b'*32)
    with pytest.raises(ValueError):b.delegate('forged-token-with-at-least-32-characters','c'*32)
    b.delegate(token,'a'*32,complete=True)
    with pytest.raises(AdmissionBusy):b.delegate(token,'a'*32)
    assert a.status()['state']=='active';b.finish(token);assert a.status()['state']=='idle'

@pytest.mark.parametrize('premature',[True,False])
def test_uncertain_child_stays_reserved(tmp_path,premature):
    a=TaskAuthority(ServerManager(tmp_path/'a.sqlite'));t=a.acquire('core_inference')['token'];a.delegate(t,'a'*32)
    if premature:assert a.finish(t)['state']=='quarantined'
    a.delegate(t,'a'*32,complete=True,uncertain=not premature)
    assert a.finish(t)['state']=='quarantined'
    with pytest.raises(AdmissionBusy):a.acquire('portal_chat')


def test_delegate_endpoint_requires_existing_private_key(tmp_path):
    from fastapi.testclient import TestClient
    from modules.memory_laboratory.web import create_app
    from test_memory_laboratory_gateway import Backend,gateway
    private=tmp_path/'runtime/client-portal';private.mkdir(parents=True)
    key='synthetic-test-key-at-least-32-characters';(private/'gguf-api-key').write_text(key)
    c=TestClient(create_app(gateway(tmp_path,Backend()),root=tmp_path,port=8772))
    body={'token':'f'*40,'request_id':'a'*32}
    assert c.post('/api/local-tutor/task/delegate',json=body).status_code==403
    h={'authorization':'Bearer '+key}
    assert c.post('/api/local-tutor/task/delegate',json=body,headers=h).status_code==400
    token=c.post('/api/local-tutor/task/acquire',json={'owner':'core_inference'},headers=h).json()['token']
    body['token']=token
    assert c.post('/api/local-tutor/task/delegate',json=body,headers=h).status_code==200
    assert c.post('/api/local-tutor/task/delegate',json=body,headers=h).status_code==409
    assert c.post('/api/local-tutor/task/delegate',json={**body,'complete':True},headers=h).status_code==200
    assert c.post('/api/local-tutor/task/finish',json={'token':token},headers=h).json()['state']=='idle'
