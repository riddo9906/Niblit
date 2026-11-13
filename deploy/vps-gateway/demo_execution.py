"""Exness demo transport for the existing Core adapter and durable DemoOrders.

No strategy, login, permission switch, automatic authorization or retry lives here.
The XM observer and its latched breaker use their original database and scope.
"""
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time

from broker import existing_terminal
from modules.mt5_bridge import MT5Bridge, LOCK
from modules.mt5_orders import DemoOrders, MAGIC
from modules.trading_session_adapters import MT5SessionAdapter
from modules.crypto_stops import policy as crypto_policy,levels as crypto_levels,RULES

VERSION = 'exness-demo/1'


def load_demo_config(path):
    cfg = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if set(cfg) != {'account', 'terminal', 'symbols'}:
        raise ValueError('Exact demo configuration required')
    a = cfg['account']
    if (set(a) != {'identity','login','server','broker','environment','terminal_id','terminal_path'}
            or a['environment'] != 'demo' or not str(a['login']).isdigit()
            or not ((a['server'].startswith('Exness-') and 'exness' in a['broker'].lower())
                    or (a['server'].startswith('XM') and 'xm' in a['broker'].lower())
                    or (a['server'].startswith('MetaQuotes-') and 'metaquotes' in a['broker'].lower()))
            or not re.fullmatch('[a-f0-9]{16}', a['identity'])
            or not re.fullmatch('[a-f0-9]{20}', a['terminal_id'])
            or not Path(cfg['terminal']).is_absolute()
            or Path(cfg['terminal']).name.lower() != 'terminal64.exe'
            or not Path(cfg['terminal']).is_file()
            or not cfg['symbols'] or len(cfg['symbols']) > 8
            or any(not re.fullmatch('[A-Za-z0-9._-]{1,40}', s) for s in cfg['symbols'])):
        raise ValueError('Pinned MT5 demo account required')
    return cfg


class BoundAPI:
    def __init__(self, api, bridge):
        self.api, self.bridge = api, bridge

    def __getattr__(self, name):
        # Deliberately no login/terminal permission APIs are exported by transport.
        if name in ('login',):
            raise PermissionError('Account switching forbidden')
        return getattr(self.api, name)

    def order_send(self, request):
        # This is the final SDK boundary, independent of Core's demo assertion.
        def permit():
            a,t=self.bridge.verify()
            if not a.trade_allowed or not t.trade_allowed or t.tradeapi_disabled:
                raise PermissionError('Terminal demo execution is disabled')
        permit()
        if (request.get('action') != self.api.TRADE_ACTION_DEAL
                or request.get('magic') != MAGIC or request.get('type') not in (0,1)
                or request.get('symbol') not in self.bridge.cfg['symbols']
                or type(request.get('volume')) not in (int,float)
                or not math.isfinite(request['volume']) or not 0 < request['volume'] <= self.bridge.max_volume):
            raise PermissionError('Only bounded demo entries/owned exits supported')
        if 'position' not in request and (not request.get('sl') or not request.get('tp')):
            raise PermissionError('Broker-side stop and target required')
        permit()
        return self.api.order_send(request)


class BoundBridge(MT5Bridge):
    def __init__(self, api, cfg, max_volume=.01):
        super().__init__()
        self.raw, self.cfg = api, cfg
        if type(max_volume) not in (int,float) or not math.isfinite(max_volume) or not 0<max_volume<=.10:
            raise ValueError("Demo volume ceiling must be finite and at most 0.10 lots")
        self.max_volume=max_volume
        self._api = BoundAPI(api, self)

    def verify(self):
        a, t = self.raw.account_info(), self.raw.terminal_info()
        if (a is None or t is None or not t.connected
                or a.trade_mode != self.raw.ACCOUNT_TRADE_MODE_DEMO
                or self.account_record(self.raw,a,t) != self.cfg['account']):
            raise PermissionError('Pinned MT5 demo account/terminal changed')
        return a,t

    def connect(self):
        existing_terminal(self.cfg['terminal'])
        if not self.raw.initialize(self.cfg['terminal'],timeout=5000):
            raise RuntimeError('MT5 IPC unavailable')
        a,t = self.verify()
        return self._api,a,t


