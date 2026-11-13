"""Observation-only wrapper around the existing pinned demo market transport.

The adapter's prepare/submit/close capabilities are deliberately not exposed.
"""
import threading
from modules.desktop_market_intelligence import analyze_snapshot


class RemoteMarketIntelligence:
    def __init__(self,adapter,core_analysis):
        self._adapter=adapter;self._core_analysis=core_analysis;self._lock=threading.Lock()

    def observe(self,symbol,expected_account,expected_terminal):
        if not isinstance(symbol,str) or not 0<len(symbol)<=80:raise ValueError('Explicit symbol required')
        with self._lock:
            market=self._adapter.market(symbol)
            identity=market.get('account') or {}
            if (market.get('connected') is not True or market.get('symbol')!=symbol
                    or identity.get('identity')!=expected_account or identity.get('terminal_id')!=expected_terminal):
                raise ValueError('Remote source binding changed or unavailable')
            result=analyze_snapshot(market,{'M5':market.get('candles') or []},identity,
                                    self._core_analysis,'mt5_vps_gateway')
            result['limitations'].append('Remote recognition currently M5 only; no account switching or execution failover')
            return result
