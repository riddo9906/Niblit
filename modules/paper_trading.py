"""Operator paper trading through Core; execution authority stays in the runtime."""
from __future__ import annotations
import json
import os
import threading
import time
import uuid
from urllib.request import Request, urlopen
import httpx

class PaperTradingError(RuntimeError):
    def __init__(self, message, status=400):
        super().__init__(message); self.status=status

class PaperTradingController:
    def __init__(self):
        self.lock=threading.RLock()
        self._clients={}
        self._clients_lock=threading.Lock()
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
