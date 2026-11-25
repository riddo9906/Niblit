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


def bound_cost_schedule(snapshot, volume, schedule, *, side, now):
    """Validate operator/broker evidence for this account and proposed size.

    Historical charges are not prospective bounds. The caller supplies trusted
    configuration; a valid schedule remains an estimate, never authority.
    """
    if not isinstance(schedule,dict):return None
    binding={k:snapshot.get(k) for k in ('account','environment','symbol')}
    if not all(binding.values()) or not snapshot.get('currency'):return None
    if schedule.get('binding')!=binding or schedule.get('currency')!=snapshot.get('currency'):return None
    provenance=schedule.get('provenance')
    if provenance=='simulation_assumption':
        # A clearly labelled paper-only estimate may support a matched demo
        # account. Never treat this as broker-certified or live fee evidence.
        if snapshot.get('environment')!='demo' or schedule.get('scope')!='local_demo_only':return None
    elif provenance not in ('broker_documented_schedule','operator_approved_bound'):return None
    if not schedule.get('version') or not schedule.get('source'):return None
    if not isinstance(schedule.get('sides'),list) or side not in ('buy','sell') or side not in schedule['sides']:return None
    if not isinstance(schedule.get('account_binding'),dict):return None
    account=snapshot.get('account_binding') or {}
    if any(not account.get(k) or schedule.get('account_binding',{}).get(k)!=account[k]
           for k in ('broker','server','terminal_id')):return None
    try:
        if not number(schedule.get('verified_at'),'cost verified at')<=now<number(schedule.get('expires'),'cost expiry'):return None
        if not 0<volume<=number(schedule.get('max_volume'),'cost size bound',positive=True):return None
    except (ValueError,TypeError):return None
    return schedule


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
    def __init__(self,bridge,orders,*,cost_model=None,cost_schedule=None):
        self.bridge=bridge;self.orders=orders;self.cost_model=cost_model;self.cost_schedule=cost_schedule

    def bind_demo_delivery(self,snapshot):
        # Called only after Core validates a human-approved bounded scope.
        if self.orders.execution_transport is not None:return
        import os
        if os.getenv('NIBLIT_DESKTOP_OBSERVATION_ONLY')=='1' or os.getenv('NIBLIT_MT5_DEMO_DELIVERY_ENABLED')!='1':
            raise PermissionError('Local MT5 demo delivery is not explicitly enabled')
        from modules.mt5_bridge import LOCK
        from modules.mt5_orders import require_exclusive_demo_core
        require_exclusive_demo_core()
        with LOCK:
            api,account,terminal=self.bridge.connect()
            binding=self.bridge.account_record(api,account,terminal)
            if snapshot.get('environment')!='demo' or binding.get('environment')!='demo' or binding!=snapshot.get('account_binding'):
                raise PermissionError('Verified demo binding changed before transport preparation')
            self.orders.expected_binding=dict(binding)
            self.orders.execution_transport=api.order_send

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
            equity=s['account']['equity'],currency=account.currency,available=s['account']['free_margin'],margin=s['account']['margin'],
            exposure=exposure,open_risk=open_risk,realized_today=loss,
            daily_loss_basis='conservative losing deal cash over wider broker-clock window',
            demo_volume_ceiling=self.orders.autonomous_max_volume,
            demo_volume_min=number(info.volume_min,'broker minimum lot',positive=True),
            observed_at=s['checked_at'],quote=s['quote'],candles=s['candles'],positions=positions,
            pending_count=s['pending_order_count'],market_context=s['market_context'])

    def draft_entry(self,s,side,limits):
        return self.prepare(s,side,limits,_draft=True)

    def prepare(self,s,side,limits,position=None,*,_draft=False):
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
            from modules.structured_trade_engine import lot_grid
            volume=lot_grid(info.volume_min,info.volume_step,info.volume_max,ceiling)
            if volume is None:raise ValueError('Broker minimum volume exceeds risk budget')
            body=sample|dict(volume=volume,max_stop_risk=budget)
        ticket=({'review':self.orders.inspect(body,core_owned=True)} if _draft else self.orders.preview(body,core_owned=True));r=ticket['review']
        if not position and not (r['stop_loss']<r['price']<r['take_profit'] if side=='buy' else r['take_profit']<r['price']<r['stop_loss']):raise ValueError('Invalid broker protective levels')
        prepared=dict(ticket=ticket.get('ticket'),intent=body,risk=r['estimated_stop_risk'] if not position else 0.,
            margin=max(0,number(r['margin_after'],'broker margin')-s['margin']),
            exposure=account_exposure(api,info,s['symbol'],body['volume'],r['price'],account.currency),stop_loss=r['stop_loss'],take_profit=r['take_profit'],
            protection=r.get('protection'),
            costs=None if position else mt5_trade_costs(api,account,s['symbol'],side,body['volume'],r,s['quote']))
        if not position:
            if r.get('protection') is not None:
                from modules.structured_trade_engine import execution_plan_record
                prepared['structured_plan']=execution_plan_record(
                    snapshot=s,review=r,intent=body,
                    risk_budget=min(s['equity']*limits['risk_fraction'],limits['risk_cash']))
                from modules.execution_venue_router import VenueBinding,resolve_route
                broker=s['account_binding']
                prepared['execution_route']=resolve_route(
                    VenueBinding(adapter='mt5',environment=s['environment'],
                        account=s['account'],symbol=s['symbol'],instrument=s['instrument'],
                        currency=s['currency'],identity='mt5:'+str(broker['server'])+':'+str(broker['terminal_id'])),
                    {'side':side,'symbol':s['symbol'],'venue':'mt5'},
                    risk_profile='scoped-mt5-demo/1',
                    feed_identity='mt5:'+s['symbol']+':M5:'+str(prepared['structured_plan']['bar']),
                    plan_hash=prepared['structured_plan']['record_hash'])
            now=time.time()
            schedule=bound_cost_schedule(s,body['volume'],self.cost_schedule,side=side,now=now)
            costs=mt5_trade_costs(api,account,s['symbol'],side,body['volume'],r,s['quote'],schedule=schedule,now=now)
            net=costs['net_evaluation']
            if net.get('costs_complete') is True:
                costs.update(costs_complete=True,commission=net['commission'],financing=net['financing'],
                    slippage=net['slippage'],net_at_target=net['net_target'],
                    modeled_loss=-float(net['net_stop']),
                    binding={k:s[k] for k in ('account','environment','symbol')},
                    observed_at=now,expires=schedule['expires'],
                    provenance=schedule['provenance'],schedule_version=schedule['version'],
                    source=schedule['source'],execution_authorized=False)
            prepared['costs']=self.cost_model(s,prepared) if self.cost_model else costs
        return prepared

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


