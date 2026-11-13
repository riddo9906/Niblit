"""Broker translation for Core sessions; original ticket ledgers still deliver.

No adapter grants permission, starts an engine or submits real-money orders.
"""
import hashlib
import json
import math
import time
from datetime import datetime,timezone,timedelta

from modules.trading_values import number
from modules.funded_risk import net_costs


def account_exposure(api,info,symbol,volume,price,currency):
    if info.currency_profit==currency:
        return number(volume*info.trade_contract_size*price,'account notional',positive=True)
    # Use the broker's own account-currency valuation. Reject asymmetric or
    # unavailable conversion instead of assuming a currency conversion rate.
    up=abs(number(api.order_calc_profit(api.ORDER_TYPE_BUY,symbol,volume,price,price*1.01),'converted upside',positive=False))/.01
    down=abs(number(api.order_calc_profit(api.ORDER_TYPE_BUY,symbol,volume,price,price*.99),'converted downside',positive=False))/.01
    if min(up,down)<=0 or abs(up-down)>max(up,down)*.01:raise ValueError('Broker exposure conversion is unavailable or nonlinear')
    return max(up,down)*1.01  # conservative conversion/spread reserve


def mt5_trade_costs(api, account, symbol, side, volume, review, quote, *, schedule=None, now=None):
    """Value protective levels on executable prices; spread is already embedded."""
    order_type = api.ORDER_TYPE_BUY if side == 'buy' else api.ORDER_TYPE_SELL
    entry = review['price']
    def value(start, end):
        result = api.order_calc_profit(order_type, symbol, volume, start, end)
        return float(result) if isinstance(result, (int, float)) and math.isfinite(result) else None

    bid, ask = quote.get('bid'), quote.get('ask')
    spread = None
    if bid is not None and ask is not None and 0 < bid <= ask:
        mark = value(ask, bid) if side == 'buy' else value(bid, ask)
        if mark is not None and mark <= 0:
            spread = abs(mark)
    gross_target = value(entry, review['take_profit'])
    gross_stop = value(entry, review['stop_loss'])
    return {'model':'mt5-executable-prices-v1','currency':account.currency,
            'spread_cost_estimate':spread,'spread_embedded_in_executable_prices':True,
            'gross_at_target':gross_target,'gross_at_stop':gross_stop,
            'commission':None,'financing':None,'slippage':None,'net_at_target':None,
            'costs_complete':False,'funded_eligible':False,
            'source':'MT5 order_calc_profit and observed bid/ask',
            'net_evaluation':net_costs(gross_target,gross_stop,volume=volume,currency=account.currency,
                schedule=schedule,now=time.time() if now is None else now)}


