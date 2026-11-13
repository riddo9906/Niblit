"""Core session integration for the existing DemoAutotrader worker.

No broker loop, permission authority, model call or projection worker is created
here. Existing workers call cycle(); existing broker tickets own delivery.
"""
import hashlib
import json
import math
import os
import sqlite3
import threading
import time
import uuid
from contextlib import nullcontext
from pathlib import Path

from modules.demo_strategy import STRATEGIES
from modules.funded_risk import evaluate as evaluate_funded_risk, breaker_after
from modules.strategy_manager import assess, assess_with_context
from modules.position_exit_policy import assess_exit
from modules.permission_manager import PermissionManager
from modules.task_admission import TaskAuthority, AdmissionBusy


def number(value, name, *, positive=False):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or (positive and value<=0):
        raise ValueError('Unverified numeric '+name)
    return float(value)


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()


def configured_limits():
    def limit(name,default,ceiling):
        value=number(float(os.getenv(name,str(default))),name,positive=True)
        if value>ceiling:raise ValueError('Configured trading limit exceeds demo release ceiling: '+name)
        return value
    return dict(risk_fraction=limit('NIBLIT_AUTO_RISK_FRACTION',.0025,.0025),
        risk_cash=limit('NIBLIT_AUTO_RISK_CASH',25,25),
        max_volume=limit('NIBLIT_AUTO_MAX_LOTS',.01,.10),
        max_margin_fraction=limit('NIBLIT_AUTO_MAX_MARGIN',.1,.1),
        max_exposure_fraction=limit('NIBLIT_MAX_TOTAL_EXPOSURE',.5,1),
        max_open_risk_fraction=limit('NIBLIT_AUTO_MAX_OPEN_RISK',.01,.02),
        max_daily_loss=limit('NIBLIT_MAX_DAILY_LOSS',.03,.03),
        max_drawdown=limit('NIBLIT_AUTO_MAX_DRAWDOWN',.02,.02),
        max_session_loss=limit('NIBLIT_AUTO_MAX_SESSION_LOSS',.02,.02),
        max_positions=int(limit('NIBLIT_MAX_OPEN_POSITIONS',3,5)),max_entries=3)