def native_dry_run_fee(engine_config,private_profile):
    """Use a private, explicitly configured paper fee when the RPC omits it.

    This is a simulation assumption, never a funded-account fee assertion.
    """
    fee=engine_config.get('fee')
    provenance='engine_show_config' if fee is not None else 'unavailable'
    if (fee is None and engine_config.get('dry_run') is True
            and private_profile.get('dry_run') is True
            and private_profile.get('strategy')==engine_config.get('strategy')
            and private_profile.get('exchange',{}).get('name')==engine_config.get('exchange')
            and private_profile.get('trading_mode')==engine_config.get('trading_mode')):
        fee=private_profile.get('fee')
        provenance='private_dry_run_simulation_assumption'
    if type(fee) not in (int,float) or not math.isfinite(fee) or not 0<=fee<=.01:
        return None,'unavailable'
    return float(fee),provenance


def freqtrade_entry_costs(snapshot,prepared,schedule,*,side,now):
    """Explicit dry-run fee plus approved funding/slippage bounds, not account-tier fees."""
    unknown={'costs_complete':False,'source':'UNKNOWN','execution_authorized':False}
    if not isinstance(schedule,dict) or snapshot.get('environment')!='dry-run':return unknown
    binding={k:snapshot.get(k) for k in ('account','environment','symbol')}
    if (schedule.get('binding')!=binding or schedule.get('currency')!=snapshot.get('currency')
            or schedule.get('provenance') not in ('operator_approved_bound','simulation_assumption')
            or not schedule.get('source') or not schedule.get('version')
            or not isinstance(schedule.get('sides'),list) or side not in schedule['sides']):return unknown
    try:
        if not number(schedule.get('verified_at'),'verified at')<=now<number(schedule.get('expires'),'expiry'):return unknown
        notional=number(prepared['exposure'],'notional',positive=True)
        if notional>number(schedule.get('max_notional'),'notional bound',positive=True):return unknown
        fee=number(prepared.get('native_fee'),'native simulation fee')
        if fee!=number(schedule.get('fee'),'approved fee') or not 0<=fee<=.01:return unknown
        funding=number(schedule.get('funding_upper_bound'),'funding bound')
        slippage=number(schedule.get('slippage_upper_bound'),'slippage bound')
        if min(funding,slippage)<0:return unknown
        # Existing risk already contains the gross stop and two entry-notional fees.
        uplift=notional*(abs(prepared['native_stoploss'])+max(map(float,prepared['native_roi'].values())))*fee
        loss=number(prepared['risk'],'stop plus base fees',positive=True)+uplift+funding+slippage
    except (KeyError,TypeError,ValueError):return unknown
    return {'costs_complete':True,'binding':binding,'currency':snapshot['currency'],
        'observed_at':now,'expires':schedule['expires'],'modeled_loss':loss,
        'native_fee_rate':fee,'fees_upper_estimate':2*notional*fee+uplift,
        'funding_upper_bound':funding,'slippage_upper_bound':slippage,
        'source':schedule['source'],'version':schedule['version'],'provenance':schedule['provenance'],
        'execution_authorized':False,'limitation':'Simulation assumptions; not verified live account costs or guaranteed loss'}


