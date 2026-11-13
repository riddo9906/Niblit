"""Bounded local lifecycle diagnostics without credentials or automatic trading recovery."""
import faulthandler
import json
import os
import threading
import time
from pathlib import Path

_lock=threading.Lock()
_fault_file=None


def event(name, **fields):
    root=os.environ.get('NIBLIT_RUNTIME_LOG_FILE')
    if not root:return
    path=Path(root).with_name('process-lifecycle.jsonl')
    # Only explicitly supplied, non-secret scalar diagnostics are accepted.
    allowed={'child_pid','exit_code','reason','error_type','owner_pid','restart_budget'}
    record={'schema_version':'runtime-lifecycle/1','event':name,'pid':os.getpid(),
            'parent_pid':os.getppid(),'timestamp':time.time(),
            **{k:v for k,v in fields.items() if k in allowed and isinstance(v,(str,int,float,bool,type(None)))}}
    try:
        with _lock:
            path.parent.mkdir(parents=True,exist_ok=True)
            if path.exists() and path.stat().st_size>2_000_000:
                backup=path.with_suffix('.previous.jsonl')
                os.replace(path,backup)
            with path.open('a',encoding='utf-8') as stream:stream.write(json.dumps(record)+'\n')
    except OSError:
        pass  # Diagnostics must not cause a second lifecycle failure.


def enable_fault_diagnostics():
    global _fault_file
    if _fault_file is not None:return
    root=os.environ.get('NIBLIT_RUNTIME_LOG_FILE')
    if not root:return
    try:
        path=Path(root).with_name('native-fault-'+str(os.getpid())+'.log')
        path.parent.mkdir(parents=True,exist_ok=True)
        _fault_file=path.open('a',encoding='utf-8')
        faulthandler.enable(file=_fault_file,all_threads=True)
        event('process_diagnostics_enabled',restart_budget=0)
    except (OSError,RuntimeError):
        event('fault_diagnostics_unavailable')
