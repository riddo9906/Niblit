import json

from fastapi.testclient import TestClient
import pytest

from modules.memory_laboratory import web
from test_memory_laboratory_gateway import Backend, gateway


@pytest.fixture
def desk(tmp_path, monkeypatch):
    g = gateway(tmp_path, Backend())
    monkeypatch.setattr(web, "inspect_containers", lambda:[])
    monkeypatch.setattr(web, "freqtrade_status", lambda:{"available":False})
    monkeypatch.setattr(web, "local_get", lambda url:{"available":False})
    app = web.create_app(g, root=tmp_path)
    headers={"origin":"http://127.0.0.1:8766","x-niblit-desk-token":app.state.session_token}
    return TestClient(app), g, headers


def test_local_control_rejects_cross_site_and_wrong_host(desk):
    client,g,headers=desk
    assert client.post('/api/backup',json={}).status_code==403
    assert client.post('/api/backup',json={},headers={**headers,'origin':'https://untrusted.example'}).status_code==403
    assert client.get('/api/records',headers={'host':'untrusted.example:8766'}).status_code==403
    assert client.get('/api/records').status_code==200
    assert client.post('/api/containers/not-managed',json={'action':'start'},headers=headers).status_code==404


def test_tutor_capability_is_scoped_and_never_verifies(tmp_path):
    g=gateway(tmp_path,Backend())
    private=tmp_path/'runtime/client-portal';private.mkdir(parents=True)
    (private/'gguf-api-key').write_text('test-local-tutor-key-not-a-real-secret-12345')
    c=TestClient(web.create_app(g,root=tmp_path,port=8772))
    header={'authorization':'Bearer test-local-tutor-key-not-a-real-secret-12345','host':'host.docker.internal:8772'}
    assert c.post('/api/local-tutor/recall',json={'query':'memory'}).status_code==403
    assert c.post('/api/local-tutor/observation',json={'source_id':'test-1','content':'A local model suggested a hypothesis.'},headers=header).status_code==200
    with g.db() as db:
        payload=json.loads(db.execute('SELECT payload FROM records').fetchone()[0])
    assert payload['category']=='episodic' and payload['verification']=='unverified'
    assert payload['namespace']=='desktop'
    assert payload['source_type']=='local_model_reflection'
    assert c.post('/api/backup',json={},headers=header).status_code==403
    assert c.post('/api/local-tutor/observation',json={'source_id':'../../other','content':'text'},headers=header).status_code==422


def test_browse_review_and_rejection_are_real_scoped_operations(desk):
    client,g,headers=desk
    g.ingest([('Liquidity describes how readily an asset can be traded.','fixture:1')],source='fixture',namespace='desktop',principal='desktop_operator')
    records=client.get('/api/records').json()
    assert records['total']==1 and records['records'][0]['verification']=='unverified'
    key=records['records'][0]['memory_id']
    body={'verification':'rejected','confidence':.2,'evidence':'Test operator checked the fixture and rejects it.','source_checked':True}
    assert client.post(f'/api/records/{key}/review',json=body,headers=headers).status_code==200
    assert client.get('/api/records').json()['total']==0
    with g.db() as db:
        assert db.execute("SELECT count(*) FROM audit WHERE action='record.reviewed'").fetchone()[0]==1


def test_document_upload_queues_actual_text_without_model_calls(desk):
    client,g,headers=desk
    response=client.post('/api/documents?filename=note.txt',content=b'The observatory fixture color is violet.',headers={**headers,'content-type':'application/octet-stream'})
    assert response.status_code==200 and response.json()['queued']==1
    with g.db() as db:
        body=json.loads(db.execute('SELECT body FROM ingestion_outbox').fetchone()[0])
    assert 'observatory fixture' in body['content'] and body['metadata']['provenance']['page']==1
    assert body['namespace']=='desktop'


def test_backup_and_html_have_no_configuration_key(desk):
    client,g,headers=desk
    page=client.get('/')
    assert page.status_code==200 and '__SESSION_TOKEN__' not in page.text
    assert 'QDRANT_API_KEY' not in page.text
    assert client.post('/api/backup',json={},headers=headers).status_code==200


def test_freqtrade_cannot_be_started_live(desk, tmp_path, monkeypatch):
    client,g,headers=desk
    path=tmp_path.parent/'freqtrade/user_data'
    path.mkdir(parents=True,exist_ok=True)
    (path/'config.json').write_text(json.dumps({'dry_run':False}))
    calls=[]
    def docker(args,**kwargs):
        calls.append(args)
        return json.dumps([{'Config':{'Image':'freqtradeorg/freqtrade:stable'}}])
    monkeypatch.setattr(web,'docker',docker)
    response=client.post('/api/containers/freqtrade',json={'action':'start'},headers=headers)
    assert response.status_code==409
    assert calls==[['inspect','freqtrade']]


def test_freqtrade_live_environment_override_is_refused(desk,tmp_path,monkeypatch):
    client,g,headers=desk
    path=tmp_path.parent/'freqtrade/user_data'
    path.mkdir(parents=True,exist_ok=True)
    (path/'config.json').write_text(json.dumps({'dry_run':True}))
    info={'Config':{'Image':'freqtradeorg/freqtrade:stable','Entrypoint':['freqtrade'],
        'Cmd':['trade','--config','/freqtrade/user_data/config.json'],
        'Env':['FREQTRADE__DRY_RUN=false']},'Mounts':[{'Destination':'/freqtrade/user_data','Source':str(path)}]}
    calls=[]
    def docker(args,**kwargs):
        calls.append(args)
        return json.dumps([info]) if args[0]=='inspect' else 'freqtrade'
    monkeypatch.setattr(web,'docker',docker)
    assert client.post('/api/containers/freqtrade',json={'action':'start'},headers=headers).status_code==409
    assert calls==[['inspect','freqtrade']]
    info['Config']['Env']=[]
    assert client.post('/api/containers/freqtrade',json={'action':'start'},headers=headers).status_code==200
    assert calls[-1]==['start','freqtrade']
