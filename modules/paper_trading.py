"""Operator paper trading through Core; execution authority stays in the runtime."""
from __future__ import annotations
import json
import os
import threading
import time
import uuid
from urllib.request import Request, urlopen
import httpx

_ACTIVE_PAPER_RUNS = set()


def _replay_scope():
    from modules.memory_laboratory.context import runtime_gateway
    gateway = runtime_gateway()
    if gateway is None:
        raise PaperTradingError('Canonical operational memory unavailable', 503)
    scope = {'namespace':os.getenv('NIBLIT_MEMORY_LAB_NAMESPACE','desktop'),
             'principal':os.getenv('NIBLIT_MEMORY_LAB_PRINCIPAL','desktop_operator')}
    gateway.require('read', **scope)
    return gateway, scope


def _replay_manifest():
    """Only trusted deployment configuration selects code, data or state paths."""
    from pathlib import Path
    import hashlib
    name = os.getenv('NIBLIT_PAPER_REPLAY_MANIFEST')
    if not name:
        raise PaperTradingError('Isolated paper replay is not configured', 503)
    manifest = json.loads(Path(name).read_text(encoding='utf-8'))
    roots = [Path(manifest[k]).resolve(strict=True) for k in ('lean_root','core_root')]
    for field in ('worker','dataset'):
        path = Path(manifest[field]).resolve(strict=True)
        if not path.is_relative_to(roots[0]):
            raise PaperTradingError('Paper source outside trusted deployment',403)
    if manifest.get('dataset_id') != 'governed_paper_v1':
        raise PaperTradingError('Unknown approved replay dataset',403)
    required = [Path(manifest['worker']).resolve(), Path(manifest['dataset']).resolve()]
    pins = manifest.get('files', {})
    if not pins or any(str(p) not in pins for p in required):
        raise PaperTradingError('Incomplete paper deployment manifest',403)
    for filename, expected in pins.items():
        path = Path(filename).resolve(strict=True)
        if not any(path.is_relative_to(root) for root in roots):
            raise PaperTradingError('Untrusted replay source pin',403)
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise PaperTradingError('Paper source identity changed; revalidate deployment',403)
    return manifest


def _paper_run_id(run_id):
    import re
    if not isinstance(run_id,str) or not re.fullmatch(r'paper-[a-z0-9-]{8,48}',run_id):
        raise PaperTradingError('Invalid paper run identity')
    return run_id


def _isolated_episode(run_id, *, cancel=False):
    from pathlib import Path
    run_id = _paper_run_id(run_id)
    gateway, scope = _replay_scope()
    if cancel:
        from modules.core_tool_runtime import _permission_manager
        if not _permission_manager().check('command.run_paper_replay'):
            raise PermissionError('Paper replay authorization required')
    with gateway.db() as db:
        row = db.execute("SELECT metadata FROM audit WHERE action IN ('paper.job','paper.episode') AND record_id=? "
            "AND json_extract(metadata,'$.namespace')=? AND json_extract(metadata,'$.principal')=? ORDER BY seq DESC LIMIT 1",
            (run_id, scope['namespace'], scope['principal'])).fetchone()
    if not row:
        return {'run_id':run_id,'status':'UNKNOWN','error':'No authorized paper episode found'}
    value = json.loads(row['metadata'])
    if value.get('status') == 'running' and run_id not in _ACTIVE_PAPER_RUNS:
        value['status'] = 'interrupted'
    if cancel and value.get('status') == 'running':
        gateway.require('ingest', **scope)
        manifest = _replay_manifest()
        root = Path(manifest['run_root']).resolve(strict=True)
        run = (root / run_id).resolve(strict=True)
        if run.parent != root:
            raise PermissionError('Unsafe paper run path')
        # Acknowledgement is only a request. The worker must confirm its boundary.
        (run / 'cancel').write_text('Authorized scoped paper cancellation', encoding='utf-8')
        return {'run_id':run_id,'status':'cancellation_requested',
                'limitation':'Read the final episode to confirm worker acknowledgement; no forced closing.'}
    return value.get('summary', {'run_id':run_id,'status':value['status'],
        'limitation':'No terminal receipt. An interrupted run is never automatically resubmitted.'})


