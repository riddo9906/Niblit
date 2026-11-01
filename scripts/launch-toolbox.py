"""Launch the connected desktop release with this checkout's explicit .env."""
from pathlib import Path
import os
import subprocess

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
bundle = root / 'dist/latest-20261028-memory-refined/niblit'
exe = bundle / 'niblit.exe'
if not exe.is_file():
    raise SystemExit('The memory desktop release has not been built yet.')
environment = os.environ.copy()
environment.update({key: value for key, value in dotenv_values(root / '.env').items() if isinstance(value, str)})
previous = root / 'dist/niblit'
for variable, filename in {
    'NIBLIT_MEMORY_PATH': 'niblit_memory.json',
    'FUSED_MEMORY_DB_PATH': 'niblit_fused.sqlite',
    'NIBLIT_LLM_CHAT_DB_PATH': 'llm_chat_history.sqlite',
    'NIBLIT_SQLITE_DB_PATH': 'niblit_data.sqlite',
    'NIBLIT_DB_PATH': 'niblit.db',
}.items():
    existing = previous / filename
    if not environment.get(variable) and existing.is_file():
        environment[variable] = str(existing)
environment.setdefault('NIBLIT_TRADING_REQUIRED', 'false')
environment.setdefault('NIBLIT_WORKSPACE_ROOT', str(root))
subprocess.Popen([str(root/'niblit-env/Scripts/pythonw.exe'), str(root/'scripts/launch-trading-desk.py')], cwd=root,
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
if environment.get('NIBLIT_MEMORY_LAB_ENABLED') == '1':
    helper = root / 'scripts/ensure-memory-service.py'
    pythonw = root / 'niblit-env/Scripts/pythonw.exe'
    subprocess.Popen([str(pythonw), str(helper)], cwd=root,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    subprocess.Popen([str(pythonw), str(root / 'scripts/launch-memory-desk.py')], cwd=root,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
subprocess.Popen([str(exe)], cwd=bundle, env=environment,
    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
