import sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

def test_packaged_boot_waits_for_selected_services(monkeypatch):
    import main
    from modules import multi_repo_orchestrator as module
    manager=Mock();manager.get_runtime_services.return_value={'service_count':1};manager.get_runtime_health.return_value={'status':'healthy'}
    core=SimpleNamespace(runtime_manager=manager,brain=object())
    orchestrator=Mock()
    orchestrator.start_managed_repositories.return_value={'niblit-cloud-server':{'state':'running'},'niblit-lean-algos':{'state':'starting'}}
    orchestrator.monitor_managed_repositories.return_value={'niblit-cloud-server':{'state':'running'},'niblit-lean-algos':{'state':'running'},'niblit-ui':{'state':'stopped'}}
    monkeypatch.setattr(module,'get_multi_repo_orchestrator',lambda:orchestrator)
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    monkeypatch.setattr(main.time,'sleep',lambda _:None)
    monkeypatch.setattr(main,'_BOOT_STATUS',main.BootStatus())
    report=main._run_staged_runtime_bootstrap(core,Mock())
    assert report['managed_repos']['status']=='success'
    orchestrator.start_managed_repositories.assert_called_once()
    orchestrator.monitor_managed_repositories.assert_called_once()

def test_packaged_boot_wait_is_bounded_without_restart(monkeypatch):
    import main
    from modules import multi_repo_orchestrator as module
    manager=Mock();manager.get_runtime_services.return_value={'service_count':1};manager.get_runtime_health.return_value={'status':'healthy'}
    orchestrator=Mock()
    starting={'niblit-cloud-server':{'state':'starting'}}
    orchestrator.start_managed_repositories.return_value=starting
    orchestrator.monitor_managed_repositories.return_value=starting
    monkeypatch.setattr(module,'get_multi_repo_orchestrator',lambda:orchestrator)
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    clock=iter([0.,0.,31.]);monkeypatch.setattr(main.time,'monotonic',lambda:next(clock))
    monkeypatch.setattr(main.time,'sleep',lambda _:None)
    monkeypatch.setattr(main,'_BOOT_STATUS',main.BootStatus())
    report=main._run_staged_runtime_bootstrap(SimpleNamespace(runtime_manager=manager,brain=object()),Mock())
    assert report['managed_repos']['status']=='degraded'
    orchestrator.start_managed_repositories.assert_called_once()
