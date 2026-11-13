"""Loopback human trading desk. No order functions are exposed to model tools.

Freqtrade remains the execution authority. Tickets are durable before delivery;
an ambiguous response is never retried automatically.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel, Field
from typing import Literal

ROOT = Path(__file__).resolve().parents[1]


class FreqtradeRejection(RuntimeError):
    pass


class Intent(BaseModel):
    action: Literal['enter_long', 'enter_short', 'exit']
    pair: str = Field(min_length=3, max_length=80)
    stake: float = Field(default=20, gt=0, le=100000)
    trade_id: int | None = Field(default=None, gt=0)


class Confirm(BaseModel):
    ticket: str
    acknowledgement: Literal['CONFIRM_SIMULATED_ORDER']


class BoundConfirm(Confirm):
    """Existing human ticket, additionally bound to an immutable Cloud request."""
    model_config = {"extra": "forbid"}
    mode: Literal["dry-run"]
    intent: Intent
    identity: dict


class MT5Check(BaseModel):
    symbol: str = Field(min_length=1,max_length=80)
    side: Literal['buy','sell']
    volume: float = Field(default=.01,gt=0,le=.01)
    account_identity: str = Field(min_length=16,max_length=16)


class MT5Intent(MT5Check):
    action: Literal['open','close'] = 'open'
    position_ticket: int | None = Field(default=None,gt=0)


class MT5Confirm(BaseModel):
    ticket: str = Field(min_length=32,max_length=32)
    acknowledgement: Literal['CONFIRM_MT5_DEMO_ORDER']


class DemoSession(BaseModel):
    symbol: str = Field(min_length=1, max_length=80)
    strategy: Literal['auto', 'trend_v1', 'breakout_v1', 'rsi_reversion_v1', 'bollinger_reversion_v1', 'ema_pullback_v1', 'squeeze_breakout_v1']
    minutes: int = Field(default=30, ge=1, le=60)
    max_entries: int = Field(default=3, ge=1, le=10)
    acknowledgement: Literal['START_BOUNDED_MT5_DEMO']
    opportunity_id: str | None = Field(default=None, max_length=250)


class Desk:
    def __init__(self, root=ROOT, transport=None):
        self.root = Path(root)
        self.transport = transport
        self.lock = threading.Lock()
        self.market_rules = None
        self.path = self.root/'runtime/trading-desk/orders.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS tickets(id TEXT PRIMARY KEY, created REAL, state TEXT, payload TEXT, result TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS outcomes(id TEXT PRIMARY KEY, payload TEXT, recorded REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS memory_exports(id TEXT PRIMARY KEY, queued REAL)')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def connection(self):
        # The Docker profile is explicit; no silent fallback to another account.
        path = self.root.parent/'freqtrade/user_data/config.json'
        config = json.loads(path.read_text(encoding='utf-8'))
        api = config['api_server']
        return config, (api['username'], api['password'])

    def api(self, path, payload=None):
        if self.transport:
            return self.transport(path, payload)
        _, auth = self.connection()
        # Fixed loopback target; configuration cannot redirect credentials.
        with httpx.Client(base_url='http://127.0.0.1:8080/api/v1/', auth=auth,
                          trust_env=False, timeout=12) as client:
            response = client.get(path) if payload is None else client.post(path, json=payload)
            if response.is_error and path=='forceenter':
                # Freqtrade's RPC exception explicitly reports execute_entry=False.
                # Other errors/timeouts remain uncertain and are never retried.
                try: message=str(response.json().get('error',''))
                except ValueError: message=''
                if 'Failed to enter position for ' in message or 'already open' in message or 'Maximum number of trades' in message:
                    raise FreqtradeRejection('Freqtrade rejected the entry; no new position was accepted')
            response.raise_for_status()
            return response.json()

    def configuration(self):
        data = self.api('show_config')
        return {key:data.get(key) for key in ('dry_run','state','exchange','trading_mode',
            'strategy','timeframe','stake_currency','max_open_trades','force_entry_enable','version')}

    def quote(self, pair, config=None):
        """Read public bid/ask for this exact configured market, without orders."""
        config = config or self.configuration()
        kind = config.get('trading_mode')
        result = {'symbol':pair, 'venue':config.get('exchange'), 'fresh':False,
                  'source':'ccxt_public_order_book'}
        if kind not in ('spot','futures') or (kind=='spot' and ':' in pair):
            return {**result,'reason':'unsupported_or_ambiguous_market_type'}
        provider = 'binanceusdm' if config.get('exchange')=='binance' and kind=='futures' else config.get('exchange')
        if not isinstance(provider,str) or not provider.isidentifier():
            return {**result,'reason':'provider_unavailable'}
        from modules.market_data_providers import MarketDataProviders
        return {**MarketDataProviders().ccxt_quote(pair,exchange=provider),'venue':config['exchange']}

    def market(self, pair, config=None):
        config = config or self.configuration()
        from urllib.parse import urlencode
        engine_error = None
        try:
            raw = self.api('pair_candles?'+urlencode({'pair':pair,'timeframe':config['timeframe'],'limit':200}))
        except Exception as exc:
            raw = {}
            engine_error = type(exc).__name__
        columns = raw.get('columns', [])
        rows = [dict(zip(columns,row)) for row in raw.get('data',[])]
        interval = raw.get('timeframe_ms', 300000)/1000
        stamp = time.time()
        closed = []
        for row in rows:
            ts = row.get('__date_ts')
            if ts is None:
                from datetime import datetime
                try: ts = datetime.fromisoformat(str(row['date']).replace('Z','+00:00')).timestamp()*1000
                except (ValueError, KeyError): continue
            ts = float(ts)/1000
            if ts+interval <= stamp:
                closed.append({key:row.get(key) for key in ('open','high','low','close','volume',
                    'enter_long','exit_long','enter_short','exit_short')} | {'timestamp':ts})
        last = closed[-1] if closed else None
        age = stamp-(last['timestamp']+interval) if last else None
        fresh = age is not None and -5 <= age <= max(interval*2,120)
        if not fresh:
            public = self.public_market(pair, config)
            public['engine_data_state'] = engine_error or ('empty' if not closed else 'stale')
            if public['fresh'] or not closed:
                return public
        return {'pair':pair,'candles':closed,'last':last,'age_seconds':age,'fresh':fresh,
                'source':'freqtrade_analyzed_exchange_candles','timeframe':config['timeframe'],
                'signal':('STALE' if not fresh else 'EXIT_LONG' if last.get('exit_long')==1
                          else 'ENTER_LONG' if last.get('enter_long')==1 else 'WAIT'),
                'signal_basis':'Configured strategy on the latest completed candle; not a profitability claim'}

    def public_market(self, pair, config):
        """Reuse existing public data provider when the stopped engine has no bars.

        This fetches no account credentials or strategy-entry flags and never
        starts the engine. Instrument/market type remain explicitly configured.
        """
        base = {'pair':pair, 'candles':[], 'last':None, 'fresh':False,
                'age_seconds':None, 'source':'ccxt_public_exchange_ohlcv',
                'timeframe':config.get('timeframe'), 'signal':'STALE',
                'native_signals_available':False,
                'signal_basis':'Public OHLCV only; native engine signals unavailable.'}
        try:
            import re
            frame = re.fullmatch(r'([1-9][0-9]*)([smhdw])', str(config.get('timeframe','')))
            if frame is None:
                raise ValueError('unsupported_timeframe')
            interval = int(frame[1])*{'s':1,'m':60,'h':3600,'d':86400,'w':604800}[frame[2]]
            exchange = config.get('exchange')
            kind = config.get('trading_mode') or ('futures' if ':' in pair else 'spot')
            if kind not in ('spot','futures'):
                raise ValueError('unsupported_market_type')
            if kind=='spot' and ':' in pair:
                raise ValueError('instrument_market_type_mismatch')
            provider = 'binanceusdm' if exchange=='binance' and kind=='futures' else exchange
            if not isinstance(provider,str) or not provider.isidentifier():
                raise ValueError('invalid_exchange_identity')
            base.update(provider=provider, market_type=kind)
            key = (provider, pair, config['timeframe'])
            cache = self.__dict__.setdefault('_public_market_cache', {})
            lock = self.__dict__.setdefault('_public_market_lock', threading.Lock())
            with lock:
                cached = cache.get(key)
                if cached is not None and time.monotonic()-cached[0]<15:
                    bars = cached[1]
                else:
                    from modules.market_data_providers import MarketDataProviders
                    bars = MarketDataProviders().ccxt_bars(pair,interval=config['timeframe'],
                                                           bars=201,exchange=provider)
                    if not isinstance(bars,list):
                        raise ValueError('public_provider_unavailable')
                    if len(cache)>=32:
                        cache.pop(next(iter(cache)))
                    cache[key] = (time.monotonic(), bars)
            if not 1<=len(bars)<=500:
                raise ValueError('missing_or_unbounded_candles')
            stamp = time.time()
            rows = []
            for bar in bars:
                if not isinstance(bar,(list,tuple)) or len(bar)<6:
                    raise ValueError('invalid_ohlcv')
                if any(isinstance(v,bool) for v in bar[:6]):
                    raise ValueError('invalid_ohlcv')
                ts,o,h,l,c,v = [float(x) for x in bar[:6]]
                ts /= 1000
                if not all(math.isfinite(x) for x in (ts,o,h,l,c,v)) or min(ts,o,h,l,c)<=0 or v<0:
                    raise ValueError('invalid_ohlcv')
                if l>min(o,c) or h<max(o,c):
                    raise ValueError('inconsistent_ohlc')
                if ts+interval<=stamp:
                    rows.append(dict(timestamp=ts,open=o,high=h,low=l,close=c,volume=v))
            if any(b['timestamp']-a['timestamp']!=interval for a,b in zip(rows,rows[1:])):
                raise ValueError('duplicate_or_gapped_candles')
            if not rows:
                raise ValueError('no_completed_candles')
            age = stamp-(rows[-1]['timestamp']+interval)
            fresh = 0<=age<=max(interval*2,120)
            return {**base,'candles':rows,'last':rows[-1],'age_seconds':age,'fresh':fresh,
                    'signal':'WAIT' if fresh else 'STALE',
                    'quality':{'ohlcv_valid':True,'closed_only':True,'contiguous':True,
                               'interval_seconds':interval}}
        except (TypeError,ValueError,KeyError,OverflowError) as exc:
            return {**base,'data_error':str(exc) if isinstance(exc,ValueError) else type(exc).__name__}

    def snapshot(self, pair=None):
        config = self.configuration()
        def read(path):
            try: return {'available':True,'data':self.api(path)}
            except Exception as exc: return {'available':False,'error':type(exc).__name__}
        paths = ['whitelist','status','balance','profit','trades?limit=100']
        with ThreadPoolExecutor(max_workers=5) as pool:
            parts = dict(zip(paths,pool.map(read,paths)))
        pairs = parts['whitelist'].get('data',{}).get('whitelist',[])
        market = None
        if pair in pairs or (not pair and pairs):
            try: market = self.market(pair or pairs[0],config)
            except Exception as exc: market = {'fresh':False,'error':type(exc).__name__}
        trades = parts['trades?limit=100'].get('data',{}).get('trades',[])
        # Realized exchange-reported simulation outcomes, kept distinct from facts.
        with self.db() as db:
            for trade in trades:
                if trade.get('is_open') is False:
                    selected = {key:trade.get(key) for key in ('trade_id','pair','open_date','close_date',
                        'profit_abs','profit_ratio','fees','strategy','exit_reason')}
                    selected.update(mode='dry-run' if config['dry_run'] is True else 'live',
                                    exchange=config['exchange'])
                    identity = json.dumps([config['exchange'],config['dry_run'],trade.get('trade_id'),trade.get('open_date')])
                    db.execute('INSERT OR IGNORE INTO outcomes VALUES(?,?,?)',
                        (hashlib.sha256(identity.encode()).hexdigest(),json.dumps(selected),time.time()))
            tickets = [dict(r) for r in db.execute('SELECT id,created,state,result FROM tickets ORDER BY created DESC LIMIT 20')]
            count = db.execute('SELECT count(*) FROM outcomes').fetchone()[0]
        memory = self.export_outcomes() if self.transport is None else {'state':'test'}
        return dict(connected=True,checked_at=time.time(),configuration=config,pairs=pairs,
                    positions=parts['status'],balance=parts['balance'],profit=parts['profit'],
                    trades=parts['trades?limit=100'],market=market,tickets=tickets,
                    recorded_outcomes=count,memory=memory,manual_execution='dry-run only',funded_execution_enabled=False)

    def export_outcomes(self):
        """Queue closed execution evidence for Core's existing memory worker.

        Never loads a second embedding model or treats simulation as live profit.
        """
        gateway = None
        try:
            from dotenv import dotenv_values
            from modules.memory_laboratory.gateway import MemoryGateway
            from modules.memory_laboratory.runtime import MemoryRuntime
            from modules.memory_laboratory.setup import Config
            values = dotenv_values(self.root/'.env')
            if values.get('NIBLIT_MEMORY_LAB_ENABLED') != '1': return {'state':'disabled'}
            permission_path = Path(values['NIBLIT_PERMISSION_FILE'])
            def authorize(action, namespace, principal):
                grants = json.loads(permission_path.read_text(encoding='utf-8'))
                return principal=='desktop_operator' and bool(grants.get(f'memory.{action}.{namespace}',False))
            gateway = MemoryGateway(Config.from_values(dotenv_values(values['NIBLIT_MEMORY_LAB_ENV_FILE'])),
                values['NIBLIT_MEMORY_LAB_LEDGER'],authorize=authorize)
            runtime = MemoryRuntime(gateway)
            with self.db() as db:
                rows = db.execute('SELECT * FROM outcomes WHERE id NOT IN (SELECT id FROM memory_exports) LIMIT 20').fetchall()
                for row in rows:
                    runtime.enqueue(source='trading-outcome://'+row['id'],
                        content='Broker/engine execution evidence, not verified strategy performance. '+row['payload'],
                        category='episodic',metadata={'confidence':.5,'source_type':'execution_outcome',
                            'provenance':{'mode':json.loads(row['payload'])['mode'],'ledger_id':row['id']}})
                    db.execute('INSERT OR IGNORE INTO memory_exports VALUES(?,?)',(row['id'],time.time()))
                total = db.execute('SELECT count(*) FROM memory_exports').fetchone()[0]
            return {'state':'queued_to_core','outcomes_queued':total}
        except Exception as exc:
            return {'state':'pending','error':type(exc).__name__}
        finally:
            if gateway: gateway.close()

    def validate(self, intent, config):
        if config.get('dry_run') is not True:
            raise ValueError('Funded orders are not enabled. This desk currently accepts dry-run orders only.')
        if intent.action in ('enter_long','enter_short'):
            if intent.action=='enter_short' and config.get('trading_mode')!='futures':raise ValueError('Short entries require verified futures mode')
            if config.get('state') != 'running': raise ValueError('Engine must be running')
            if config.get('force_entry_enable') is not True: raise ValueError('Freqtrade manual entry is disabled in its configuration')
            if intent.pair not in self.api('whitelist').get('whitelist',[]): raise ValueError('Pair is not in the engine whitelist')
            market=self.market(intent.pair,config)
            if not market['fresh']: raise ValueError('Market data is stale or unavailable')
            minimum=self.minimum_stake(intent.pair,config,market['last']['close'])
            if intent.stake<minimum:
                raise ValueError(f'Exchange minimum with reserve is approximately {minimum:.2f} {config.get("stake_currency") or "stake units"}; increase stake or choose another pair')
            if not math.isfinite(intent.stake) or intent.stake > 100: raise ValueError('Manual dry-run stake limit is 100 account currency units')
            positions = self.api('status')
            if any(p.get('pair')==intent.pair for p in positions): raise ValueError('Position already exists for this pair')
            if len(positions) >= (config.get('max_open_trades') or 0): raise ValueError('Maximum open positions reached')
        else:
            positions = self.api('status')
            if not any(p.get('trade_id')==intent.trade_id and p.get('pair')==intent.pair for p in positions):
                raise ValueError('Open trade identity does not match; refresh positions')

    def minimum_stake(self,pair,config,price):
        if config.get('exchange')!='binance': raise ValueError('Exchange minimum validation is not implemented for this adapter')
        if self.market_rules is None or time.monotonic()-self.market_rules[0]>1800:
            futures=config.get('trading_mode')=='futures'
            url='https://fapi.binance.com/fapi/v1/exchangeInfo' if futures else 'https://api.binance.com/api/v3/exchangeInfo'
            with httpx.Client(trust_env=False,timeout=8) as client:
                response=client.get(url);response.raise_for_status()
            self.market_rules=(time.monotonic(),{s['symbol']:s for s in response.json()['symbols']})
        symbol=pair.split(':')[0].replace('/','')
        rule=self.market_rules[1].get(symbol)
        if not rule: raise ValueError('Exchange symbol minimum unavailable')
        filters={f['filterType']:f for f in rule['filters']}
        quantity=float(filters.get('LOT_SIZE',{}).get('minQty',0))
        cost=filters.get('NOTIONAL',filters.get('MIN_NOTIONAL',{}))
        notional=float(cost.get('minNotional',cost.get('notional',0)))
        # Freqtrade reserves 5% by default, plus a bounded stop-loss reserve.
        # Use the maximum 50% cost reserve to avoid a silent stake increase.
        return max(quantity*price*1.05,notional*1.5)

    def preview(self, intent, core_owned=False):
        config = self.configuration()
        with self.db() as db:
            if db.execute("SELECT 1 FROM tickets WHERE state IN ('sending','unknown') LIMIT 1").fetchone():
                raise ValueError('An earlier delivery is unresolved. Reconcile the engine and ticket ledger before another order.')
        self.validate(intent,config)
        key = secrets.token_urlsafe(24)
        payload = {'intent':intent.model_dump(),'identity':config,**({'core_owned':True,'entry_tag':'niblit_core:'+key} if core_owned else {})}
        with self.db() as db:
            db.execute('INSERT INTO tickets VALUES(?,?,?,?,?)',(key,time.time(),'preview',json.dumps(payload),None))
        return {'ticket':key,'expires_in':30,**payload,'notice':'Simulated order; actual price and fill are determined by Freqtrade'}

    def confirm(self, key, expected=None, guard=None):
        with self.lock:
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT * FROM tickets WHERE id=?',(key,)).fetchone()
                if not row: raise ValueError('Unknown ticket')
                data = json.loads(row['payload'])
                if data.get('core_owned') and guard is None:raise PermissionError('Core-owned ticket requires current Core session guard')
                config = None
                if expected is not None:
                    # Binding and current non-live identity are checked inside
                    # the original durable ticket transaction, even on replay.
                    if (not isinstance(expected,dict) or data != expected
                            or data['identity'].get('dry_run') is not True):
                        raise ValueError('Core ticket does not match the requested operation or identity')
                    config = self.configuration()
                    if config.get('dry_run') is not True or config != data['identity']:
                        raise ValueError('Core non-live identity changed or cannot be verified')
                if row['state'] != 'preview': return {'state':row['state'],'result':json.loads(row['result'] or 'null')}
                if db.execute("SELECT 1 FROM tickets WHERE state IN ('sending','unknown') LIMIT 1").fetchone():
                    raise ValueError('An earlier delivery is unresolved; reconcile before submitting another ticket')
                if time.time()-row['created'] > 30: raise ValueError('Ticket expired; preview again')
                config = config or self.configuration()
                if config != data['identity']: raise ValueError('Engine identity or configuration changed; preview again')
                intent = Intent(**data['intent'])
                self.validate(intent,config)
                db.execute("UPDATE tickets SET state='sending' WHERE id=?",(key,))
            # Persisted sending means a restart cannot cause a duplicate retry.
            if guard is not None:
                try: guard()
                except Exception:
                    with self.db() as db:
                        db.execute("UPDATE tickets SET state='rejected',result=? WHERE id=?",(json.dumps({'message':'Core scope/risk guard denied; no order sent'}),key))
                    raise
            try:
                result = self.api('forceenter',{'pair':intent.pair,'side':'short' if intent.action=='enter_short' else 'long','stakeamount':intent.stake,
                    'ordertype':'market','entry_tag':data.get('entry_tag','niblit_'+key[:12]),'leverage':1}) if intent.action in ('enter_long','enter_short') else self.api(
                    'forceexit',{'tradeid':str(intent.trade_id),'ordertype':'market'})
                selected = {k:result.get(k) for k in ('trade_id','status','pair','is_open')}
                state = 'submitted'  # Submission is not proof of a fill.
            except FreqtradeRejection as exc:
                state, selected = 'rejected', {'message':str(exc)}
            except Exception:
                state, selected = 'unknown', {'message':'Delivery uncertain. Inspect engine trades before another order.'}
            with self.db() as db:
                db.execute('UPDATE tickets SET state=?,result=? WHERE id=?',(state,json.dumps(selected),key))
            return {'state':state,'result':selected}

    def reconcile(self):
        config = self.configuration()
        trades = self.api('trades?limit=100').get('trades',[])
        resolved = 0
        with self.lock, self.db() as db:
            rows = db.execute("SELECT * FROM tickets WHERE state IN ('sending','unknown')").fetchall()
            for row in rows:
                payload = json.loads(row['payload'])
                if payload['identity'] != config:
                    continue
                intent = payload['intent']
                match = next((t for t in trades if t.get('pair')==intent['pair'] and (
                    t.get('enter_tag')==payload.get('entry_tag','niblit_'+row['id'][:12]) if intent['action'] in ('enter_long','enter_short')
                    else t.get('trade_id')==intent['trade_id'] and t.get('is_open') is False)),None)
                if match:
                    db.execute("UPDATE tickets SET state='reconciled',result=? WHERE id=?",
                        (json.dumps({'trade_id':match.get('trade_id'),'is_open':match.get('is_open')}),row['id']))
                    resolved += 1
        return {'resolved':resolved,'notice':'Only matching engine evidence resolves a ticket. No orders were sent.'}


def core_market_analysis(observation):
    """Forward evidence to the existing Core; never retry or submit an order."""
    try:
        port=int(os.getenv("NIBLIT_API_PORT","5000"))
        if not 1 <= port <= 65535:
            raise ValueError("Invalid Core port")
        with httpx.Client(base_url=f"http://127.0.0.1:{port}",trust_env=False,timeout=httpx.Timeout(60,connect=2)) as client:
            response=client.post("/api/trading/analysis",json={"observation":observation})
            response.raise_for_status()
            payload=response.json()
        metadata=payload.get("metadata",{})
        analysis=metadata.get("market_analysis")
        if not isinstance(analysis,dict) or analysis.get("execution_authorized") is not False:
            raise ValueError("Core analysis-only contract unavailable")
        return {"state":"analyzed_by_core","analysis":analysis,
                "authorization":metadata.get("authorization"),
                "memory":metadata.get("market_memory"),"trace_id":payload.get("trace_id"),
                "annotations":metadata.get("chart_annotations"),
                "execution_authorized":False}
    except Exception as exc:
        return {"state":"pending","error_type":type(exc).__name__,
                "execution_authorized":False}


def create_app(desk=None, mt5=None, core_hosted=False):
    desk = desk or Desk()
    @asynccontextmanager
    async def lifespan(app):
        yield
        app.state.demo_autotrader.stop()
    app = FastAPI(docs_url=None,redoc_url=None,lifespan=lifespan)
    token = secrets.token_urlsafe(32)
    from modules.mt5_bridge import MT5Bridge, MT5Unavailable
    mt5 = mt5 or MT5Bridge()
    from modules.mt5_orders import DemoOrders
    mt5_orders = DemoOrders(mt5,desk.path.parent/'mt5-orders.sqlite3')
    from modules.demo_autotrader import DemoAutotrader
    def demo_outcome_sink(identity, body):
        # Reuse Core's durable episodic outbox; no paid model request.
        with desk.db() as db:
            db.execute('INSERT OR IGNORE INTO outcomes VALUES(?,?,?)',
                       ('mt5-demo:'+identity, json.dumps({**body,'exchange':'mt5'}), time.time()))
        desk.export_outcomes()
    from modules.market_events import MarketEvents
    events = MarketEvents(desk.path.parent/'macro-research.sqlite3')
    auto = DemoAutotrader(mt5, mt5_orders, desk.path.parent/'demo-learning.sqlite3', demo_outcome_sink, events)
    app.state.demo_autotrader = auto
    from modules.freqtrade_research import FreqtradeResearch
    from modules.freqtrade_native_analysis import NativeAnalysisCache
    native_analysis=NativeAnalysisCache()
    freqtrade_research=FreqtradeResearch(desk,core_analysis=core_market_analysis,native_analysis=native_analysis.snapshot)

    @app.get('/api/freqtrade/positions')
    def core_position_intelligence():
        try:
            with httpx.Client(trust_env=False,timeout=8) as client:
                response=client.get('http://127.0.0.1:5000/api/trading/positions')
                response.raise_for_status()
                return response.json()
        except Exception:raise HTTPException(503,'Core position observations unavailable; no order was sent')

    @app.get('/api/freqtrade/research')
    def freqtrade_research_snapshot(pair:str):
        try: return freqtrade_research.snapshot(pair)
        except ValueError as exc: raise HTTPException(409,str(exc))
        except Exception: raise HTTPException(503,'Freqtrade research unavailable; no order was sent')

    @app.get('/api/demo/events')
    def demo_events():
        return events.snapshot()

    @app.post('/api/demo/events/refresh')
    def demo_events_refresh():
        return events.refresh()

    @app.get('/api/demo/status')
    def demo_status():
        return auto.status()

    @app.post('/api/demo/start')
    def demo_start(body:DemoSession):
        try:
            if body.opportunity_id is not None:
                match=next((o for o in auto.status()['opportunities'] if o['id']==body.opportunity_id and o['symbol']==body.symbol),None)
                if match is None: raise ValueError('Opportunity expired or conditions changed; wait for another alert')
            if mt5.snapshot(body.symbol)['account']['mode']!='demo':raise ValueError('Connect a verified demo account')
            raise ValueError('Review and activate the bounded session in Core trading controls; this legacy route cannot grant execution')
        except ValueError as exc: raise HTTPException(409, str(exc))
        except Exception: raise HTTPException(503, 'Demo session unavailable; inspect the terminal')

    @app.post('/api/demo/stop')
    def demo_stop():
        return auto.stop()

    @app.post('/api/demo/observe')
    def demo_observe(body:DemoSession):
        try: return auto.start(body.symbol, body.strategy, 1, 1, observe_only=True)
        except ValueError as exc: raise HTTPException(409, str(exc))
        except Exception: raise HTTPException(503, 'Observation unavailable; inspect MT5')

    @app.get('/api/mt5/snapshot')
    def mt5_snapshot(symbol:str|None=None):
        try:
            snapshot = mt5.snapshot(symbol, allow_symbol_fallback=True)
            return {**snapshot, 'order_history':mt5_orders.history(snapshot['account']['identity'])}
        except ValueError as exc: return {'connected':False,'error':str(exc)}
        except MT5Unavailable as exc: return {'connected':False,'error':str(exc)}
        except Exception: return {'connected':False,'error':'MT5 bridge unavailable; check the desktop terminal'}

    # Independent desktop observation is explicitly account-bound and cannot
    # route any mutations around the selected remote execution profile.
    from modules.desktop_market_intelligence import DesktopMarketIntelligence, component_inventory
    intelligence=DesktopMarketIntelligence(mt5,core_market_analysis)

    @app.get('/api/intelligence/desktop-binding')
    def desktop_binding():
        try:return intelligence.binding()
        except Exception as exc:return {'connected':False,'error_type':type(exc).__name__,
                                        'reason':'Open and connect the desktop MT5 terminal'}

    @app.get('/api/intelligence/desktop')
    def desktop_intelligence(symbol:str,account_identity:str,terminal_id:str):
        try:return intelligence.observe(symbol,account_identity,terminal_id)
        except (ValueError,MT5Unavailable) as exc:return {'connected':False,'reason':str(exc),'execution_authorized':False}
        except Exception as exc:return {'connected':False,'error_type':type(exc).__name__,
            'reason':'Desktop intelligence unavailable','execution_authorized':False}

    @app.get('/api/intelligence/components')
    def desktop_components(account_identity:str,terminal_id:str):
        try:
            from modules.mt5_bridge import LOCK
            with LOCK:
                api,account,terminal=mt5.connect()
                identity=mt5.account_record(api,account,terminal)
                if identity['identity']!=account_identity or identity['terminal_id']!=terminal_id:
                    raise ValueError('Desktop binding changed')
                return component_inventory(terminal.data_path)
        except Exception as exc:return {'components':[],'available':False,'error_type':type(exc).__name__,'execution_enabled':False}

    @app.post('/api/mt5/check-order')
    def mt5_check(body:MT5Check):
        try: return mt5.check_order(body.symbol,body.side,body.volume,body.account_identity)
        except ValueError as exc: raise HTTPException(409,str(exc))
        except MT5Unavailable as exc: raise HTTPException(503,str(exc))
        except Exception: raise HTTPException(503,'MT5 preflight unavailable')

    @app.post('/api/mt5/preview')
    def mt5_preview(body:MT5Intent):
        try: return mt5_orders.preview(body.model_dump())
        except ValueError as exc: raise HTTPException(409,str(exc))
        except Exception: raise HTTPException(503,'MT5 demo review unavailable')

    @app.post('/api/mt5/confirm')
    def mt5_confirm(body:MT5Confirm):
        try: return mt5_orders.confirm(body.ticket)
        except ValueError as exc: raise HTTPException(409,str(exc))
        except Exception: raise HTTPException(503,'MT5 delivery unavailable; inspect order activity before retrying')

    @app.post('/api/mt5/reconcile')
    def mt5_reconcile():
        try: return mt5_orders.reconcile()
        except Exception: raise HTTPException(503,'Broker deal evidence unavailable')

    @app.middleware('http')
    async def guard(request:Request, call_next):
        host = request.headers.get('host','')
        allowed_hosts={'127.0.0.1:8767','localhost:8767','testserver'}
        if core_hosted:allowed_hosts.update({'127.0.0.1:5000','localhost:5000'})
        if host not in allowed_hosts:
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail':'Invalid host'},400)
        if core_hosted and os.getenv('NIBLIT_VPS_GATEWAY_PROFILE','').strip():
            path=request.url.path
            prefix=request.scope.get('root_path','')
            if prefix and path.startswith(prefix):path=path[len(prefix):]
            remote_blocked=(path.startswith('/api/mt5/') or path.startswith('/api/demo/')
                or (path.startswith('/api/charts/') and request.query_params.get('environment')=='mt5'))
            if remote_blocked:
                from fastapi.responses import JSONResponse
                return JSONResponse({'detail':'Remote XM profile selected; desktop MT5 fallback and mutations disabled. Use Core remote observation.'},403)
        if request.method != 'GET':
            origin = request.headers.get('origin','')
            allowed_origins={'http://127.0.0.1:8767','http://localhost:8767'}
            if core_hosted:allowed_origins.update({'http://127.0.0.1:5000','http://localhost:5000'})
            if origin not in allowed_origins or not secrets.compare_digest(request.headers.get('x-desk-token',''),token):
                from fastapi.responses import JSONResponse
                return JSONResponse({'detail':'Open the local desk to review orders'},403)
        response = await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors http://tauri.localhost tauri://localhost http://localhost:5173 http://127.0.0.1:5173; base-uri 'none'; form-action 'none'"
        return response

    @app.get('/',response_class=HTMLResponse)
    def index(request:Request):
        base=request.scope.get('root_path','').rstrip('/')
        content=(ROOT/'assets/trading-desk/index.html').read_text(encoding='utf-8').replace('TOKEN_PLACEHOLDER',token).replace('BASE_PLACEHOLDER',base)
        content=content.replace('</head>','<script src="/exness-demo.js" defer></script></head>')
        for asset in ('desk.css','chart.js','desk.js','sessions.js','remote-observation.js','exness-demo.js','broker-view.js','intelligence.js'):
            content=content.replace('/'+asset,base+'/'+asset)
        if core_hosted and os.getenv('NIBLIT_VPS_GATEWAY_PROFILE','').strip():
            content=content.replace('<body>','<body data-remote-observation="true">')
        return content

    @app.api_route('/api/core-trading/{action:path}',methods=['GET','POST'])
    async def core_trading_proxy(action:str,request:Request):
        import re
        paths={'status':'','observe':'/observe','propose':'/propose','activate':'/activate','stop':'/stop'}
        if action in paths:tail=paths[action]
        elif re.fullmatch(r'alerts/[a-f0-9]{64}/delivered',action):tail='/'+action
        else:raise HTTPException(404,'Unknown Core trading action')
        if (action=='status') != (request.method=='GET'):raise HTTPException(405,'Invalid method')
        data=await request.json() if request.method=='POST' else None
        nonce=data.pop('operator_nonce','') if data is not None else ''
        port=int(os.getenv('NIBLIT_API_PORT','5000'))
        if not 1<=port<=65535:raise HTTPException(503,'Invalid Core port')
        headers={'origin':'http://127.0.0.1:8767','x-niblit-trading-nonce':nonce}
        async with httpx.AsyncClient(trust_env=False,timeout=120) as client:
            url=f'http://127.0.0.1:{port}/api/trading/sessions'+tail
            result=await client.get(url,headers=headers) if data is None else await client.post(url,json=data,headers=headers)
        if result.is_error:raise HTTPException(result.status_code,result.json().get('detail','Core trading unavailable'))
        return result.json()

    @app.get('/remote-observation.js')
    def remote_observation_javascript():return FileResponse(ROOT/'assets/trading-desk/remote-observation.js',media_type='text/javascript')

    @app.get('/exness-demo.js')
    def exness_demo_javascript():return FileResponse(ROOT/'assets/trading-desk/exness-demo.js',media_type='text/javascript')

    @app.get('/broker-view.js')
    def broker_view_javascript():return FileResponse(ROOT/'assets/trading-desk/broker-view.js',media_type='text/javascript')

    @app.get('/sessions.js')
    def core_trading_javascript():return FileResponse(ROOT/'assets/trading-desk/sessions.js',media_type='text/javascript')

    @app.get('/desk.js')
    def js(): return FileResponse(ROOT/'assets/trading-desk/desk.js',media_type='text/javascript')

    @app.get('/intelligence.js')
    def intelligence_javascript():return FileResponse(ROOT/'assets/trading-desk/intelligence.js',media_type='text/javascript')

    @app.get('/desk.css')
    def css(): return FileResponse(ROOT/'assets/trading-desk/desk.css',media_type='text/css')

    from modules.chart_views import ChartView, pine_export, freqtrade_annotations
    from fastapi.responses import PlainTextResponse
    chart_view=ChartView(desk,mt5,core_market_analysis)

    @app.get('/chart.js')
    def chart_javascript():return FileResponse(ROOT/'assets/trading-desk/chart.js',media_type='text/javascript')

    @app.get('/api/charts/snapshot')
    def chart_snapshot(environment:str='freqtrade',symbol:str='BTC/USDT:USDT',timeframe:str='5m'):
        try:return chart_view.snapshot(environment,symbol,timeframe)
        except ValueError as exc:raise HTTPException(422,str(exc))
        except Exception as exc:raise HTTPException(503,'Chart observation unavailable: '+type(exc).__name__)

    @app.get('/api/charts/history')
    def chart_history(environment:str='freqtrade',symbol:str='BTC/USDT:USDT',timeframe:str='5m'):
        result=chart_snapshot(environment,symbol,timeframe);bundle=result['annotations']
        if not bundle.get('namespace'):return {'history':[],'state':'history_unavailable'}
        with httpx.Client(trust_env=False,timeout=10) as client:
            response=client.get('http://127.0.0.1:5000/api/trading/chart-annotations',params={'chart_key':bundle['chart_key'],'namespace':bundle['namespace'],'history':'true'})
            response.raise_for_status();return response.json()

    @app.get('/api/charts/pine',response_class=PlainTextResponse)
    def chart_pine(environment:str='freqtrade',symbol:str='BTC/USDT:USDT',timeframe:str='5m'):
        result=chart_snapshot(environment,symbol,timeframe)
        return PlainTextResponse(pine_export(result['annotations']),headers={'Content-Disposition':'attachment; filename="NiblitEvidence.pine"'})

    @app.get('/api/charts/freqtrade')
    def chart_freqtrade(symbol:str='BTC/USDT:USDT',timeframe:str='5m'):
        result=chart_snapshot('freqtrade',symbol,timeframe)
        return {'pair':symbol,'timeframe':timeframe,'annotations':freqtrade_annotations(result['annotations']),
                'notice':'Supported FreqUI area contract. Endpoint is an export, not proof FreqUI consumes it.',
                'execution_authorized':False}

    @app.get('/api/snapshot')
    def snapshot(pair:str|None=None):
        try: return desk.snapshot(pair)
        except Exception as exc: return {'connected':False,'error':type(exc).__name__,'funded_execution_enabled':False}

    @app.post('/api/preview')
    def preview(body:Intent):
        try: return desk.preview(body)
        except ValueError as exc: raise HTTPException(409,str(exc))
        except Exception: raise HTTPException(503,'Execution engine unavailable')

    @app.post('/api/cloud/confirm')
    def cloud_confirm(body:BoundConfirm):
        # The original same-origin/session-token middleware applies. Cloud can
        # neither mint tickets nor obtain that human consent token from here.
        try:
            result = desk.confirm(body.ticket, expected={
                "intent":body.intent.model_dump(), "identity":body.identity})
            return {**result, "mode":"dry-run", "authority":"core_human_ticket"}
        except ValueError as exc: raise HTTPException(409,str(exc))
        except Exception: raise HTTPException(503,'Core confirmation unavailable; inspect tickets before retrying')

    @app.post('/api/confirm')
    def confirm(body:Confirm):
        try: return desk.confirm(body.ticket)
        except ValueError as exc: raise HTTPException(409,str(exc))
        except Exception: raise HTTPException(503,'Execution engine unavailable; inspect tickets before retrying')

    @app.post('/api/reconcile')
    def reconcile():
        try: return desk.reconcile()
        except Exception: raise HTTPException(503,'Cannot reconcile without engine trade evidence')

    return app