class CoreTradingSessions:
    """Registration/API/risk integration; DemoAutotrader remains the worker."""
    def __init__(self,runtime,adapters,*,journal,permission=None,clock=time.time,notify=None):
        self.runtime=runtime;self.gateway=runtime.gateway
        from modules.remote_broker_gateway import configured_gateway
        self.remote_gateway = configured_gateway()
        self.remote_stop_event = threading.Event()
        self.remote_worker = None
        self.pm=permission or PermissionManager();self.adapters=adapters
        self.clock=clock;self.runtime_id=uuid.uuid4().hex
        self.nonce=__import__('secrets').token_urlsafe(32)
        self._mt5_registry_lock = threading.Lock()
        self.lock=threading.RLock();self.bots={};self.journal=Path(journal)
        self.journal.parent.mkdir(parents=True,exist_ok=True)
        if notify is None:
            from core.notification_queue import notif_queue
            notify=notif_queue.push
        self.notify=notify;self.admission=TaskAuthority(self.gateway)
        self.pm.trading_schema(self.gateway,self.runtime_id)
        with self.gateway.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS funded_risk_evaluations(
                    id TEXT PRIMARY KEY, account TEXT NOT NULL, created REAL NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS funded_breakers(
                    account TEXT PRIMARY KEY, state TEXT NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS trading_events(
                    id TEXT PRIMARY KEY,created REAL,kind TEXT,payload TEXT,alert INTEGER,
                    delivered INTEGER NOT NULL DEFAULT 0,memory_receipt TEXT);
                CREATE TABLE IF NOT EXISTS trading_orders(
                    id TEXT PRIMARY KEY,session_id TEXT,adapter TEXT,account TEXT,instrument TEXT,
                    symbol TEXT,action TEXT,state TEXT,payload TEXT,result TEXT,updated REAL);
                CREATE UNIQUE INDEX IF NOT EXISTS trading_instrument_claim ON trading_orders(instrument)
                    WHERE action='open' AND state IN ('prepared','sending','unknown','submitted','open','partial');
            ''')
            # A prepared claim proves that Core's final guard was never consumed.
            # On restart it can be cancelled, unlike sending/unknown outcomes.
            stale=[dict(r) for r in db.execute("SELECT o.* FROM trading_orders o JOIN trading_sessions s ON s.id=o.session_id WHERE o.state='prepared' AND s.state='interrupted'")]
        for order in stale:
            adapter=self.adapters.get(order['adapter'])
            if adapter is not None and adapter.cancel_prepared(order):
                with self.gateway.db() as db:
                    db.execute("UPDATE trading_orders SET state='rejected',result=? WHERE id=? AND state='prepared'",(json.dumps({'state':'rejected','reason':'Core restarted before delivery guard'}),order['id']))

    def emit(self,kind,body,*,alert=False,key=None,_db=None):
        """Event and original memory outbox are committed together before send."""
        event={'kind':kind,**body};ident=key or digest(event)
        self.gateway.require('ingest',**self.runtime.scope)
        with (self.gateway.db() if _db is None else nullcontext(_db)) as db:
            if _db is None:db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM trading_events WHERE id=?',(ident,)).fetchone():return ident
            receipt=self.runtime.enqueue(source='trading-event://'+ident,
                content=json.dumps(event,sort_keys=True,allow_nan=False),category='episodic',
                metadata={'source_type':'trading_telemetry','provenance':{'event_id':ident,
                    'environment':body.get('environment','unspecified'),'verification':'provider_evidence_not_profit_prediction'}},_db=db)
            db.execute('INSERT INTO trading_events(id,created,kind,payload,alert,memory_receipt) VALUES(?,?,?,?,?,?)',
                (ident,self.clock(),kind,json.dumps(event,allow_nan=False),int(alert),receipt))
        if alert:self.notify('Trading: '+kind+' '+str(body.get('symbol','')))
        return ident

    def remote_status(self):
        """Commit state transitions through the existing canonical memory outbox."""
        if getattr(self.remote_gateway,'last_verified',None) is None:
            try:
                self.gateway.require('read',**self.runtime.scope)
                with self.gateway.db() as db:
                    saved=db.execute("SELECT payload FROM trading_events WHERE kind='remote_broker_state' "
                        "AND json_extract(payload,'$.remote_binding')=? "
                        "AND json_extract(payload,'$.identity_verified')=1 ORDER BY created DESC,rowid DESC LIMIT 1",
                        (digest(self.remote_gateway.profile.account),)).fetchone()
                if saved:
                    event=json.loads(saved['payload'])
                    if event.get('account_metrics'):
                        self.remote_gateway.last_verified={**event['account_metrics'],
                            'account':event['account'],'observed_at':event.get('broker_observed_at'),
                            'breaker':event.get('breaker')}
            except (sqlite3.Error,PermissionError,ValueError,TypeError):
                pass  # History unavailable is UNKNOWN, never current broker proof.
        remote = self.remote_gateway.status()
        observed = remote.get('observation') or {}
        account = observed.get('effective_config', {}).get('account', {})
        binding = digest(self.remote_gateway.profile.account)
        state = {
            'remote_binding': binding,
            'identity_verified': remote.get('broker_verified') is True,
            'gateway_reachable': remote.get('gateway_reachable') is True,
            'account': account,
            'environment': account.get('environment', 'unverified'),
            'breaker': remote.get('breaker'),
            'inventory': observed.get('last_verified_inventory'),
            'account_metrics': {k:(observed.get('account_observation') or {}).get(k)
                for k in ('balance','equity','margin','free_margin','positions','orders')}
                if remote.get('broker_verified') else None,
            'history': observed.get('history'),
            'execution_enabled': False,
        }
        fingerprint = digest(state)
        try:
            with self.gateway.db() as db:
                db.execute('BEGIN IMMEDIATE')
                previous = db.execute(
                    "SELECT id,payload FROM trading_events WHERE kind='remote_broker_state' "
                    "AND json_extract(payload,'$.remote_binding')=? ORDER BY created DESC,rowid DESC LIMIT 1",
                    (binding,)).fetchone()
                if previous and json.loads(previous['payload']).get('state_fingerprint') == fingerprint:
                    event_id = previous['id']
                else:
                    event_id = digest({'state': fingerprint, 'previous': previous['id'] if previous else None})
                    body = {**state, 'state_fingerprint': fingerprint,
                            'broker_observed_at': (observed.get('account_observation') or {}).get('observed_at',observed.get('last_probe_at_unix')),
                            'recorded_at': self.clock()}
                    self.emit('remote_broker_state', body, key=event_id, _db=db)
            return {**remote, 'canonical_journal': {'recorded': True, 'event_id': event_id}}
        except (sqlite3.Error, PermissionError, ValueError, TypeError):
            return {**remote, 'canonical_journal': {
                'recorded': False, 'error': 'canonical_observation_persistence_unavailable'}}

    def start_remote_observer(self):
        """One read-only observer, independent of inference and UI request timing."""
        if self.remote_gateway is None:
            return
        with self.lock:
            if self.remote_worker and self.remote_worker.is_alive():
                return
            self.remote_stop_event.clear()
            def observe_remote():
                while not self.remote_stop_event.is_set():
                    self.remote_status()
                    self.remote_stop_event.wait(15)
            self.remote_worker = threading.Thread(
                target=observe_remote, name='niblit-remote-observation', daemon=True)
            self.remote_worker.start()

    def observe(self,adapter,symbol,*,threaded=True):
        if adapter == 'mt5' and self.remote_gateway is not None:
            raise PermissionError('XM remote profile is observation-only; local MT5 fallback disabled')
        if adapter not in self.adapters:raise ValueError('Unregistered broker adapter')
        if not isinstance(symbol,str) or not 1<=len(symbol)<=80:raise ValueError('Broker symbol required')
        key=(adapter,symbol)
        with self.lock:
            if key not in self.bots:
                from modules.demo_autotrader import DemoAutotrader
                bot=DemoAutotrader(self.adapters[adapter],None,self.journal,events=None,core_cycle=self.cycle)
                bot.session={'state':'observing','adapter':adapter,'symbol':symbol,'id':None}
                bot.core_cycle=self.cycle;bot.error=None
                self.bots[key]=bot
            bot=self.bots[key]
            if threaded and not (bot.worker and bot.worker.is_alive()):
                bot.stop_event.clear()
                bot.worker=threading.Thread(target=bot.run,name='niblit-core-demo-'+adapter,daemon=True)
                bot.worker.start()
        return bot

    def propose(self,adapter,symbol,seconds=1800,limits=None,*,close_order_id=None):
        if adapter == 'mt5' and self.remote_gateway is not None:
            raise PermissionError('XM remote profile cannot authorize broker operations')
        if isinstance(seconds,bool) or not isinstance(seconds,int) or not 60<=seconds<=3600:raise ValueError('Session must be 60–3600 seconds')
        if adapter == 'mt5':
            active = self.refresh_mt5_account()
            if active and active['environment'] == 'live':
                self.funded_preflight(None, {'account':active,'symbol':symbol,'action':'open'})
                raise PermissionError('Real-money execution disabled')
        snap=self.adapters[adapter].snapshot(symbol)
        self.validate_snapshot(snap,symbol)
        if snap['environment'] not in ('demo','dry-run','simulation'):raise PermissionError('Real-money execution disabled')
        ceiling=configured_limits()
        if adapter in ('mt5','exness_demo'):
            ceiling['max_volume']=min(.10,number(float(os.getenv('NIBLIT_AUTO_MAX_LOTS','.10')),'demo lot ceiling',positive=True),snap.get('demo_volume_ceiling',.01))
        selected=dict(ceiling)
        selected['max_volume']=min(.01,ceiling['max_volume'])
        for name,value in (limits or {}).items():
            if name not in ceiling:raise ValueError('Unknown risk limit')
            value=number(value,name,positive=True)
            if value>ceiling[name]:raise ValueError('Risk limit exceeds configured ceiling')
            if name in ('max_entries','max_positions'):
                if int(value)!=value:raise ValueError('Whole-number entry/position limit required')
                value=int(value)
            selected[name]=value
        if adapter in ('mt5','exness_demo') and selected['max_volume']>snap.get('demo_volume_ceiling',.01):
            raise ValueError('Reviewed lot cap exceeds verified demo adapter ceiling')
        spec=dict(adapter=adapter,symbol=symbol,account=snap['account'],environment=snap['environment'],
            instrument=snap['instrument'],seconds=seconds,limits=selected,strategies=list(STRATEGIES),
            timeframe='5m',position_actions=['open','close'],live_money=False)
        if adapter in ('mt5','exness_demo'):
            spec['account_binding'] = snap['account_binding']
        if adapter=='exness_demo':
            protection=snap.get('protection_policy')
            if not isinstance(protection,dict) or protection.get('version')!='crypto-atr-structure/1':
                raise PermissionError('Verified crypto protection policy required')
            spec['protection_policy']=protection
        if close_order_id is not None:
            if adapter not in ('mt5','exness_demo') or snap['environment'] != 'demo':
                raise PermissionError('Close-only scope requires MT5 demo')
            with self.gateway.db() as db:
                entry = db.execute(
                    "SELECT * FROM trading_orders WHERE id=? AND action='open' AND state='open'",
                    (close_order_id,),
                ).fetchone()
            if not entry or any(entry[key] != spec[key] for key in ('adapter','account','symbol','instrument')):
                raise PermissionError('No matching Core-owned entry')
            origin = self.session(entry['session_id'])
            if origin['state'] not in ('expired','stopped','interrupted'):
                raise PermissionError('Original session must have ended')
            receipt = self.adapters[adapter].reconcile(dict(entry))
            identifier = receipt.get('position_identifier')
            if receipt['state'] != 'open' or not identifier:
                raise PermissionError('Broker has not confirmed the Core-owned position')
            if number(receipt.get('volume'), 'position volume', positive=True) > selected['max_volume']:
                raise PermissionError('Owned position exceeds the proposed volume cap')
            spec.update(position_actions=['close'], close_order_id=close_order_id,
                        position_identifier=identifier)
            spec['limits']['max_entries'] = 0
        ident=self.pm.propose_trading(self.gateway,spec,self.runtime_id,snap['equity'])
        self.emit('session_proposed',{'session':ident,**spec})
        return self.session(ident)

    def session(self,ident):
        with self.gateway.db() as db:row=db.execute('SELECT * FROM trading_sessions WHERE id=?',(ident,)).fetchone()
        if not row:raise ValueError('Unknown session')
        result=dict(row);result['spec']=json.loads(result['spec'])
        return result

    def activate(self,ident,fingerprint,*,clear_stop=False,threaded=True):
        with self.lock:
            row=self.session(ident);spec=row['spec']
            if spec['adapter'] == 'mt5' and self.remote_gateway is not None:
                raise PermissionError('Remote observation profile cannot activate local MT5 authority')
            snap=self.adapters[spec['adapter']].snapshot(spec['symbol'])
            self.validate_snapshot(snap,spec['symbol'],spec)
            # Re-review after equity changes: proposal sizing is account-aware.
            if abs(snap['equity']-row['initial_equity'])>max(.01,row['initial_equity']*.001):
                raise PermissionError('Account equity changed; review a fresh proposal')
            self.pm.activate_trading(self.gateway,ident,fingerprint,self.runtime_id,clear_stop=clear_stop)
            self.emit('session_activated',{'session':ident,**spec},alert=True)
            bot=self.observe(spec['adapter'],spec['symbol'],threaded=False)
            bot.session.update(id=ident,state='running')
            if threaded:self.observe(spec['adapter'],spec['symbol'])
        return self.session(ident)

    def stop(self,ident=None,*,emergency=False):
        with self.lock:
            self.pm.stop_trading(self.gateway,ident,emergency=emergency)
            telemetry_pending=False
            if emergency and 'exness_demo' in self.adapters:
                try:self.adapters['exness_demo'].emergency_stop()
                except Exception:telemetry_pending=True
            try:
                self.emit('emergency_stop' if emergency else 'session_stopped',
                    {'session':ident or 'all','notice':'No new broker calls; an in-flight delivery may already have completed. Observation/reconciliation remain active.'},alert=True)
            except Exception:
                # PermissionManager has already persisted stop and its audit in
                # the canonical ledger. Projection failure cannot undo a stop.
                telemetry_pending=True
                self.notify('Trading stopped; memory projection notification pending')
        return {'state':'stopped','observation_continues':True,'inflight_may_finish':True,'telemetry_pending':telemetry_pending}

    def shutdown(self):
        self.remote_stop_event.set()
        if self.remote_worker:
            self.remote_worker.join(timeout=4)
        try:self.stop()
        finally:
            for bot in list(self.bots.values()):bot.stop()
        for bot in list(self.bots.values()):
            if bot.worker:bot.worker.join(timeout=20)

    def refresh_mt5_account(self):
        if self.remote_gateway is not None:
            return None
        """Observe the active IPC account and interrupt incompatible grants."""
        with self._mt5_registry_lock:
            return self._refresh_mt5_account()

    def _refresh_mt5_account(self):
        adapter = self.adapters.get('mt5')
        bridge = getattr(adapter, 'bridge', None)
        if bridge is None:
            return None
        try:
            active = bridge.connection_record()
        except Exception:
            active = None
        change = None
        now = self.clock()
        with self.gateway.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS mt5_accounts(identity TEXT PRIMARY KEY, profile TEXT NOT NULL, verified REAL)')
            db.execute('CREATE TABLE IF NOT EXISTS mt5_connection(singleton INTEGER PRIMARY KEY CHECK(singleton=1), profile TEXT, updated REAL)')
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT profile FROM mt5_connection WHERE singleton=1').fetchone()
            previous = json.loads(prior['profile']) if prior and prior['profile'] else None
            for item in getattr(self, 'configured_mt5_accounts', ()):
                db.execute('INSERT OR IGNORE INTO mt5_accounts VALUES(?,?,NULL)',
                           (item['identity'], json.dumps(item, sort_keys=True)))
            if active:
                db.execute('INSERT OR REPLACE INTO mt5_accounts VALUES(?,?,?)',
                           (active['identity'], json.dumps(active, sort_keys=True), now))
            if prior is None or previous != active:
                db.execute('INSERT OR REPLACE INTO mt5_connection VALUES(1,?,?)',
                           (json.dumps(active, sort_keys=True) if active else None, now))
                grants = db.execute("SELECT id,spec FROM trading_sessions WHERE state IN ('pending','active','risk_halted')").fetchall()
                interrupted = []
                for grant in grants:
                    scope = json.loads(grant['spec'])
                    if scope.get('adapter') != 'mt5':
                        continue
                    if not active or active['environment'] != 'demo' or scope.get('account_binding') != active:
                        db.execute("UPDATE trading_sessions SET state='interrupted',reason='MT5 account or terminal binding changed' WHERE id=?",
                                   (grant['id'],))
                        interrupted.append(grant['id'])
                change = {'previous':previous,'active':active,'observed_at':now,'interrupted_sessions':interrupted}
                self.gateway.audit(db, 'trading.mt5_connection_changed', active['identity'] if active else 'disconnected', **change)
        if change:
            try:
                self.emit('mt5_connection_changed', change, alert=True)
            except Exception:
                # Connection and authority change are already durable in SQLite.
                pass
        return active

    def mt5_account_status(self, active):
        with self.gateway.db() as db:
            accounts = [dict(row) for row in db.execute('SELECT * FROM mt5_accounts ORDER BY verified DESC')]
            current = db.execute('SELECT updated FROM mt5_connection WHERE singleton=1').fetchone()
        return {'connected':active is not None,'active':active,
                'last_transition':current['updated'] if current else None,
                'known':[dict(json.loads(row['profile']), last_verified=row['verified'],
                              verification='observed' if row['verified'] is not None else 'configured')
                         for row in accounts]}

    def status(self):
        active_mt5 = self.refresh_mt5_account()
        with self.gateway.db() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM trading_sessions ORDER BY created DESC LIMIT 30')]
            events=[dict(r) for r in db.execute('SELECT * FROM trading_events ORDER BY created DESC LIMIT 100')]
            orders=[dict(r) for r in db.execute('SELECT * FROM trading_orders ORDER BY updated DESC LIMIT 100')]
            funded = None
            if active_mt5 and active_mt5['environment'] == 'live':
                account = digest({k:active_mt5.get(k) for k in ('login','server','terminal_id','environment')})
                funded = db.execute('SELECT payload FROM funded_risk_evaluations WHERE account=? ORDER BY created DESC LIMIT 1',
                                    (account,)).fetchone()
            stopped=bool(db.execute('SELECT stopped FROM trading_control WHERE singleton=1').fetchone()[0])
        for row in rows:row['spec']=json.loads(row['spec'])
        for event in events:event['payload']=json.loads(event['payload'])
        return dict(sessions=rows,events=events,orders=orders,emergency_stopped=stopped,
            mt5_accounts=self.mt5_account_status(active_mt5) if self.remote_gateway is None and getattr(self.adapters.get('mt5'),'bridge',None) is not None else None,
            observers=[{'adapter':key[0],'symbol':key[1],'error':bot.error,'assessment':getattr(bot,'manager',None),
                        'running':bool(bot.worker and bot.worker.is_alive())} for key,bot in self.bots.items()],
            admission={key:self.admission.status(key) for key in ('inference','broker')},
            funded_preflight=json.loads(funded['payload']) if funded else None,
            remote_gateway=self.remote_status() if self.remote_gateway else {
                'configured':False,'gateway_reachable':False,'broker_verified':False,
                'observation_enabled':False,'execution_enabled':False},
            remote_demo=self.adapters['exness_demo'].status() if 'exness_demo' in self.adapters else {'configured':False},
            operator_nonce=self.nonce,real_money_enabled=False,execution_at_startup=False)

    def funded_preflight(self, policy, evidence):
        """Record a funded engineering decision without granting or delivering."""
        now = self.clock()
        account = digest({k: evidence.get('account', {}).get(k)
                          for k in ('login','server','terminal_id','environment')})
        with self.gateway.db() as db:
            db.execute('BEGIN IMMEDIATE')
            previous = db.execute('SELECT state FROM funded_breakers WHERE account=?',(account,)).fetchone()
            current = previous['state'] if previous else 'NORMAL'
            decision = evaluate_funded_risk(policy, evidence, now=now, breaker=current)
            state = breaker_after(current, evidence, decision)
            decision['breaker_state'] = state
            db.execute('INSERT INTO funded_risk_evaluations VALUES(?,?,?,?)',
                       (uuid.uuid4().hex,account,now,json.dumps(decision,allow_nan=False)))
            if state != current or previous is None:
                db.execute('INSERT OR REPLACE INTO funded_breakers VALUES(?,?,?)',(account,state,now))
                self.gateway.audit(db,'trading.funded_breaker_changed',account,previous=current,state=state)
        return decision

    def acknowledge_alert(self,ident):
        with self.gateway.db() as db:db.execute('UPDATE trading_events SET delivered=1 WHERE id=? AND alert=1',(ident,))

    def validate_snapshot(self,s,symbol,spec=None):
        if s.get('environment') not in ('demo','dry-run','simulation'):raise PermissionError('Live or unknown account environment; observation only')
        if not isinstance(s.get('account'),str) or not s['account']:raise ValueError('Verified account identity required')
        if s.get('symbol')!=symbol:raise ValueError('Market symbol mismatch')
        if spec and spec['adapter'] in ('mt5','exness_demo') and spec['limits']['max_volume']>s.get('demo_volume_ceiling',.01):
            raise PermissionError('Demo volume ceiling changed; review a fresh scope')
        if spec and any(s.get(k)!=spec[k] for k in ('account','environment','instrument','account_binding','protection_policy') if k in spec):raise PermissionError('Account/environment/instrument/protection policy changed')
        for name in ('equity','available','margin','exposure','realized_today','observed_at'):
            number(s.get(name),name,positive=name=='equity')
        if min(s['margin'],s['exposure'])<0:raise ValueError('Invalid account amounts')
        if not 0<=self.clock()-s['observed_at']<=15:raise ValueError('Account observation stale')
        q=s.get('quote') or {}
        if q.get('fresh') is not True or not 0<=number(q.get('age_seconds'),'quote age')<=15:raise ValueError('Stale broker quote')
        if not 0<number(q.get('bid'),'bid')<=number(q.get('ask'),'ask'):raise ValueError('Invalid quote')
        bars=s.get('candles') or []
        if not 51<=len(bars)<=500 or any(b['timestamp']-a['timestamp']!=300 for a,b in zip(bars,bars[1:])):raise ValueError('Incomplete M5 history')
        if not 300<=number(q.get('timestamp'),'market clock')-bars[-1]['timestamp']<=620:raise ValueError('Stale completed candle')
        for bar in bars:
            values=[number(bar.get(k),k,positive=True) for k in ('open','high','low','close')]
            if values[2]>min(values[0],values[3]) or values[1]<max(values[0],values[3]):raise ValueError('Inconsistent candle')

    def risk(self,row,s,prepared=None,*,action='open'):
        spec=row['spec'];limits=spec['limits'];initial=row['initial_equity'];peak=max(row['peak_equity'],s['equity'])
        halt=(s['equity']<=initial*(1-limits['max_session_loss']) or
              s['equity']<=peak*(1-limits['max_drawdown']) or
              s['realized_today']<=-initial*limits['max_daily_loss'] or s['available']<0 or
              s['margin']>s['equity']*limits['max_margin_fraction'] or
              s['exposure']>s['equity']*limits['max_exposure_fraction'] or
              len(s['positions'])>limits['max_positions'] or
              (s.get('open_risk') is not None and number(s['open_risk'],'open risk')>s['equity']*limits['max_open_risk_fraction']))
        with self.gateway.db() as db:
            db.execute('UPDATE trading_sessions SET peak_equity=? WHERE id=?',(peak,row['id']))
            if halt:db.execute("UPDATE trading_sessions SET state='risk_halted',reason='Account loss, drawdown, exposure or protection limit' WHERE id=? AND state='active'",(row['id'],))
        if halt:
            self.emit('risk_limit',{'session':row['id'],'symbol':spec['symbol'],'environment':spec['environment'],'reason':'Account loss, drawdown, exposure or protection limit'},alert=True)
            if action=='open':raise PermissionError('Account loss/drawdown limit reached')
        if action=='open':
            if len(s['positions'])>=limits['max_positions'] or s.get('pending_count',0):raise PermissionError('Account exposure or pending-order capacity reached')
            if any(p['symbol']==spec['symbol'] for p in s['positions']):raise PermissionError('Existing symbol exposure is not adopted')
            if prepared:
                cash=number(prepared.get('risk'),'stop risk',positive=True)
                margin=number(prepared.get('margin'),'proposed margin')
                exposure=number(prepared.get('exposure'),'proposed exposure',positive=True)
                if margin<0:raise ValueError('Invalid margin')
                if cash>min(s['equity']*limits['risk_fraction'],limits['risk_cash']):raise PermissionError('Per-entry stop risk exceeded')
                if number(s.get('open_risk'),'account open stop risk')+cash>s['equity']*limits['max_open_risk_fraction']:raise PermissionError('Aggregate stop risk exceeded')
                if s['margin']+margin>s['equity']*limits['max_margin_fraction'] or margin>s['available']:raise PermissionError('Margin limit exceeded')
                if s['exposure']+exposure>s['equity']*limits['max_exposure_fraction']:raise PermissionError('Exposure limit exceeded')
                if not prepared.get('stop_loss') or not prepared.get('take_profit'):raise PermissionError('Verified stop and target required')
        return halt

    def native_entry_receipt(self,body):
        """Consume one already-sending Freqtrade claim. Never grants a session.

        This callback does not take the worker lock or call Freqtrade: the native
        engine is waiting for it while the original Core RPC is in flight.
        """
        with self.gateway.db() as db:
            db.execute('BEGIN IMMEDIATE')
            rows=db.execute("SELECT * FROM trading_orders WHERE adapter='freqtrade' AND action='open' AND state='sending' AND json_extract(payload,'$.prepared.ticket')=?",(body['ticket'],)).fetchall()
            if len(rows)!=1:raise PermissionError('No unique sending Core claim')
            order=dict(rows[0]);payload=json.loads(order['payload']);prepared=payload['prepared']
            if payload.get('native_claimed'):raise PermissionError('Native receipt already consumed')
            if not payload.get('admission_hash'):raise PermissionError('Core delivery admission absent')
            spec=self.pm.check_trading(self.gateway,order['session_id'],self.runtime_id,'','open',
                db=db,token_hash=payload['admission_hash'],claimed_receipt=True)
            intent=prepared['expected']['intent']
            if (body['symbol']!=order['symbol'] or body['side']!=('long' if intent['action']=='enter_long' else 'short')
                    or body['account_binding']!=prepared['native_account_binding']
                    or prepared['expected']['identity'].get('strategy')!='NiblitCoreManaged'
                    or spec['account']!=order['account']):raise PermissionError('Native account/strategy/intent mismatch')
            for field,expected in (('stoploss','native_stoploss'),('minimal_roi','native_roi'),('fee','native_fee')):
                if body[field]!=prepared[expected]:raise PermissionError('Native protective configuration mismatch')
            amount=number(body['amount'],'native amount',positive=True);rate=number(body['rate'],'native rate',positive=True)
            if amount*rate>intent['stake']+1e-7 or abs(rate/prepared['reference_price']-1)>.001:
                raise PermissionError('Native sizing or slippage exceeds approved preflight')
            payload['native_claimed']=True
            db.execute('UPDATE trading_orders SET payload=? WHERE id=?',(json.dumps(payload,allow_nan=False),order['id']))
            self.emit('native_entry_authorized',{'session':order['session_id'],'order':order['id'],
                'symbol':order['symbol'],'environment':spec['environment'],'amount':amount,'rate':rate},_db=db)
        return {'allowed':True,'claim':order['id'],'session_granted':False}


    def _reconcile(self,bot,s):
        adapter=bot.bridge;key=bot.session['adapter']
        with self.gateway.db() as db:
            rows=[dict(r) for r in db.execute("SELECT * FROM trading_orders WHERE adapter=? AND account=? AND symbol=? AND state IN ('sending','unknown','submitted','open','partial')",(key,s['account'],bot.session['symbol']))]
        for order in rows:
            report=adapter.reconcile(order)
            if report.get('state') not in ('open','closed','rejected','unknown','partial'):raise ValueError('Invalid reconciliation state')
            if report['state'] in ('open','closed') and not report.get('position_id'):raise ValueError('Unproven broker position ownership')
            encoded=json.dumps(report,sort_keys=True,allow_nan=False)
            if order['result']!=encoded:
                self.emit('reconciliation',{'session':order['session_id'],'order':order['id'],'symbol':order['symbol'],
                    'environment':s['environment'],'evidence':report},alert=report['state'] in ('open','closed','rejected'))
            if order['action'] == 'open' and report['state'] == 'closed' and 'realized_net' in report:
                thesis = json.loads(order['payload'])
                self.emit('trading_outcome', {
                    'session':order['session_id'], 'order':order['id'], 'symbol':order['symbol'],
                    'environment':s['environment'], 'strategy':thesis['context']['strategy'],
                    'initial_estimated_risk':thesis['prepared']['risk'], 'evidence':report,
                }, key=digest({'trading_outcome':order['id']}))
            with self.gateway.db() as db:
                db.execute('UPDATE trading_orders SET state=?,result=?,updated=? WHERE id=?',(report['state'],encoded,self.clock(),order['id']))
        if getattr(bot,'quarantined_lease',None):
            with self.gateway.db() as db:
                uncertain=db.execute("SELECT 1 FROM trading_orders WHERE state IN ('sending','unknown','partial') LIMIT 1").fetchone()
            if not uncertain:
                self.admission.finish(bot.quarantined_lease);bot.quarantined_lease=None

    def _record_owned_positions(self, bot, snapshot, bar):
        # Positions survive the entry grant. Observation and broker-side
        # protection continue, but expired grants cannot send modifications.
        with self.gateway.db() as db:
            rows = db.execute(
                "SELECT id,session_id,result FROM trading_orders WHERE adapter=? AND account=? "
                "AND symbol=? AND action='open' AND state='open'",
                (bot.session['adapter'], snapshot['account'], snapshot['symbol']),
            ).fetchall()
        positions = {str(position['id']): position for position in snapshot['positions']}
        for row in rows:
            position = positions.get(str(json.loads(row['result'])['position_id']))
            if position is None:
                continue
            mark = snapshot['quote']['bid' if position['side'] == 'buy' else 'ask']
            evidence = {'session': row['session_id'], 'order': row['id'], 'bar': bar,
                        'symbol': snapshot['symbol'], 'environment': snapshot['environment'],
                        'observed_at': snapshot['observed_at'], 'mark': mark, 'position': position}
            key = digest({'position_watch': row['id'], 'bar': bar,
                          'stop': position.get('stop_loss'), 'target': position.get('take_profit')})
            self.emit('position_watch', evidence, key=key)

    def cycle(self,bot):
        """One existing worker tick: observe -> reconcile -> consensus -> risk -> ticket."""
        if bot.session.get('adapter') == 'mt5' and self.remote_gateway is not None:
            bot.error = 'Local MT5 worker blocked by remote observation profile'
            return
        try:
            adapter=bot.bridge;symbol=bot.session['symbol']
            ident = bot.session.get('id')
            if ident:
                row = self.session(ident)
                with self.gateway.db() as db:
                    expired = db.execute(
                        "UPDATE trading_sessions SET state='expired',reason='Execution window ended' "
                        "WHERE id=? AND expires<=? AND state IN ('active','risk_halted')",
                        (ident, self.clock()),
                    ).rowcount
                if expired:
                    self.emit('session_expired', {
                        'session': ident, 'symbol': symbol,
                        'environment': row['spec']['environment'],
                    }, alert=True)
            if bot.session['adapter'] == 'mt5':
                active = self.refresh_mt5_account()
                if active is None:
                    bot.manager = None
                    raise ValueError('MT5 connection unavailable')
                if active['environment'] != 'demo':
                    # Observe quotes without invoking the demo risk or delivery adapter.
                    observed = adapter.bridge.snapshot(symbol, allow_symbol_fallback=True, include_context=True)
                    bot.manager = assess_with_context(observed['candles'], observed['market_context']) if observed['candles'] else None
                    bot.error = ('MT5 account is read-only' if observed['symbol']
                                 else 'Configured symbol is unavailable on the active MT5 account')
                    return
            # Broker readback needs identity, not a fresh entry quote or daily
            # risk feed. Record late fills/exits even during market-data outages.
            self._reconcile(bot,adapter.reconciliation_identity())
            s=adapter.snapshot(symbol)
            self.validate_snapshot(s,symbol)
            decision=assess_with_context(s['candles'],s.get('market_context'));bot.manager=decision;bot.error=None
            signal={'adapter':bot.session['adapter'],'account':s['account'],'environment':s['environment'],
                'symbol':symbol,'session':ident,'timeframe':'5m','bar':decision.get('bar'),'assessment':decision,'quote':s['quote']}
            self.emit('signal',signal,alert=decision['side'] in ('buy','sell'),key=digest({'signal':signal['adapter'],'session':ident,'account':s['account'],'symbol':symbol,'bar':decision.get('bar'),'assessment':decision}))
            directions = {candidate['side'] for candidate in decision['candidates']} & {'buy', 'sell'}
            if len(directions) > 1:
                self.emit('strategy_disagreement', {
                    'session': ident, 'symbol': symbol, 'environment': s['environment'],
                    'bar': decision.get('bar'), 'reason': decision['selection_reason'],
                }, alert=True)
            self._record_owned_positions(bot, s, decision.get('bar'))
            if not ident:return
            row=self.session(ident);spec=row['spec']
            self.validate_snapshot(s,symbol,spec)
            if row['state'] not in ('active','risk_halted'):return
            # Only an entry linked through this canonical execution ledger may
            # supply an exit thesis. Manual/pre-existing positions stay untouched.
            with self.gateway.db() as db:
                entries=[dict(r) for r in db.execute("SELECT * FROM trading_orders WHERE session_id=? AND action='open' AND state='open'",(ident,))]
                bound = spec.get('close_order_id')
                if bound:
                    entries = [dict(x) for x in db.execute(
                        "SELECT * FROM trading_orders WHERE id=? AND action='open' AND state='open'",
                        (bound,))]
                    attempted = db.execute(
                        "SELECT 1 FROM trading_orders WHERE session_id=? AND action='close'",
                        (ident,)).fetchone()
                    if attempted:
                        return
                unresolved=db.execute("SELECT 1 FROM trading_orders WHERE state IN ('sending','unknown','partial') LIMIT 1").fetchone()
            if unresolved:
                self.emit('execution_blocked', {'session':ident,'symbol':symbol,'environment':s['environment'],
                          'bar':decision.get('bar'),'reason':'Broker delivery awaiting reconciliation'})
                return
            action='open';position=None;context=None;side=decision['side'];exit_reason=None
            halt=self.risk(row,s,action='close')
            for entry in entries:
                receipt=json.loads(entry['result']);position=next((p for p in s['positions'] if str(p['id'])==str(receipt['position_id'])),None)
                if position is None:continue
                if bound and (receipt.get('position_identifier') != spec['position_identifier']
                              or position['quantity'] > spec['limits']['max_volume']):
                    raise PermissionError('Owned position no longer matches close-only scope')
                payload=json.loads(entry['payload']);context=payload['context']
                protection_missing=not position.get('stop_loss') or (bot.session['adapter'] in ('mt5','exness_demo') and not position.get('take_profit'))
                if bot.session['adapter']=='freqtrade':
                    protection_missing=protection_missing or any(s.get('protections',{}).get(k)!=payload['prepared'].get(v) for k,v in (('stoploss','native_stoploss'),('minimal_roi','native_roi')))
                position=dict(position)
                position['stop_loss']=position.get('stop_loss') or payload['prepared']['stop_loss']
                position['take_profit']=position.get('take_profit') or payload['prepared']['take_profit']
                held=assess(s['candles'],'auto',held_strategy=context['strategy'])
                exit_report=assess_exit({'type':0 if position['side']=='buy' else 1,'price_open':position['entry']},s['candles'],s['quote'],context)
                mark=s['quote']['bid'] if position['side']=='buy' else s['quote']['ask']
                crossed=(mark<=position['stop_loss'] or mark>=position['take_profit']) if position['side']=='buy' else (mark>=position['stop_loss'] or mark<=position['take_profit'])
                opposite=held['assessment_complete'] and held['side'] in ('buy','sell') and held['side']!=position['side']
                with self.gateway.db() as db:
                    payload['context']=context;db.execute('UPDATE trading_orders SET payload=? WHERE id=?',(json.dumps(payload,allow_nan=False),entry['id']))
                if halt or protection_missing or crossed or opposite or exit_report['action']=='close':
                    exit_reason = ('Account risk limit' if halt else 'Broker protection missing' if protection_missing
                                   else 'Broker protection level crossed' if crossed else 'Entry strategy reversed'
                                   if opposite else exit_report.get('reason') or 'Entry strategy exit condition')
                    action='close';side='sell' if position['side']=='buy' else 'buy';break
                return
            else:
                position=None
            if action=='open':
                if 'open' not in spec['position_actions']:return
                if not decision['assessment_complete'] or side not in ('buy','sell'):return
                self.risk(self.session(ident),s)
            lease=None
            with self.lock:
                try:
                    lease=self.admission.acquire('trading_cycle',session_id=ident)['token']
                except AdmissionBusy as exc:
                    self.emit('execution_blocked', {'session':ident,'symbol':symbol,'environment':s['environment'],
                              'bar':decision.get('bar'),'action':action,'reason':str(exc)})
                    return
                try:
                    self.pm.check_trading(self.gateway,ident,self.runtime_id,lease,action)
                    prepared=adapter.prepare({**s,'entry_strategy':decision['strategy']},side,spec['limits'],position=position)
                    self.risk(self.session(ident),s,prepared,action=action)
                    claim=digest({'session':ident,'instrument':s['instrument'],'bar':decision.get('bar'),'action':action,'position':position['id'] if position else None})
                    context=context or {'strategy':decision['strategy'],'initial_stop':prepared['stop_loss'],
                        'breakout_level':decision.get('evidence',{}).get('prior20_high' if side=='buy' else 'prior20_low'),
                        'giveback_checks':0,'peak_price_gain':0}
                    payload={'prepared':prepared,'context':context,'decision':decision}
                    if exit_reason:
                        payload.update(exit_reason=exit_reason, originating_order=entry['id'])
                    self.emit('execution_prepared',{'session':ident,'order':claim,'environment':s['environment'],'symbol':symbol,'action':action,'evidence':payload})
                    try:
                        with self.gateway.db() as db:
                            db.execute('INSERT INTO trading_orders VALUES(?,?,?,?,?,?,?,?,?,?,?)',(claim,ident,bot.session['adapter'],s['account'],s['instrument'],symbol,action,'prepared',json.dumps(payload,allow_nan=False),None,self.clock()))
                    except sqlite3.IntegrityError:
                        self.emit('execution_blocked', {'session':ident,'symbol':symbol,'environment':s['environment'],
                                  'bar':decision.get('bar'),'action':action,'reason':'Duplicate order or instrument claim'})
                        return
                    def guard():
                        latest=adapter.snapshot(symbol);self.validate_snapshot(latest,symbol,spec)
                        if bound:
                            confirmed = adapter.reconcile(entry)
                            if (confirmed['state'] != 'open'
                                or confirmed.get('position_identifier') != spec['position_identifier']
                                or confirmed['position_id'] != str(position['id'])
                                or confirmed['volume'] != position['quantity']):
                                raise PermissionError('Close target changed before delivery')
                        self.risk(self.session(ident),latest,prepared,action=action)
                        self.emit('execution_attempt',{'session':ident,'order':claim,'symbol':symbol,'environment':s['environment'],'action':action})
                        with self.gateway.db() as db:
                            db.execute('BEGIN IMMEDIATE')
                            self.pm.check_trading(self.gateway,ident,self.runtime_id,lease,action,consume=True,db=db)
                            payload['admission_hash']=hashlib.sha256(lease.encode()).hexdigest()
                            changed=db.execute("UPDATE trading_orders SET state='sending',payload=? WHERE id=? AND state='prepared'",(json.dumps(payload,allow_nan=False),claim)).rowcount
                            if changed!=1:raise PermissionError('Execution claim already consumed')
                        return {'environment':spec['environment'],'expires':self.session(ident)['expires']}
                    try:
                        result=adapter.submit(prepared,guard)
                        with self.gateway.db() as db:
                            if db.execute('SELECT state FROM trading_orders WHERE id=?',(claim,)).fetchone()[0]!='sending':raise PermissionError('Adapter did not consume Core delivery guard')
                        state=result.get('state')
                        if state not in ('submitted','rejected','unknown','partial'):raise ValueError('Unknown submission result')
                    except Exception as exc:
                        with self.gateway.db() as db:state=db.execute('SELECT state FROM trading_orders WHERE id=?',(claim,)).fetchone()[0]
                        state='unknown' if state=='sending' else 'rejected'
                        result={'state':state,'error_type':type(exc).__name__,'reason':str(exc)[:180]}
                    with self.gateway.db() as db:db.execute('UPDATE trading_orders SET state=?,result=?,updated=? WHERE id=?',(state,json.dumps(result,allow_nan=False),self.clock(),claim))
                    if state in ('unknown','partial'):
                        self.admission.finish(lease,uncertain=True);bot.quarantined_lease=lease;lease=None
                    self.emit('execution_result',{'session':ident,'order':claim,'symbol':symbol,'environment':s['environment'],'action':action,'result':result},alert=True)
                finally:
                    if lease:self.admission.finish(lease)
        except Exception as exc:
            bot.error=type(exc).__name__+': '+str(exc)[:180]
            try:self.emit('trading_error',{'session':bot.session.get('id'),'adapter':bot.session['adapter'],'symbol':bot.session['symbol'],'error':bot.error},alert=True)
            except Exception:pass  # failure to persist prevents delivery above


_install_lock=threading.RLock()

def install_core_trading(core):
    """Register the existing worker with Core; boot never activates execution."""
    with _install_lock:
        current=getattr(core,'core_trading_sessions',None)
        if current is not None:return current
        from modules.memory_laboratory.runtime import runtime_memory
        runtime=runtime_memory()
        if runtime is None:return None
        from modules.mt5_bridge import MT5Bridge
        from modules.mt5_orders import DemoOrders
        from modules.trading_desk import Desk,ROOT
        from modules.trading_session_adapters import MT5SessionAdapter,FreqtradeSessionAdapter
        # The packaged launcher already selects an explicit source environment.
        # Credentials remain in that authority, never in the release folder.
        selected=os.getenv('NIBLIT_ENV_FILE','')
        root=Path(selected).resolve().parent if selected else ROOT
        desk=Desk(root)
        bridge=MT5Bridge();orders=DemoOrders(bridge,desk.path.parent/'mt5-orders.sqlite3',autonomous_max_volume=.10)
        adapters={'mt5':MT5SessionAdapter(bridge,orders),'freqtrade':FreqtradeSessionAdapter(desk)}
        demo_profile=os.getenv('NIBLIT_MT5_DEMO_PROFILE',os.getenv('NIBLIT_EXNESS_DEMO_PROFILE','')).strip()
        if demo_profile:
            from modules.remote_demo_adapter import RemoteDemoAdapter
            adapters['exness_demo']=RemoteDemoAdapter(demo_profile)
        service=CoreTradingSessions(runtime,adapters,journal=desk.path.parent/'demo-learning.sqlite3')
        configured = json.loads(os.getenv('NIBLIT_MT5_KNOWN_ACCOUNTS', '[]'))
        service.configured_mt5_accounts = []
        for item in configured:
            login, server = str(item['login']), str(item['server'])
            mode = item['environment']
            if not login.isdigit() or not server or mode not in ('demo','live'):
                raise ValueError('Invalid configured MT5 account metadata')
            service.configured_mt5_accounts.append({
                'identity':hashlib.sha256(f'{server}:{login}'.encode()).hexdigest()[:16],
                'login':login, 'server':server, 'broker':str(item['broker']), 'environment':mode,
            })
        core.core_trading_sessions=service
        service.start_remote_observer()
        observers = json.loads(os.getenv('NIBLIT_CORE_TRADING_OBSERVE', '[]'))
        with service.gateway.db() as db:
            outstanding = db.execute(
                "SELECT DISTINCT adapter,symbol FROM trading_orders "
                "WHERE state IN ('sending','unknown','submitted','open','partial')"
            ).fetchall()
        for item in [*observers, *outstanding]:
            if item['adapter'] == 'mt5' and service.remote_gateway is not None:
                continue
            if item['adapter'] in service.adapters:
                service.observe(item['adapter'], item['symbol'])
        return service

