"""Official desktop MT5 IPC adapter for observation and demo preflight.

Attaches to the current terminal session. Never logs in, switches accounts,
    changes terminal permissions. Demo order submission is handled separately
    by the durable human-only ticket controller. No paid inference is used.
"""
from collections import deque
import hashlib
import math
import os
from pathlib import Path
import threading
import time

LOCK = threading.RLock()


TIMEFRAME_SECONDS = {'M1':60,'M5':300,'M15':900,'M30':1800,'H1':3600,'H4':14400,'D1':86400,'W1':604800}


def summarize_completed(rows, frame, as_of):
    """Summarize native closed bars as of a timestamp in the broker clock."""
    seconds = TIMEFRAME_SECONDS[frame]
    if not isinstance(as_of, (int, float)) or not math.isfinite(as_of):
        return {'status':'clock_unavailable'}
    if rows is None:
        return {'status':'missing'}
    try:
        bars = [(int(row['time']), *(float(row[key]) for key in ('open','high','low','close')))
                for row in rows]
        if any(b[0] <= a[0] for a,b in zip(bars,bars[1:])):
            return {'status':'unordered'}
        if any(not all(math.isfinite(x) and x > 0 for x in b) or
               b[3] > min(b[1],b[4]) or b[2] < max(b[1],b[4]) for b in bars):
            return {'status':'invalid_ohlc'}
    except (TypeError, ValueError, KeyError, OverflowError):
        return {'status':'invalid_ohlc'}
    closed = [bar for bar in bars if bar[0]+seconds <= as_of]
    if len(closed) < 20:
        return {'status':'insufficient_closed_history'}
    sample = closed[-20:]
    completed_at = sample[-1][0]+seconds
    if as_of-completed_at > 2*seconds:
        return {'status':'stale','completed_at':completed_at}
    if any(b[0]-a[0] != seconds for a,b in zip(sample,sample[1:])):
        return {'status':'session_gap','completed_at':completed_at}
    first = sum(b[4] for b in sample[:10])/10
    last = sum(b[4] for b in sample[10:])/10
    return {'status':'ready','trend':'up' if last>first else 'down' if last<first else 'flat',
            'completed_at':completed_at,'support':min(b[3] for b in sample),
            'resistance':max(b[2] for b in sample),'source':'mt5_native_closed_bars'}


class MT5Unavailable(RuntimeError):
    pass


