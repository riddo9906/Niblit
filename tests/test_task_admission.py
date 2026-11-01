from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock
import pytest
from modules.task_admission import TaskAuthority,AdmissionBusy,admitted
from modules.server_manager import ServerManager


def test_independent_authorities_share_one_persistent_slot(tmp_path):
    m=ServerManager(tmp_path/'authority.sqlite')
    a,b=TaskAuthority(m),TaskAuthority(m)
    def attempt(authority):
        try:return authority.acquire('core_inference')
        except AdmissionBusy:return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(attempt,[a,b]))
    leases=[r for r in results if r]
    assert len(leases)==1
    assert b.status()['state']=='active'
    with pytest.raises(ValueError):a.finish('not-the-owner-token')
    a.finish(leases[0]['token'],uncertain=True)
    restarted=TaskAuthority(ServerManager(m.path))
    assert restarted.status()['state']=='quarantined'
    with pytest.raises(AdmissionBusy):restarted.acquire('portal_chat')
    # Only the real ownership token can complete the original task.
    restarted.finish(leases[0]['token'])
    assert a.status()['state']=='idle'


def test_nested_calls_share_ownership_and_busy_never_runs(monkeypatch,tmp_path):
    key=tmp_path/'key';key.write_text('test-admission-key-not-a-real-secret-12345')
    monkeypatch.setenv('NIBLIT_SHARED_ADMISSION','1')
    monkeypatch.setenv('NIBLIT_PORTAL_GGUF_KEY_FILE',str(key))
    client=Mock();response=client.post.return_value;response.status_code=200;response.json.return_value={'token':'local-test-lease'}
    factory=Mock();factory.return_value.__enter__=Mock(return_value=client);factory.return_value.__exit__=Mock(return_value=False)
    monkeypatch.setattr('modules.task_admission.httpx.Client',factory)
    with admitted('portal_chat'):
        with admitted('core_inference'):pass
    assert client.post.call_count==2
    assert client.post.call_args.kwargs['json']['uncertain'] is False
    response.status_code=409
    with pytest.raises(AdmissionBusy):
        with admitted('portal_chat'):pytest.fail('Busy task was executed')


def test_unknown_failure_quarantines_and_off_is_compatible(monkeypatch,tmp_path):
    monkeypatch.delenv('NIBLIT_SHARED_ADMISSION',raising=False)
    with admitted('portal_chat'):pass
    key=tmp_path/'key';key.write_text('test-admission-key-not-a-real-secret-12345')
    monkeypatch.setenv('NIBLIT_SHARED_ADMISSION','1');monkeypatch.setenv('NIBLIT_PORTAL_GGUF_KEY_FILE',str(key))
    client=Mock();client.post.return_value.status_code=200;client.post.return_value.json.return_value={'token':'lease'}
    factory=Mock();factory.return_value.__enter__=Mock(return_value=client);factory.return_value.__exit__=Mock(return_value=False)
    monkeypatch.setattr('modules.task_admission.httpx.Client',factory)
    with pytest.raises(TimeoutError):
        with admitted('local_tutor'):raise TimeoutError()
    assert client.post.call_args.kwargs['json']['uncertain'] is True
