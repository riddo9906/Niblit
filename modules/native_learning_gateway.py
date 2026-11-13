"""Core-owned local learning transport. Reuses the canonical gateway and worker."""
import os
import socket
import threading
import time
from pathlib import Path

_lock=threading.Lock()

def install(core):
    if os.getenv('NIBLIT_NATIVE_LEARNING_GATEWAY')!='1':return {'enabled':False}
    with _lock:
        existing=getattr(core,'_native_learning_server',None)
        if existing is not None:
            owned=getattr(core,'_native_learning_thread',None)
            if owned is not None and owned.is_alive():
                return {'enabled':True,'started':bool(existing.started),'reused':True}
            core._native_learning_server=None
            core._native_learning_thread=None
        from modules.memory_laboratory.runtime import runtime_memory
        runtime=runtime_memory()
        if runtime is None:raise RuntimeError('Canonical memory runtime unavailable')
        root=Path(os.environ['NIBLIT_WORKSPACE_ROOT'])
        if len((root/'runtime/client-portal/gguf-api-key').read_text(encoding='utf-8').strip())<32:
            raise RuntimeError('Existing local authentication unavailable')
        with socket.socket() as check:
            if check.connect_ex(('127.0.0.1',8772))==0:
                # Never replace another listener. Readiness verifies its existing auth and idle authority.
                return {'enabled':True,'started':False,'external_listener':True}
        from modules.memory_laboratory.web import create_app
        import uvicorn
        application=create_app(gateway=runtime.gateway,runtime=runtime,root=root,port=8772)
        server=uvicorn.Server(uvicorn.Config(application,host='127.0.0.1',port=8772,log_level='warning',log_config=None))
        thread=threading.Thread(target=server.run,name='NiblitNativeMemoryAPI',daemon=True)
        core._native_learning_server=server;core._native_learning_thread=thread
        thread.start()
        deadline=time.monotonic()+5
        while not server.started and thread.is_alive() and time.monotonic()<deadline:time.sleep(.05)
        if not server.started:raise RuntimeError('Core-owned local learning transport did not start')
        return {'enabled':True,'started':True,'same_memory_runtime':True}
