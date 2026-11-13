from pathlib import Path
import ast
from types import SimpleNamespace
from unittest.mock import Mock
from modules.command_registry import CommandRegistry

def test_essential_commands_independent_of_optional_improvements():
    source=Path(__file__).resolve().parents[1]/'niblit_core.py'
    tree=ast.parse(source.read_text(encoding='utf-8'))
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='NiblitCore')
    init=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='__init__')
    calls=[n for n in ast.walk(init) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='_init_command_registry']
    assert len(calls)==1
    optional=next(n for n in ast.walk(init) if isinstance(n,ast.If) and ast.unparse(n.test)=='self.config.enable_improvements')
    assert calls[0].lineno<optional.lineno
    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_init_command_registry')
    module=ast.Module(body=[method],type_ignores=[]);ns={'CommandRegistry':CommandRegistry,'log':Mock()}
    exec(compile(module,str(source),'exec'),ns)
    core=SimpleNamespace(command_registry=None,_emit_capability_event=lambda *a:None,_command_registry_snapshot=lambda:{})
    def register():core.command_registry.register('status',lambda:'ready','status','core')
    core._register_commands=Mock(side_effect=register)
    ns['_init_command_registry'](core);assert 'status' in core.command_registry.commands
    ns['_init_command_registry'](core);assert core._register_commands.call_count==1
