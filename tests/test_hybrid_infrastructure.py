import importlib.util
from pathlib import Path
import sqlite3
import pytest
import yaml
from types import SimpleNamespace
import json,hashlib,httpx

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('hybrid_backup',ROOT/'scripts/hybrid-backup.py')
backup=importlib.util.module_from_spec(spec);spec.loader.exec_module(backup)

def test_online_backup_restore_retains_events_and_never_overwrites(tmp_path):
    source=tmp_path/'source.sqlite3'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE events(id TEXT PRIMARY KEY,body TEXT)')
        db.execute("INSERT INTO events VALUES('stable-id','abstention')");db.commit()
        receipt=backup.backup_sqlite(source,tmp_path/'backups')
    target=tmp_path/'restored.sqlite3';backup.restore_new(receipt['backup'],target)
    with sqlite3.connect(target) as db:assert db.execute('SELECT * FROM events').fetchall()==[('stable-id','abstention')]
    with pytest.raises(FileExistsError):backup.restore_new(receipt['backup'],source)
    Path(receipt['backup']).write_bytes(b'corrupt')
    with pytest.raises(ValueError):backup.restore_new(receipt['backup'],tmp_path/'bad.sqlite3')

def test_compose_preserves_native_authority_and_external_data():
    config=yaml.safe_load((ROOT/'deploy/hybrid/compose.yml').read_text(encoding='utf-8'))
    assert set(config['services'])=={'portal-development','portal-production'}
    assert config['volumes']['existing-portal-data']['external'] is True
    assert config['networks']['backend']['internal'] is True
    for service in config['services'].values():
        assert service['read_only'] and service['cap_drop']==['ALL']
        assert service['environment']['NIBLIT_SHARED_ADMISSION']=='1'
        assert service['environment']['NIBLIT_PORTAL_LOCAL_LEARNING']=='0'
        assert service['ports'][0].startswith('127.0.0.1:')
        assert service['tmpfs']==['/tmp:size=64m,mode=1777']

def test_container_build_context_never_contains_private_dotenv_models_or_ledger():
    dockerfile=(ROOT/'deploy/hybrid/Dockerfile').read_text(encoding='utf-8')
    assert 'COPY . .' not in dockerfile and 'pip install' not in dockerfile
    allowlist=(ROOT/'deploy/hybrid/Dockerfile.dockerignore').read_text(encoding='utf-8')
    assert allowlist.startswith('**') and '!runtime/' not in allowlist and '!.env' not in allowlist


def test_kubernetes_contract_is_restricted_and_never_provisions_qdrant_or_volumes():
    docs=list(yaml.safe_load_all((ROOT/'deploy/hybrid/kubernetes.yaml').read_text(encoding='utf-8')))
    assert {d['kind'] for d in docs}=={'ConfigMap','Deployment','Service','NetworkPolicy'}
    deployment=next(d for d in docs if d['kind']=='Deployment')
    assert deployment['spec']['strategy']['type']=='Recreate' and deployment['spec']['replicas']==1
    pod=deployment['spec']['template']['spec']
    assert pod['automountServiceAccountToken'] is False
    assert pod['containers'][0]['securityContext']['allowPrivilegeEscalation'] is False
    assert next(d for d in docs if d['kind']=='Service')['spec']['type']=='ClusterIP'


def test_qdrant_backup_resume_reuses_verified_snapshot_without_mutating_collection(tmp_path,monkeypatch):
    spec=importlib.util.spec_from_file_location('qdrant_backup',ROOT/'scripts/hybrid-qdrant-backup.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    config=tmp_path/'config';config.write_text('QDRANT_API_KEY=fixture-key')
    data=b'synthetic snapshot';digest=hashlib.sha256(data).hexdigest();created=[]
    def handler(request):
        assert request.headers['api-key']=='fixture-key'
        assert request.method in ('GET','POST')
        path=request.url.path
        if path=='/collections':return httpx.Response(200,json={'result':{'collections':[{'name':'fixture'}]}})
        if path=='/collections/fixture':return httpx.Response(200,json={'result':{'points_count':1,'config':{}}})
        if request.method=='POST':
            assert path=='/collections/fixture/snapshots';created.append(path)
            return httpx.Response(200,json={'result':{'name':'fixture.snapshot','size':len(data),'checksum':digest}})
        assert path=='/collections/fixture/snapshots/fixture.snapshot'
        return httpx.Response(200,content=data)
    client=httpx.Client
    monkeypatch.setattr(module.httpx,'Client',lambda **kwargs:client(**kwargs,transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(module.shutil,'disk_usage',lambda *a:SimpleNamespace(free=8*1024**3))
    first=module.backup(config,tmp_path/'backup');second=module.backup(config,tmp_path/'backup',True)
    assert len(created)==1 and first==second and first[0]['provider_checksum_verified']
    assert not first[0]['restore_tested']
    Path(first[0]['snapshot']).write_bytes(b'corrupted')
    with pytest.raises(ValueError):module.backup(config,tmp_path/'backup',True)
    assert len(created)==1
