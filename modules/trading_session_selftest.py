"""Offline integration fixture: actual Core policy/tickets, broker doubles only.

This command never constructs a real broker connector or loads private config.
"""
import json
import sqlite3
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace as Obj


class FixtureGateway:
    def __init__(self,path):self.path=Path(path);self.denied=False
    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=10);db.row_factory=sqlite3.Row
        try:
            with db:yield db
        finally:db.close()
    def require(self,action,*args,**kwargs):
        if self.denied and action=='ingest':raise PermissionError('Fixture memory permission revoked')
    def audit(self,db,kind,ident,**kwargs):
        db.execute('CREATE TABLE IF NOT EXISTS fixture_audit(kind TEXT,id TEXT)')
        db.execute('INSERT INTO fixture_audit VALUES(?,?)',(kind,ident))


class FixtureMT5:
    ACCOUNT_TRADE_MODE_DEMO=0
    ORDER_TYPE_BUY=0;ORDER_TYPE_SELL=1;TRADE_ACTION_DEAL=1
    ORDER_FILLING_FOK=0;ORDER_FILLING_IOC=1;ORDER_FILLING_RETURN=2;ORDER_TIME_GTC=0;TIMEFRAME_M5=5
    def __init__(self):
        self.account=Obj(server='OFFLINE_FIXTURE',login=1,trade_mode=0,equity=1000000.,balance=1000000.,
            currency='USD',profit=0.,margin=0.,margin_free=1000000.,leverage=1,trade_allowed=True)
        self.info=Obj(visible=True,name='EURUSD',currency_profit='USD',currency_base='EUR',volume_min=.01,
            volume_max=10.,volume_step=.01,point=.00001,digits=5,trade_stops_level=10,filling_mode=1,
            trade_contract_size=100000.,trade_mode=4)
        self.price=160.;self.ticks=0;self.positions=[];self.deals=[];self.sent=[];self.behavior='filled'
        self.bar=int(time.time()//300)*300-300
        self.rates=[dict(time=self.bar-(59-i)*300,open=100.+i,high=101.+i,low=99.+i,close=100.5+i,tick_volume=10) for i in range(60)]
    def initialize(self,*args,**kwargs):return True
    def account_info(self):return self.account
    def terminal_info(self):return Obj(connected=True,trade_allowed=True,tradeapi_disabled=False,build=1)
    def symbols_get(self):return [self.info]
    def symbol_info(self,symbol):return self.info if symbol=='EURUSD' else None
    def symbol_info_tick(self,symbol):
        self.ticks+=1
        return Obj(time=self.bar+310,time_msc=(self.bar+310)*1000+self.ticks,bid=self.price,ask=self.price+.00002)
    def copy_rates_from_pos(self,*args):return self.rates
    def positions_get(self):return tuple(self.positions)
    def orders_get(self):return ()
    def history_deals_get(self,*args):return tuple(self.deals)
    def order_calc_profit(self,side,symbol,volume,entry,exit):return (exit-entry)*volume*100000*(1 if side==0 else -1)
    def order_check(self,request):return Obj(retcode=0,margin=10.,margin_free=self.account.margin_free,comment='Fixture preflight')
    def order_send(self,request):
        self.sent.append(dict(request))
        if self.behavior=='timeout':raise TimeoutError('Fixture ambiguous delivery')
        if self.behavior=='reject':return Obj(retcode=10006,deal=0,order=0,volume=0.,price=request['price'],comment='Fixture reject')
        ident=100+len(self.sent);position=request.get('position',ident)
        closing='position' in request
        if closing:self.positions=[p for p in self.positions if p.ticket!=position]
        else:
            self.positions.append(Obj(ticket=ident,symbol=request['symbol'],type=request['type'],volume=request['volume'],
                price_open=request['price'],price_current=self.price,profit=0.,sl=request['sl'],tp=request['tp'],time=self.bar+310,magic=request['magic']))
        self.deals.append(Obj(ticket=1000+ident,order=ident,position_id=position,symbol=request['symbol'],
            type=request['type'],magic=request['magic'],comment=request['comment'],entry=1 if closing else 0,
            profit=5. if closing else 0.,commission=-.1,swap=0.,fee=0.))
        return Obj(retcode=10010 if self.behavior=='partial' else 10009,deal=1000+ident,order=ident,
            volume=request['volume'],price=request['price'],comment='Fixture fill')


def fixture(folder):
    from modules.mt5_bridge import MT5Bridge
    from modules.mt5_orders import DemoOrders
    from modules.memory_laboratory.runtime import MemoryRuntime
    from modules.core_trading_sessions import CoreTradingSessions
    from modules.trading_session_adapters import MT5SessionAdapter
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    api=FixtureMT5();bridge=MT5Bridge(api);bridge.snapshot('EURUSD');bridge.snapshot('EURUSD')
    orders=DemoOrders(bridge,folder/'mt5-orders.sqlite')
    gateway=FixtureGateway(folder/'canonical.sqlite');runtime=MemoryRuntime(gateway)
    service=CoreTradingSessions(runtime,{'mt5':MT5SessionAdapter(bridge,orders)},journal=folder/'demo-learning.sqlite',notify=lambda _:None)
    return Obj(api=api,bridge=bridge,orders=orders,gateway=gateway,runtime=runtime,service=service,
        bot=service.observe('mt5','EURUSD',threaded=False))


def activate(f,**kwargs):
    proposal=f.service.propose('mt5','EURUSD',60,kwargs.get('limits'))
    f.service.activate(proposal['id'],proposal['spec_hash'],threaded=False)
    return proposal


def exercise(folder):
    f=fixture(folder);f.bot.step()
    assert not f.api.sent,'Observation must not submit'
    proposal=activate(f);f.bot.step()
    assert len(f.api.sent)==1,f.bot.error
    f.bot.step();assert len(f.api.sent)==1,'Same-bar position must not be duplicated'
    f.api.price+=.01;f.bot.step();assert len(f.api.sent)==2,f.bot.error
    f.bot.step()
    status=f.service.status()
    assert any(json.loads(o['result'] or '{}').get('realized_net')is not None and abs(json.loads(o['result'] or '{}').get('realized_net',0)-4.8)<1e-8 for o in status['orders']),[(o['state'],o['result']) for o in status['orders']]
    f.service.stop(emergency=True);f.bot.step();assert len(f.api.sent)==2
    with f.gateway.db() as db:
        receipts=db.execute('SELECT count(*) FROM ingestion_outbox').fetchone()[0]
        events=db.execute('SELECT count(*) FROM trading_events WHERE memory_receipt IS NOT NULL').fetchone()[0]
    assert receipts==events and events>=8
    return {'scope':'offline broker double; actual Core/PermissionManager/TaskAuthority/six-strategy/MT5-ticket/memory-outbox path',
        'passed':True,'fixture_submissions':len(f.api.sent),'real_broker_orders':0,'durable_events':events,
        'session_state':f.service.session(proposal['id'])['state'],'emergency_stopped':f.service.status()['emergency_stopped']}


class FixtureFreqtrade:
    def __init__(self):
        self.price=160.;self.sent=[];self.trades=[];self.behavior='filled'
        self.bar=int(time.time()//300)*300-300
        self.config=dict(dry_run=True,state='running',exchange='binance',trading_mode='futures',
            strategy='NiblitCoreManaged',timeframe='5m',stake_currency='USDT',max_open_trades=3,
            force_entry_enable=True,version='fixture',stoploss=-.01,minimal_roi={'0':.02},fee=.001)
        self.candles=[dict(timestamp=self.bar-(59-i)*300,open=100.+i,high=101.+i,low=99.+i,close=100.5+i,volume=10) for i in range(60)]
    def rpc(self,path,payload=None):
        if path=='show_config':return dict(self.config)
        if path=='status':return [dict(p) for p in self.trades if p['is_open']]
        if path=='balance':return {'total':10000.,'currencies':[{'currency':'USDT','free':10000.-sum(p['stake_amount'] for p in self.trades if p['is_open'])}]}
        if path.startswith('daily'):return {'data':[{'date':datetime_utc_day(),'abs_profit':'0.0'}]}
        if path=='whitelist':return {'whitelist':['BTC/USDT:USDT']}
        if path.startswith('trades'):return {'trades':[dict(p) for p in self.trades]}
        if path in ('forceenter','forceexit'):
            self.sent.append((path,dict(payload)))
            if self.behavior=='timeout':raise TimeoutError('Fixture provider ambiguity')
            if path=='forceenter':
                from modules.freqtrade_core_claim import confirm_core_entry
                from modules.trading_desk import FreqtradeRejection
                native=dict(self.config,exchange={'name':'binance'},db_url='sqlite:///fixture.sqlite')
                allowed=confirm_core_entry(native,self.config['stoploss'],self.config['minimal_roi'],
                    pair=payload['pair'],side=payload['side'],amount=payload['stakeamount']/self.price,
                    rate=self.price,entry_tag=payload['entry_tag'],verify=self.verify_core)
                if not allowed:raise FreqtradeRejection('Native Core-managed fixture rejected the entry')
                short=payload['side']=='short';ident=len(self.trades)+1
                trade=dict(trade_id=ident,pair=payload['pair'],is_open=True,is_short=short,
                    stake_amount=payload['stakeamount'],amount=payload['stakeamount']/self.price,
                    open_rate=self.price,profit_abs=0.,leverage=1.,stop_loss_ratio=-.01,
                    stop_loss_abs=self.price*(1.01 if short else .99),enter_tag=payload['entry_tag'],
                    has_open_orders=self.behavior=='partial')
                self.trades.append(trade);return dict(trade)
            trade=next(p for p in self.trades if str(p['trade_id'])==payload['tradeid'])
            trade.update(is_open=False,close_profit_abs=1.5,profit_abs=1.5);return dict(trade)
        raise ValueError('Unexpected fixture RPC '+path)


def datetime_utc_day():
    from datetime import datetime,timezone
    return datetime.now(timezone.utc).date().isoformat()


def freq_fixture(folder):
    from modules.trading_desk import Desk
    from modules.memory_laboratory.runtime import MemoryRuntime
    from modules.core_trading_sessions import CoreTradingSessions
    from modules.trading_session_adapters import FreqtradeSessionAdapter
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    rpc=FixtureFreqtrade();desk=Desk(folder/'Niblit',transport=rpc.rpc)
    private={'dry_run':True,'exchange':{'name':'binance'},'stake_currency':'USDT','trading_mode':'futures','db_url':'sqlite:///fixture.sqlite'}
    desk.connection=lambda:(private,('fixture','fixture'))
    desk.market=lambda symbol,config=None:{'candles':rpc.candles,'fresh':True,'last':rpc.candles[-1]}
    desk.quote=lambda symbol,config=None:{'bid':rpc.price,'ask':rpc.price+.00002,'timestamp':rpc.bar+310,
        'received_at':time.time(),'fresh':True}
    def minimum(symbol,config,price):
        desk.market_rules=(time.monotonic(),{'BTCUSDT':{'filters':[{'filterType':'LOT_SIZE','stepSize':'.001','minQty':'.001'}]}})
        return 5.
    desk.minimum_stake=minimum
    gateway=FixtureGateway(folder/'canonical.sqlite');runtime=MemoryRuntime(gateway)
    service=CoreTradingSessions(runtime,{'freqtrade':FreqtradeSessionAdapter(desk)},journal=folder/'demo-learning.sqlite',notify=lambda _:None)
    rpc.verify_core=service.native_entry_receipt
    return Obj(api=rpc,desk=desk,gateway=gateway,runtime=runtime,service=service,
               bot=service.observe('freqtrade','BTC/USDT:USDT',threaded=False))


def exercise_freq(folder):
    f=freq_fixture(folder);f.bot.step();assert not f.api.sent
    proposal=f.service.propose('freqtrade','BTC/USDT:USDT',60)
    f.service.activate(proposal['id'],proposal['spec_hash'],threaded=False)
    f.bot.step();assert len(f.api.sent)==1,f.bot.error
    f.bot.step();assert len(f.api.sent)==1
    f.api.price*=1.03;f.bot.step();assert len(f.api.sent)==2,f.bot.error
    f.bot.step()
    results=[json.loads(o['result'] or '{}') for o in f.service.status()['orders']]
    assert any(r.get('realized_net')==1.5 for r in results),results
    return {'passed':True,'scope':'actual Core/consensus/risk/Freqtrade-ticket/RPC-double/reconciliation/canonical-outbox',
            'fixture_submissions':2,'real_broker_orders':0}


def main():
    with tempfile.TemporaryDirectory(prefix='niblit-trading-selftest-') as folder:
        result={'mt5':exercise(Path(folder)/'mt5'),'freqtrade':exercise_freq(Path(folder)/'freqtrade'),'real_broker_orders':0,'passed':True}
    print(json.dumps(result,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
