"""Bounded MT5 demo sessions using durable order tickets and a decision journal.

Start or Observe enables a worker; restart never rearms execution. The same worker
monitors positions and generates explanations without an LLM. Stop prevents new
work, but cannot recall an order already being delivered or close positions.
"""
from datetime import datetime, timezone, timedelta
import json
import math
import sqlite3
import threading
import time
import uuid

from modules.demo_strategy import STRATEGIES, EVENT_LESSONS, evaluate, risk_budget, position_volume
from modules.mt5_bridge import LOCK
from modules.mt5_orders import MAGIC
from modules.strategy_manager import assess
from modules.strategy_research import study


class DemoAutotrader:
    def __init__(self, bridge, orders, path, outcome_sink=None, events=None):
        self.bridge, self.orders, self.path = bridge, orders, str(path)
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.worker = None
        self.session = None
        self.error = None
        self.outcome_sink = outcome_sink
        self.events = events
        self.manager = None
        self.research = None
        self.research_key = None
        from modules.online_market_study import OnlineMarketStudy
        from pathlib import Path
        self.online_study=OnlineMarketStudy(Path(self.path).parent/'online-market-study.sqlite3')
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS decisions(id TEXT PRIMARY KEY, ts REAL, payload TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS demo_outcomes(id TEXT PRIMARY KEY, payload TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS opportunities(id TEXT PRIMARY KEY, created REAL, expires REAL, payload TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS research_reports(id TEXT PRIMARY KEY, created REAL, payload TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS forecast_outcomes(id TEXT PRIMARY KEY, payload TEXT)')

    def db(self):
        return sqlite3.connect(self.path, timeout=10)

    def record(self, payload):
        with self.db() as db:
            db.execute('INSERT INTO decisions VALUES(?,?,?)', (uuid.uuid4().hex, time.time(), json.dumps(payload)))

    def start(self, symbol, strategy, minutes=30, max_entries=3, observe_only=False):
        if strategy not in {*STRATEGIES, 'auto'} or not 1 <= minutes <= 60 or not 1 <= max_entries <= 10:
            raise ValueError('Choose a known strategy, 1–60 minutes and 1–10 entries')
        with self.lock:
            alive = bool(self.worker and self.worker.is_alive())
            if alive and (self.stop_event.is_set() or self.session.get('state')!='observing'):
                raise ValueError('A session is already running or stopping')
            s = self.bridge.snapshot(symbol)
            if s['account']['mode'] != 'demo' or (not observe_only and not s['capabilities']['order_submission']):
                raise ValueError('Connect an execution-enabled MT5 demo account')
            if not observe_only and (s['positions'] or s['pending_order_count']):
                raise ValueError('Start with no positions or pending orders')
            equity = s['account']['equity']
            risk_budget(equity)
            self.session = {'id':uuid.uuid4().hex, 'symbol':symbol, 'strategy':strategy,
                'account':s['account']['identity'], 'initial_equity':equity, 'peak_equity':equity,
                'until':time.time() if observe_only else time.time()+minutes*60, 'max_entries':max_entries, 'entries':0,
                'last_bar':None, 'started':time.time(), 'state':'observing' if observe_only else 'running', 'held_strategy':None}
            self.record({'type':'observation_started' if observe_only else 'session_started', **self.session})
            self.stop_event.clear()
            self.error = None
            if not alive:
                self.worker = threading.Thread(target=self.run, name='niblit-demo-trader', daemon=True)
                self.worker.start()
            return self.status()

    def stop(self):
        self.stop_event.set()
        return {'state':'stop_requested', 'notice':'No new cycles. In-flight delivery may finish; broker stops remain active. Existing positions are not closed.'}

    def run(self):
        try:
            while not self.stop_event.is_set():
                if self.events:
                    self.events.refresh()
                if self.stop_event.is_set():
                    break
                self.step()
                if self.stop_event.wait(15):
                    break
        except Exception as exc:
            self.error = type(exc).__name__ + ': ' + str(exc)
            self.record({'type':'session_error', 'message':self.error})
        finally:
            if self.session:
                self.session['state'] = 'stopped'

    def outcomes(self, s):
        """Record complete broker positions, including entry/exit commissions.

        Ledger is account-scoped and idempotent. External/manual positions and
        open partial exits never become completed strategy samples.
        """
        api, account, _ = self.bridge.connect()
        if self.bridge.identity(account) != self.session['account']:
            raise ValueError('Account changed')
        deals = api.history_deals_get(datetime.now(timezone.utc)-timedelta(days=7),
                                      datetime.now(timezone.utc)+timedelta(days=1))
        if deals is None:
            raise ValueError('Broker outcome history unavailable')
        groups = {}
        for d in deals:
            if d.magic == MAGIC:
                groups.setdefault(d.position_id, []).append(d)
        open_ids = {p['ticket'] for p in s['positions']}
        with self.db() as db:
            history = [json.loads(r[0]) for r in db.execute('SELECT payload FROM decisions')]
            deliveries = {r['ticket']:r['result'].get('result',{}).get('order') for r in history if r.get('type')=='delivery'}
            for position, group in groups.items():
                if position in open_ids or not any(d.entry == 1 for d in group) or not any(d.entry == 0 for d in group):
                    continue
                net = sum(d.profit+d.commission+d.swap+getattr(d,'fee',0) for d in group)
                entry_orders = {d.order for d in group if d.entry==0}
                linked = next((r for r in history if r.get('type')=='decision' and r.get('action')=='open'
                               and deliveries.get(r.get('ticket')) in entry_orders and r.get('account')==self.session['account']), None)
                if linked is None:
                    continue
                body = {'mode':'demo','account':self.session['account'],'position':position,
                        'net':net,'currency':s['account']['currency'],
                        'source':'mt5_broker_deals','strategy':linked['strategy'], 'ticket':linked['ticket'],
                        'symbol':linked['symbol'],'decision_evidence':linked['evidence']}
                exit_event=next((r for r in reversed(history) if r.get('type')=='adaptive_exit'
                    and r.get('position')==position and r.get('account')==self.session['account']),None)
                body['adaptive_exit']=exit_event.get('exit_report') if exit_event else None
                body['exit_learning_limit']='Realized net outcome only; no claim about profit or loss an alternative exit would have produced.'
                db.execute('INSERT OR IGNORE INTO demo_outcomes VALUES(?,?)',
                           (self.session['account']+':'+str(position), json.dumps(body)))
                if self.outcome_sink:
                    self.outcome_sink(self.session['account']+':'+str(position), body)

    def step(self):
        # Start/rearm and each scan share a lock, so old and new sessions cannot
        # race to deliver an order. Broker LOCK still serializes manual controls.
        with self.lock:
            self._step()

    def _step(self):
        c = self.session
        expired = time.time() >= c['until']
        if expired and c.get('state')!='observing':
            c['state']='observing'
            self.record({'type':'session_expired','session':c['id'],
                         'reason':'Execution window ended; strategy observation continues without orders.'})
        with LOCK:
            s = self.bridge.snapshot(c['symbol'])
            a = s['account']
            if a['mode'] != 'demo' or a['identity'] != c['account']:
                raise ValueError('Demo account identity changed; session stopped')
            self.outcomes(s)
            equity = a['equity']
            risk_budget(equity)
            c['peak_equity'] = max(c['peak_equity'], equity)
            loss_halt = equity <= c['initial_equity']*.98 or equity <= c['peak_equity']*.98
            if loss_halt:
                if c.get('state')!='observing':
                    self.record({'type':'risk_halt','session':c['id'],'reason':'2% session loss/drawdown limit reached; observation only.'})
                c['state']='observing'
                c['risk_halted']=True
            positions = s['positions']
            owned = [p for p in positions if p['magic']==MAGIC and p['symbol']==c['symbol']]
            held = c.get('held_strategy') if owned else None
            # Never let a newly selected rule take over pre-existing/manual exposure.
            unknown_owner = bool(owned and not held and c['strategy']=='auto')
            decision = assess(s['candles'], c['strategy'], held_strategy=held)
            decision.update(type='decision', session=c['id'], account=c['account'], mode='demo',
                            symbol=c['symbol'], risk_budget=risk_budget(equity))
            decision['research_context'] = self.events.context() if self.events else []
            decision['research_use'] = 'Known source context logged for later study; not used as a directional signal.'
            quote = s.get('quote') or {}
            bar = decision.get('bar')
            fresh = bool(quote.get('fresh') and bar is not None and 300 <= quote.get('timestamp',0)-bar <= 620)
            research_key=(c['account'],c['symbol'],bar)
            if fresh and research_key!=self.research_key:
                midpoint=(quote['ask']+quote['bid'])/2
                self.research={**study(s['candles'],(quote['ask']-quote['bid'])/midpoint,
                                     generate=decision['side']=='wait'),
                               'account':c['account'],'symbol':c['symbol'],'mode':'demo_research',
                               'available_at':time.time(),'broker_clock':'unverified; bar timestamp is broker time'}
                self.research['online_comparer']=self.online_study.observe(
                    json.dumps(['mt5',c['account'],c['symbol'],'demo','M5']),s['candles'],
                    market_time=quote.get('timestamp',0),fresh=fresh)
                with self.db() as db:
                    available={r['timestamp']:r['close'] for r in s['candles']}
                    # Score only prior saved predictions whose target bar has
                    # since completed. No hindsight replacement of a forecast.
                    prior=db.execute('SELECT id,payload FROM research_reports ORDER BY created DESC LIMIT 500').fetchall()
                    for identity,encoded in prior:
                        report=json.loads(encoded)
                        if report.get('account')!=c['account'] or report.get('symbol')!=c['symbol'] or not report.get('forecast'):
                            continue
                        target=report['bar']+300
                        if target not in available: continue
                        realized=available[target]/report['reference_close']-1
                        forecast=report['forecast']['expected_return']
                        outcome={'account':c['account'],'symbol':c['symbol'],'mode':'demo_research',
                                 'forecast_bar':report['bar'],'target_bar':target,'recorded_at':time.time(),
                                 'predicted_return':forecast,'realized_return':realized,
                                 'absolute_error':abs(forecast-realized),
                                 'direction_correct':(forecast>0)==(realized>0),
                                 'notice':'Prediction score, not trade profit.'}
                        db.execute('INSERT OR IGNORE INTO forecast_outcomes VALUES(?,?)',(identity,json.dumps(outcome)))
                    db.execute('INSERT OR IGNORE INTO research_reports VALUES(?,?,?)',
                               (json.dumps(research_key),time.time(),json.dumps(self.research)))
                self.research_key=research_key
            self.manager = {**decision,'checked_at':time.time(),'execution_active':c.get('state')=='running' and not expired,
                            'risk_checks':{'demo_account':True,'same_account':True,
                                'fresh_market':fresh,'within_drawdown':not loss_halt,
                                'entry_capacity':c['entries']<c['max_entries'],
                                'no_unowned_exposure':not unknown_owner and not any(p not in owned for p in positions),
                                'broker_size_margin_stop':'Checked again by broker preflight only for an eligible order'}}
            # Quote profit protection runs on each sequential observer cycle,
            # independently of the once-per-completed-bar entry gate below.
            if owned and c.get('state')=='running' and not expired and fresh:
                from modules.position_exit_policy import assess_exit
                position=owned[0]
                context=c.get('exit_context') if c.get('exit_position') in (None,position['ticket']) else None
                if context:
                    c['exit_position']=position['ticket']
                exit_report=assess_exit(position,s['candles'],quote,context)
                self.manager['position_exit']=exit_report
                if exit_report['action']=='close' and c.get('exit_sent')!=position['ticket']:
                    body={'action':'close','symbol':c['symbol'],'side':'sell' if position['type']==0 else 'buy',
                          'volume':position['volume'],'account_identity':c['account'],'position_ticket':position['ticket']}
                    ticket=self.orders.preview(body)
                    self.record({'type':'adaptive_exit','session':c['id'],'position':position['ticket'],
                                 'account':c['account'],'strategy':context['strategy'],
                                 'ticket':ticket['ticket'],'exit_report':exit_report})
                    if self.stop_event.is_set():return
                    c['exit_sent']=position['ticket']
                    result=self.orders.confirm(ticket['ticket'])
                    self.record({'type':'adaptive_exit_delivery','session':c['id'],'ticket':ticket['ticket'],'result':result})
                    if result['state']=='filled':
                        c['exit_sent']=position['ticket'];c['held_strategy']=None
                    elif result['state']!='rejected':
                        raise ValueError('Unresolved adaptive exit; reconcile manually')
                    c['last_bar']=bar
                    return
            if c.get('state')=='observing' and fresh and not loss_halt and not positions and not s['pending_order_count'] and decision['side'] in ('buy','sell'):
                try:
                    body = self.entry_body(s, decision['side'])
                    review = self.orders.inspect(body)
                    if review['estimated_stop_risk'] is None or review['estimated_stop_risk']>risk_budget(equity):
                        raise ValueError('Preflight exceeds current risk budget')
                    self.manager['risk_checks']['broker_size_margin_stop']='Passed non-delivering broker preflight'
                    key=f"{c['account']}:{c['symbol']}:{bar}:{decision['strategy']}:{decision['side']}"
                    now=time.time()
                    payload={'id':key,'symbol':c['symbol'],'strategy':decision['strategy'],'side':decision['side'],
                             'reason':decision['selection_reason'],'review':review,'created_at':now,
                             'expires_at':now+120,'question':'Start a bounded demo session?',
                             'notice':'Conditions and preflight passed at this time; profitability is unproven. Recheck before execution.'}
                    with self.db() as db:
                        db.execute('INSERT OR IGNORE INTO opportunities VALUES(?,?,?,?)',(key,now,now+120,json.dumps(payload)))
                except ValueError as exc:
                    self.manager['risk_checks']['broker_size_margin_stop']=str(exc)
            if bar is None or bar == c['last_bar']:
                return
            c['last_bar'] = bar
            if c.get('state')!='running' or expired:
                self.record({**decision,'blocked':'Observation only: execution expired or risk halted'})
                return
            # Require the latest completed bar relative to the broker's own clock.
            if not fresh:
                self.record({**decision,'blocked':'Stale tick or completed candle'})
                return
            if unknown_owner:
                self.record({**decision,'blocked':'Position entry strategy is unknown; manual management required'})
                return
            side = decision['side']
            action, position = 'open', None
            if owned and side in ('buy','sell'):
                position = owned[0]
                if (position['type']==0) == (side=='buy'):
                    self.record({**decision,'blocked':'Holding matching direction'})
                    return
                action = 'close'
            elif positions or s['pending_order_count'] or side=='wait' or c['entries']>=c['max_entries']:
                self.record({**decision,'blocked':'Wait, exposure, pending order or session entry limit'})
                return
            body = {'action':action,'symbol':c['symbol'],'side':side,'volume':position['volume'] if position else .01,
                    'account_identity':c['account'],'position_ticket':position['ticket'] if position else None}
            if action=='open':
                try: body=self.entry_body(s,side)
                except ValueError as exc:
                    self.record({**decision,'blocked':str(exc)})
                    return
            p = self.orders.preview(body)
            risk = p['review']['estimated_stop_risk']
            if action=='open' and (risk is None or not math.isfinite(risk) or risk>risk_budget(equity)):
                self.record({**decision,'blocked':'Minimum demo size exceeds 0.25% equity / 25 currency risk budget'})
                return
            # Decision and ticket are durable before sending. A crash never rearms.
            self.record({**decision,'action':action,'ticket':p['ticket'],'review':p['review']})
            if self.stop_event.is_set():
                return
            result = self.orders.confirm(p['ticket'])
            self.record({'type':'delivery','session':c['id'],'ticket':p['ticket'],'result':result})
            if action=='open':
                c['entries'] += 1
                if result['state']=='filled':
                    c['held_strategy']=decision['strategy']
                    entry_side=1 if side=='buy' else -1
                    c['exit_context']={'strategy':decision['strategy'],'initial_stop':p['review'].get('stop_loss'),
                        'breakout_level':max(r['high'] for r in s['candles'][-21:-1]) if entry_side==1 else min(r['low'] for r in s['candles'][-21:-1]),
                        'peak_price_gain':0.,'giveback_checks':0}
                    c['exit_position']=None;c['exit_sent']=None
            elif result['state']=='filled':
                c['held_strategy']=None
            if result['state'] not in ('filled','rejected'):
                raise ValueError('Unresolved or partial delivery; reconcile manually before restarting')

    def entry_body(self, snapshot, side):
        """The same sizing/spread policy serves alerts and execution candidates."""
        c=self.session
        api, _, _=self.bridge.connect()
        info=api.symbol_info(c['symbol'])
        quote=snapshot['quote']
        price=quote['ask'] if side=='buy' else quote['bid']
        distance=max(info.point*200,(info.trade_stops_level+10)*info.point)
        stop=round(price-distance if side=='buy' else price+distance,info.digits)
        estimate=api.order_calc_profit(api.ORDER_TYPE_BUY if side=='buy' else api.ORDER_TYPE_SELL,c['symbol'],.01,price,stop)
        if estimate is None: raise ValueError('Broker risk estimate unavailable')
        equity=snapshot['account']['equity']
        volume=position_volume(equity,abs(estimate),info.volume_min,info.volume_step)
        if volume is None: raise ValueError('Broker minimum size exceeds risk budget')
        if quote['ask']-quote['bid']>distance*.2: raise ValueError('Spread exceeds 20% of stop distance')
        return {'action':'open','symbol':c['symbol'],'side':side,'volume':volume,
                'account_identity':c['account'],'position_ticket':None,'max_stop_risk':risk_budget(equity)}

    def status(self):
        with self.db() as db:
            decisions = [{'at':r[0], **json.loads(r[1])} for r in db.execute('SELECT ts,payload FROM decisions ORDER BY ts DESC LIMIT 40')]
            outcomes = [json.loads(r[0]) for r in db.execute('SELECT payload FROM demo_outcomes ORDER BY rowid DESC LIMIT 40')]
            all_outcomes = [json.loads(r[0]) for r in db.execute('SELECT payload FROM demo_outcomes')]
            forecast_outcomes=[json.loads(r[0]) for r in db.execute('SELECT payload FROM forecast_outcomes ORDER BY rowid DESC LIMIT 40')]
            opportunities=[json.loads(r[0]) for r in db.execute('SELECT payload FROM opportunities WHERE expires>? ORDER BY created DESC LIMIT 5',(time.time(),))]
        if not self.manager or time.time()-self.manager['checked_at']>30 or not self.worker or not self.worker.is_alive() or self.session.get('state')!='observing':
            opportunities=[]
        else:
            # An alert is actionable only while the latest scan still agrees and
            # the latest non-delivering broker check passed. Cached alerts cannot
            # remain actionable after market or risk conditions change.
            valid=self.manager['risk_checks']['broker_size_margin_stop']=='Passed non-delivering broker preflight'
            opportunities=[o for o in opportunities if valid and o['strategy']==self.manager['strategy'] and o['side']==self.manager['side'] and o['symbol']==self.session['symbol']]
        performance = []
        for strategy in STRATEGIES:
            groups = {(o['account'], o['symbol'], o['currency']) for o in all_outcomes if o['strategy']==strategy}
            for account, symbol, currency in sorted(groups):
                sample = [o['net'] for o in all_outcomes if o['strategy']==strategy and
                          (o['account'],o['symbol'],o['currency'])==(account,symbol,currency)]
                performance.append({'strategy':strategy,'account':account,'symbol':symbol,'currency':currency,
                    'closed_trades':len(sample),'net':sum(sample),'mean_net':sum(sample)/len(sample),
                    'win_rate':sum(x>0 for x in sample)/len(sample),
                    'assessment':'Descriptive demo evidence only; no out-of-sample profitability validation or automatic promotion.'})
        return {'running':bool(self.worker and self.worker.is_alive()),'session':self.session,
                'manager':self.manager,
                'opportunities':opportunities,
                'research':self.research,
                'forecast_outcomes':forecast_outcomes,
                'execution_active':bool(self.worker and self.worker.is_alive() and self.session and self.session.get('state')=='running' and time.time()<self.session['until']),
                'error':self.error,'strategies':STRATEGIES,'decisions':decisions,'outcomes':outcomes,
                'market_lessons':EVENT_LESSONS,'performance':performance,'funded_execution_enabled':False,
                'learning':'Persistent decisions and broker outcomes; no automatic model training or strategy promotion.',
                'risk_policy':'0.25% equity risk capped at 25 currency units; 0.01 lot ceiling; 2% session drawdown stop.'}
