"""Bound desktop observation using the existing MT5 adapter, six rules and Core ingress."""
from copy import deepcopy
import threading
import time
from pathlib import Path
from modules.mt5_bridge import LOCK, MT5Unavailable
from modules.market_evidence import recognize, closed_rows


class DesktopMarketIntelligence:
    def __init__(self, bridge, core_analysis):
        self.bridge=bridge
        self.core_analysis=core_analysis
        self._cache={}
        self._lock=threading.Lock()

    def binding(self):
        return {**self.bridge.connection_record(),'execution_authorized':False}

    def observe(self, symbol, expected_account, expected_terminal):
        if not symbol or len(symbol)>80:raise ValueError('Explicit broker symbol required')
        start=time.perf_counter()
        with self._lock:
            with LOCK:
                api,account,terminal=self.bridge.connect()
                identity=self.bridge.account_record(api,account,terminal)
                if identity['identity']!=expected_account or identity['terminal_id']!=expected_terminal:
                    raise ValueError('Desktop account or terminal changed; explicitly bind again')
                key=(expected_account,expected_terminal,symbol)
                cached=self._cache.get(key)
                if cached and time.monotonic()-cached[0]<5:
                    result=deepcopy(cached[1]);result['cache_hit']=True
                    result['receipt_age_seconds']=time.time()-result['received_at']
                    return result
                snapshot=self.bridge.snapshot(symbol)
                frames={'M5':snapshot['candles']}
                for name in ('H1','H4'):
                    native=getattr(api,'TIMEFRAME_'+name,None)
                    rows=api.copy_rates_from_pos(symbol,native,1,100) if native is not None else None
                    frames[name]=[{'timestamp':int(r['time']),**{k:float(r[k]) for k in ('open','high','low','close')},'volume':int(r['tick_volume'])} for r in rows] if rows is not None else []
                after=self.bridge.account_record(*self.bridge.connect())
                if after!=identity:raise MT5Unavailable('Account changed during intelligence read')
            result=analyze_snapshot({**snapshot,'symbol':symbol},frames,identity,self.core_analysis,'mt5_desktop',start)
            if len(self._cache)>=16:self._cache.pop(next(iter(self._cache)))
            self._cache[key]=(time.monotonic(),deepcopy(result))
            return result


def analyze_snapshot(snapshot,frames,identity,core_analysis,adapter,start=None):
    """One shared evidence/strategy ingress for independent terminal sources."""
    start=time.perf_counter() if start is None else start
    symbol=snapshot['symbol']
    received=time.time();quote=snapshot.get('quote') or {};clock=quote.get('timestamp')
    if not isinstance(clock,(int,float)):raise MT5Unavailable('Broker clock unavailable')
    source={'adapter':adapter,'account_identity':identity['identity'],
        'terminal_id':identity['terminal_id'],'server':identity['server'],'environment':identity['environment']}
    evidence={frame:recognize(rows,symbol,frame,seconds,clock,source)
              for (frame,rows),seconds in zip(frames.items(),(300,3600,14400))}
    m5=closed_rows(frames['M5'],300,clock)
    # Broker-clock features remain visible, but cannot claim UTC-valid Core freshness.
    utc_verified=abs(clock-received)<=5
    observation={'symbol':symbol,'venue':identity['server'],'timeframe':'5m','mode':'observe',
        'account_scope':identity['identity'],'source':adapter,'candles':m5,
        'received_at':received,'fresh':bool(utc_verified and quote.get('fresh')),
        'evidence_schema':'market-evidence-v1','market_evidence':evidence}
    from modules.mt5_bridge import summarize_completed
    observation['market_context']={frame:summarize_completed(
        [{'time':r['timestamp'],**{k:r[k] for k in ('open','high','low','close')}} for r in rows],frame,clock)
        for frame,rows in frames.items()}
    response=core_analysis(observation)
    comparison=response.get('analysis',{'candidates':[], 'assessment_complete':False,
        'side':'wait','selection_reason':'Core analysis unavailable or freshness unverified'})
    result={'schema_version':'desktop-intelligence-v1' if adapter=='mt5_desktop' else 'source-intelligence-v1','connected':True,'account':identity,
        'symbol':symbol,'prediction_inputs':{'candles':m5},'received_at':received,'quote':quote,'specification':snapshot.get('specification'),
        'evidence':evidence,'strategy_comparison':comparison,'core':response,
        'utc_clock_verified':utc_verified,'fresh':observation['fresh'],
        'execution_authorized':False,'execution_mode':'observation_only',
        'vps_dependency':adapter!='mt5_desktop','cache_hit':False,
        'duration_ms':round((time.perf_counter()-start)*1000,2),
        'limitations':['Only supplied closed-candle frames are recognized; other frames remain unavailable',
            'Pattern reliability unevaluated; indicator parity not verified',
            'No MQL5 buffer publisher or automatic script execution']}
    return result


def component_inventory(data_path):
    """Bounded metadata inventory; compiled internals and execution are unavailable."""
    root=Path(data_path)/'MQL5'
    records=[]
    for category in ('Indicators','Experts','Scripts'):
        base=root/category
        if not base.is_dir():continue
        for path in base.rglob('*'):
            if len(records)>=500:return {'components':records,'truncated':True}
            if path.suffix.lower() not in ('.mq5','.ex5') or path.is_symlink():continue
            try:
                path.resolve().relative_to(root.resolve())
                records.append({'name':path.stem,'path':path.relative_to(root).as_posix(),
                    'category':category,'file_type':path.suffix.lower(),
                    'source_available':path.suffix.lower()=='.mq5',
                    'version':None,'inputs':None,'outputs':None,'approved_for_observation':False,
                    'execution_enabled':False,'required_permissions':'separate_allowlist_required'})
            except (OSError,ValueError):continue
    return {'components':records,'truncated':False,'execution_enabled':False}
