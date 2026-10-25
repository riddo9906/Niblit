"""Desktop operator access to original handlers, separate from LLM tools."""
from __future__ import annotations

import ast
from functools import lru_cache
import json
from pathlib import Path
import re
import time
import sys
from threading import Lock

from modules.command_surface_audit import (
    READ_ONLY_EVIDENCE, VARIANT_SPELLINGS, canonical_id, match_risk_rule, read_cli_vocabulary,
)

_execution_lock = Lock()
_HIGH_RISK = {'CODE_EXECUTION', 'SYSTEM_MUTATION', 'GITHUB_MUTATION',
              'DEPLOYMENT', 'TRADING', 'SECURITY_SENSITIVE', 'WORKSPACE_WRITE'}
_SHELL_ONLY = {'exit', 'quit', 'shutdown', 'debug on', 'debug off'}


def _risk(name):
    for alias, canonical in sorted(VARIANT_SPELLINGS.items(),key=lambda pair:len(pair[0]),reverse=True):
        if name == alias or name.startswith(alias+' '):
            name=canonical+name[len(alias):]
            break
    if name.startswith(('tools run ', 'reload ', 'upgrade', 'update-self', 'update self',
                        'auto-research start', 'auto-research stop')):
        return 'CODE_EXECUTION'
    if name in READ_ONLY_EVIDENCE:
        return 'READ_ONLY'
    return (match_risk_rule(name) or {}).get('risk_class', 'INTERNAL')


def _strings(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return [value for item in node.elts for value in _strings(item)]
    return []


@lru_cache(maxsize=16)
def _guards(path, stamp):
    """Read positive guards on the full command, never subcommand variables."""
    del stamp
    try:
        tree = ast.parse(Path(path).read_text(encoding='utf-8-sig'))
    except (OSError, SyntaxError):
        return {}
    found = {}
    names = {'lower', 'lcmd', 'ltext', 'cmd', 'command'}
    def visit(test, line):
        if isinstance(test, ast.UnaryOp):
            return
        values = []
        if isinstance(test, ast.Call) and isinstance(test.func, ast.Attribute):
            owner = test.func.value
            if isinstance(owner, ast.Name) and owner.id in names and test.func.attr == 'startswith' and test.args:
                values = _strings(test.args[0])
        elif isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) and test.left.id in names:
            if len(test.ops) == 1 and isinstance(test.ops[0], (ast.Eq, ast.In)):
                values = _strings(test.comparators[0])
        for value in values:
            value = value.strip().lower()
            if value and len(value) < 120:
                found.setdefault(value, line)
        if isinstance(test, ast.BoolOp):
            for child in test.values:
                visit(child, line)
    for fn in ast.walk(tree):
        if isinstance(fn, ast.FunctionDef) and fn.name in {'_handle_impl', 'handle_command'}:
            for node in ast.walk(fn):
                if isinstance(node, ast.If):
                    visit(node.test, node.lineno)
    return found


def _source_guards(root, filename):
    path = root / filename
    try:
        return _guards(str(path), path.stat().st_mtime_ns)
    except OSError:
        return {}


def _inventory(core, root=None):
    root = Path(root or Path(__file__).resolve().parents[1])
    registry = getattr(core, 'command_registry', None)
    commands = dict(getattr(registry, 'commands', {}) or {})
    bindings = {name: ('registry', meta) for name, meta in commands.items()}
    # Core owns current commands; Brain's deprecated adapter is used only for
    # a verified legacy guard absent from both Core and Router.
    for filename, target in (('niblit_core.py', 'core'), ('niblit_router.py', 'router'), ('niblit_brain.py', 'brain')):
        if target == 'core' and not callable(getattr(core, 'handle', None)):
            continue
        for name, line in _source_guards(root, filename).items():
            current = bindings.get(name)
            if current is None or (current[0] == 'registry' and not callable(current[1].handler)):
                bindings[name] = (target, (filename, line))
    cli = read_cli_vocabulary(str(root))
    for name in [*cli.get('legacy_commands', []), *cli.get('direct_commands', {})]:
        bindings.setdefault(name, ('cli', ('main.py', 0)))
    if 'unified status' in cli.get('direct_commands', {}):
        bindings['unified status'] = ('main', ('main.py', '_cmd_unified_status'))
    for alias, canonical in VARIANT_SPELLINGS.items():
        if canonical in bindings:
            bindings[alias]=bindings[canonical]
    return registry, bindings


