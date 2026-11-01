"""Prepare the official Codex executor for an existing self-hosted session."""
import os
from pathlib import Path
import re
import shutil
from urllib.parse import urlsplit

from modules.steward_agent import StewardBridge


def codex_executable():
    override = os.getenv('NIBLIT_CODEX_PATH')
    if override and Path(override).is_file():
        return str(Path(override).resolve())
    base = Path(os.getenv('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'OpenAI/Codex/bin'
    candidates = list(base.glob('*/codex.exe'))
    if candidates:
        return str(max(candidates, key=lambda path: path.stat().st_mtime))
    found = shutil.which('codex')
    if not found:
        raise ValueError('Codex CLI is not installed; install the official Codex CLI first')
    return found


def executor_configuration(session_id, bridge=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', session_id):
        raise ValueError('Invalid session ID')
    bridge = bridge or StewardBridge()
    session = bridge.request('GET', '/sessions/' + session_id)
    environment = session.get('environment') or {}
    if environment.get('type') != 'self_hosted':
        raise ValueError('This session is not self-hosted')
    remote = environment.get('remote_url', '')
    parsed = urlsplit(remote)
    if parsed.scheme != 'https' or parsed.hostname != 'api.openai.com' or not parsed.path.startswith('/v1/agents/api/connect/') or parsed.username or parsed.password:
        raise ValueError('The API did not return a supported official executor connection URL')
    environment_id = environment.get('id', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', environment_id):
        raise ValueError('The API did not return a valid environment ID')
    workspace = Path(environment.get('workspace_directory', ''))
    if not workspace.is_absolute() or not workspace.is_dir():
        raise ValueError('The session workspace directory does not exist on this PC')
    turns = bridge.request('GET', '/sessions/' + session_id + '/turns?limit=20')
    if any(turn.get('status') in ('queued', 'in_progress') for turn in turns.get('data', [])):
        raise ValueError('This session has queued inference work. Connection was not started because it could resume paid work')
    key = os.getenv('OPENAI_EXECUTOR_API_KEY', '')
    if not key:
        raise ValueError('Set OPENAI_EXECUTOR_API_KEY to a restricted environment key in the private .env file')
    # No application provider keys are inherited by the executor process.
    allowed = {'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','USERPROFILE','HOMEDRIVE','HOMEPATH',
        'LOCALAPPDATA','APPDATA','COMSPEC','PATHEXT','NUMBER_OF_PROCESSORS','PROCESSOR_ARCHITECTURE','PROGRAMDATA'}
    child_env = {name:value for name,value in os.environ.items() if name.upper() in allowed}
    child_env['CODEX_API_KEY'] = key
    child_env.setdefault('USERPROFILE', str(Path.home()))
    return {'command': [codex_executable(), 'exec-server', '--remote', remote, '--environment-id', environment_id,
            '--name', 'Niblit Steward workspace', '--exit-on-stdin-close'],
        'cwd': str(workspace), 'env': child_env, 'session_id': session_id, 'environment_id': environment_id}