class DemoService:
    def __init__(self, cfg, state, api, *, max_volume=.01):
        self.cfg, self.state = cfg, Path(state)
        self.state.mkdir(exist_ok=True)
        self.bridge = BoundBridge(api,cfg,max_volume)
        self.orders = DemoOrders(self.bridge,self.state/'demo-orders.sqlite3',price_drift_fraction=.0001,crypto_stops=True,autonomous_max_volume=max_volume)
        self.adapter = MT5SessionAdapter(self.bridge,self.orders)
        self.identity = hashlib.sha256(json.dumps(cfg,sort_keys=True).encode()).hexdigest()
        with self.orders.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS remote_demo_meta(id INTEGER PRIMARY KEY, binding TEXT, stopped INTEGER)')
            db.execute('INSERT OR IGNORE INTO remote_demo_meta VALUES(1,?,0)',(self.identity,))
            if db.execute('SELECT binding FROM remote_demo_meta').fetchone()[0] != self.identity:
                raise PermissionError('Demo database belongs to another binding')
            db.execute('CREATE TABLE IF NOT EXISTS remote_demo_prepared(ticket TEXT PRIMARY KEY, payload TEXT)')
            # Restart never turns a previously prepared ticket into authority.
            db.execute("UPDATE mt5_tickets SET state='rejected',result=? WHERE state='preview'",
                       (json.dumps({'message':'Gateway restarted before delivery; fresh Core review required'}),))

    def enabled(self):
        with self.orders.db() as db:
            if db.execute('SELECT stopped FROM remote_demo_meta').fetchone()[0]:
                raise PermissionError('Persistent demo emergency stop active; no automatic reset')

    def symbol(self, value):
        if value not in self.cfg['symbols']:
            raise PermissionError('Symbol outside pinned demo scope')
        api,_,_ = self.bridge.connect()
        info = api.symbol_info(value)
        if info is None or not info.currency_base or not info.currency_profit:
            raise PermissionError('Verified broker symbol currencies required')
        # Market Watch subscription only; never toggles execution or account.
        if not info.visible and not api.symbol_select(value,True):
            raise ValueError('Broker symbol subscription unavailable')
        return value

    def dispatch(self, action, body):
        # One shared lock spans prepare/confirm and all local SDK identity checks.
        with LOCK:
            if action == 'emergency-stop':
                with self.orders.db() as db:
                    db.execute('UPDATE remote_demo_meta SET stopped=1')
                return {'stopped':True,'positions_closed':False}
            self.bridge.connect()
            if action == 'status':
                with self.orders.db() as db:
                    stopped=bool(db.execute('SELECT stopped FROM remote_demo_meta').fetchone()[0])
                    uncertain=db.execute("SELECT COUNT(*) FROM mt5_tickets WHERE state IN ('sending','unknown','placed','partial')").fetchone()[0]
                a,t = self.bridge.verify()
                return {'schema_version':VERSION,'gateway_id':self.identity,'account':self.cfg['account'],
                        'observed_at':time.time(),'symbols':self.cfg['symbols'],'balance':a.balance,'equity':a.equity,
                        'margin':a.margin,'free_margin':a.margin_free,'terminal_trade_allowed':t.trade_allowed,
                        'python_tradeapi_disabled':t.tradeapi_disabled,'account_trade_allowed':a.trade_allowed,
                        'emergency_stopped':stopped,'unresolved_deliveries':uncertain,
                        'max_volume':self.bridge.max_volume,'review_price_drift_fraction':.0001,
                        'protection_policy':crypto_policy(),
                        'funded_execution_enabled':False,'execution_at_startup':False}
            if action == 'market':
                symbol=self.symbol(body['symbol'])
                market=self.bridge.snapshot(symbol,include_context=True)
                market['demo_volume_ceiling']=self.bridge.max_volume
                market['protection_policy']=crypto_policy()
                try:
                    if not market['quote'].get('fresh'):raise ValueError('Fresh quote required')
                    market['protection_preview']={'status':'available','strategy':'crypto_default',
                        **{side:crypto_levels(market['candles'][-64:],market['specification'],market['quote'],side)
                           for side in ('buy','sell')}}
                    api,account,_=self.bridge.connect()
                    volume=market['specification']['volume_min']
                    for side in ('buy','sell'):
                        plan=market['protection_preview'][side]
                        risk=api.order_calc_profit(api.ORDER_TYPE_BUY if side=='buy' else api.ORDER_TYPE_SELL,
                            symbol,volume,plan['reviewed_entry'],plan['stop_loss'])
                        plan.update(broker_minimum_volume=volume,account_currency=account.currency,
                            estimated_stop_loss_at_minimum_volume=abs(risk) if type(risk) in (int,float) and math.isfinite(risk) else None,
                            minimum_volume_within_niblit_cap=volume<=self.bridge.max_volume,
                            cost_basis='broker_profit_calculation_before_unknown_commission_financing_slippage')
                except (ValueError,TypeError,KeyError,IndexError):
                    market['protection_preview']={'status':'unavailable','reason':'verified_closed_history_and_quote_required'}
                return market
            if action == 'snapshot':
                return {**self.adapter.snapshot(self.symbol(body['symbol'])),'protection_policy':crypto_policy()}
            if action == 'identity':
                return self.adapter.reconciliation_identity()
            if action == 'prepare':
                self.enabled()
                with self.orders.db() as db:
                    if db.execute("SELECT 1 FROM mt5_tickets WHERE state='partial' LIMIT 1").fetchone():
                        raise PermissionError('Partial demo delivery requires explicit reconciliation')
                symbol=self.symbol(body['symbol'])
                snapshot=self.adapter.snapshot(symbol)
                strategy=body.get('strategy') or 'crypto_default'
                if strategy not in RULES:raise PermissionError('Known crypto strategy required')
                snapshot['entry_strategy']=strategy
                if snapshot['account_binding'] != self.cfg['account']:
                    raise PermissionError('Demo binding mismatch')
                limits=body['limits']
                ceilings={'risk_fraction':.0025,'risk_cash':25,'max_volume':self.bridge.max_volume,
                          'max_margin_fraction':.1,'max_exposure_fraction':1,
                          'max_open_risk_fraction':.02,'max_daily_loss':.03,
                          'max_drawdown':.02,'max_session_loss':.02,'max_positions':5,'max_entries':3}
                if set(limits) != set(ceilings) or any(type(v) not in (int,float) or not math.isfinite(v)
                      or not 0<v<=ceilings[k] for k,v in limits.items()):
                    raise PermissionError('Demo risk ceiling exceeded')
                if body['side'] not in ('buy','sell'):
                    raise ValueError('Invalid side')
                position=body.get('position')
                if position is not None:
                    # Caller must identify a current position; DemoOrders further
                    # requires its original magic, exact volume and symbol.
                    matches=[p for p in snapshot['positions'] if p['id']==position.get('id')]
                    if len(matches)!=1:raise PermissionError('Owned position unavailable')
                    position=matches[0]
                prepared=self.adapter.prepare(snapshot,body['side'],limits,position)
                with self.orders.db() as db:
                    db.execute('INSERT INTO remote_demo_prepared VALUES(?,?)',
                               (prepared['ticket'],json.dumps(prepared,allow_nan=False)))
                return prepared
            if action == 'submit':
                self.enabled()
                expires=body['expires']
                if type(expires) not in (int,float) or not math.isfinite(expires) or not time.time()<expires<=time.time()+3600:
                    raise PermissionError('Core demo scope expired')
                with self.orders.db() as db:
                    row=db.execute('SELECT payload FROM remote_demo_prepared WHERE ticket=?',(body['ticket'],)).fetchone()
                if row is None:raise PermissionError('No durable prepared demo ticket')
                prepared=json.loads(row[0])
                def guard():
                    self.enabled();self.bridge.verify()
                    if time.time()>=expires:raise PermissionError('Demo scope expired before delivery')
                try:
                    return self.adapter.submit(prepared,guard)
                except (ValueError,PermissionError) as exc:
                    # Only a durable PREVIEW proves external delivery never began.
                    # SENDING/UNKNOWN must remain uncertain and cannot be retried.
                    reasons={
                        'Price moved outside the review range; review again':'price_moved_outside_review',
                        'Risk changed; review again':'stop_risk_changed',
                        'Review expired; refresh and review again':'review_expired',
                    }
                    code=reasons.get(str(exc),'final_demo_preflight_rejected')
                    with self.orders.db() as db:
                        db.execute('BEGIN IMMEDIATE')
                        changed=db.execute("UPDATE mt5_tickets SET state='rejected',result=? WHERE id=? AND state='preview'",
                             (json.dumps({'reason_code':code,'delivery_began':False}),body['ticket'])).rowcount
                    if changed:
                        return {'state':'rejected','ticket':body['ticket'],
                                'broker':{'reason_code':code,'delivery_began':False}}
                    raise
            if action in ('reconcile','cancel-prepared'):
                # Use server-owned prepared body, not a caller's broker request.
                order=body['order'];ticket=json.loads(order['payload'])['prepared']['ticket']
                with self.orders.db() as db:
                    row=db.execute('SELECT payload FROM remote_demo_prepared WHERE ticket=?',(ticket,)).fetchone()
                if row is None:return {'state':'unknown','reason':'No durable demo ticket'}
                if order['account'] != self.cfg['account']['identity']:
                    raise PermissionError('Wrong reconciliation account')
                order={**order,'payload':json.dumps({'prepared':json.loads(row[0])})}
                return self.adapter.reconcile(order) if action=='reconcile' else self.adapter.cancel_prepared(order)
            raise ValueError('Unsupported demo operation')