def _permission_actions(name, meta, risk):
    actions = list(getattr(meta, 'governance_requirements', ()) or ())
    if risk in _HIGH_RISK:
        actions.append('command.operator.' + canonical_id(name))
    return list(dict.fromkeys(actions))


def list_operator_commands(core, root=None):
    registry, bindings = _inventory(core, root)
    if registry is None:
        return {'source': 'original_operator_handlers', 'commands': [], 'count': 0, 'error': 'Core command registry is not ready'}
    snapshots = {item['name']: item for item in registry.capability_snapshot(surface='desktop')}
    from modules.permission_manager import PermissionManager
    permissions = PermissionManager()
    output = []
    for name, (target, binding) in sorted(bindings.items()):
        meta = getattr(registry, 'commands', {}).get(name)
        snapshot = snapshots.get(name, {})
        rule = match_risk_rule(name) or {}
        risk = _risk(name)
        side = 'read_only' if risk == 'READ_ONLY' else rule.get('side_effect_level', 'LOW')
        source = getattr(meta, 'source_authority', '') or (binding[0] if target != 'registry' else '')
        reason = ''
        owner = core if target == 'core' else getattr(core, target, None)
        implemented = target == 'main' or (callable(getattr(binding, 'handler', None)) if target == 'registry' else callable(getattr(owner, 'handle' if target == 'core' else 'handle_command', None)))
        if name in _SHELL_ONLY or target == 'cli':
            reason = 'Interactive CLI command; no desktop handler is bound.'
        elif not implemented:
            reason = 'The original handler is not available in this runtime.'
        elif snapshot and not snapshot.get('available', False):
            reason = snapshot.get('availability_reason') or 'Disabled on the desktop surface.'
        actions = _permission_actions(name, meta, risk)
        denied = [action for action in actions if not permissions.check(action)]
        state = 'UNAVAILABLE' if reason else 'REQUIRES_AUTHORIZATION' if denied else 'EXECUTABLE'
        output.append({
            'name': name, 'original_name': name, 'aliases': list(dict.fromkeys([*getattr(meta, 'aliases', ()),*[a for a,c in VARIANT_SPELLINGS.items() if c==name]])),
            'description': getattr(meta, 'description', '') or f'Original {target} command from {source}',
            'category': getattr(meta, 'category', '') or target,
            'original_source': source, 'source_symbol': f'{source}:{binding[1]}' if target != 'registry' else getattr(meta, 'execution_authority', ''),
            'execution_channel': 'operator', 'llm_exposed': False,
            'state': state, 'execution_enabled': state == 'EXECUTABLE',
            'confirmation_required': risk != 'READ_ONLY',
            'risk_class': risk, 'side_effect_level': side,
            'requires_authorization': bool(actions), 'authorization_action': denied[0] if denied else None,
            'unavailable_reason': reason or ('Permission required: ' + ', '.join(denied) if denied else ''),
            'input_schema': {'type': 'object', 'properties': {'text': {'type': 'string',
                'description': 'Original arguments or subcommand (for example: key: value)'}}, 'additionalProperties': False},
        })
    return {'source': 'original_operator_handlers', 'commands': output, 'count': len(output)}


