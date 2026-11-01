"""Locate existing desktop prerequisites without downloads or configuration edits."""
from pathlib import Path
import os
import shutil
import subprocess
import time


def docker_desktop_path(environment=None):
    """Docker supports both per-user and all-users Windows installations."""
    env = os.environ if environment is None else environment
    candidates = [
        Path(env.get('LOCALAPPDATA', '')) / 'Programs/DockerDesktop/Docker Desktop.exe',
        Path(env.get('ProgramFiles', 'C:/Program Files')) / 'Docker/Docker/Docker Desktop.exe',
    ]
    return next((path for path in candidates if path.is_absolute() and path.is_file()), None)


def docker_ready(cli):
    # Discard raw Docker output: it may contain private registry configuration.
    try:
        return subprocess.run([cli, 'version', '--format', '{{.Server.Version}}'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def ensure_docker(*, wait_seconds=45, ready=None, launch=None, clock=None, sleep=None,
                  cli=None, desktop=None):
    """Bounded startup only. Never install, rebuild, reset or remove volumes."""
    cli = cli or shutil.which('docker')
    if not cli:
        return {'ready': False, 'started': False, 'reason': 'Docker CLI is not installed or not on PATH'}
    ready = ready or (lambda: docker_ready(cli))
    if ready():
        return {'ready': True, 'started': False}
    desktop = desktop or docker_desktop_path()
    if not desktop:
        return {'ready': False, 'started': False, 'reason': 'Existing Docker Desktop installation not found'}
    if launch is None:
        launch = lambda path: subprocess.Popen([str(path)], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    try:
        launch(desktop)
    except OSError:
        return {'ready': False, 'started': False, 'reason': 'Docker Desktop could not start'}
    clock, sleep = clock or time.monotonic, sleep or time.sleep
    deadline = clock() + max(0, min(wait_seconds, 45))
    while clock() < deadline:
        if ready():
            return {'ready': True, 'started': True}
        sleep(1)
    return {'ready': False, 'started': True,
            'reason': 'Docker is not ready yet. Check Docker Desktop, then retry; no data was reset'}
