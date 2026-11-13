"""Human-only demo order tickets. No live-account or automatic retry path."""
from contextlib import contextmanager
import json
import math
from pathlib import Path
import secrets
import sqlite3
import time

from modules.mt5_bridge import LOCK, MT5Unavailable

MAGIC = 29102026


class DemoOrders:
    def __init__(self, bridge, path, *, price_drift_fraction=0.,crypto_stops=False,autonomous_max_volume=.01):
        if type(autonomous_max_volume) not in (int,float) or not math.isfinite(autonomous_max_volume) or not 0<autonomous_max_volume<=.10:
            raise ValueError("Autonomous demo volume ceiling must be finite and at most 0.10 lots")
        self.autonomous_max_volume=autonomous_max_volume
        self.bridge = bridge
        if type(price_drift_fraction) not in (int,float) or not math.isfinite(price_drift_fraction) or not 0<=price_drift_fraction<=.0001:
            raise ValueError('Demo review drift must be finite and at most one basis point')
        self.price_drift_fraction=price_drift_fraction
        if type(crypto_stops) is not bool:raise ValueError('Explicit crypto protection mode required')
        self.crypto_stops=crypto_stops
        self.path = Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS mt5_tickets(id TEXT PRIMARY KEY, created REAL, state TEXT, body TEXT, result TEXT)')

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def build(self, body, key, *, approved_protection=None,core_owned=False):
        api,account,terminal=self.bridge.connect()
        if account.trade_mode!=api.ACCOUNT_TRADE_MODE_DEMO:
            raise ValueError('Only demo accounts may submit orders')
        if self.bridge.identity(account)!=body['account_identity']:
            raise ValueError('MT5 account changed; refresh and review again')
        if not account.trade_allowed or not terminal.trade_allowed or terminal.tradeapi_disabled:
            raise ValueError('MT5 or broker trading permission is disabled')
        symbol=body['symbol']; volume=body['volume']
        info=api.symbol_info(symbol)
        if info is None or not info.visible: raise ValueError('Select a visible broker symbol')
        if type(volume) not in (int,float) or not math.isfinite(volume) or not 0<volume<=(self.autonomous_max_volume if core_owned else .01):
            raise ValueError('Volume exceeds the reviewed demo execution ceiling')
        if not info.volume_min<=volume<=info.volume_max or info.volume_step<=0 or abs((volume-info.volume_min)/info.volume_step-round((volume-info.volume_min)/info.volume_step))>1e-6:
            raise ValueError('Volume does not match broker constraints')
        tick=self.bridge.tick(api,symbol,account)
        if not tick['fresh'] or tick['age_seconds']>15:
            raise ValueError('Wait for a recently advancing broker quote, then refresh')
        positions=api.positions_get()
        if positions is None: raise MT5Unavailable('Cannot verify current positions')
        side=body['side']
        if body['action']=='close':
            position=next((p for p in positions if p.ticket==body.get('position_ticket') and p.symbol==symbol and p.magic==MAGIC),None)
            if position is None or abs(position.volume-volume)>1e-8:
                raise ValueError('Only the exact current Niblit test position may be closed')
            side='sell' if position.type==api.ORDER_TYPE_BUY else 'buy'
        else:
            if any(p.symbol==symbol or p.magic==MAGIC for p in positions):
                raise ValueError('Close the existing Niblit test position before another entry; existing symbol exposure is blocked')
            pending=api.orders_get()
            if pending is None or any(o.symbol==symbol or o.magic==MAGIC for o in pending):
                raise ValueError('Pending order state prevents another entry')
        order_type=api.ORDER_TYPE_BUY if side=='buy' else api.ORDER_TYPE_SELL
        price=tick['ask'] if side=='buy' else tick['bid']
        filling=api.ORDER_FILLING_FOK if info.filling_mode&1 else api.ORDER_FILLING_IOC if info.filling_mode&2 else api.ORDER_FILLING_RETURN
        request={'action':api.TRADE_ACTION_DEAL,'symbol':symbol,'volume':volume,'type':order_type,
            'price':price,'deviation':20,'magic':MAGIC,'comment':'niblit_'+key[:12],
            'type_time':api.ORDER_TIME_GTC,'type_filling':filling}
        risk=None;protection=None
        if body['action']=='close': request['position']=body['position_ticket']
        else:
            if self.crypto_stops and info.currency_base in ('BTC','ETH'):
                from modules.crypto_stops import from_mt5,fixed_levels,SPEC_FIELDS
                protection=(fixed_levels(approved_protection,{k:getattr(info,k,None) for k in SPEC_FIELDS},tick,side)
                     if approved_protection is not None else
                     from_mt5(api,symbol,info,tick,side,body.get('strategy') or 'crypto_default'))
                request['sl']=protection['stop_loss'];request['tp']=protection['take_profit']
            else:
                distance=max(200,int(info.trade_stops_level)+math.ceil((tick['ask']-tick['bid'])/info.point)+2)*info.point
                request['sl']=round(price-distance if side=='buy' else price+distance,info.digits)
                request['tp']=round(price+2*distance if side=='buy' else price-2*distance,info.digits)
            profit=api.order_calc_profit(order_type,symbol,volume,price,request['sl'])
            if profit is None or not math.isfinite(profit): raise ValueError('Broker risk calculation unavailable')
            risk=abs(profit)
            if risk>min(25,account.equity*.01): raise ValueError('Stop-loss risk exceeds the demo test limit')
            # The automatic controller supplies its stricter equity budget. It
            # must survive both preview and confirm's final broker rebuild.
            if 'max_stop_risk' in body:
                limit=body['max_stop_risk']
                if not isinstance(limit,(float,int)) or not math.isfinite(limit) or limit<=0 or risk>min(limit,account.equity*.0025):
                    raise ValueError('Automatic demo risk budget changed or exceeded')
        check=api.order_check(request)
        if check is None or check.retcode!=0:
            raise ValueError('Broker rejected preflight'+(f' (code {check.retcode}): {check.comment}' if check else ''))
        if body['action']!='close' and check.margin>account.equity*.1:
            raise ValueError('Margin exceeds 10% of demo equity')
        return api,request,{'mode':'demo','server':account.server,'currency':account.currency,
            'symbol':symbol,'side':side,'volume':volume,'action':body['action'],
            'price':price,'stop_loss':request.get('sl'),'take_profit':request.get('tp'),
            'estimated_stop_risk':risk,'margin_after':check.margin,
            'crypto_protection_required':self.crypto_stops and info.currency_base in ('BTC','ETH'),
            'account_identity':body['account_identity'],'account_binding':self.bridge.account_record(api,account,terminal),'point':info.point,
            'max_review_price_drift':max(20*info.point,abs(price)*self.price_drift_fraction),
            'protection':protection}

    def inspect(self, body, *, core_owned=False):
        """Non-delivering broker preflight for opportunity alerts; no ticket created."""
        with LOCK,self.db() as db:
            if db.execute("SELECT 1 FROM mt5_tickets WHERE state IN ('sending','unknown','placed') LIMIT 1").fetchone():
                raise ValueError('An order delivery is unresolved')
            _,_,review=self.build(body,'observeonly',core_owned=core_owned)
            return review

    def preview(self, body, core_owned=False):
        with LOCK,self.db() as db:
            if db.execute("SELECT 1 FROM mt5_tickets WHERE state IN ('sending','unknown','placed') LIMIT 1").fetchone():
                raise ValueError('A delivery is unresolved; reconcile before another order')
            key=secrets.token_hex(16)
            _,request,review=self.build(body,key,core_owned=core_owned)
            db.execute('INSERT INTO mt5_tickets VALUES(?,?,?,?,?)',
                (key,time.time(),'preview',json.dumps({'intent':body,'request':request,'review':review,**({'core_owned':True} if core_owned else {})}),None))
            return {'ticket':key,'review':review,'expires_in':30}

    def confirm(self, key, guard=None):
        with LOCK,self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM mt5_tickets WHERE id=?',(key,)).fetchone()
            if row is None: raise ValueError('Unknown ticket')
            if row['state']!='preview': return {'state':row['state'],'result':json.loads(row['result'] or 'null')}
            if db.execute("SELECT 1 FROM mt5_tickets WHERE state IN ('sending','unknown','placed') LIMIT 1").fetchone():
                raise ValueError('Reconcile the earlier delivery before submitting another ticket')
            if time.time()-row['created']>30: raise ValueError('Review expired; refresh and review again')
            body=json.loads(row['body'])
            if body.get('core_owned') and guard is None:raise PermissionError('Core-owned ticket requires current Core session guard')
            if self.crypto_stops and body['intent']['action']!='close' and body['review'].get('crypto_protection_required',True) and not body['review'].get('protection'):
                raise PermissionError('Reviewed crypto protection required; create a fresh ticket')
            api,request,review=self.build(body['intent'],key,
                approved_protection=body['review'].get('protection') if self.crypto_stops else None,core_owned=bool(body.get('core_owned')))
            if body['review'].get('account_binding') != review['account_binding']:
                raise PermissionError('MT5 terminal/account binding changed; create a new review')
            allowed_drift=min(body['review'].get('max_review_price_drift',20*review['point']),
                              review['max_review_price_drift'])
            if abs(request['price']-body['request']['price'])>allowed_drift:
                raise ValueError('Price moved outside the review range; review again')
            if review['estimated_stop_risk'] is not None and review['estimated_stop_risk']>body['review']['estimated_stop_risk']+.01:
                raise ValueError('Risk changed; review again')
            # Persist before external delivery, and never retry a sending ticket.
            db.execute("UPDATE mt5_tickets SET state='sending',body=? WHERE id=?",(json.dumps({'intent':body['intent'],'request':request,'review':review,**({'core_owned':True} if body.get('core_owned') else {})}),key))
        with LOCK:
            current=api.account_info()
            if current is None or current.trade_mode!=api.ACCOUNT_TRADE_MODE_DEMO or self.bridge.identity(current)!=body['intent']['account_identity']:
                state,result='rejected',{'message':'Account changed before delivery; no order sent'}
            else:
                if guard is not None:
                    try: guard()
                    except Exception:
                        with self.db() as db:
                            db.execute("UPDATE mt5_tickets SET state='rejected',result=? WHERE id=?",(json.dumps({'message':'Core scope/risk guard denied; no order sent'}),key))
                        raise
                try:
                    final_account = api.account_info()
                    final_terminal = api.terminal_info()
                    safe = (final_account is not None and final_terminal is not None and final_terminal.connected
                            and final_account.trade_mode == api.ACCOUNT_TRADE_MODE_DEMO
                            and self.bridge.account_record(api,final_account,final_terminal) == review['account_binding']
                            and final_account.trade_allowed and final_terminal.trade_allowed
                            and not final_terminal.tradeapi_disabled)
                except Exception:
                    safe = False
                if not safe:
                    state,result='rejected',{'message':'MT5 binding or execution permission changed before delivery; no order sent'}
                else:
                    try:
                        response=api.order_send(request)
                        after_account, after_terminal = api.account_info(), api.terminal_info()
                        if (after_account is None or after_terminal is None or not after_terminal.connected
                                or self.bridge.account_record(api,after_account,after_terminal) != review['account_binding']):
                            raise RuntimeError('MT5 binding changed during broker delivery')
                        if response is None: state,result='unknown',{'message':'No delivery response; inspect MT5 before another order'}
                        else:
                            result={k:getattr(response,k,None) for k in ('retcode','deal','order','volume','price','comment')}
                            state='filled' if response.retcode==10009 else 'partial' if response.retcode==10010 else 'placed' if response.retcode==10008 else 'unknown' if response.retcode in (10012,10031) else 'rejected'
                    except Exception:
                        state,result='unknown',{'message':'Delivery uncertain; inspect MT5 before another order'}
            with self.db() as db:
                db.execute('UPDATE mt5_tickets SET state=?,result=? WHERE id=?',(state,json.dumps(result),key))
            return {'state':state,'result':result,'mode':'demo'}

    def history(self, account_identity=None):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT id,created,state,result FROM mt5_tickets WHERE (? IS NULL OR json_extract(body,'$.intent.account_identity')=?) ORDER BY created DESC LIMIT 20",(account_identity,account_identity))]

    def reconcile(self):
        from datetime import datetime,timezone,timedelta
        with LOCK:
            api,account,_=self.bridge.connect()
            positions=api.positions_get()
            if positions is None: raise MT5Unavailable('Cannot inspect positions')
            # Broker clocks may differ from UTC; request a bounded wider history.
            deals=api.history_deals_get(datetime.now(timezone.utc)-timedelta(days=2),datetime.now(timezone.utc)+timedelta(days=1))
            if deals is None: raise MT5Unavailable('Cannot inspect deal history')
            resolved=0
            with self.db() as db:
                rows=db.execute("SELECT * FROM mt5_tickets WHERE state IN ('sending','unknown','placed')").fetchall()
                for row in rows:
                    body=json.loads(row['body'])
                    if body['intent']['account_identity']!=self.bridge.identity(account): continue
                    comment='niblit_'+row['id'][:12]
                    matches=[d for d in deals if d.magic==MAGIC and d.comment==comment and d.symbol==body['intent']['symbol']]
                    if matches:
                        db.execute("UPDATE mt5_tickets SET state='reconciled',result=? WHERE id=?",(json.dumps({'deal':matches[0].ticket}),row['id']))
                        resolved+=1
            return {'resolved':resolved,'notice':'Only matching broker deal evidence resolves delivery. No orders were sent.'}