def execute_operator_command(core, name, arguments=None, *, confirmed=False, request_id='', root=None):
    started = time.monotonic()
    base = {'command': name, 'request_id': request_id, 'result': None, 'error': None}
    if core is None:
        return {**base, 'status': 'unavailable', 'error': 'Core is not ready'}
    arguments = {} if arguments is None else arguments
    if not isinstance(arguments, dict) or set(arguments) - {'text'} or not isinstance(arguments.get('text', ''), str):
        return {**base, 'status': 'rejected', 'error': 'Expected only an optional text argument'}
    name = str(name).strip().lower()
    name = VARIANT_SPELLINGS.get(name,name)
    suffix = arguments.get('text', '').strip()
    if len(suffix) > 32000:
        return {**base, 'status': 'rejected', 'error': 'Command arguments exceed 32000 characters'}
    with _execution_lock:
        registry, bindings = _inventory(core, root)
        alias = next((key for key, (kind, value) in bindings.items()
                      if kind == 'registry' and name in getattr(value, 'aliases', ())), None)
        selected = name if name in bindings else alias
        entry = next((item for item in list_operator_commands(core, root)['commands'] if item['name'] == selected), None)
        if entry is None:
            return {**base, 'status': 'rejected', 'error': 'Unknown original command; no chat fallback was used'}
        if entry['state'] != 'EXECUTABLE':
            return {**base, 'status': 'authorization_required' if entry['state'] == 'REQUIRES_AUTHORIZATION' else 'unavailable',
                    'error': entry['unavailable_reason'], 'authorization_action': entry['authorization_action']}
        if entry['confirmation_required'] and confirmed is not True:
            return {**base, 'status': 'rejected', 'error': 'Confirm this operator command before execution'}
        target, binding = bindings[selected]
        text = selected + (' ' + suffix if suffix else '')
        if _risk(text) != 'READ_ONLY' and confirmed is not True:
            return {**base,'status':'rejected','error':'Confirm this operator command before execution'}
        # Classify the complete invocation too: a read-only family can contain
        # mutating subcommands, such as `tools run` or `runtime provider`.
        from modules.permission_manager import PermissionManager
        actions = _permission_actions(selected, getattr(registry, 'commands', {}).get(selected), _risk(text))
        denied = [action for action in actions if not PermissionManager().check(action)]
        if denied:
            return {**base,'status':'authorization_required','error':'Permission required: '+', '.join(denied),
                    'authorization_action':denied[0]}
        from modules.core_tool_runtime import _emit_command_event
        _emit_command_event('command.execution.started', {**base, 'channel': 'operator'})
        try:
            if target == 'registry':
                # Exact selection avoids a broad, higher-priority prefix
                # stealing a more specific command chosen in the desktop.
                result = binding.handler(suffix)
            elif target == 'core':
                result = core.handle(text)
            elif target == 'main':
                module = sys.modules.get('__main__')
                if not callable(getattr(module, binding[1], None)):
                    import main as module
                result = getattr(module, binding[1])(core)
            else:
                result = getattr(core, target).handle_command(text)
            status, error = 'success', None
            if result is None:
                status, error = 'unavailable', 'The original handler returned no response'
            elif isinstance(result, str):
                if re.search(r'(?i)(not available|unavailable|not initialized|not running)', result) and len(result) < 600:
                    status, error = 'unavailable', result
                elif re.match(r'(?is)^\s*(?:\[ERROR\]|❌|Unknown\b|Invalid\b|Usage:|Error:)', result):
                    status, error = 'error', result
            elif isinstance(result, dict) and (result.get('success') is False or result.get('ok') is False):
                status, error = 'error', str(result.get('error') or result.get('message') or 'Original handler failed')
            elif isinstance(result, dict) and result.get('status') in {'error','failed','rejected','unavailable','blocked'}:
                status, error = 'error', str(result.get('error') or result.get('message') or 'Original handler failed')
            result = json.loads(json.dumps(result, default=str))
        except Exception as exc:
            result, status, error = None, 'error', str(exc)
        outcome = {**base, 'status': status, 'result': result, 'error': error,
                   'duration_ms': round((time.monotonic()-started)*1000, 2),
                   'governance': {'schema_validated': True, 'executor': f'original.{target}',
                       'dispatch_path': 'Desktop operator -> original handler (not an LLM tool)'}}
        _emit_command_event('command.execution.completed', {**base, 'channel': 'operator', 'status': status})
        return outcome