class MT5SessionAdapter:
    def __init__(self,bridge,orders):self.bridge=bridge;self.orders=orders

    def reconciliation_identity(self):
        api,account,_=self.bridge.connect()
        if account.trade_mode!=api.ACCOUNT_TRADE_MODE_DEMO:raise PermissionError('MT5 demo identity required for readback')
        return {'account':self.bridge.identity(account),'environment':'demo'}

    def snapshot(self,symbol):
        s=self.bridge.snapshot(symbol,include_context=True);api,account,terminal=self.bridge.connect()
        binding=self.bridge.account_record(api,account,terminal)
        if any(s['account'].get(k)!=v for k,v in binding.items() if k != 'login'):raise ValueError('MT5 account changed')
        info=api.symbol_info(symbol)
        if not info or not getattr(info,'currency_profit',None):raise ValueError('Verified symbol currency unavailable')
        positions=[];exposure=0.;open_risk=0.
        for raw in s['positions']:
            contract=api.symbol_info(raw['symbol'])
            if not contract or not getattr(contract,'currency_profit',None):raise ValueError('Position currency unavailable')
            side='buy' if raw['type']==0 else 'sell'
            exposure+=account_exposure(api,contract,raw['symbol'],raw['volume'],raw['price_current'],account.currency)
            if not raw['sl']:open_risk=None
            elif open_risk is not None:
                loss=api.order_calc_profit(raw['type'],raw['symbol'],raw['volume'],raw['price_current'],raw['sl'])
                open_risk+=max(0,-number(loss,'position stop loss'))
            positions.append(dict(id=str(raw['ticket']),symbol=raw['symbol'],side=side,entry=raw['price_open'],
                quantity=raw['volume'],stop_loss=raw['sl'],take_profit=raw['tp'],profit=raw['profit']))
        start=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
        deals=api.history_deals_get(start-timedelta(days=1),datetime.now(timezone.utc)+timedelta(days=1))
        if deals is None:raise ValueError('Account loss history unavailable')
        # Broker absolute clock is unverified. A wider window and losing cash
        # only cannot let earlier gains hide today's loss. Actual realized net
        # is recorded separately by reconciliation from all linked deals.
        loss=sum(min(0,number(d.profit+d.commission+d.swap+getattr(d,'fee',0),'deal net'))
                 for d in deals if getattr(d,'type',None) in (0,1))
        if self.bridge.connection_record() != binding:
            raise ValueError('MT5 account changed while reading risk state')
        return dict(account=s['account']['identity'],environment=binding['environment'],account_binding=binding,
            symbol=symbol,instrument=info.currency_base+'/'+info.currency_profit,
            equity=s['account']['equity'],available=s['account']['free_margin'],margin=s['account']['margin'],
            exposure=exposure,open_risk=open_risk,realized_today=loss,
            daily_loss_basis='conservative losing deal cash over wider broker-clock window',
            demo_volume_ceiling=self.orders.autonomous_max_volume,observed_at=s['checked_at'],quote=s['quote'],candles=s['candles'],positions=positions,
            pending_count=s['pending_order_count'],market_context=s['market_context'])

    def prepare(self,s,side,limits,position=None):
        api,account,_=self.bridge.connect();info=api.symbol_info(s['symbol'])
        if position:
            body=dict(action='close',symbol=s['symbol'],side=side,volume=position['quantity'],
                account_identity=s['account'],position_ticket=int(position['id']))
        else:
            reference=number(info.volume_min,'broker minimum volume',positive=True)
            cap=min(self.orders.autonomous_max_volume,limits['max_volume'])
            if reference>cap:raise ValueError('Broker minimum volume exceeds reviewed lot cap')
            sample=dict(action='open',symbol=s['symbol'],side=side,volume=reference,
                account_identity=s['account'],position_ticket=None,strategy=s.get('entry_strategy'))
            review=self.orders.inspect(sample,core_owned=True)
            budget=min(s['equity']*limits['risk_fraction'],limits['risk_cash'])
            risk=number(review['estimated_stop_risk'],'broker stop risk',positive=True)
            ceiling=min(cap,reference*budget/risk)
            if info.volume_step<=0 or ceiling<info.volume_min:raise ValueError('Broker minimum volume exceeds risk budget')
            volume=round(info.volume_min+math.floor((ceiling-info.volume_min+1e-12)/info.volume_step)*info.volume_step,8)
            body=sample|dict(volume=volume,max_stop_risk=budget)
        ticket=self.orders.preview(body,core_owned=True);r=ticket['review']
        if not position and not (r['stop_loss']<r['price']<r['take_profit'] if side=='buy' else r['take_profit']<r['price']<r['stop_loss']):raise ValueError('Invalid broker protective levels')
        return dict(ticket=ticket['ticket'],intent=body,risk=r['estimated_stop_risk'] if not position else 0.,
            margin=max(0,number(r['margin_after'],'broker margin')-s['margin']),
            exposure=account_exposure(api,info,s['symbol'],body['volume'],r['price'],account.currency),stop_loss=r['stop_loss'],take_profit=r['take_profit'],
            protection=r.get('protection'),
            costs=None if position else mt5_trade_costs(api,account,s['symbol'],side,body['volume'],r,s['quote']))

    def submit(self,prepared,guard):
        if not callable(guard):raise PermissionError('Core delivery guard required')
        result=self.orders.confirm(prepared['ticket'],guard=guard)
        state={'filled':'submitted','rejected':'rejected','partial':'partial'}.get(result['state'],'unknown')
        return {'state':state,'ticket':prepared['ticket'],'broker':result}

    def cancel_prepared(self,order):
        ticket=json.loads(order['payload'])['prepared']['ticket']
        with self.orders.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM mt5_tickets WHERE id=?',(ticket,)).fetchone()
            if not row or not json.loads(row['body']).get('core_owned') or row['state'] not in ('preview','sending'):return False
            db.execute("UPDATE mt5_tickets SET state='rejected',result=? WHERE id=?",(json.dumps({'reason':'Core restarted before final guard; no order sent'}),ticket))
        return True

    def reconcile(self,order):
        prepared=json.loads(order['payload'])['prepared']
        with self.orders.db() as db:row=db.execute('SELECT * FROM mt5_tickets WHERE id=?',(prepared['ticket'],)).fetchone()
        if not row:return {'state':'unknown','reason':'Original ticket unavailable'}
        api,account,terminal=self.bridge.connect()
        binding=self.bridge.account_record(api,account,terminal)
        if self.bridge.identity(account)!=order['account'] or account.trade_mode!=api.ACCOUNT_TRADE_MODE_DEMO:raise PermissionError('MT5 account changed during reconciliation')
        if row['state']=='rejected':return {'state':'rejected'}
        data=json.loads(row['body']);result=json.loads(row['result'] or '{}')
        end=datetime.now(timezone.utc)+timedelta(days=1)
        deals=api.history_deals_get(end-timedelta(days=9),end)
        positions=api.positions_get()
        if self.bridge.connection_record() != binding:
            raise PermissionError('MT5 account changed during broker history readback')
        if deals is None or positions is None:return {'state':'unknown','reason':'Broker history/positions unavailable'}
        matches=[d for d in deals if d.magic==29102026 and d.symbol==order['symbol'] and
            (d.comment=='niblit_'+prepared['ticket'][:12] or (result.get('order') and d.order==result['order']))]
        ids={str(d.position_id) for d in matches}
        if len(ids)!=1:return {'state':'unknown','reason':'No unique broker deal attribution'}
        identifier = next(iter(ids))
        owned_positions = [
            position for position in positions
            if position.symbol == order['symbol']
            and str(getattr(position, 'identifier', position.ticket)) == identifier
        ]
        if len(owned_positions) > 1:
            return {'state': 'unknown', 'reason': 'MT5 position identifier is ambiguous'}
        position = owned_positions[0] if owned_positions else None
        ticket = str(position.ticket) if position else identifier
        identity = {'position_id': ticket, 'position_identifier': identifier}
        if row['state'] == 'partial':
            return {'state': 'partial', **identity, 'reason': 'Partial fill requires explicit reconciliation; no retry'}
        linked = [
            deal for deal in deals
            if str(deal.position_id) == identifier and deal.symbol == order['symbol']
        ]
        entries = [deal for deal in linked if deal.entry in (0, 2)]
        if (not entries or len({deal.order for deal in entries}) != 1
                or any(deal.entry == 2 or deal.magic != 29102026 for deal in entries)):
            return {'state': 'unknown', **identity, 'reason': 'MT5 position opening attribution is incomplete or mixed'}
        if row['state'] in ('sending', 'unknown', 'placed'):
            self.orders.reconcile()
        if position:
            if order['action'] == 'close':
                return {'state': 'partial', **identity, 'reason': 'Closing order not fully reconciled; no retry'}
            return {'state': 'open', **identity, 'volume': position.volume,
                    'stop_loss': position.sl, 'take_profit': position.tp}
        exits = [deal for deal in linked if deal.entry in (1, 3)]
        if not exits:
            return {'state': 'unknown', **identity, 'reason': 'No linked closing deal'}
        net = sum(deal.profit + deal.commission + deal.swap + getattr(deal, 'fee', 0) for deal in linked)
        return {'state': 'closed', **identity, 'realized_net': number(net, 'realized net'),
                'currency': account.currency, 'source': 'mt5_linked_demo_deals',
                'exit_deals': [str(deal.ticket) for deal in exits],
                'exit_fills': [{'deal': str(deal.ticket), 'price': getattr(deal, 'price', None),
                                'volume': getattr(deal, 'volume', None),
                                'reason': getattr(deal, 'reason', None)} for deal in exits],
                'costs': {key: number(sum(getattr(deal, key, 0) for deal in linked), key)
                          for key in ('commission', 'swap', 'fee')}}


