from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from core.runtime_manager import RuntimeManager
from modules import desktop_diagnostics

@pytest.fixture
def manager():
    m=RuntimeManager.__new__(RuntimeManager)
    m._service_registry={};m._service_statuses={};m._service_load_durations_ms={};m._service_init_order=[]
    m._bind_module_singleton=Mock()
    return m

def test_missing_factory_never_claims_ready_and_can_recover(manager):
    manager._set_service_status('local_brain','degraded','original factory mismatch')
    assert manager._initialize_service('local_brain',lambda:None) is None
    assert manager._service_statuses['local_brain']=={'status':'degraded','detail':'original factory mismatch'}
    assert 'local_brain' not in manager._service_registry
    manager._bind_module_singleton.assert_not_called()
    service=object()
    assert manager._initialize_service('local_brain',lambda:service) is service
    assert manager._service_statuses['local_brain']=={'status':'ready'}
    assert manager._initialize_service('local_brain',Mock(side_effect=AssertionError('duplicate'))) is service

def test_builder_exception_remains_degraded(manager):
    with pytest.raises(RuntimeError):manager._initialize_service('bad',Mock(side_effect=RuntimeError('fixture fault')))
    assert manager._service_statuses['bad']=={'status':'degraded','detail':'fixture fault'}

def test_local_brain_uses_current_factory_contract(manager,monkeypatch):
    import modules.local_brain as local
    expected=object();factory=Mock(return_value=expected);monkeypatch.setattr(local,'get_local_brain',factory)
    assert manager._build_local_brain() is expected
    factory.assert_called_once_with()

def test_ale_reuses_core_owner_without_constructing_or_starting(manager):
    engine=SimpleNamespace(running=False,start=Mock());manager._core_ale=engine
    assert manager._build_ale() is engine
    engine.start.assert_not_called()

def test_current_layers_and_idle_ale_do_not_relabel_old_startup_faults():
    engine=SimpleNamespace(running=False)
    core=SimpleNamespace(runtime_manager=SimpleNamespace(get_runtime_health=lambda:{'services':{'local_brain':{'status':'ready','object_type':'LocalBrainGateway'}}}),
        autonomous_engine=engine,db=None,_staged_bootstrap_report={'local_brain':{'status':'degraded'}})
    result=desktop_diagnostics.desktop_snapshot(core,'overview')
    assert result['current_layers']['local_brain']['status']=='ready'
    assert result['startup_stages']['local_brain']['status']=='degraded'
    assert result['startup_stages_are_historical'] is True
    assert result['ale_runtime']['status']=='ready_idle'
    assert result['ale_runtime']['running'] is False
