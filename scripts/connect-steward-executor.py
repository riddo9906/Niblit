"""Connect an existing browser-created session using its restricted key."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from dotenv import load_dotenv
load_dotenv(root / '.env')
from modules.steward_executor import executor_configuration
from modules.steward_agent import StewardBridge

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--session-id', required=True)
parser.add_argument('--check', action='store_true')
args = parser.parse_args()
try:
    config = executor_configuration(args.session_id)
except (ValueError, RuntimeError) as exc:
    print(str(exc))
    raise SystemExit(1)
print(json.dumps({'prepared':True, 'workspace':config['cwd'], 'restricted_key_configured':True, 'inference_started':False}), flush=True)
if args.check:
    raise SystemExit(0)
log_dir = root / 'diagnostics/steward-executor'
log_dir.mkdir(parents=True, exist_ok=True)
process = subprocess.Popen(config['command'], cwd=config['cwd'], env=config['env'],
    stdin=subprocess.PIPE, stdout=(log_dir/'stdout.log').open('ab'), stderr=(log_dir/'stderr.log').open('ab'),
    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
(log_dir/'process.json').write_text(json.dumps({'pid':process.pid,'session_id':args.session_id,'workspace':config['cwd']},indent=2))
print('Executor started. Waiting for the existing session to report its environment connection.',flush=True)
try:
    bridge = StewardBridge()
    for _ in range(12):
        if process.poll() is not None:
            print('Executor stopped before connection was verified. See local diagnostics; no inference was submitted.',flush=True)
            raise SystemExit(1)
        session = bridge.request('GET', '/sessions/' + args.session_id)
        if not any(action.get('type') == 'environment_connection' for action in session.get('required_actions', [])):
            print(json.dumps({'environment_connected':True,'session_status':session.get('status'),'inference_submitted':False}),flush=True)
            (log_dir/'connection.json').write_text(json.dumps({'environment_connected':True,'session_id':args.session_id},indent=2))
            break
        time.sleep(2)
    else:
        print('Connection is not verified yet. Check the session and local diagnostics.',flush=True)
    while process.poll() is None:
        time.sleep(2)
finally:
    if process.poll() is None:
        process.terminate()
        process.wait(timeout=10)
