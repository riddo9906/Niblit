import json,os
from unittest.mock import Mock
import pytest
from modules.niblit_ui_launcher import _api_owned_by_current_process


@pytest.mark.parametrize('pid,bound,expected',[(os.getpid(),True,True),(os.getpid()+1,True,False),(os.getpid(),False,False),(None,True,False)])
def test_api_process_identity(monkeypatch,pid,bound,expected):
    response=Mock();response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
    response.read.return_value=json.dumps({'service':'niblit','process_id':pid,'core_bound':bound}).encode()
    monkeypatch.setattr('urllib.request.urlopen',lambda *a,**k:response)
    assert _api_owned_by_current_process('http://127.0.0.1:5000/health') is expected


def test_api_owner_unavailable(monkeypatch):
    def fail(*a,**k):raise TimeoutError()
    monkeypatch.setattr('urllib.request.urlopen',fail)
    assert not _api_owned_by_current_process('http://127.0.0.1:5000/health')


def test_foreign_core_blocks_ui_without_attempting_port_takeover(monkeypatch):
    from types import SimpleNamespace
    from modules import niblit_ui_launcher as launcher
    start=Mock();ui=Mock()
    monkeypatch.setattr(launcher,'_wait_for_http_ready',lambda *a,**k:True)
    monkeypatch.setattr(launcher,'_api_owned_by_current_process',lambda url:False)
    monkeypatch.setattr(launcher,'_start_api_server_thread',start)
    monkeypatch.setattr(launcher,'_launch_tauri_dev_process',ui)
    outcome=launcher.launch_primary_ui(core=SimpleNamespace())
    assert not outcome.success and outcome.readiness['api']=='unavailable'
    start.assert_not_called();ui.assert_not_called()
