"""Isolated Core readiness profiler with per-layer waits and live worker stacks."""
from __future__ import annotations
import argparse, json, logging, os, platform, site, sys, threading, time, traceback
from collections import defaultdict
from pathlib import Path

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--checkout',type=Path,required=True); ap.add_argument('--run-dir',type=Path,required=True); ap.add_argument('--dependency-site',type=Path,required=True); ns=ap.parse_args()
    checkout=ns.checkout.resolve(); run=ns.run_dir.resolve(); run.mkdir(parents=True,exist_ok=True)
    safe={k:os.environ[k] for k in ('PATH','SYSTEMROOT','WINDIR','COMSPEC','PATHEXT','SYSTEMDRIVE','PROCESSOR_ARCHITECTURE','NUMBER_OF_PROCESSORS','OS') if k in os.environ}
    paths={n:run/n for n in ('home','appdata','localappdata','temp','cache','memory','workspace')}
    for x in paths.values(): x.mkdir(parents=True,exist_ok=True)
    safe.update({'HOME':str(paths['home']),'USERPROFILE':str(paths['home']),'APPDATA':str(paths['appdata']),'LOCALAPPDATA':str(paths['localappdata']),'TEMP':str(paths['temp']),'TMP':str(paths['temp']),'HF_HOME':str(paths['cache']/'hf'),'HUGGINGFACE_HUB_CACHE':str(paths['cache']/'hf'/'hub'),'TRANSFORMERS_CACHE':str(paths['cache']/'transformers'),'TORCH_HOME':str(paths['cache']/'torch'),'XDG_CACHE_HOME':str(paths['cache']/'xdg'),'NIBLIT_MEMORY_PATH':str(paths['memory']/'niblit_memory.json'),'NIBLIT_WORKSPACE_ROOT':str(paths['workspace']),'NIBLIT_RUNTIME_MODE':'api','NIBLIT_TRADING_MODE':'observe','NIBLIT_TRADING_ALLOW_EXECUTION':'false','PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1','PYTHON_DOTENV_DISABLED':'1'})
    os.environ.clear(); os.environ.update(safe); site.addsitedir(str(ns.dependency_site.resolve()))
    repo=Path(__file__).resolve().parents[2]; sys.path[:]=[x for x in sys.path if not (Path(x or os.getcwd()).resolve()==repo or repo in Path(x or os.getcwd()).resolve().parents)]; sys.path.insert(0,str(checkout)); os.chdir(checkout)
    logging.basicConfig(filename=str(run/'core.log'),level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
    from niblit_core import NiblitCore
    t0=time.perf_counter(); ti=time.perf_counter(); core=NiblitCore(memory_path=str(paths['memory']/'niblit_memory.json')); ctor=(time.perf_counter()-ti)*1000
    waits=[]; layer_elapsed={}; lock=threading.Lock(); original=core._init_with_timeout
    def timed(layer_fn,layer_name,timeout=0):
        outer_start=time.perf_counter(); finished=threading.Event()
        def measured_layer():
            begin=time.perf_counter()
            try: layer_fn()
            finally:
                with lock: layer_elapsed[layer_name]=(time.perf_counter()-begin)*1000
                finished.set()
        ok=original(measured_layer,layer_name,timeout)
        with lock: waits.append({'layer':layer_name,'wait_ms':round((time.perf_counter()-outer_start)*1000,3),'completed_in_wait':bool(ok),'worker_finished':finished.is_set(),'timeout_seconds':timeout or core._INIT_LAYER_TIMEOUT_DEFAULT})
        return ok
    core._init_with_timeout=timed
    ready_start=time.perf_counter(); ready=core.wait_for_ready(timeout=900); wait_ms=(time.perf_counter()-ready_start)*1000
    time.sleep(3)
    frames=sys._current_frames(); stack={}
    for th in threading.enumerate():
        if th.name.startswith('niblit-layer-'):
            frame=frames.get(th.ident); rows=[]
            while frame:
                rows.append({'file':frame.f_code.co_filename,'line':frame.f_lineno,'function':frame.f_code.co_name})
                frame=frame.f_back
            stack[th.name]={'alive':th.is_alive(),'stack_oldest_to_newest':list(reversed(rows))}
    result={'python':sys.version.split()[0],'platform':platform.platform(),'ready':ready,'phase':getattr(core,'_deferred_init_phase',None),'import_ms':None,'constructor_ms':round(ctor,3),'wait_for_ready_ms':round(wait_ms,3),'elapsed_to_ready_ms':round((time.perf_counter()-t0)*1000,3),'layer_waits':waits,'layer_worker_function_elapsed_ms':{k:round(v,3) for k,v in layer_elapsed.items()},'live_layer_stacks_after_ready_plus_3s':stack,'startup_report_summary':core.startup_report.summary() if hasattr(core,'startup_report') else None}
    (run/'readiness.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    core.shutdown()
    print(json.dumps({k:result[k] for k in ('ready','phase','constructor_ms','wait_for_ready_ms','elapsed_to_ready_ms','layer_waits','layer_worker_function_elapsed_ms','live_layer_stacks_after_ready_plus_3s')},indent=2))
if __name__=='__main__': main()
