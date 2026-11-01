"""Exercise native desktop autostart and SSE using disposable state only."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from urllib.request import ProxyHandler, Request, build_opener

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    bundle, output = args.bundle.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    for port in (5000, 8000, 28130, 28150):
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', port))
    env = {k:v for k,v in os.environ.items() if not any(word in k.upper() for word in ('TOKEN','API_KEY','PASSWORD','SECRET'))
           and not k.startswith('NIBLIT_')}
    env.update(PYTHON_DOTENV_DISABLED='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
        NIBLIT_HEADLESS='0', NIBLIT_LOW_RESOURCE_MODE='0', NIBLIT_SKIP_INIT_WAIT='0',
        NIBLIT_API_PORT='5000', NIBLIT_PORT='8000', NIBLIT_CLOUD_SERVER_PRIMARY_PORT='8000',
        NIBLIT_CLOUD_SERVER_URL='http://127.0.0.1:8000', NIBLIT_CLOUD_BASE_URL='http://127.0.0.1:8000',
        NIBLIT_TRADING_BACKEND='paper', NIBLIT_TRADING_MODE='observe',
        NIBLIT_TRADING_ALLOW_EXECUTION='false', NIBLIT_FREQTRADE_ALLOW_EXECUTION='false',
        NIBLIT_MARKET_DATA_PROVIDER='replay', NIBLIT_TRADING_API_PORT='28130', NIBLIT_STRATEGY_API_PORT='28150',
        NIBLIT_REPLAY_DATA_DIR=str(bundle/'freqtrade/data'), NIBLIT_REPLAY_STATE_FILE=str(output/'replay.json'),
        NIBLIT_PAPER_STATE_FILE=str(output/'paper.json'), NIBLIT_TRADING_CONTROL_FILE=str(output/'control.json'),
        NIBLIT_EXECUTION_DB=str(output/'executions.sqlite'), NIBLIT_MEMORY_PATH=str(output/'memory.json'),
        FUSED_MEMORY_DB_PATH=str(output/'fused.sqlite'), NIBLIT_LLM_CHAT_DB_PATH=str(output/'chat.sqlite'),
        NIBLIT_RUNTIME_LOG_FILE=str(output/'runtime.jsonl'), NIBLIT_PERMISSION_FILE=str(output/'permissions.json'),
        NIBLIT_SERVICE_LOG_DIR=str(output/'service-logs'), NIBLIT_UNIFIED_RUNTIME_STATE=str(output/'unified.json'),
        NIBLIT_WORKSPACE_ROOT=str(output), QDRANT_URL='http://127.0.0.1:1', NIBLIT_LLM_PROVIDER='qwen',
        NIBLIT_N_CTX='4096', NIBLIT_GGUF_N_CTX='4096')
    opener = build_opener(ProxyHandler({}))
    def get(url, timeout=10):
        with opener.open(url, timeout=timeout) as response:
            return json.load(response)
    report = {'ready':False, 'checks':{}}
    process = None
    try:
        with (output/'desktop.log').open('w',encoding='utf-8') as log:
            process = subprocess.Popen([str(bundle/'niblit.exe')],cwd=output,env=env,
                stdout=log,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            deadline = time.monotonic()+240
            while time.monotonic()<deadline and process.poll() is None:
                try:
                    if get('http://127.0.0.1:5000/health',2).get('service')=='niblit':
                        models=get('http://127.0.0.1:5000/v1/inference/models',5)
                        if models.get('data'): break
                except Exception: pass
                time.sleep(1)
            else: raise RuntimeError('Native autostart did not become ready')
            report['checks']['native_autostart']=True
            report['model_ids']=[m['id'] for m in models['data']]
            for _ in range(80):
                get('http://127.0.0.1:8000/v1/models')
            report['checks']['responsive_after_log_burst']=True
            for number in range(3):
                payload={'model':'qwen2.5-0.5b','messages':[{'role':'user','content':'Reply with READY only.'}],
                         'max_tokens':16,'temperature':0,'stream':True}
                req=Request('http://127.0.0.1:5000/v1/inference/chat',data=json.dumps(payload).encode(),
                            headers={'Content-Type':'application/json','Origin':'http://tauri.localhost'})
                content=[]; done=False
                with opener.open(req,timeout=90) as response:
                    for raw in response:
                        line=raw.decode('utf-8').strip()
                        if not line.startswith('data:'): continue
                        value=line[5:].strip()
                        if value=='[DONE]': done=True; break
                        frame=json.loads(value)
                        if frame.get('error'): raise RuntimeError('Upstream streaming error: '+str(frame['error']))
                        for choice in frame.get('choices',[]): content.append(choice.get('delta',{}).get('content',''))
                assert ''.join(content).strip() and done, 'Incomplete/empty model stream'
                get('http://127.0.0.1:5000/health')
                get('http://127.0.0.1:8000/healthz')
                report['checks'][f'stream_{number+1}_with_healthy_backends']=True
            report['ready']=True
            (output/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print('READY: native desktop and sustained SSE verified. Awaiting UI acceptance marker.',flush=True)
            deadline=time.monotonic()+600
            while time.monotonic()<deadline and process.poll() is None and not (output/'ui-finished').exists():
                time.sleep(1)
    except Exception as exc:
        report.update(ready=False,error=str(exc))
    finally:
        if process is not None and process.poll() is None:
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
            process.wait(timeout=20)
        (output/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    return 0 if report['ready'] else 1

if __name__=='__main__':
    raise SystemExit(main())