class MT5Bridge:
    def __init__(self, api=None):
        self._api = api
        self._ticks = {}
        self._spread_samples = {}

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

    def account_record(self, api, account, terminal):
        mode = next((label for name, label in (
            ('ACCOUNT_TRADE_MODE_DEMO', 'demo'),
            ('ACCOUNT_TRADE_MODE_REAL', 'live'),
            ('ACCOUNT_TRADE_MODE_CONTEST', 'contest'),
        ) if getattr(api, name, None) is not None and getattr(api, name) == account.trade_mode), 'unknown')
        terminal_path = str(getattr(terminal, 'path', '') or
                            os.getenv('NIBLIT_MT5_TERMINAL', 'C:/Program Files/MetaTrader 5/terminal64.exe'))
        terminal_key = os.path.normcase(terminal_path) + '|' + os.path.normcase(str(getattr(terminal, 'data_path', '')))
        return {'identity':self.identity(account), 'login':str(account.login),
                'server':str(account.server), 'broker':str(getattr(account, 'company', '') or account.server),
                'environment':mode, 'terminal_id':hashlib.sha256(terminal_key.encode()).hexdigest()[:20],
                'terminal_path':terminal_path}

    def connection_record(self):
        with LOCK:
            return self.account_record(*self.connect())

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

    def snapshot(self, symbol=None, *, allow_symbol_fallback=False, include_context=False):
        with LOCK:
            api, account, terminal = self.connect()
            demo = account.trade_mode==api.ACCOUNT_TRADE_MODE_DEMO
            all_symbols = api.symbols_get()
            if all_symbols is None: raise MT5Unavailable('MT5 could not list broker symbols')
            symbols = sorted(s.name for s in all_symbols if s.visible)[:100]
            selected = symbol or ('EURUSD' if 'EURUSD' in symbols else (symbols[0] if symbols else None))
            unavailable_symbol = None
            if selected and selected not in symbols:
                if not allow_symbol_fallback:
                    raise ValueError('Choose a visible broker symbol from the MT5 list')
                unavailable_symbol, selected = selected, None
            tick, candles, specs, context = None, [], None, {}
            if selected:
                tick = self.tick(api,selected,account)
                info = api.symbol_info(selected)
                if info:
                    specs = {key:getattr(info,key,None) for key in ('digits','point','volume_min','volume_max',
                        'volume_step','trade_contract_size','trade_mode','filling_mode','trade_tick_size',
                        'trade_tick_value','trade_tick_value_profit','trade_tick_value_loss','trade_stops_level',
                        'trade_freeze_level','trade_exemode','trade_calc_mode','swap_mode','swap_long','swap_short',
                        'swap_rollover3days','currency_base','currency_profit','currency_margin')}
                    point = specs['point']
                    if point and point > 0 and 'spread' in tick:
                        tick['spread_points'] = tick['spread']/point
                        if include_context and tick['fresh']:
                            key = (self.identity(account), selected)
                            if key not in self._spread_samples and len(self._spread_samples) >= 128:
                                self._spread_samples.pop(next(iter(self._spread_samples)))
                            samples = self._spread_samples.setdefault(key, deque(maxlen=120))
                            if not samples or tick['timestamp'] > samples[-1][0]:
                                samples.append((tick['timestamp'], tick['spread_points']))
                            ordered = sorted(value for _, value in samples)
                            tick['spread_sample'] = {'count':len(ordered),'unit':'points',
                                'median':ordered[len(ordered)//2],
                                'p95':ordered[math.ceil(.95*len(ordered))-1]}
                # Position 1 starts with the previous completed bar, not current bar 0.
                rates = api.copy_rates_from_pos(selected,api.TIMEFRAME_M5,1,200)
                if rates is not None:
                    candles = [{'timestamp':int(r['time']),'open':float(r['open']),'high':float(r['high']),
                        'low':float(r['low']),'close':float(r['close']),'volume':int(r['tick_volume'])}
                        for r in rates]
                if include_context:
                    for frame in TIMEFRAME_SECONDS:
                        native_frame = getattr(api, 'TIMEFRAME_'+frame, None)
                        native_rows = (rates if frame == 'M5' else
                                       api.copy_rates_from_pos(selected,native_frame,1,32)
                                       if native_frame is not None else None)
                        context[frame] = summarize_completed(native_rows, frame, tick.get('timestamp'))
            positions = api.positions_get()
            orders = api.orders_get()
            if positions is None or orders is None:
                raise MT5Unavailable('MT5 could not read positions or pending orders')
            confirmed_account = api.account_info()
            confirmed_terminal = api.terminal_info()
            if (confirmed_account is None or confirmed_terminal is None or not confirmed_terminal.connected
                    or self.account_record(api, confirmed_account, confirmed_terminal) != self.account_record(api, account, terminal)):
                raise MT5Unavailable('MT5 account changed while reading; refresh the connection')
            return {'connected':True,'adapter':'mt5_desktop','checked_at':time.time(),
                'account':{**{k:v for k,v in self.account_record(api,account,terminal).items() if k != 'login'},'currency':account.currency,
                    'mode':'demo' if demo else 'live_read_only','balance':account.balance,'equity':account.equity,
                    'profit':account.profit,'margin':account.margin,'free_margin':account.margin_free,
                    'leverage':account.leverage,'trade_allowed':account.trade_allowed,
                    'account_subtype':None,'margin_mode':getattr(account,'margin_mode',None),
                    'stopout_mode':getattr(account,'margin_so_mode',None),
                    'margin_call':getattr(account,'margin_so_call',None),'stopout':getattr(account,'margin_so_so',None)},
                'terminal':{'connected':terminal.connected,'build':terminal.build,
                    'trade_allowed':terminal.trade_allowed,'python_trading_disabled':terminal.tradeapi_disabled},
                'symbols':symbols,'symbol':selected,'unavailable_symbol':unavailable_symbol,'quote':tick,'specification':specs,'candles':candles,
                'positions':[{key:getattr(p,key,None) for key in ('ticket','symbol','type','volume',
                    'price_open','price_current','profit','sl','tp','time','magic')} for p in positions],
                'market_context':context,'field_provenance':{'account':'mt5_account_info',
                    'specification':'mt5_symbol_info','quote':'mt5_symbol_info_tick',
                    'account_subtype':'unknown','commission':'unknown'},'pending_order_count':len(orders),'capabilities':{'quotes':True,'positions':True,
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