class FreqtradeSessionAdapter:
    def __init__(self,desk,*,cost_model=None,cost_schedule=None):
        self.desk=desk;self.cost_model=cost_model;self.cost_schedule=cost_schedule

    def identity(self):
        private,_=self.desk.connection()
        material=[str(self.desk.config_path.resolve()),
            private.get('exchange',{}).get('name'),private.get('dry_run'),private.get('stake_currency'),private.get('trading_mode'),private.get('db_url')]
        # No password/key/token enters an identity or telemetry record.
        return hashlib.sha256(json.dumps(material,sort_keys=True).encode()).hexdigest()[:24]

    def bind_demo_delivery(self,snapshot):
        if self.desk.transport is not None:return # Intercepted fixtures only.
        config=self.desk.configuration()
        if not self.desk.native_demo_delivery or snapshot.get('environment')!='dry-run' or config.get('dry_run') is not True or config.get('strategy')!='NiblitCoreManaged' or config.get('state')!='running':
            raise PermissionError('Isolated CoreManaged dry-run delivery is not enabled and running')

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
        # Freqtrade balance.total already includes open-position valuation.
        # Subtracting a negative floating P&L again double-counts the loss.
        equity=total
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
        # The RPC omits the private simulation fee; verify the same running
        # dry-run identity before using that explicitly configured assumption.
        private_profile,_=self.desk.connection()
        fee,fee_source=native_dry_run_fee(raw_config,private_profile)
        return dict(account=account,environment='dry-run' if config.get('dry_run') is True and raw_config.get('dry_run') is True else 'live',
            symbol=symbol,instrument=symbol.split(':')[0],equity=equity,currency=currency,available=free,margin=exposure,
            exposure=exposure,open_risk=risk,realized_today=realized,observed_at=time.time(),quote=quote,
            candles=market['candles'],positions=normalized,pending_count=sum(bool(p.get('has_open_orders')) for p in positions),
            equity_basis='Freqtrade balance.total marked equity; floating profit shown separately',unrealized=floating,
            configuration=config,protections={'stoploss':raw_config.get('stoploss'),'minimal_roi':raw_config.get('minimal_roi'),
                'fee':fee,'fee_source':fee_source,'trading_mode':raw_config.get('trading_mode'),
                'position_adjustment_enable':raw_config.get('position_adjustment_enable',False)})

    def prepare(self,s,side,limits,position=None):
        from modules.trading_desk import Intent
        if position:
            intent=Intent(action='exit',pair=s['symbol'],trade_id=int(position['id']))
            ticket=self.desk.preview(intent,core_owned=True)
            return dict(ticket=ticket['ticket'],expected={k:ticket[k] for k in ('intent','identity','core_owned','entry_tag')},
                risk=0.,margin=0.,exposure=0.,stop_loss=position['stop_loss'],take_profit=position['take_profit'])
        if s['configuration']['state']!='running':raise PermissionError('Stopped Freqtrade engine; no automatic activation')
        prepared=self.draft_entry(s,side,limits)
        intent=Intent(action='enter_long' if side=='buy' else 'enter_short',pair=s['symbol'],stake=prepared['exposure'])
        ticket=self.desk.preview(intent,core_owned=True)
        prepared.update(ticket=ticket['ticket'],expected={k:ticket[k] for k in ('intent','identity','core_owned','entry_tag')})
        return prepared

    def draft_entry(self,s,side,limits):
        """Same sizing/protections, without a ticket, session activation or delivery.

        A stopped engine may be described in a conditional human proposal. The
        existing prepare() gate still requires RUNNING before any ticket exists.
        """
        if side not in ('buy','sell'):raise ValueError('Explicit entry direction required')
        if s['environment']!='dry-run' or s['quote'].get('fresh') is not True:
            raise PermissionError('Fresh isolated dry-run observation required')
        if s['configuration'].get('strategy')!='NiblitCoreManaged':raise PermissionError('Select the Core-managed native strategy before bounded execution')
        if s['protections'].get('position_adjustment_enable'):raise PermissionError('Unscoped native position adjustments must be disabled')
        protection=s['protections'];stop=number(protection.get('stoploss'),'native stoploss')
        rois=protection.get('minimal_roi')
        if not -.1<=stop<0 or not isinstance(rois,dict) or not rois:raise ValueError('Verified native stop/ROI protection required')
        targets=[number(float(v),'native ROI',positive=True) for v in rois.values()]
        target=min(targets)
        if protection.get('fee') is None:
            raise ValueError('New-entry fee evidence unavailable; historical position fees cannot authorize a new entry')
        fee=number(protection.get('fee'),'verified fee')
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
        prepared=dict(risk=stake*(abs(stop)+2*fee),margin=stake,exposure=stake,
            quantity=quantity,quantity_step=step,minimum_stake=minimum,
            reference_price=price,native_account_binding=__import__('modules.freqtrade_core_claim',fromlist=['account_binding']).account_binding(self.desk.connection()[0]),
            stop_loss=price*(1-abs(stop) if side=='buy' else 1+abs(stop)),
            take_profit=price*(1+target if side=='buy' else 1-target),native_stoploss=stop,native_roi=rois,native_fee=fee)
        schedule=self.cost_schedule
        if isinstance(schedule,dict) and isinstance(schedule.get('by_symbol'),dict):
            schedule=schedule['by_symbol'].get(s['symbol'])
        prepared['costs']=self.cost_model(s,prepared) if self.cost_model else freqtrade_entry_costs(s,prepared,schedule,side=side,now=time.time())
        return prepared

    def submit(self,prepared,guard):
        if not callable(guard):raise PermissionError('Core delivery guard required')
        # Repeat native protective configuration checks immediately before send.
        def final_guard():
            if 'native_stoploss' in prepared:
                config=self.desk.api('show_config')
                fee,_=native_dry_run_fee(config,self.desk.connection()[0])
                if (fee!=prepared['native_fee'] or any(config.get(field)!=prepared[value] for field,value in
                       (('stoploss','native_stoploss'),('minimal_roi','native_roi')))):
                    raise PermissionError('Native protections changed')
            return guard()  # Pass Core's exact scoped receipt to native delivery.
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
        trades=self.desk.attributed_trades()
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

