"""Official desktop MT5 IPC adapter for observation and demo preflight.

Attaches to the current terminal session. Never logs in, switches accounts,
    changes terminal permissions. Demo order submission is handled separately
    by the durable human-only ticket controller. No paid inference is used.
"""
import hashlib
import math
import os
from pathlib import Path
import threading
import time

LOCK = threading.RLock()


class MT5Unavailable(RuntimeError):
    pass


class MT5Bridge:
    def __init__(self, api=None):
        self._api = api
        self._ticks = {}

    def connect(self):
        if self._api is None:
            try:
                import MetaTrader5
                self._api = MetaTrader5
            except ImportError:
                raise MT5Unavailable('Official MT5 connector is not installed in the host environment')
        api = self._api
        terminal = os.getenv('NIBLIT_MT5_TERMINAL', r'C:\Program Files\MetaTrader 5\terminal64.exe')
        if not api.initialize(terminal, timeout=5000):
            raise MT5Unavailable('Cannot attach to the desktop MT5 terminal; open it and sign in')
        account, info = api.account_info(), api.terminal_info()
        if account is None or info is None or not info.connected:
            raise MT5Unavailable('MT5 has no connected account; check the terminal connection')
        return api, account, info

    @staticmethod
    def identity(account):
        # Correlate account switches without exposing login/name in browser logs.
        return hashlib.sha256(f'{account.server}:{account.login}'.encode()).hexdigest()[:16]

    def tick(self, api, symbol, account):
        tick = api.symbol_info_tick(symbol)
        if tick is None: return {'fresh':False,'reason':'No broker tick received'}
        timestamp = (getattr(tick,'time_msc',0) or tick.time*1000)/1000
        key = (self.identity(account),symbol)
        previous = self._ticks.get(key)
        monotonic = time.monotonic()
        advanced = previous is not None and timestamp>previous[0]
        changed_at = monotonic if advanced else previous[1] if previous and timestamp==previous[0] else None
        self._ticks[key] = (timestamp,changed_at)
        age = monotonic-changed_at if changed_at is not None else None
        valid = all(math.isfinite(v) and v>0 for v in (tick.bid,tick.ask)) and tick.ask>=tick.bid
        return {'bid':tick.bid,'ask':tick.ask,'spread':tick.ask-tick.bid,'timestamp':timestamp,
                'age_seconds':age,'fresh':valid and age is not None and age<=60,
                'timestamp_basis':'broker_clock_unverified',
                'raw_clock_difference_seconds':timestamp-time.time(),
                'freshness_basis':'locally observed tick advancement; absolute UTC age is not verified'}

    def snapshot(self, symbol=None):
        with LOCK:
            api, account, terminal = self.connect()
            demo = account.trade_mode==api.ACCOUNT_TRADE_MODE_DEMO
            all_symbols = api.symbols_get()
            if all_symbols is None: raise MT5Unavailable('MT5 could not list broker symbols')
            symbols = sorted(s.name for s in all_symbols if s.visible)[:100]
            selected = symbol or ('EURUSD' if 'EURUSD' in symbols else (symbols[0] if symbols else None))
            if selected and selected not in symbols:
                raise ValueError('Choose a visible broker symbol from the MT5 list')
            tick, candles, specs = None, [], None
            if selected:
                tick = self.tick(api,selected,account)
                info = api.symbol_info(selected)
                if info:
                    specs = {key:getattr(info,key,None) for key in ('digits','point','volume_min','volume_max',
                        'volume_step','trade_contract_size','trade_mode','filling_mode')}
                # Position 1 starts with the previous completed bar, not current bar 0.
                rates = api.copy_rates_from_pos(selected,api.TIMEFRAME_M5,1,200)
                if rates is not None:
                    candles = [{'timestamp':int(r['time']),'open':float(r['open']),'high':float(r['high']),
                        'low':float(r['low']),'close':float(r['close']),'volume':int(r['tick_volume'])}
                        for r in rates]
            positions = api.positions_get()
            orders = api.orders_get()
            if positions is None or orders is None:
                raise MT5Unavailable('MT5 could not read positions or pending orders')
            confirmed_account = api.account_info()
            if confirmed_account is None or self.identity(confirmed_account)!=self.identity(account):
                raise MT5Unavailable('MT5 account changed while reading; refresh the connection')
            return {'connected':True,'adapter':'mt5_desktop','checked_at':time.time(),
                'account':{'identity':self.identity(account),'server':account.server,'currency':account.currency,
                    'mode':'demo' if demo else 'live_read_only','balance':account.balance,'equity':account.equity,
                    'profit':account.profit,'margin':account.margin,'free_margin':account.margin_free,
                    'leverage':account.leverage,'trade_allowed':account.trade_allowed},
                'terminal':{'connected':terminal.connected,'build':terminal.build,
                    'trade_allowed':terminal.trade_allowed,'python_trading_disabled':terminal.tradeapi_disabled},
                'symbols':symbols,'symbol':selected,'quote':tick,'specification':specs,'candles':candles,
                'positions':[{key:getattr(p,key,None) for key in ('ticket','symbol','type','volume',
                    'price_open','price_current','profit','sl','tp','time','magic')} for p in positions],
                'pending_order_count':len(orders),'capabilities':{'quotes':True,'positions':True,
                    'completed_candles':True,'demo_preflight':demo,
                    'order_submission':bool(demo and terminal.trade_allowed and not terminal.tradeapi_disabled and account.trade_allowed)},
                'notice':'Manual demo orders require a reviewed ticket. Funded-account submissions are blocked.'}

    def check_order(self, symbol, side, volume, expected_account):
        with LOCK:
            api, account, terminal = self.connect()
            if account.trade_mode!=api.ACCOUNT_TRADE_MODE_DEMO:
                raise ValueError('Order preflight is restricted to verified demo accounts')
            if self.identity(account)!=expected_account:
                raise ValueError('MT5 account changed; refresh before testing')
            if side not in ('buy','sell') or not math.isfinite(volume) or not 0<volume<=.01:
                raise ValueError('Preflight accepts buy/sell and at most 0.01 lots')
            info = api.symbol_info(symbol)
            if info is None or not info.visible: raise ValueError('Select a visible broker symbol')
            if not info.volume_min<=volume<=info.volume_max or abs((volume-info.volume_min)/info.volume_step-round((volume-info.volume_min)/info.volume_step))>1e-6:
                raise ValueError('Volume does not match the broker minimum or step')
            tick = self.tick(api,symbol,account)
            if not tick['fresh']: raise ValueError('Broker quote is stale or invalid; wait for a fresh tick')
            # Filling modes are broker symbol flags, not the ORDER_FILLING enum.
            fill = api.ORDER_FILLING_FOK if info.filling_mode & 1 else api.ORDER_FILLING_IOC if info.filling_mode & 2 else api.ORDER_FILLING_RETURN
            request = {'action':api.TRADE_ACTION_DEAL,'symbol':symbol,'volume':volume,
                'type':api.ORDER_TYPE_BUY if side=='buy' else api.ORDER_TYPE_SELL,
                'price':tick['ask'] if side=='buy' else tick['bid'],'deviation':20,
                'type_time':api.ORDER_TIME_GTC,'type_filling':fill,'comment':'Niblit preflight only'}
            result = api.order_check(request)
            if result is None: raise MT5Unavailable('MT5 order preflight returned no result')
            # Check account again, before presenting any result from a changed session.
            current = api.account_info()
            if current is None or self.identity(current)!=expected_account or current.trade_mode!=api.ACCOUNT_TRADE_MODE_DEMO:
                raise ValueError('MT5 account changed during preflight; discard this result')
            return {'checked':True,'accepted':result.retcode==0,'retcode':result.retcode,
                'comment':result.comment,'margin':result.margin,'free_margin':result.margin_free,
                'symbol':symbol,'side':side,'volume':volume,'price':request['price'],
                'order_submitted':False,'terminal_execution_allowed':bool(terminal.trade_allowed and not terminal.tradeapi_disabled and account.trade_allowed),
                'notice':'Broker preflight only; acceptance does not guarantee a future fill. Terminal permissions are unchanged.'}
