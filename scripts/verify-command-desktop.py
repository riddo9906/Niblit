"""Verify original commands against a real packaged Core and isolated data."""
import argparse,json,os,subprocess,time,uuid
from pathlib import Path
from urllib.request import Request,urlopen
import psutil

def request(path,payload=None):
    req=Request('http://127.0.0.1:28500'+path,data=json.dumps(payload).encode() if payload is not None else None,
                headers={'Content-Type':'application/json'})
    with urlopen(req,timeout=60) as response:return json.load(response)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--bundle',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--hold-for-ui',action='store_true')
    args=parser.parse_args();bundle=args.bundle.resolve();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    env={k:v for k,v in os.environ.items() if not any(word in k.upper() for word in ('TOKEN','API_KEY','SECRET','PASSWORD','CREDENTIAL'))}
    env.update(PYTHON_DOTENV_DISABLED='1',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',NIBLIT_HEADLESS='1',NIBLIT_API_AUTOSTART='1',NIBLIT_API_PORT='28500',NIBLIT_TRADING_API_PORT='28100',NIBLIT_MARKET_DATA_PROVIDER='mock',NIBLIT_TRADING_BACKEND='paper',NIBLIT_TRADING_MODE='observe',NIBLIT_TRADING_ALLOW_EXECUTION='false',QDRANT_URL='http://127.0.0.1:1')
    for key,name in {'NIBLIT_MEMORY_PATH':'memory.json','FUSED_MEMORY_DB_PATH':'fused.sqlite','NIBLIT_LLM_CHAT_DB_PATH':'chat.sqlite','NIBLIT_UNIFIED_RUNTIME_STATE':'unified.json','NIBLIT_RUNTIME_LOG_FILE':'runtime.jsonl','NIBLIT_PAPER_STATE_FILE':'paper.json','NIBLIT_EXECUTION_DB':'executions.sqlite'}.items():env[key]=str(out/name)
    processes=[];logs=[];report={'checks':{},'bundle':str(bundle)}
    def launch(name,command,interactive=False):
        stream=(out/(name+'.log')).open('w',encoding='utf-8');logs.append(stream)
        proc=subprocess.Popen([str(x) for x in command],cwd=out,env=env,stdin=subprocess.PIPE if interactive else subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        processes.append(proc);return proc
    try:
        launch('runtime',[bundle/'lean-algos/niblit-lean-algos.exe'])
        launch('core',[bundle/'niblit.exe','--headless','--cli'],True)
        deadline=time.monotonic()+180
        while time.monotonic()<deadline:
            try:
                if request('/health').get('service')=='niblit':break
            except Exception:pass
            time.sleep(1)
        catalog=request('/api/commands/operator');items={item['name']:item for item in catalog['commands']}
        report['operator_count']=len(items)
        (out/'operator-registry.json').write_text(json.dumps(catalog,indent=2))
        for name in ('threads','unified status','remember','knowledge-stats','help'):
            report['checks']['discovered_'+name]=name in items
        for name in ('threads','unified status'):
            result=request('/api/commands/operator/execute',{'command':name,'arguments':{},'confirmed':True})
            report['checks']['execute_'+name]=result.get('status')=='success'
            (out/(name.replace(' ','-')+'.json')).write_text(json.dumps(result,indent=2))
        value='PersistedValue-'+uuid.uuid4().hex
        marker='OriginalCommandCase: '+value
        result=request('/api/commands/operator/execute',{'command':'remember','arguments':{'text':marker},'confirmed':True})
        report['checks']['remember_executed']=result.get('status')=='success'
        report['checks']['remember_written_to_disk']=value in (out/'memory.json').read_text(encoding='utf-8')
        recalled=request('/api/commands/execute',{'command':'recall','arguments':{'query':value}})
        report['checks']['remember_recalled_by_governed_memory']=any(value in json.dumps(entry) for entry in recalled.get('result',{}).get('entries',[]))
        alias=request('/api/commands/execute',{'command':'knowledge-stats','arguments':{}})
        report['checks']['original_spelling_alias']=alias.get('status')=='success' and alias.get('alias_of')=='knowledge_stats'
        unknown=request('/api/commands/operator/execute',{'command':'__not_a_command__','confirmed':True})
        report['checks']['unknown_rejected_without_chat']=unknown.get('status')=='rejected'
        blocked=request('/api/commands/operator/execute',{'command':'tools','arguments':{'text':'run __operator_permission_probe__ {}'},'confirmed':True})
        report['checks']['risky_subcommand_permission_preserved']=blocked.get('status')=='authorization_required'
        if args.hold_for_ui:
            (out/'verification.json').write_text(json.dumps(report,indent=2))
            print('Command UI ready on port 28500',flush=True)
            deadline=time.monotonic()+600
            while time.monotonic()<deadline and not (out/'release-ui').exists():time.sleep(1)
    except Exception as exc:report['error']=str(exc)
    finally:
        for proc in reversed(processes):
            if proc.poll() is None:
                for child in reversed(psutil.Process(proc.pid).children(recursive=True)):
                    try:child.terminate()
                    except psutil.NoSuchProcess:pass
                proc.terminate()
                try:proc.wait(timeout=10)
                except subprocess.TimeoutExpired:proc.kill()
        for stream in logs:stream.close()
        (out/'verification.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
    return 0 if not report.get('error') and all(report['checks'].values()) else 1

if __name__=='__main__':raise SystemExit(main())