class FreqtradeSessionAdapter:
    def __init__(self,desk):self.desk=desk

    def identity(self):
        private,_=self.desk.connection()
        material=[str((self.desk.root.parent/'freqtrade/user_data/config.json').resolve()),
            private.get('exchange',{}).get('name'),private.get('dry_run'),private.get('stake_currency'),private.get('trading_mode'),private.get('db_url')]
        # No password/key/token enters an identity or telemetry record.
        return hashlib.sha256(json.dumps(material,sort_keys=True).encode()).hexdigest()[:24]

    def reconciliation_identity(self):
        if self.desk.configuration().get('dry_run') is not True:raise PermissionError('Freqtrade dry-run identity required for readback')
        return {'account':self.identity(),'environment':'dry-run'}

    def snapshot(self,symbol):
        config=self.desk.configuration();raw_config=self.desk.api('show_config')
        account=self.identity();positions=self.desk.api('status');balance=self.desk.api('balance')
        quote=self.desk.quote(symbol,config);market=self.desk.market(symbol,config)
        if config!=self.desk.configuration() or account!=self.identity():raise ValueError('Freqtrade identity/configuration changed')
        currency=config.get('stake_currency')
        wallet=next((c for c in balance.get('currencies',[]) if c.get('currency')==currency),None)
        if not wallet:raise ValueError('Account-currency balance unavailable')
        total=number(balance.get('total'),'account value',positive=True)
        free=number(wallet.get('free'),'free stake currency')
        floating=sum(number(p.get('profit_abs'),'unrealized profit') for p in positions)
        equity=min(total,total+floating)
        daily=self.desk.api('daily?timescale=1');today=datetime.now(timezone.utc).date().isoformat()
        day=next((d for d in daily.get('data',[]) if str(d.get('date',''))[:10]==today),None)
        if day is None:raise ValueError('Verified daily account P&L unavailable')
        realized=number(float(day['abs_profit']),'daily realized P&L')
        exposure=sum(number(p.get('stake_amount'),'position stake')*number(p.get('leverage',1),'leverage',positive=True) for p in positions)
        risk=0.;normalized=[]
        for p in positions:
            if p.get('stop_loss_abs') is None or p.get('stop_loss_ratio') is None:risk=None
            elif risk is not None:risk+=p['stake_amount']*max(0,-p['stop_loss_ratio'])
            normalized.append(dict(id=str(p['trade_id']),symbol=p['pair'],side='sell' if p['is_short'] else 'buy',
                quantity=p['amount'],entry=p['open_rate'],stop_loss=p.get('stop_loss_abs',0),
                take_profit=0.,profit=p['profit_abs']))
        # Quote uses locally received actual public order book. The provider's
        # timestamp is explicit; no cached observation may claim currentness.
        quote={'bid':quote.get('bid'),'ask':quote.get('ask'),'timestamp':quote.get('timestamp'),
            'fresh':quote.get('fresh') is True and market.get('fresh') is True,
            'age_seconds':max(0,time.time()-quote['received_at']) if quote.get('received_at') else None}
        return dict(account=account,environment='dry-run' if config.get('dry_run') is True and raw_config.get('dry_run') is True else 'live',
            symbol=symbol,instrument=symbol.split(':')[0],equity=equity,available=free,margin=exposure,
            exposure=exposure,open_risk=risk,realized_today=realized,observed_at=time.time(),quote=quote,
            candles=market['candles'],positions=normalized,pending_count=sum(bool(p.get('has_open_orders')) for p in positions),
            configuration=config,protections={'stoploss':raw_config.get('stoploss'),'minimal_roi':raw_config.get('minimal_roi'),
                'fee':raw_config.get('fee'),'trading_mode':raw_config.get('trading_mode'),
                'position_adjustment_enable':raw_config.get('position_adjustment_enable',False)})

    def prepare(self,s,side,limits,position=None):
        from modules.trading_desk import Intent
        if position:
            intent=Intent(action='exit',pair=s['symbol'],trade_id=int(position['id']))
            ticket=self.desk.preview(intent,core_owned=True)
            return dict(ticket=ticket['ticket'],expected={k:ticket[k] for k in ('intent','identity','core_owned','entry_tag')},
                risk=0.,margin=0.,exposure=0.,stop_loss=position['stop_loss'],take_profit=position['take_profit'])
        if s['configuration']['state']!='running':raise PermissionError('Stopped Freqtrade engine; no automatic activation')
        if s['configuration'].get('strategy')!='NiblitCoreManaged':raise PermissionError('Select the Core-managed native strategy before bounded execution')
        if s['protections'].get('position_adjustment_enable'):raise PermissionError('Unscoped native position adjustments must be disabled')
        protection=s['protections'];stop=number(protection.get('stoploss'),'native stoploss')
        rois=protection.get('minimal_roi')
        if not -.1<=stop<0 or not isinstance(rois,dict) or not rois:raise ValueError('Verified native stop/ROI protection required')
        targets=[number(float(v),'native ROI',positive=True) for v in rois.values()]
        target=min(targets);fee=number(protection.get('fee'),'verified fee')
        if not 0<=fee<=.01:raise ValueError('Unbounded fee')
        price=s['quote']['ask'] if side=='buy' else s['quote']['bid']
        budget=min(limits['risk_cash'],s['equity']*limits['risk_fraction'])
        stake=min(100.,budget/(abs(stop)+2*fee),s['available']*.95,
            s['equity']*limits['max_margin_fraction']-s['margin'],s['equity']*limits['max_exposure_fraction']-s['exposure'])
        minimum=self.desk.minimum_stake(s['symbol'],s['configuration'],price)
        rule=self.desk.market_rules[1].get(s['symbol'].split(':')[0].replace('/',''))
        filters={f['filterType']:f for f in rule['filters']};step=float(filters['LOT_SIZE']['stepSize'])
        if step<=0:raise ValueError('Broker quantity step unavailable')
        quantity=math.floor(stake/price/step)*step;stake=quantity*price
        if stake<minimum or stake<=0:raise ValueError('Minimum broker size exceeds account budget')
        intent=Intent(action='enter_long' if side=='buy' else 'enter_short',pair=s['symbol'],stake=stake)
        ticket=self.desk.preview(intent,core_owned=True)
        return dict(ticket=ticket['ticket'],expected={k:ticket[k] for k in ('intent','identity','core_owned','entry_tag')},
            risk=stake*(abs(stop)+2*fee),margin=stake,exposure=stake,
            reference_price=price,native_account_binding=__import__('modules.freqtrade_core_claim',fromlist=['account_binding']).account_binding(self.desk.connection()[0]),
            stop_loss=price*(1-abs(stop) if side=='buy' else 1+abs(stop)),
            take_profit=price*(1+target if side=='buy' else 1-target),native_stoploss=stop,native_roi=rois,native_fee=fee)

    def submit(self,prepared,guard):
        if not callable(guard):raise PermissionError('Core delivery guard required')
        # Repeat native protective configuration checks immediately before send.
        def final_guard():
            if 'native_stoploss' in prepared:
                config=self.desk.api('show_config')
                if any(config.get(field)!=prepared[value] for field,value in
                       (('stoploss','native_stoploss'),('minimal_roi','native_roi'),('fee','native_fee'))):raise PermissionError('Native protections changed')
            guard()
        return self.desk.confirm(prepared['ticket'],expected=prepared['expected'],guard=final_guard)

    def cancel_prepared(self,order):
        prepared=json.loads(order['payload'])['prepared']
        with self.desk.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM tickets WHERE id=?',(prepared['ticket'],)).fetchone()
            if not row or json.loads(row['payload'])!=prepared['expected'] or not prepared['expected'].get('core_owned') or row['state'] not in ('preview','sending'):return False
            db.execute("UPDATE tickets SET state='rejected',result=? WHERE id=?",(json.dumps({'reason':'Core restarted before final guard; no order sent'}),prepared['ticket']))
        return True

    def reconcile(self,order):
        if self.identity()!=order['account'] or self.desk.configuration().get('dry_run') is not True:raise PermissionError('Freqtrade identity changed')
        prepared=json.loads(order['payload'])['prepared']
        with self.desk.db() as db:ticket=db.execute('SELECT * FROM tickets WHERE id=?',(prepared['ticket'],)).fetchone()
        if not ticket:return {'state':'unknown','reason':'Original ticket unavailable'}
        if ticket['state']=='rejected':return {'state':'rejected'}
        result=json.loads(ticket['result'] or '{}');intent=prepared['expected']['intent']
        trades=self.desk.api('trades?limit=100').get('trades',[])
        matches=[t for t in trades if t.get('pair')==order['symbol'] and
            ((intent['action']=='exit' and t.get('trade_id')==intent['trade_id']) or
             (intent['action']!='exit' and t.get('enter_tag')==prepared['expected']['entry_tag']))]
        if len(matches)!=1:return {'state':'unknown','reason':'No unique engine attribution'}
        trade=matches[0]
        if ticket['state'] in ('sending','unknown'):self.desk.reconcile()
        if trade.get('has_open_orders'):return {'state':'partial','position_id':str(trade['trade_id']),'reason':'Pending/partial engine order; no retry'}
        if trade.get('is_open'):
            if intent['action']=='exit':return {'state':'unknown','position_id':str(trade['trade_id']),'reason':'Exit not confirmed; no retry'}
            return {'state':'open','position_id':str(trade['trade_id']),'volume':trade['amount'],'stop_loss':trade.get('stop_loss_abs')}
        net=trade.get('close_profit_abs',trade.get('profit_abs'))
        return {'state':'closed','position_id':str(trade['trade_id']),'realized_net':number(net,'realized net'),
                'currency':self.desk.configuration()['stake_currency'],'source':'linked_freqtrade_dry_run_ledger'}
