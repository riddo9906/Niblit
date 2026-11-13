import json,sys,threading
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from modules import learning_commands
from modules.command_effects import observe
from modules.operator_commands import _command_outcome
from modules.permission_manager import PermissionManager
from test_memory_laboratory_gateway import Backend,gateway

@pytest.fixture
def activation(tmp_path,monkeypatch):
    g=gateway(tmp_path,Backend());pm=PermissionManager();pm.path=str(tmp_path/'permissions.json')
    perms={'command.operator.autonomous_learn_start':True,'trading.execute':False}
    (tmp_path/'permissions.json').write_text(json.dumps(perms));pm._load()
    monkeypatch.setitem(sys.modules,'server',SimpleNamespace(_get_learning_control=lambda:(pm,g,'test-core',None),_learning_decision_lock=threading.Lock()))
    monkeypatch.setattr('modules.native_runtime_readiness.check_readiness',lambda *a:{'ready':True,'checks':[]})
    engine=SimpleNamespace(running=False,lifecycle_status=lambda:{'worker_alive':False,'unfinished_steps':0})
    return SimpleNamespace(autonomous_engine=engine),pm,g

def test_start_activates_exactly_one_approved_bounded_task(activation):
    core,pm,g=activation;calls=[]
    def start(**kwargs):
        calls.append(kwargs);core.autonomous_engine.running=True;return True
    core.autonomous_engine.start=start
    result=learning_commands.start(core,'Memory durability')
    assert result['execution_started'] and result['cycles']==1 and result['paid_requests']==0
    task=pm.learning_requests(g,'test-core')[0]
    assert task['state']=='approved' and task['spec']['limits']['model_calls']==1
    assert calls[0]['task_authorization'][:2]==(pm,g)
    assert learning_commands.start(core)['state']=='busy' and len(calls)==1
    assert not pm.check('trading.execute')

def test_failed_start_revokes_scoped_authority(activation):
    core,pm,g=activation;core.autonomous_engine.start=Mock(return_value=False)
    assert learning_commands.start(core)['state']=='busy'
    assert pm.learning_requests(g,'test-core')[0]['state']=='failed'

def test_unready_start_does_not_create_task(activation,monkeypatch):
    core,pm,g=activation;core.autonomous_engine.start=Mock()
    monkeypatch.setattr('modules.native_runtime_readiness.check_readiness',lambda *a:{'ready':False,'checks':[]})
    assert learning_commands.start(core)['state']=='unavailable'
    core.autonomous_engine.start.assert_not_called();assert pm.learning_requests(g,'test-core')==[]

def test_permission_revocation_is_reloaded(activation):
    core,pm,g=activation
    open(pm.path,'w').write(json.dumps({'command.operator.autonomous_learn_start':False}))
    with pytest.raises(PermissionError):learning_commands.start(core)
    assert pm.learning_requests(g,'test-core')==[]

def test_stop_pending_is_not_reported_complete():
    engine=SimpleNamespace(stop=lambda:False,lifecycle_status=lambda:{'worker_alive':True,'unfinished_steps':1})
    result=learning_commands.stop(SimpleNamespace(autonomous_engine=engine))
    assert not result['worker_finished'] and _command_outcome(result)[0]=='pending'

@pytest.mark.parametrize('command,active,verified', [('evolve start',False,False),('evolve start',True,True),('evolve stop',True,False),('evolve stop',False,True)])
def test_lifecycle_checks_actual_worker(command,active,verified):
    engine=SimpleNamespace(running=active,_thread=SimpleNamespace(is_alive=lambda:active))
    assert observe(SimpleNamespace(evolve_engine=engine),command)['verified']==verified

@pytest.mark.parametrize('action',['start','on','resume','stop','off','pause'])
def test_research_aliases_use_same_owned_worker(action):
    from niblit_router import NiblitRouter
    router=NiblitRouter.__new__(NiblitRouter)
    router.core=SimpleNamespace(_cmd_autonomous_start=Mock(return_value={'state':'started'}),_cmd_autonomous_stop=Mock(return_value={'state':'stopped'}))
    router._handle_auto_research('auto-research '+action)
    getattr(router.core,'_cmd_autonomous_start' if action in ('start','on','resume') else '_cmd_autonomous_stop').assert_called_once_with('')

def test_memory_app_reuses_owned_runtime(tmp_path):
    from modules.memory_laboratory.web import create_app
    from modules.memory_laboratory.runtime import MemoryRuntime
    g=gateway(tmp_path,Backend());runtime=MemoryRuntime(g)
    app=create_app(g,root=tmp_path,runtime=runtime)
    assert app is not None
    with pytest.raises(ValueError):create_app(g,root=tmp_path,runtime=SimpleNamespace(gateway=object()))
