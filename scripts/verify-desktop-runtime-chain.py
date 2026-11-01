"""Verify the unified packaged boot chain and UI request responsiveness with isolated paper-only state."""
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
            from websockets.sync.client import connect
            latencies = []
            report['stage'] = 'connect_telemetry'
            with connect('ws://127.0.0.1:5000/ws/runtime', open_timeout=10, close_timeout=2, max_size=16*1024*1024) as telemetry:
                frame = json.loads(telemetry.recv(timeout=30))
                assert frame.get('stream_format') == 'niblit.runtime.stream.v1'
                report['checks']['runtime_telemetry_frame'] = True
                report['stage'] = 'health_with_telemetry'
                for _ in range(20):
                    began = time.monotonic()
                    assert get('http://127.0.0.1:5000/health', 3).get('service') == 'niblit'
                    latencies.append(round((time.monotonic()-began)*1000, 1))
                    time.sleep(0.15)
                report['checks']['health_responsive_with_active_telemetry'] = True
                report['health_latency_ms'] = {'max':max(latencies), 'mean':round(sum(latencies)/len(latencies),1)}
                report['stage'] = 'runtime_help_reply'
                command_started = time.monotonic()
                request = Request('http://127.0.0.1:5000/chat', data=json.dumps({'text':'help'}).encode(), headers={'Content-Type':'application/json','Origin':'http://tauri.localhost'})
                with opener.open(request, timeout=90) as response:
                    answer = json.load(response)
                    assert response.headers.get('access-control-allow-origin') == 'http://tauri.localhost'
                assert isinstance(answer.get('reply'), str) and answer['reply'].strip() and '[error]' not in answer['reply']
                report['first_command_latency_ms'] = round((time.monotonic()-command_started)*1000, 1)
                report['checks']['runtime_command_reply_with_telemetry'] = True
                report['checks']['native_origin_cors'] = True
                report['stage'] = 'selected_model_conversation'
                request = Request('http://127.0.0.1:5000/chat', data=json.dumps({'text':'Say hello in one sentence.', 'model':'qwen2.5-0.5b', 'use_model':True}).encode(), headers={'Content-Type':'application/json'})
                with opener.open(request, timeout=120) as response:
                    conversation = json.load(response)
                assert conversation.get('source') == 'cloud' and conversation.get('reply', '').strip()
                assert 'no stored knowledge' not in conversation['reply'].lower()
                report['checks']['selected_model_conversation'] = True
                report['stage'] = 'live_tool_observation'
                tool_arguments = {'environment_type':'workspace', 'action':'explore', 'environment_details':
                    {'name':'isolated test workspace', 'url':'.', 'additional_context':'Read-only smoke test', 'object_id':''}}
                request = Request('http://127.0.0.1:5000/api/tools/runs', data=json.dumps(tool_arguments).encode(), headers={'Content-Type':'application/json'})
                with opener.open(request, timeout=10) as response:
                    tool_run = json.load(response)
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    tool_run = next(r for r in get('http://127.0.0.1:5000/api/tools/runs')['runs'] if r['id']==tool_run['id'])
                    if tool_run['status'] in ('completed','failed'): break
                    time.sleep(.1)
                assert tool_run['status'] == 'completed'
                assert any(e['kind']=='action.result' for e in tool_run['events'])
                report['checks']['live_tool_ledger'] = True
                assert get('http://127.0.0.1:8000/health', 5).get('inference_ready') is True
                trading = get('http://127.0.0.1:28130/health', 5)
                assert trading.get('healthy') is True and trading.get('state') == 'ready'
                assert trading.get('execution_enabled') is False
                report['checks']['cloud_and_lean_ready_execution_disabled'] = True
                report['checks']['health_responsive_with_active_telemetry'] = True
                report['health_latency_ms'] = {'max':max(latencies), 'mean':round(sum(latencies)/len(latencies),1)}
            report['ready']=True
            (output/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
            print('READY: native desktop and sustained SSE verified. Awaiting UI acceptance marker.',flush=True)
            deadline=time.monotonic()+600
            while time.monotonic()<deadline and process.poll() is None and not (output/'ui-finished').exists():
                time.sleep(1)
    except Exception as exc:
        report.update(ready=False,error=str(exc))
        (output/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print('Failure stage: '+str(report.get('stage'))+'; holding isolated process for diagnosis.',flush=True)
        deadline=time.monotonic()+180
        while time.monotonic()<deadline and process is not None and process.poll() is None and not (output/'ui-finished').exists():
            time.sleep(1)
    finally:
        if process is not None and process.poll() is None:
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True)
            process.wait(timeout=20)
        (output/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    return 0 if report['ready'] else 1

if __name__=='__main__':
    raise SystemExit(main())