def _isolated_replay(run_id, dataset):
    """Reuse Lean's adapter/coordinator, persisting operational memory in Core.

    No HTTP, broker adapter factory or generic shell surface. Started IDs are
    reserved durably before launch; an ambiguous/interrupted ID cannot retry.
    """
    from pathlib import Path
    import hashlib
    import subprocess
    import sys
    from modules.core_tool_runtime import _permission_manager
    run_id = _paper_run_id(run_id)
    if dataset != 'governed_paper_v1':
        raise PaperTradingError('Only the approved synthetic replay is supported',403)
    if not _permission_manager().check('command.run_paper_replay'):
        raise PermissionError('Paper replay authorization required')
    gateway, scope = _replay_scope()
    gateway.require('ingest', **scope)
    manifest = _replay_manifest()
    root = Path(manifest['run_root']).resolve(strict=True)
    run = root / run_id
    if run.resolve().parent != root:
        raise PermissionError('Unsafe isolated state path')
    with gateway.db() as db:
        db.execute('BEGIN IMMEDIATE')
        prior = db.execute("SELECT 1 FROM audit WHERE action='paper.job' AND record_id=? LIMIT 1",(run_id,)).fetchone()
        if prior:
            return {**_isolated_episode(run_id), 'replayed_existing':True,
                    'no_new_execution':True}
        gateway.audit(db,'paper.job',run_id,**scope,status='running',dataset=dataset)
    try:
        run.mkdir(exist_ok=False)
        dataset_sha = hashlib.sha256(Path(manifest['dataset']).read_bytes()).hexdigest()
        config = {**manifest, 'run_root':str(run), 'run_id':run_id,'dataset_sha256':dataset_sha,'lease_required':True}
        request = run / 'request.json'
        request.write_text(json.dumps(config),encoding='utf-8')
        (run / 'heartbeat').write_text('Owned Core worker lease',encoding='utf-8')
        _ACTIVE_PAPER_RUNS.add(run_id)
        # Windows exposes case-insensitive environment names as uppercase.
        # Omitting SYSTEMROOT breaks Winsock/asyncio even in an offline worker.
        env = {k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','COMSPEC'}}
        env.update(PYTHONDONTWRITEBYTECODE='1', TEMP=str(run), TMP=str(run),
                   OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
        with (run / 'worker.log').open('w',encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable,'-I','-B',manifest['worker'],str(request)],
                cwd=manifest['lean_root'],env=env,stdout=log,stderr=log,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            started = time.monotonic()
            while process.poll() is None:
                (run / 'heartbeat').touch()
                if not _permission_manager().check('command.run_paper_replay'):
                    (run / 'cancel').write_text('Paper permission revoked',encoding='utf-8')
                if time.monotonic()-started > 70:
                    (run / 'cancel').write_text('Paper deadline',encoding='utf-8')
                    try:process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill();process.wait()  # Only this owned network-denied worker.
                    raise TimeoutError('Paper worker interrupted; inspect persisted state, do not retry this ID')
                time.sleep(.1)
        if process.returncode:
            raise RuntimeError('Paper worker failed; inspect isolated worker log')
        raw = (run / 'receipt.json').read_bytes()
        if len(raw)>2_000_000:
            raise ValueError('Paper receipt exceeds bound')
        receipt = json.loads(raw)
        if process.returncode or receipt['status'] not in {'completed','cancelled','interrupted'}:
            raise RuntimeError('Paper worker failed; persisted partial state requires inspection')
        summary = {'run_id':run_id,'status':receipt['status'],'mode':'paper_replay',
            'dataset_sha256':dataset_sha,'source':'deterministic_synthetic_fixture',
            'broker_calls':receipt['broker_calls'],'duration_seconds':receipt['duration_seconds'],
            'receipt_sha256':hashlib.sha256(raw).hexdigest(),
            'cancellation_acknowledged_at':receipt.get('cancellation_acknowledged_at'),
            'cancel_requested_at':receipt.get('cancel_requested_at'),
            'stop_reason':receipt.get('cancel_reason'),
            'evidence':f'paper://{run_id}', 'scenarios':[],
            'limitations':['Synthetic coverage is not evidence of profitability.',
                'No external demo/broker execution. No model generated this accounting.',
                'Canonical operational audit persisted; no semantic/Qdrant projection claimed.']}
        for episode in receipt['scenarios']:
            summary['scenarios'].append({'name':episode['name'],'status':episode['status'],
                'observations':len(episode['timeline']), 'signals':[
                    {'strategy':c['strategy'],'side':c['side']} for c in episode['timeline'][0]['signals']
                ] if episode['timeline'] else [],
                'decisions':[{'action':o['decision']['action'],'strategy':o['decision']['strategy'],
                    'status':o['result']['status'],'error':o['result'].get('error'),
                    'decision_id':o['decision']['decision_id'],
                    'duplicate_status':o.get('duplicate_probe',{}).get('status')} for o in episode['orders']],
                'exit_reasons':[e['exit_check']['reason'] for e in episode['timeline']
                    if e.get('exit_check',{}).get('action')=='close'],
                'actuals':episode['actuals'],'fees':episode['account']['fees'],
                'realized_net':episode['account']['realized_pnl'],
                'open_positions':len([p for p in episode['account']['positions'] if p['status']=='open']),
                'account_reload_equal':episode['account_reload_equal']})
        gateway.require('ingest', **scope)
        with gateway.db() as db:
            gateway.audit(db,'paper.episode',run_id,**scope,status=receipt['status'],
                summary=summary, receipt=receipt, source_type='paper_simulation_outcome')
        return summary
    except Exception as exc:
        with gateway.db() as db:
            gateway.audit(db,'paper.job',run_id,**scope,status='interrupted',error_type=type(exc).__name__)
        return {'run_id':run_id,'status':'interrupted','reason':'Isolated paper run failed; do not resubmit this ID',
                'error_type':type(exc).__name__,'evidence':f'paper://{run_id}'}
    finally:
        _ACTIVE_PAPER_RUNS.discard(run_id)

class PaperTradingError(RuntimeError):
    def __init__(self, message, status=400):
        super().__init__(message); self.status=status

class PaperTradingController:
    def __init__(self):
        self.lock=threading.RLock()
        self._clients={}
        self._clients_lock=threading.Lock()
    def evaluate_replay(self, run_id, dataset='governed_paper_v1'):
        """Bounded offline integration client; never calls the service bridge."""
        return _isolated_replay(run_id, dataset)

    def replay_episode(self, run_id, cancel=False):
        return _isolated_episode(run_id, cancel=cancel)

    def _call(self, service, path, payload=None, timeout=10):
        port=int(os.getenv('NIBLIT_STRATEGY_API_PORT','8150') if service=='strategy' else os.getenv('NIBLIT_TRADING_API_PORT','8100'))
        base=f'http://127.0.0.1:{port}'
        with self._clients_lock:
            if base not in self._clients:
                self._clients[base]=httpx.Client(base_url=base,trust_env=False)
            client=self._clients[base]
        # Reuse connections during long replays. Only reads and the durable
        # pending/ack handshake may retry after an ambiguous transport failure.
        attempts=3 if payload is None or path in ('/v1/replay/step','/v1/replay/ack') else 1
        for attempt in range(attempts):
            try:
                response=client.request('GET' if payload is None else 'POST',path,
                    timeout=timeout,**({'json':payload} if payload is not None else {}))
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                try:
                    body=exc.response.json(); message=body.get('detail',body.get('error',str(exc)))
                except Exception: message=str(exc)
                raise PaperTradingError(str(message),exc.response.status_code) from exc
            except httpx.TransportError as exc:
                if attempt+1 == attempts:
                    raise PaperTradingError(f'{service} service unavailable: {exc}',503) from exc
                time.sleep(.1*(attempt+1))
    def _paper(self, armed=False):
        health=self._call('runtime','/health')
        if health.get('backend')!='paper': raise PaperTradingError('This operator path is restricted to the paper backend',403)
        if not health.get('healthy'): raise PaperTradingError('Trading runtime is not healthy',503)
        if armed and health.get('mode')!='paper': raise PaperTradingError('Enable paper trading before submitting an intent',409)
        return health
    def status(self):
        health=self._paper()
        return {'health':health, **self._call('runtime','/v1/paper/account'),
                'executions':self._call('runtime','/v1/executions?limit=50'),
                'strategy':self._call('strategy','/v1/replay/current'),
                'available':self._call('strategy','/v1/strategies'),
                'profit_target':{'monthly_net':100,'status':'not_forward_validated','guaranteed':False}}
    def control(self, enabled):
        with self.lock:
            self._paper()
            return self._call('runtime','/v1/paper/control',{'enabled':bool(enabled)})
    def load(self, dataset, strategy, cursor):
        with self.lock:
            self._paper()
            account=self._call('runtime','/v1/paper/account')['account']
            if any(p['status']=='open' for p in account['positions']):
                raise PaperTradingError('Close existing paper positions before changing the replay dataset',409)
            return self._call('strategy','/v1/replay/load',{'dataset':dataset,'strategy':strategy,'cursor':cursor})
    def decision(self, action, stake_amount, decision_id=None, observation=None, rationale='Operator paper intent'):
        with self.lock:
            self._paper(armed=True)
            if action not in ('enter_long','exit_long'): raise PaperTradingError('This paper profile supports long entry and full-position exit')
            from_strategy=observation is not None
            observed=observation or self._call('strategy','/v1/replay/current')
            if observed.get('source')!='historical_replay': raise PaperTradingError('Recorded data provenance is missing')
            payload={'decision_id':decision_id or 'operator-'+uuid.uuid4().hex,'symbol':observed['symbol'],
                'action':action,'stake_amount':stake_amount,'stake_currency':'USDT','order_type':'market',
                'leverage':1,'confidence':.9,'rationale':rationale,'strategy':observed['strategy'] if from_strategy else 'operator',
                'metadata':{'source':'core_strategy_paper' if from_strategy else 'core_operator_paper','market_timestamp':observed['as_of'],
                            'ai_advice':observed.get('_ai_advice'),
                            'data_sha256':observed['data_sha256'],'replay_cursor':observed['cursor']}}
            return self._call('runtime','/v1/decisions/execute',payload)
    def step(self, stake_amount=100, use_ai=False):
        with self.lock:
            self._paper(armed=True)
            observation=self._call('strategy','/v1/replay/step',{})
            identifier='replay:'+observation['observation_id']
            try:
                existing=self._call('runtime','/v1/executions/'+identifier)
            except PaperTradingError as exc:
                if exc.status!=404: raise
                existing=None
            account=self._call('runtime','/v1/paper/account')['account']
            position=next((p for p in account['positions'] if p['status']=='open' and p['symbol']==observation['symbol']),None)
            action='exit_long' if position and observation['exit_long'] else 'enter_long' if not position and observation['enter_long'] else 'hold'
            if existing:
                outcome={'action':existing['action'],'status':existing['status'],'decision_id':identifier,'recovered':True}
            elif action=='hold': outcome={'action':'hold','status':'no_signal','decision_id':identifier}
            else:
                advice=self.advice(observation,action) if use_ai else None
                if advice is not None and not advice['approved']:
                    outcome={'action':action,'status':'advisor_veto','decision_id':identifier,'advice':advice}
                else:
                    if advice is not None: observation={**observation,'_ai_advice':advice}
                    outcome=self.decision(action,position['stake_amount'] if position else stake_amount,
                        identifier,observation,rationale='Freqtrade strategy signal'+(' with local AI approval' if use_ai else ''))
                    outcome['action']=action
                    if advice is not None: outcome['advice']=advice
            self._call('strategy','/v1/replay/ack',{'observation_id':observation['observation_id'],'outcome':outcome})
            return {'observation':{k:v for k,v in observation.items() if k!='candles'},'outcome':outcome,
                    'portfolio':self._call('runtime','/v1/paper/account')}
    def advice(self, observation, action):
        port=int(os.getenv('NIBLIT_CLOUD_SERVER_PRIMARY_PORT','8000'))
        payload={'model':os.getenv('NIBLIT_PAPER_ADVISOR_MODEL','qwen2.5-0.5b'),'stream':False,'temperature':0,'max_tokens':96,
            'messages':[{'role':'system','content':'Evaluate only this offline simulated trade using the recorded past observations. Reply with exactly one JSON object containing only the boolean approved, for example {"approved":false}. Do not include a reason, explanation, markdown, or any other field.'},
                        {'role':'user','content':json.dumps({'action':action,'symbol':observation['symbol'],'as_of':observation['as_of'],'past_candles':observation['candles'][-5:]})}]}
        request=Request(f'http://127.0.0.1:{port}/v1/chat/completions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
        try:
            with urlopen(request,timeout=45) as response: result=json.load(response)
            text=result['choices'][0]['message']['content']; start=text.find('{'); end=text.rfind('}')
            vote=json.loads(text[start:end+1])
            if type(vote.get('approved')) is not bool: raise ValueError('Invalid advisor vote')
            return {'approved':vote['approved'],'reason':str(vote.get('reason',''))[:300],
                    'model':result.get('model'),'source':'local_cloud_model'}
        except Exception as exc: raise PaperTradingError('Local AI advice could not be verified; replay step remains pending',503) from exc

    def advise(self, action):
        self._paper()
        if action not in ('enter_long','exit_long','hold'): raise PaperTradingError('Unknown advisory action')
        return self.advice(self._call('strategy','/v1/replay/current'),action)

_controller=PaperTradingController()
def get_paper_trading_controller(): return _controller
