#!/usr/bin/env python3
"""
modules/market_data_providers.py — Multi-provider free market data for Niblit.

Provides :class:`MarketDataProviders`, a unified gateway to multiple free
(or free-tier) market data sources covering crypto, stocks, ETFs, forex,
CFDs, and indices.

Supported providers
-------------------
* **yfinance** (Yahoo Finance) — stocks, ETFs, indices, forex pairs, crypto.
  No API key required.  Free, unlimited (rate-limited).
  Install: ``pip install yfinance``

* **CCXT** — 100+ crypto exchanges (Binance, Coinbase, Kraken, Bybit, OKX, …).
  No API key needed for public market-data endpoints.
  Authenticated trading uses CCXT_EXCHANGE_API_KEY / CCXT_EXCHANGE_API_SECRET.
  Install: ``pip install ccxt``

* **Twelve Data** — stocks, ETFs, forex, crypto, indices.
  Free tier: 800 API credits / day, 8 req/min.
  Set TWELVE_DATA_API_KEY env var.
  Install: ``pip install twelvedata``

* **OANDA** — forex, CFDs, indices via REST v20.
  Free practice (paper) account available.
  Set OANDA_API_KEY and OANDA_ACCOUNT_ID env vars.
  Set OANDA_ENVIRONMENT=practice (default) or live.
  Install: ``pip install oandapyV20``

* **Alpaca** — US equities and crypto.
  Free paper-trading account; free market data for IEX/SIP.
  Set ALPACA_API_KEY and ALPACA_API_SECRET env vars.
  Install: ``pip install alpaca-py``

All methods degrade gracefully — if a provider library is not installed,
the method returns an explanatory string rather than raising.

Wiring
------
Instantiated in ``niblit_core._init_optional_services()`` as
``self.market_data_providers``.  The TradingBrain and LeanEngine can request
data through the unified :meth:`fetch` dispatcher.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("MarketDataProviders")

# ── optional provider imports ─────────────────────────────────────────────────

try:
    import yfinance as _yf
    _YFINANCE_OK = True
except (ImportError, ModuleNotFoundError, SyntaxError):
    _yf = None  # type: ignore[assignment]
    _YFINANCE_OK = False

try:
    import ccxt as _ccxt
    _CCXT_OK = True
except (ImportError, ModuleNotFoundError, SyntaxError):
    _ccxt = None  # type: ignore[assignment]
    _CCXT_OK = False

try:
    from twelvedata import TDClient as _TDClient
    _TWELVE_OK = True
except (ImportError, ModuleNotFoundError, SyntaxError):
    _TDClient = None  # type: ignore[assignment]
    _TWELVE_OK = False

try:
    import oandapyV20 as _oanda
    import oandapyV20.endpoints.instruments as _oanda_instr
    import oandapyV20.endpoints.accounts as _oanda_acct
    import oandapyV20.endpoints.orders as _oanda_orders
    import oandapyV20.endpoints.trades as _oanda_trades
    _OANDA_OK = True
except (ImportError, ModuleNotFoundError, SyntaxError):
    _oanda = None  # type: ignore[assignment]
    _OANDA_OK = False

try:
    from alpaca.data.historical import StockHistoricalDataClient as _AlpacaStockClient
    from alpaca.data.historical import CryptoHistoricalDataClient as _AlpacaCryptoClient
    from alpaca.data.requests import (
        StockBarsRequest as _StockBarsReq,
        CryptoBarsRequest as _CryptoBarsReq,
    )
    from alpaca.data.timeframe import TimeFrame as _AlpacaTF
    from alpaca.trading.client import TradingClient as _AlpacaTradingClient
    from alpaca.trading.requests import MarketOrderRequest as _AlpacaMktOrder
    from alpaca.trading.enums import OrderSide as _AlpacaOrderSide, TimeInForce as _AlpacaTIF
    _ALPACA_OK = True
except (ImportError, ModuleNotFoundError, SyntaxError):
    _ALPACA_OK = False

# ── notification queue ────────────────────────────────────────────────────────

try:
    from core.notification_queue import notif_queue as _notif_queue
except (ImportError, ModuleNotFoundError):
    class _NopQueue:
        def push(self, msg: str) -> None:
            pass
    _notif_queue = _NopQueue()  # type: ignore[assignment]

# ─────────────────────────────────────────────────────────────────────────────
# Provider availability helper
# ─────────────────────────────────────────────────────────────────────────────

_PROVIDER_STATUS: Dict[str, str] = {
    "yfinance":  "✅ available" if _YFINANCE_OK else "⚠️  pip install yfinance",
    "ccxt":      "✅ available" if _CCXT_OK else "⚠️  pip install ccxt",
    "twelvedata":"✅ available" if _TWELVE_OK else "⚠️  pip install twelvedata",
    "oanda":     "✅ available" if _OANDA_OK else "⚠️  pip install oandapyV20",
    "alpaca":    "✅ available" if _ALPACA_OK else "⚠️  pip install alpaca-py",
}


# ─────────────────────────────────────────────────────────────────────────────
# MarketDataProviders
# ─────────────────────────────────────────────────────────────────────────────

class MarketDataProviders:
    """Unified free-tier market data gateway for Niblit.

    Parameters
    ----------
    knowledge_db:   Optional KnowledgeDB for caching fetched data as research.
    """

    def __init__(self, knowledge_db: Optional[Any] = None) -> None:
        self._kb = knowledge_db
        # OANDA lazy client (created on first use)
        self._oanda_client: Optional[Any] = None
        # Alpaca clients (lazy)
        self._alpaca_stock: Optional[Any] = None
        self._alpaca_crypto: Optional[Any] = None
        self._alpaca_trading: Optional[Any] = None
        log.info("[MarketData] Providers: %s", list(_PROVIDER_STATUS.keys()))

    # ─────────────────────────────────────────────────────────────── status ──

    def status(self) -> str:
        lines = ["=== Market Data Providers ==="]
        for name, s in _PROVIDER_STATUS.items():
            lines.append(f"  {name:<12} {s}")
        lines.append("")
        # env var hints
        td_key = "✅ set" if os.environ.get("TWELVE_DATA_API_KEY") else "⚠️  not set (TWELVE_DATA_API_KEY)"
        oanda_key = "✅ set" if os.environ.get("OANDA_API_KEY") else "⚠️  not set (OANDA_API_KEY)"
        alpaca_key = "✅ set" if os.environ.get("ALPACA_API_KEY") else "⚠️  not set (ALPACA_API_KEY)"
        lines += [
            "API Keys:",
            f"  Twelve Data:  {td_key}",
            f"  OANDA:        {oanda_key}",
            f"  Alpaca:       {alpaca_key}",
        ]
        return "\n".join(lines)

    # ───────────────────────────────────────────────────────── unified fetch ──

    def fetch(
        self,
        symbol: str,
        provider: str = "auto",
        interval: str = "1d",
        bars: int = 100,
        **kwargs: Any,
    ) -> Any:
        """Fetch OHLCV bars for *symbol* via the chosen provider.

        Parameters
        ----------
        symbol:     Ticker / pair (e.g. ``"AAPL"``, ``"BTC/USDT"``,
                    ``"EUR_USD"``, ``"SPY"``).
        provider:   One of ``yfinance|ccxt|twelvedata|oanda|alpaca|auto``.
                    ``auto`` picks the first available provider.
        interval:   Bar interval: ``1m``, ``5m``, ``15m``, ``1h``, ``1d``, etc.
        bars:       Number of bars to fetch.
        **kwargs:   Provider-specific extras (e.g. ``exchange="binance"`` for ccxt).

        Returns
        -------
        pandas.DataFrame or list[dict] depending on provider, or str on error.
        """
        p = provider.lower()
        if p == "auto":
            # Prefer: yfinance (no key needed) → ccxt for crypto → twelvedata
            if _YFINANCE_OK:
                p = "yfinance"
            elif _CCXT_OK:
                p = "ccxt"
            elif _TWELVE_OK:
                p = "twelvedata"
            else:
                return "[MarketData] No provider available — install yfinance, ccxt, or twelvedata"

        if p == "yfinance":
            return self.yfinance_bars(symbol, interval=interval, bars=bars)
        if p == "ccxt":
            return self.ccxt_bars(symbol, interval=interval, bars=bars,
                                  exchange=kwargs.get("exchange", "binance"))
        if p == "twelvedata":
            return self.twelvedata_bars(symbol, interval=interval, bars=bars)
        if p == "oanda":
            return self.oanda_candles(symbol, interval=interval, bars=bars)
        if p == "alpaca":
            return self.alpaca_bars(symbol, interval=interval, bars=bars,
                                    asset_class=kwargs.get("asset_class", "stock"))
        return f"[MarketData] Unknown provider: {provider}"

    # ────────────────────────────────────────────────────────────── yfinance ──

    def yfinance_bars(
        self,
        symbol: str,
        interval: str = "1d",
        bars: int = 100,
    ) -> Any:
        """Fetch OHLCV bars from Yahoo Finance (no API key required).

        Covers stocks, ETFs, indices (^GSPC, ^DJI, ^IXIC, ^FTSE …),
        forex (EURUSD=X), and crypto (BTC-USD).

        Returns pandas.DataFrame with columns Open/High/Low/Close/Volume.
        """
        if not _YFINANCE_OK:
            return "[MarketData] yfinance not installed (pip install yfinance)"
        try:
            # Map bars → period string
            _period_map = {
                "1m": f"{max(1, bars // 1440 + 1)}d",
                "5m": f"{max(1, bars // 288 + 1)}d",
                "15m": f"{max(1, bars // 96 + 1)}d",
                "30m": f"{max(1, bars // 48 + 1)}d",
                "1h": f"{max(1, bars // 24 + 1)}d",
                "1d": f"{max(1, bars)}d",
                "1wk": f"{max(1, bars * 7)}d",
                "1mo": f"{max(1, bars * 31)}d",
            }
            period = _period_map.get(interval, f"{bars}d")
            ticker = _yf.Ticker(symbol)
            df = ticker.history(period=period, interval=interval)
            if df is not None and not df.empty:
                df = df.tail(bars)
                self._store_in_kb(
                    f"yfinance:{symbol}:{interval}",
                    f"Yahoo Finance bars for {symbol} ({interval}): "
                    f"latest_close={df['Close'].iloc[-1]:.4f}",
                )
                return df
            return f"[yfinance] No data for {symbol}"
        except Exception as exc:
            log.warning("[MarketData:yfinance] %s: %s", symbol, exc)
            return f"[yfinance] Error fetching {symbol}: {exc}"

    def yfinance_info(self, symbol: str) -> Dict[str, Any]:
        """Return fundamental info dict for *symbol* from Yahoo Finance."""
        if not _YFINANCE_OK:
            return {"error": "yfinance not installed"}
        try:
            return _yf.Ticker(symbol).info or {}
        except Exception as exc:
            return {"error": str(exc)}

    # ──────────────────────────────────────────────────────────────────── CCXT ──

    def ccxt_bars(
        self,
        symbol: str,
        interval: str = "1h",
        bars: int = 100,
        exchange: str = "binance",
    ) -> Any:
        """Fetch OHLCV data from a CCXT-supported exchange.

        No API key needed for public endpoints.
        *symbol* should be in CCXT format: ``"BTC/USDT"``.

        Returns list of [timestamp, open, high, low, close, volume] arrays.
        """
        if not _CCXT_OK:
            return "[MarketData] CCXT not installed (pip install ccxt)"
        try:
            exch_class = getattr(_ccxt, exchange, None)
            if exch_class is None:
                return f"[ccxt] Unknown exchange: {exchange}"
            exch = exch_class({"enableRateLimit": True})
            ohlcv = exch.fetch_ohlcv(symbol, timeframe=interval, limit=bars)
            self._store_in_kb(
                f"ccxt:{exchange}:{symbol}:{interval}",
                f"CCXT {exchange} bars for {symbol} ({interval}): "
                f"{len(ohlcv)} bars, latest_close="
                + (f"{ohlcv[-1][4]:.4f}" if ohlcv else "n/a"),
            )
            return ohlcv
        except Exception as exc:
            log.warning("[MarketData:ccxt] %s %s: %s", exchange, symbol, exc)
            return f"[ccxt] Error fetching {symbol} from {exchange}: {exc}"

    def ccxt_exchanges(self) -> List[str]:
        """Return list of all exchange IDs available in CCXT."""
        if not _CCXT_OK:
            return []
        return list(_ccxt.exchanges)  # type: ignore[attr-defined]

    def ccxt_tickers(self, exchange: str = "binance") -> Any:
        """Fetch all tickers from *exchange* (no API key required)."""
        if not _CCXT_OK:
            return "[MarketData] CCXT not installed"
        try:
            exch_class = getattr(_ccxt, exchange, None)
            if exch_class is None:
                return f"[ccxt] Unknown exchange: {exchange}"
            exch = exch_class({"enableRateLimit": True})
            return exch.fetch_tickers()
        except Exception as exc:
            return f"[ccxt] Error fetching tickers from {exchange}: {exc}"

    # ────────────────────────────────────────────────────────────── Twelve Data ──

    def twelvedata_bars(
        self,
        symbol: str,
        interval: str = "1day",
        bars: int = 100,
    ) -> Any:
        """Fetch OHLCV bars from Twelve Data.

        Covers stocks, ETFs, forex, crypto, and indices.
        Requires TWELVE_DATA_API_KEY env var (free tier: 800 credits/day).

        Returns pandas.DataFrame or dict.
        """
        if not _TWELVE_OK:
            return "[MarketData] twelvedata not installed (pip install twelvedata)"
        api_key = os.environ.get("TWELVE_DATA_API_KEY", "")
        if not api_key:
            return "[MarketData] TWELVE_DATA_API_KEY env var not set"
        try:
            # Normalize interval format
            iv_map = {"1m": "1min", "5m": "5min", "15m": "15min",
                      "1h": "1h", "4h": "4h", "1d": "1day", "1w": "1week"}
            td_interval = iv_map.get(interval, interval)
            client = _TDClient(apikey=api_key)
            ts = client.time_series(
                symbol=symbol,
                interval=td_interval,
                outputsize=bars,
            )
            df = ts.as_pandas()
            if df is not None and not df.empty:
                self._store_in_kb(
                    f"twelvedata:{symbol}:{interval}",
                    f"Twelve Data bars for {symbol} ({interval}): "
                    f"latest_close={df['close'].iloc[0]:.4f}",
                )
            return df
        except Exception as exc:
            log.warning("[MarketData:twelvedata] %s: %s", symbol, exc)
            return f"[twelvedata] Error fetching {symbol}: {exc}"

    # ──────────────────────────────────────────────────────────────────── OANDA ──

    def _get_oanda_client(self) -> Any:
        """Lazy-initialize the OANDA REST v20 client."""
        if self._oanda_client is not None:
            return self._oanda_client
        if not _OANDA_OK:
            return None
        api_key = os.environ.get("OANDA_API_KEY", "")
        if not api_key:
            return None
        env = os.environ.get("OANDA_ENVIRONMENT", "practice")
        self._oanda_client = _oanda.API(  # type: ignore[attr-defined]
            access_token=api_key,
            environment=env,
        )
        return self._oanda_client

    def oanda_candles(
        self,
        instrument: str = "EUR_USD",
        interval: str = "H1",
        bars: int = 100,
    ) -> Any:
        """Fetch forex / CFD / index candles from OANDA REST v20.

        Covers EUR_USD, GBP_USD, USD_JPY, XAU_USD (gold), SPX500_USD,
        NAS100_USD, UK100_GBP, BCO_USD (Brent), etc.

        Requires OANDA_API_KEY env var and a free practice account at
        https://www.oanda.com/

        *interval* uses OANDA granularity codes: S5,S10,S30,M1,M5,M15,M30,
        H1,H2,H4,H8,H12,D,W,M.
        """
        if not _OANDA_OK:
            return "[MarketData] oandapyV20 not installed (pip install oandapyV20)"
        client = self._get_oanda_client()
        if client is None:
            return "[MarketData] OANDA_API_KEY not set"
        # Map common shorthand to OANDA granularity
        _gran = {
            "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
            "1h": "H1", "4h": "H4", "1d": "D", "1w": "W",
        }
        gran = _gran.get(interval, interval.upper())
        params = {"granularity": gran, "count": str(bars)}
        try:
            req = _oanda_instr.InstrumentsCandles(  # type: ignore[attr-defined]
                instrument=instrument, params=params
            )
            resp = client.request(req)
            candles = resp.get("candles", [])
            self._store_in_kb(
                f"oanda:{instrument}:{interval}",
                f"OANDA candles for {instrument} ({interval}): "
                f"{len(candles)} bars",
            )
            return candles
        except Exception as exc:
            log.warning("[MarketData:oanda] %s: %s", instrument, exc)
            return f"[oanda] Error fetching {instrument}: {exc}"

    def oanda_account_summary(self) -> Any:
        """Return OANDA account summary (requires OANDA_ACCOUNT_ID env var)."""
        if not _OANDA_OK:
            return "[MarketData] oandapyV20 not installed"
        client = self._get_oanda_client()
        if client is None:
            return "[MarketData] OANDA_API_KEY not set"
        account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
        if not account_id:
            return "[MarketData] OANDA_ACCOUNT_ID not set"
        try:
            req = _oanda_acct.AccountSummary(accountID=account_id)  # type: ignore[attr-defined]
            return client.request(req)
        except Exception as exc:
            return f"[oanda] Account summary error: {exc}"

    def oanda_place_order(
        self,
        instrument: str,
        units: int,
        order_type: str = "MARKET",
    ) -> Any:
        """Place a market order via OANDA (requires credentials + OANDA_ACCOUNT_ID).

        *units* > 0 = buy; < 0 = sell.
        """
        if not _OANDA_OK:
            return "[MarketData] oandapyV20 not installed"
        client = self._get_oanda_client()
        if client is None:
            return "[MarketData] OANDA_API_KEY not set"
        account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
        if not account_id:
            return "[MarketData] OANDA_ACCOUNT_ID not set"
        body = {
            "order": {
                "type": order_type,
                "instrument": instrument,
                "units": str(units),
                "timeInForce": "FOK",
                "positionFill": "DEFAULT",
            }
        }
        try:
            req = _oanda_orders.OrderCreate(accountID=account_id, data=body)  # type: ignore[attr-defined]
            resp = client.request(req)
            _notif_queue.push(f"[OANDA] Order placed: {instrument} units={units} → {resp}")
            return resp
        except Exception as exc:
            log.error("[MarketData:oanda] place_order %s: %s", instrument, exc)
            return f"[oanda] Order error: {exc}"

    def oanda_open_trades(self) -> Any:
        """List open trades on the OANDA account."""
        if not _OANDA_OK:
            return "[MarketData] oandapyV20 not installed"
        client = self._get_oanda_client()
        if client is None:
            return "[MarketData] OANDA_API_KEY not set"
        account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
        if not account_id:
            return "[MarketData] OANDA_ACCOUNT_ID not set"
        try:
            req = _oanda_trades.OpenTrades(accountID=account_id)  # type: ignore[attr-defined]
            return client.request(req)
        except Exception as exc:
            return f"[oanda] Open trades error: {exc}"

    # ──────────────────────────────────────────────────────────────── Alpaca ──

    def _get_alpaca_stock_client(self) -> Any:
        if self._alpaca_stock is not None:
            return self._alpaca_stock
        if not _ALPACA_OK:
            return None
        api_key = os.environ.get("ALPACA_API_KEY", "")
        api_secret = os.environ.get("ALPACA_API_SECRET", "")
        if api_key and api_secret:
            self._alpaca_stock = _AlpacaStockClient(  # type: ignore[misc]
                api_key=api_key, secret_key=api_secret
            )
        else:
            self._alpaca_stock = _AlpacaStockClient()  # type: ignore[misc]
        return self._alpaca_stock

    def _get_alpaca_trading_client(self) -> Any:
        if self._alpaca_trading is not None:
            return self._alpaca_trading
        if not _ALPACA_OK:
            return None
        api_key = os.environ.get("ALPACA_API_KEY", "")
        api_secret = os.environ.get("ALPACA_API_SECRET", "")
        paper = os.environ.get("ALPACA_PAPER", "true").lower() != "false"
        if not (api_key and api_secret):
            return None
        self._alpaca_trading = _AlpacaTradingClient(  # type: ignore[misc]
            api_key=api_key, secret_key=api_secret, paper=paper
        )
        return self._alpaca_trading

    def alpaca_bars(
        self,
        symbol: str,
        interval: str = "1d",
        bars: int = 100,
        asset_class: str = "stock",
    ) -> Any:
        """Fetch historical bars from Alpaca.

        asset_class: ``stock`` or ``crypto``.
        """
        if not _ALPACA_OK:
            return "[MarketData] alpaca-py not installed (pip install alpaca-py)"
        # Map interval to Alpaca TimeFrame
        _tf_map = {
            "1m": _AlpacaTF.Minute,  # type: ignore[attr-defined]
            "5m": _AlpacaTF(5, _AlpacaTF.Minute),  # type: ignore[attr-defined]
            "15m": _AlpacaTF(15, _AlpacaTF.Minute),  # type: ignore[attr-defined]
            "1h": _AlpacaTF.Hour,  # type: ignore[attr-defined]
            "1d": _AlpacaTF.Day,  # type: ignore[attr-defined]
            "1w": _AlpacaTF.Week,  # type: ignore[attr-defined]
            "1mo": _AlpacaTF.Month,  # type: ignore[attr-defined]
        } if _ALPACA_OK else {}
        try:
            tf = _tf_map.get(interval, _AlpacaTF.Day)  # type: ignore[attr-defined]
            end_dt = datetime.now(tz=timezone.utc)
            # Approximate how many calendar days we need for `bars` bars at this interval
            _bars_per_day = {
                "1m": 390, "5m": 78, "15m": 26, "30m": 13,
                "1h": 7, "4h": 2, "1d": 1, "1w": 1, "1mo": 1,
            }
            bpd = _bars_per_day.get(interval, 1)
            days_back = max(5, bars // bpd + 1) if bpd > 1 else max(bars, 5)
            start_dt = end_dt - timedelta(days=days_back)
            if asset_class == "crypto":
                client = _AlpacaCryptoClient()  # type: ignore[misc]
                req = _CryptoBarsReq(  # type: ignore[misc]
                    symbol_or_symbols=symbol, timeframe=tf,
                    start=start_dt, end=end_dt, limit=bars
                )
                bars_data = client.get_crypto_bars(req)
            else:
                client = self._get_alpaca_stock_client()
                if client is None:
                    return "[MarketData] Alpaca client not available"
                req = _StockBarsReq(  # type: ignore[misc]
                    symbol_or_symbols=symbol, timeframe=tf,
                    start=start_dt, end=end_dt, limit=bars
                )
                bars_data = client.get_stock_bars(req)
            df = bars_data.df
            if df is not None and not df.empty:
                self._store_in_kb(
                    f"alpaca:{symbol}:{interval}",
                    f"Alpaca bars for {symbol} ({interval}): "
                    f"{len(df)} bars",
                )
            return df
        except Exception as exc:
            log.warning("[MarketData:alpaca] %s: %s", symbol, exc)
            return f"[alpaca] Error fetching {symbol}: {exc}"

    def alpaca_place_order(
        self,
        symbol: str,
        qty: float,
        side: str = "buy",
        time_in_force: str = "gtc",
    ) -> Any:
        """Place a market order via Alpaca.

        Requires ALPACA_API_KEY and ALPACA_API_SECRET.
        Defaults to paper trading (set ALPACA_PAPER=false for live).
        """
        if not _ALPACA_OK:
            return "[MarketData] alpaca-py not installed"
        client = self._get_alpaca_trading_client()
        if client is None:
            return "[MarketData] Alpaca API key/secret not set"
        try:
            order_side = _AlpacaOrderSide.BUY if side.lower() == "buy" else _AlpacaOrderSide.SELL  # type: ignore[attr-defined]
            tif = _AlpacaTIF.GTC if time_in_force.lower() == "gtc" else _AlpacaTIF.DAY  # type: ignore[attr-defined]
            req = _AlpacaMktOrder(  # type: ignore[misc]
                symbol=symbol, qty=qty,
                side=order_side, time_in_force=tif,
            )
            resp = client.submit_order(order_data=req)
            _notif_queue.push(f"[Alpaca] Order: {side} {qty} {symbol} → {resp.id}")
            return resp
        except Exception as exc:
            log.error("[MarketData:alpaca] place_order %s: %s", symbol, exc)
            return f"[alpaca] Order error: {exc}"

    def alpaca_account(self) -> Any:
        """Return Alpaca account info."""
        if not _ALPACA_OK:
            return "[MarketData] alpaca-py not installed"
        client = self._get_alpaca_trading_client()
        if client is None:
            return "[MarketData] Alpaca API key/secret not set"
        try:
            return client.get_account()
        except Exception as exc:
            return f"[alpaca] Account error: {exc}"

    # ────────────────────────────────────────────────────────── batch helpers ──

    def fetch_multi(
        self,
        symbols: List[str],
        provider: str = "yfinance",
        interval: str = "1d",
        bars: int = 50,
    ) -> Dict[str, Any]:
        """Fetch bars for multiple symbols at once.

        Returns ``{symbol: data_or_error_string}``.
        """
        return {s: self.fetch(s, provider=provider, interval=interval, bars=bars)
                for s in symbols}

    def available_instruments_oanda(self) -> List[str]:
        """List OANDA tradeable instruments (forex, CFDs, indices, metals)."""
        return [
            # Forex majors
            "EUR_USD", "GBP_USD", "USD_JPY", "USD_CHF", "AUD_USD",
            "NZD_USD", "USD_CAD",
            # Forex crosses
            "EUR_GBP", "EUR_JPY", "GBP_JPY", "AUD_JPY",
            # Precious metals
            "XAU_USD", "XAG_USD",
            # Energy (CFD)
            "BCO_USD", "WTICO_USD",
            # Equity indices (CFD)
            "SPX500_USD", "NAS100_USD", "US30_USD",
            "UK100_GBP", "DE30_EUR", "FR40_EUR", "JP225_USD",
            # Crypto (via OANDA)
            "BTC_USD", "ETH_USD", "LTC_USD",
        ]

    def available_instruments_ccxt(self, exchange: str = "binance") -> Any:
        """List trading pairs available on a CCXT exchange."""
        if not _CCXT_OK:
            return []
        try:
            exch_class = getattr(_ccxt, exchange, None)
            if exch_class is None:
                return []
            exch = exch_class({"enableRateLimit": True})
            exch.load_markets()
            return list(exch.markets.keys())
        except Exception as exc:
            log.debug("[MarketData:ccxt] list_markets %s: %s", exchange, exc)
            return []

    def market_overview(self, symbols: Optional[List[str]] = None) -> str:
        """Return a quick text summary of latest prices for a basket of symbols.

        Uses yfinance for stocks/indices and CCXT for crypto.
        """
        if symbols is None:
            symbols = [
                "BTC-USD", "ETH-USD", "SPY", "QQQ", "^GSPC",
                "EURUSD=X", "GBPUSD=X", "GC=F",  # gold futures
            ]
        lines = ["=== Market Overview ==="]
        for sym in symbols:
            try:
                if _YFINANCE_OK:
                    df = self.yfinance_bars(sym, interval="1d", bars=2)
                    if isinstance(df, str):
                        lines.append(f"  {sym:<15} {df}")
                    else:
                        close = df["Close"].iloc[-1]
                        prev = df["Close"].iloc[-2] if len(df) >= 2 else close
                        chg = (close - prev) / prev * 100 if prev else 0.0
                        lines.append(f"  {sym:<15} {close:>10.4f}  ({chg:+.2f}%)")
                else:
                    lines.append(f"  {sym:<15} (install yfinance for prices)")
            except Exception as exc:
                lines.append(f"  {sym:<15} error: {exc}")
        return "\n".join(lines)

    # ─────────────────────────────────────────────────────── KB helper ────────

    def _store_in_kb(self, key: str, text: str) -> None:
        """Store a market data snippet in KnowledgeDB for RAG access."""
        if self._kb is None:
            return
        try:
            self._kb.store(
                key,
                text,
                tags=["market_data", "trading"],
            )
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_market_data_providers: Optional[MarketDataProviders] = None


def get_market_data_providers(knowledge_db: Optional[Any] = None) -> MarketDataProviders:
    """Return global :class:`MarketDataProviders` singleton."""
    global _market_data_providers
    if _market_data_providers is None:
        _market_data_providers = MarketDataProviders(knowledge_db=knowledge_db)
    elif knowledge_db is not None and _market_data_providers._kb is None:
        _market_data_providers._kb = knowledge_db
    return _market_data_providers


if __name__ == "__main__":
    print('Running market_data_providers.py')
