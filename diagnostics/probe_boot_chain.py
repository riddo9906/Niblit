import os, subprocess, time, json
from pathlib import Path
from urllib.request import build_opener,ProxyHandler
root=Path.cwd();out=root/'diagnostics'/'boot-chain-20261028';out.mkdir(exist_ok=True)
bundle=root/'dist/latest-20261026-inference-fix/niblit'
env={k:v for k,v in os.environ.items() if not k.startswith('NIBLIT_') and not any(w in k.upper() for w in ['TOKEN','API_KEY','PASSWORD','SECRET'])}
env.update(PYTHON_DOTENV_DISABLED='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',NIBLIT_HEADLESS='1',NIBLIT_TRADING_BACKEND='paper',NIBLIT_TRADING_MODE='observe',NIBLIT_TRADING_ALLOW_EXECUTION='false',NIBLIT_FREQTRADE_ALLOW_EXECUTION='false',NIBLIT_MARKET_DATA_PROVIDER='replay',NIBLIT_API_PORT='28500',NIBLIT_PORT='28080',NIBLIT_CLOUD_SERVER_PRIMARY_PORT='28080',NIBLIT_CLOUD_SERVER_URL='http://127.0.0.1:28080',NIBLIT_CLOUD_BASE_URL='http://127.0.0.1:28080',NIBLIT_TRADING_API_PORT='28130',NIBLIT_STRATEGY_API_PORT='28150',NIBLIT_MEMORY_PATH=str(out/'memory.json'),FUSED_MEMORY_DB_PATH=str(out/'fused.sqlite'),NIBLIT_LLM_CHAT_DB_PATH=str(out/'chat.sqlite'),NIBLIT_RUNTIME_LOG_FILE=str(out/'runtime.jsonl'),NIBLIT_SERVICE_LOG_DIR=str(out/'service-logs'),NIBLIT_UNIFIED_RUNTIME_STATE=str(out/'unified.json'),NIBLIT_WORKSPACE_ROOT=str(out),NIBLIT_EXECUTION_DB=str(out/'executions.sqlite'),NIBLIT_TRADING_CONTROL_FILE=str(out/'control.json'),NIBLIT_PAPER_STATE_FILE=str(out/'paper.json'),NIBLIT_REPLAY_STATE_FILE=str(out/'replay.json'),NIBLIT_REPLAY_DATA_DIR=str(bundle/'freqtrade/data'),QDRANT_URL='http://127.0.0.1:1',NIBLIT_INIT_WAIT_MAX_SECONDS='90',NIBLIT_N_CTX='2048',NIBLIT_GGUF_N_CTX='2048')
opener=build_opener(ProxyHandler({}))
log=(out/'core.log').open('w',encoding='utf-8');p=subprocess.Popen([str(bundle/'niblit.exe'),'--headless','--cli'],cwd=out,env=env,stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
(out/'pid.json').write_text(json.dumps({'pid':p.pid}));print('Probe PID',p.pid,flush=True)
seen={}
try:
 for i in range(100):
  for name,port in [('cloud',28080),('lean',28130),('core',28500)]:
   if name in seen:continue
   try:
    with opener.open(f'http://127.0.0.1:{port}/health',timeout=.3) as response:body=json.load(response)
    seen[name]={'http':200,'status':body.get('status'),'state':body.get('state'),'service':body.get('service'),'inference_ready':body.get('inference_ready')};print(name,seen[name],flush=True)
   except Exception:pass
  if len(seen)==3 or p.poll() is not None:break
  time.sleep(1)
 print(json.dumps({'services':seen,'exit':p.poll()}),flush=True)
 (out/'result.json').write_text(json.dumps({'services':seen,'exit':p.poll()},indent=2))
finally:
 if p.poll() is None:subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],capture_output=True);p.wait(timeout=15)
 log.close()
