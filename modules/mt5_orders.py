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
    def __init__(self, bridge, path):
        self.bridge = bridge
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

    def build(self, body, key):
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
        if not math.isfinite(volume) or not 0<volume<=.01:
            raise ValueError('Demo tests are capped at 0.01 lots')
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
        risk=None
        if body['action']=='close': request['position']=body['position_ticket']
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
            'account_identity':body['account_identity'],'point':info.point}

    def inspect(self, body):
        """Non-delivering broker preflight for opportunity alerts; no ticket created."""
        with LOCK,self.db() as db:
            if db.execute("SELECT 1 FROM mt5_tickets WHERE state IN ('sending','unknown','placed') LIMIT 1").fetchone():
                raise ValueError('An order delivery is unresolved')
            _,_,review=self.build(body,'observeonly')
            return review

    def preview(self, body):
        with LOCK,self.db() as db:
            if db.execute("SELECT 1 FROM mt5_tickets WHERE state IN ('sending','unknown','placed') LIMIT 1").fetchone():
                raise ValueError('A delivery is unresolved; reconcile before another order')
            key=secrets.token_hex(16)
            _,request,review=self.build(body,key)
            db.execute('INSERT INTO mt5_tickets VALUES(?,?,?,?,?)',
                (key,time.time(),'preview',json.dumps({'intent':body,'request':request,'review':review}),None))
            return {'ticket':key,'review':review,'expires_in':30}

    def confirm(self, key):
        with LOCK,self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM mt5_tickets WHERE id=?',(key,)).fetchone()
            if row is None: raise ValueError('Unknown ticket')
            if row['state']!='preview': return {'state':row['state'],'result':json.loads(row['result'] or 'null')}
            if db.execute("SELECT 1 FROM mt5_tickets WHERE state IN ('sending','unknown','placed') LIMIT 1").fetchone():
                raise ValueError('Reconcile the earlier delivery before submitting another ticket')
            if time.time()-row['created']>30: raise ValueError('Review expired; refresh and review again')
            body=json.loads(row['body'])
            api,request,review=self.build(body['intent'],key)
            if abs(request['price']-body['request']['price'])>20*review['point']:
                raise ValueError('Price moved outside the review range; review again')
            if review['estimated_stop_risk'] is not None and review['estimated_stop_risk']>body['review']['estimated_stop_risk']+.01:
                raise ValueError('Risk changed; review again')
            # Persist before external delivery, and never retry a sending ticket.
            db.execute("UPDATE mt5_tickets SET state='sending',body=? WHERE id=?",(json.dumps({'intent':body['intent'],'request':request,'review':review}),key))
        with LOCK:
            current=api.account_info()
            if current is None or current.trade_mode!=api.ACCOUNT_TRADE_MODE_DEMO or self.bridge.identity(current)!=body['intent']['account_identity']:
                state,result='rejected',{'message':'Account changed before delivery; no order sent'}
            else:
                try:
                    response=api.order_send(request)
                    if response is None: state,result='unknown',{'message':'No delivery response; inspect MT5 before another order'}
                    else:
                        result={k:getattr(response,k,None) for k in ('retcode','deal','order','volume','price','comment')}
                        state='filled' if response.retcode==10009 else 'partial' if response.retcode==10010 else 'placed' if response.retcode==10008 else 'unknown' if response.retcode in (10012,10031) else 'rejected'
                except Exception:
                    state,result='unknown',{'message':'Delivery uncertain; inspect MT5 before another order'}
            with self.db() as db:
                db.execute('UPDATE mt5_tickets SET state=?,result=? WHERE id=?',(state,json.dumps(result),key))
            return {'state':state,'result':result,'mode':'demo'}

    def history(self):
        with self.db() as db:
            return [dict(r) for r in db.execute('SELECT id,created,state,result FROM mt5_tickets ORDER BY created DESC LIMIT 20')]

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
