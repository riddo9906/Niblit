from pathlib import Path
from types import SimpleNamespace
import pytest
from modules.command_registry import CanonicalRuntimeCapabilityRegistry
from modules.operator_commands import list_operator_commands, execute_operator_command, _source_guards
from niblit_router import NiblitRouter

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def core(monkeypatch):
    monkeypatch.setattr('modules.permission_manager.PermissionManager.check',lambda *args:False)
    from modules import core_tool_runtime
    monkeypatch.setattr(core_tool_runtime,'_emit_command_event',lambda *args:None)
    registry=CanonicalRuntimeCapabilityRegistry()
    facts=[]
    owner=SimpleNamespace(command_registry=registry,db=SimpleNamespace(add_fact=lambda k,v:facts.append((k,v))),facts=facts)
    router=NiblitRouter.__new__(NiblitRouter)
    router.core=owner; router.brain=None; router.memory=owner.db
    owner.router=router; owner.brain=None
    registry.register('remember',None,source_authority='niblit_router.py')
    return owner

def test_discovers_real_router_guards_missing_from_prefix_catalogue(core):
    entries={c['name']:c for c in list_operator_commands(core,ROOT)['commands']}
    assert entries['threads']['execution_enabled']
    assert entries['threads']['execution_channel']=='operator'
    assert not entries['threads']['llm_exposed']
    result=execute_operator_command(core,'threads',confirmed=True,root=ROOT)
    assert result['status']=='success' and 'Active threads' in result['result']

def test_original_remember_executes_real_router_and_preserves_case(core):
    result=execute_operator_command(core,'remember',{'text':'MyKey: Value: With Colon'},confirmed=True,root=ROOT)
    assert result['status']=='success'
    assert core.facts==[('MyKey','Value: With Colon')]

def test_remember_disk_failure_is_not_reported_saved(core):
    def fail(*args): raise OSError('disk full')
    core.db.add_fact=fail
    result=execute_operator_command(core,'remember',{'text':'key: value'},confirmed=True,root=ROOT)
    assert result['status']=='error' and 'disk full' in result['error']

def test_no_confirmation_no_mutation(core):
    assert execute_operator_command(core,'remember',{'text':'key: value'},root=ROOT)['status']=='rejected'
    assert not core.facts

def test_unknown_does_not_fall_back_to_chat(core):
    core.handle=lambda text:pytest.fail('Unknown command reached chat')
    assert execute_operator_command(core,'made up command',confirmed=True,root=ROOT)['status']=='rejected'

def test_exact_command_is_not_stolen_by_broad_higher_priority_prefix(core):
    core.command_registry.register('example',lambda text:'wrong',priority=100)
    core.command_registry.register('example child',lambda text:'right:'+text,priority=1,aliases=['child-alias'])
    assert execute_operator_command(core,'child-alias',{'text':'AbC'},confirmed=True,root=ROOT)['result']=='right:AbC'

def test_risky_subcommand_rechecks_permissions_before_dispatch(core):
    core.command_registry.register('tools',lambda text:pytest.fail('Unauthorized tool ran'))
    result=execute_operator_command(core,'tools',{'text':'run niblit_exec {}'},confirmed=True,root=ROOT)
    assert result['status']=='authorization_required'

def test_shell_lifecycle_and_missing_core_are_truthful(core):
    entries={c['name']:c for c in list_operator_commands(core,ROOT)['commands']}
    assert entries['exit']['state']=='UNAVAILABLE'
    assert list_operator_commands(None,ROOT)['count']==0

def test_source_discovery_ignores_negative_and_subcommand_guards(tmp_path):
    (tmp_path/'niblit_router.py').write_text('def handle_command(cmd):\n lower=cmd.lower()\n if lower == "real": return 1\n if not lower.startswith("fake"): pass\n if sub == "not global": pass\n')
    assert _source_guards(tmp_path,'niblit_router.py')=={'real':3}

def test_argument_shape_rejected_before_handler(core):
    assert execute_operator_command(core,'remember',{'other':'x'},confirmed=True,root=ROOT)['status']=='rejected'

def test_invalid_remember_is_not_a_success(core):
    assert execute_operator_command(core,'remember',{'text':'invalid'},confirmed=True,root=ROOT)['status']=='error'
