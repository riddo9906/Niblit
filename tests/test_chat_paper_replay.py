import pytest
from modules.cognitive_chat import admission, evidence_reply
from modules.paper_trading import _paper_run_id, PaperTradingError


def test_explicit_paper_request_and_exact_recall():
    intent,plan=admission('Run a governed paper trading evaluation using the approved replay dataset as paper-acceptance-001')
    assert intent=='paper_replay'
    assert plan==[('run_paper_replay',{'run_id':'paper-acceptance-001','dataset':'governed_paper_v1'})]
    assert admission('Explain paper episode paper-acceptance-001')[1]==[('read_paper_episode',{'run_id':'paper-acceptance-001'})]
    assert admission('Cancel paper evaluation paper-acceptance-001')[1][0][0]=='cancel_paper_replay'


@pytest.mark.parametrize('text',[
    'Run a governed paper trading evaluation using the approved replay dataset and enable MT5 demo',
    'Run a governed paper trading evaluation using dataset C:/private.json',
    'Place a real buy order', 'Activate funded trading'])
def test_unapproved_execution_never_routes_to_paper(text):
    assert not admission(text)[1]


@pytest.mark.parametrize('value',['paper-../private','paper-abc','../paper-abcdefgh',None,'paper-ABCDEFGH'])
def test_run_paths_are_not_user_filesystem_paths(value):
    with pytest.raises(PaperTradingError):_paper_run_id(value)


def test_failed_dispatch_does_not_claim_execution():
    reply=evidence_reply('paper_replay',{},[{'status':'authorization_required'}])
    assert 'No paper execution is established' in reply


def test_permission_checked_before_worker_or_manifest(tmp_path,monkeypatch):
    from modules import permission_manager
    from modules.core_tool_runtime import build_governed_tool_loop
    p=tmp_path/'permissions.json';p.write_text('{}')
    monkeypatch.setattr(permission_manager,'PERM_FILE',str(p))
    monkeypatch.setenv('NIBLIT_PAPER_REPLAY_MANIFEST',str(tmp_path/'not-opened.json'))
    loop=build_governed_tool_loop(lambda:None)
    assert loop.invoke('run_paper_replay',{'run_id':'paper-denied-0001'})['status']=='authorization_required'
    assert loop.invoke('cancel_paper_replay',{'run_id':'paper-denied-0001'})['status']=='authorization_required'


def test_mutated_worker_identity_fails_closed(tmp_path,monkeypatch):
    import hashlib,json
    from modules.paper_trading import _replay_manifest
    lean=tmp_path/'lean';lean.mkdir();core=tmp_path/'core';core.mkdir()
    worker=lean/'worker.py';worker.write_text('trusted')
    data=lean/'data.json';data.write_text('{}')
    manifest=dict(lean_root=str(lean),core_root=str(core),worker=str(worker),dataset=str(data),
        dataset_id='governed_paper_v1',files={str(p.resolve()):hashlib.sha256(p.read_bytes()).hexdigest() for p in (worker,data)})
    path=tmp_path/'manifest.json';path.write_text(json.dumps(manifest))
    monkeypatch.setenv('NIBLIT_PAPER_REPLAY_MANIFEST',str(path))
    assert _replay_manifest()['dataset_id']=='governed_paper_v1'
    worker.write_text('untrusted replacement')
    with pytest.raises(PaperTradingError,match='identity changed'):_replay_manifest()


def test_exact_operational_recall_respects_principal_and_missing_receipt(tmp_path,monkeypatch):
    from test_memory_laboratory_gateway import Backend,gateway
    from modules.memory_laboratory import context
    from modules.paper_trading import _isolated_episode
    g=gateway(tmp_path,Backend())
    monkeypatch.setattr(context,'runtime_gateway',lambda:g)
    monkeypatch.setenv('NIBLIT_MEMORY_LAB_NAMESPACE','test')
    monkeypatch.setenv('NIBLIT_MEMORY_LAB_PRINCIPAL','operator')
    with g.db() as db:
        g.audit(db,'paper.episode','paper-exact-0001',namespace='test',principal='operator',
            status='completed',summary={'status':'completed','run_id':'paper-exact-0001'})
        g.audit(db,'paper.job','paper-interrupted-0001',namespace='test',principal='operator',status='running')
    assert _isolated_episode('paper-exact-0001')['status']=='completed'
    assert _isolated_episode('paper-interrupted-0001')['status']=='interrupted'
    monkeypatch.setenv('NIBLIT_MEMORY_LAB_PRINCIPAL','foreign')
    assert _isolated_episode('paper-exact-0001')['status']=='UNKNOWN'
