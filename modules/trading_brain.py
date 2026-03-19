#!/usr/bin/env python3
"""
modules/trading_brain.py — Niblit Trading Brain (V1).

Connects Niblit's fused memory system (SQLite + Qdrant) to live crypto
market data so the agent can observe the market, build state vectors,
store them in memory, retrieve similar past states, and produce a simple
trade decision.

Architecture::

    Market APIs (Binance)
         │
         ▼
    MarketIngestor          ← fetch_market_data()
         │
         ▼
    FeatureEngineer         ← compute_indicators()  [RSI, MACD, EMA, vol]
         │
         ▼
    StateVectorBuilder      ← build_state_vector()  [normalised numpy → list]
         │
         ▼
    MemoryStorage           ← store_market_state()  [SQLite + Qdrant]
         │
         ▼
    PatternRetrieval        ← retrieve_similar_states()
         │
         ▼
    DecisionEngine          ← decide_action()  → BUY / SELL / HOLD

Autonomous cycle control::

    brain.start()   — Launches a background daemon thread that calls cycle()
                       every ``cycle_secs`` seconds.
    brain.stop()    — Signals the background thread to exit cleanly.
    brain.status()  — Returns a human-readable status dict.

Configuration (environment variables)::

    BINANCE_API_KEY     — Binance API key (optional; public data is keyless)
    BINANCE_API_SECRET  — Binance API secret (optional)
    TRADING_SYMBOL      — Trading pair, default BTCUSDT
    TRADING_INTERVAL    — Kline interval, default 1m
    TRADING_KLINE_LIMIT — Number of candles to fetch per cycle, default 200

Usage::

    from modules.trading_brain import TradingBrain

    brain = TradingBrain()          # keyless — read-only market data
    decision = brain.cycle()        # observe → store → decide
    print(decision)                 # "BUY" | "SELL" | "HOLD"

See run_trading_brain.py for the continuous-loop runner.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("niblit_trading_brain")

# ── optional third-party dependencies ────────────────────────────────────────
try:
    import numpy as np
    _NP_AVAILABLE = True
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]
    _NP_AVAILABLE = False

try:
    import pandas as pd
    _PD_AVAILABLE = True
except ImportError:  # pragma: no cover
    pd = None  # type: ignore[assignment]
    _PD_AVAILABLE = False

try:
    import ta
    _TA_AVAILABLE = True
except ImportError:  # pragma: no cover
    ta = None  # type: ignore[assignment]
    _TA_AVAILABLE = False

try:
    from binance.client import Client as _BinanceClient
    _BINANCE_AVAILABLE = True
except ImportError:  # pragma: no cover
    _BinanceClient = None  # type: ignore[assignment]
    _BINANCE_AVAILABLE = False

# ── Niblit memory ─────────────────────────────────────────────────────────────
try:
    from niblit_memory import NiblitMemory
    _MEMORY_AVAILABLE = True
except ImportError:  # pragma: no cover
    NiblitMemory = None  # type: ignore[assignment,misc]
    _MEMORY_AVAILABLE = False

# ── defaults ──────────────────────────────────────────────────────────────────
_DEFAULT_SYMBOL = os.getenv("TRADING_SYMBOL", "BTCUSDT")
_DEFAULT_INTERVAL = os.getenv("TRADING_INTERVAL", "1m")
_DEFAULT_KLINE_LIMIT = int(os.getenv("TRADING_KLINE_LIMIT", "200"))
_DEFAULT_CYCLE_SECS = int(os.getenv("TRADING_CYCLE_SECS", "60"))

# Decision thresholds (similarity scores returned by Qdrant range 0–1)
_BUY_THRESHOLD = 0.85
_SELL_THRESHOLD = 0.60

_KLINE_COLUMNS = [
    "time", "open", "high", "low", "close", "volume",
    "close_time", "qav", "num_trades",
    "taker_base", "taker_quote", "ignore",
]


class TradingBrain:
    """Niblit's market observation and decision engine.

    The brain is intentionally read-only by default: it fetches data,
    computes indicators, vectorises the market state, stores it in the
    fused memory, and returns a high-level action string.  Actual order
    execution is left to a separate execution layer (V3+).

    Args:
        api_key:    Binance API key.  *None* for public-data access only.
        api_secret: Binance API secret.  *None* for public-data access only.
        symbol:     Trading symbol, e.g. ``"BTCUSDT"``.
        interval:   Kline interval string accepted by Binance, e.g. ``"1m"``.
        kline_limit: Number of candles fetched per cycle (default 200).
        cycle_secs: Seconds between autonomous cycles (default 60).
        memory:     Optional pre-constructed :class:`NiblitMemory` instance.
                    A new singleton will be created when *None*.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        symbol: str = _DEFAULT_SYMBOL,
        interval: str = _DEFAULT_INTERVAL,
        kline_limit: int = _DEFAULT_KLINE_LIMIT,
        cycle_secs: int = _DEFAULT_CYCLE_SECS,
        memory: Optional[Any] = None,
    ) -> None:
        self.symbol = symbol
        self.interval = interval
        self.kline_limit = kline_limit
        self.cycle_secs = cycle_secs

        # ── autonomous background thread state ───────────────────────────────
        self._running: bool = False
        self._thread: Optional[threading.Thread] = None
        self._cycle_count: int = 0
        self._last_decision: str = "HOLD"
        self._last_cycle_ts: Optional[str] = None

        # ── optional ReflectModule (wired by niblit_core after both objects exist) ──
        self.reflect_module: Optional[Any] = None

        # ── Binance client ──────────────────────────────────────────────────
        self._client: Optional[Any] = None
        if _BINANCE_AVAILABLE:
            resolved_key = api_key or os.getenv("BINANCE_API_KEY", "")
            resolved_secret = api_secret or os.getenv("BINANCE_API_SECRET", "")
            try:
                self._client = _BinanceClient(resolved_key, resolved_secret)
                log.info("[TradingBrain] Binance client initialised (symbol=%s)", symbol)
            except Exception as exc:  # pragma: no cover
                log.warning("[TradingBrain] Binance client init failed: %s", exc)
        else:
            log.warning(
                "[TradingBrain] python-binance not installed — "
                "market data ingestion unavailable.  "
                "Install with: pip install python-binance"
            )

        # ── memory ──────────────────────────────────────────────────────────
        if memory is not None:
            self.memory: Optional[Any] = memory
        elif _MEMORY_AVAILABLE:
            try:
                self.memory = NiblitMemory()
            except Exception as exc:  # pragma: no cover
                log.warning("[TradingBrain] NiblitMemory init failed: %s", exc)
                self.memory = None
        else:
            log.warning("[TradingBrain] niblit_memory unavailable — storage disabled.")
            self.memory = None

    # ─────────────────────────────────────────────────────────────────────────
    # MARKET INGESTION
    # ─────────────────────────────────────────────────────────────────────────

    def fetch_market_data(self, limit: Optional[int] = None) -> Any:
        """Fetch OHLCV klines from Binance and return a pandas DataFrame.

        Args:
            limit: Number of candles to fetch.  Defaults to ``self.kline_limit``.

        Returns:
            A :class:`pandas.DataFrame` with columns ``time``, ``open``,
            ``high``, ``low``, ``close``, ``volume`` (numeric), plus the raw
            Binance fields.  Returns an empty DataFrame when Binance is
            unavailable.

        Raises:
            RuntimeError: If *pandas* is not installed.
        """
        if not _PD_AVAILABLE:
            raise RuntimeError(
                "pandas is required for market data ingestion.  "
                "Install with: pip install pandas"
            )

        if self._client is None:
            log.warning("[TradingBrain] No Binance client — returning empty DataFrame.")
            return pd.DataFrame(columns=_KLINE_COLUMNS)

        n = limit if limit is not None else self.kline_limit
        try:
            klines = self._client.get_klines(
                symbol=self.symbol,
                interval=self.interval,
                limit=n,
            )
        except Exception as exc:
            log.error("[TradingBrain] fetch_market_data failed: %s", exc)
            return pd.DataFrame(columns=_KLINE_COLUMNS)

        df = pd.DataFrame(klines, columns=_KLINE_COLUMNS)
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = df[col].astype(float)
        return df

    # ─────────────────────────────────────────────────────────────────────────
    # FEATURE ENGINEERING
    # ─────────────────────────────────────────────────────────────────────────

    def compute_indicators(self, df: Any) -> Any:
        """Compute RSI, MACD, EMA-20, and intra-bar volatility.

        Args:
            df: DataFrame produced by :meth:`fetch_market_data`.

        Returns:
            The same DataFrame with four new columns — ``rsi``, ``macd``,
            ``ema``, ``volatility`` — with rows containing NaN values dropped.

        Raises:
            RuntimeError: If *ta* or *pandas* is not installed, or if the
                DataFrame is missing required price columns.
        """
        if not _PD_AVAILABLE:
            raise RuntimeError("pandas is required.")
        if not _TA_AVAILABLE:
            raise RuntimeError(
                "ta is required for indicator computation.  "
                "Install with: pip install ta"
            )
        if df is None or df.empty:
            return df

        df = df.copy()
        df["rsi"] = ta.momentum.RSIIndicator(df["close"]).rsi()

        macd_indicator = ta.trend.MACD(df["close"])
        df["macd"] = macd_indicator.macd()

        df["ema"] = ta.trend.EMAIndicator(df["close"], window=20).ema_indicator()
        df["volatility"] = df["high"] - df["low"]

        return df.dropna().reset_index(drop=True)

    # ─────────────────────────────────────────────────────────────────────────
    # STATE VECTOR CREATION
    # ─────────────────────────────────────────────────────────────────────────

    def build_state_vector(self, row: Any) -> List[float]:
        """Convert a single OHLCV + indicator row into a normalised float vector.

        The six-dimensional vector ``[close, volume, rsi, macd, ema,
        volatility]`` is z-score normalised so all features live on a
        comparable scale before being stored in Qdrant.

        Args:
            row: A pandas Series (or dict-like) representing one candle.

        Returns:
            A plain Python list of floats suitable for Qdrant upsert.

        Raises:
            RuntimeError: If *numpy* is not installed.
        """
        if not _NP_AVAILABLE:
            raise RuntimeError(
                "numpy is required for vector normalisation.  "
                "Install with: pip install numpy"
            )

        vector = np.array([
            float(row["close"]),
            float(row["volume"]),
            float(row["rsi"]),
            float(row["macd"]),
            float(row["ema"]),
            float(row["volatility"]),
        ], dtype=float)

        # z-score normalisation (guard against zero std)
        std = np.std(vector)
        vector = (vector - np.mean(vector)) / (std + 1e-9)

        return vector.tolist()

    # ─────────────────────────────────────────────────────────────────────────
    # MEMORY STORAGE
    # ─────────────────────────────────────────────────────────────────────────

    def store_market_state(
        self,
        state_vector: List[float],
        metadata: Dict[str, Any],
    ) -> None:
        """Persist a market state vector and its metadata via NiblitMemory.

        The record ID is derived from the ISO-8601 timestamp embedded in
        *metadata* so that each minute produces a deterministic, unique key.

        Args:
            state_vector: Float vector from :meth:`build_state_vector`.
            metadata:     Dict containing at minimum a ``"timestamp"`` key.
        """
        if self.memory is None:
            log.debug("[TradingBrain] Memory unavailable — skipping store.")
            return

        state_id = "market_{}".format(metadata.get("timestamp", "unknown"))
        try:
            self.memory.save_record(state_id, metadata, state_vector)
            log.info("[TradingBrain] Stored market state %s", state_id)
        except Exception as exc:
            log.warning("[TradingBrain] store_market_state failed: %s", exc)

    # ─────────────────────────────────────────────────────────────────────────
    # PATTERN RETRIEVAL
    # ─────────────────────────────────────────────────────────────────────────

    def retrieve_similar_states(
        self,
        vector: List[float],
        top_k: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search the fused memory for past states similar to *vector*.

        Args:
            vector: Query vector from :meth:`build_state_vector`.
            top_k:  Maximum number of results to return.

        Returns:
            A list of result dicts (each containing at least a ``"score"``
            key) ordered by descending similarity.  Returns an empty list
            when memory is unavailable or the query fails.
        """
        if self.memory is None:
            return []
        try:
            return self.memory.query_vector(vector, top_k=top_k)
        except Exception as exc:
            log.warning("[TradingBrain] retrieve_similar_states failed: %s", exc)
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # DECISION ENGINE (initial scaffold)
    # ─────────────────────────────────────────────────────────────────────────

    def decide_action(self, current_vector: List[float]) -> str:
        """Produce a trade signal based on similarity scores of past states.

        This is a placeholder heuristic that will be replaced by a proper
        reinforcement-learning policy in V2/V3.  The current logic:

        * If fewer than 5 similar past states exist → **HOLD**.
        * If the mean similarity score ≥ ``_BUY_THRESHOLD`` (0.85) → **BUY**.
        * If the mean similarity score < ``_SELL_THRESHOLD`` (0.60) → **SELL**.
        * Otherwise → **HOLD**.

        Args:
            current_vector: Normalised float vector for the current candle.

        Returns:
            One of ``"BUY"``, ``"SELL"``, or ``"HOLD"``.
        """
        similar = self.retrieve_similar_states(current_vector)

        if len(similar) < 5:
            log.debug("[TradingBrain] Insufficient history — defaulting to HOLD.")
            return "HOLD"

        scores = [s.get("score", 0.0) for s in similar]
        if not _NP_AVAILABLE:
            avg_score = sum(scores) / len(scores)
        else:
            avg_score = float(np.mean(scores))

        log.debug("[TradingBrain] avg_score=%.4f (n=%d)", avg_score, len(scores))

        if avg_score >= _BUY_THRESHOLD:
            return "BUY"
        if avg_score < _SELL_THRESHOLD:
            return "SELL"
        return "HOLD"

    # ─────────────────────────────────────────────────────────────────────────
    # MAIN CYCLE
    # ─────────────────────────────────────────────────────────────────────────

    def cycle(self) -> str:
        """Run one full observe → engineer → vectorise → store → decide cycle.

        This method is designed to be called on a fixed schedule (e.g. every
        60 seconds by :mod:`run_trading_brain`).

        Returns:
            Trade decision string — ``"BUY"``, ``"SELL"``, or ``"HOLD"``.
            Returns ``"HOLD"`` on any error to avoid unintended actions.
        """
        try:
            # 1. Fetch market data
            df = self.fetch_market_data()
            if df is None or df.empty:
                log.warning("[TradingBrain] No market data — skipping cycle.")
                return "HOLD"

            # 2. Compute indicators
            df = self.compute_indicators(df)
            if df is None or df.empty:
                log.warning("[TradingBrain] Indicator computation produced empty frame.")
                return "HOLD"

            # 3. Extract latest candle
            latest = df.iloc[-1]

            # 4. Build state vector
            vector = self.build_state_vector(latest)

            # 5. Build metadata
            metadata: Dict[str, Any] = {
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "symbol": self.symbol,
                "price": float(latest["close"]),
                "rsi": float(latest["rsi"]),
                "macd": float(latest["macd"]),
                "ema": float(latest["ema"]),
                "volatility": float(latest["volatility"]),
            }

            # 6. Store in fused memory
            self.store_market_state(vector, metadata)

            # 7. Decide
            decision = self.decide_action(vector)
            self._last_decision = decision
            self._last_cycle_ts = metadata["timestamp"]
            self._cycle_count += 1
            log.info(
                "[TradingBrain] %s | price=%.2f rsi=%.2f decision=%s (cycle #%d)",
                self.symbol,
                metadata["price"],
                metadata["rsi"],
                decision,
                self._cycle_count,
            )

            # 8. Trigger reflection so the brain understands this decision
            if self.reflect_module and hasattr(self.reflect_module, "reflect_on_trading"):
                try:
                    self.reflect_module.reflect_on_trading(
                        symbol=self.symbol,
                        decision=decision,
                        metadata=metadata,
                    )
                except Exception as _exc:  # pragma: no cover
                    log.debug("[TradingBrain] reflect_on_trading failed: %s", _exc)

            return decision

        except Exception as exc:
            log.error("[TradingBrain] cycle() error: %s", exc, exc_info=True)
            return "HOLD"

    # ─────────────────────────────────────────────────────────────────────────
    # AUTONOMOUS CYCLE CONTROL
    # ─────────────────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Start the autonomous trading cycle in a background daemon thread.

        Calls :meth:`cycle` every ``self.cycle_secs`` seconds until
        :meth:`stop` is called.

        Returns:
            ``True`` if the thread was launched, ``False`` if it was already
            running.
        """
        if self._running:
            log.info("[TradingBrain] Already running — ignoring start().")
            return False

        self._running = True
        self._thread = threading.Thread(
            target=self._autonomous_loop,
            name="TradingBrainCycle",
            daemon=True,
        )
        self._thread.start()
        log.info(
            "[TradingBrain] Autonomous cycle started (symbol=%s, interval=%ds).",
            self.symbol,
            self.cycle_secs,
        )
        return True

    def stop(self) -> bool:
        """Stop the autonomous trading cycle.

        Signals the background thread to exit.  The thread will finish its
        current ``cycle_secs`` sleep before terminating.

        Returns:
            ``True`` if the thread was running and has been signalled to stop,
            ``False`` if it was not running.
        """
        if not self._running:
            log.info("[TradingBrain] Not running — ignoring stop().")
            return False

        self._running = False
        log.info("[TradingBrain] Autonomous cycle stop requested.")
        return True

    @property
    def running(self) -> bool:
        """``True`` when the autonomous cycle thread is active."""
        return self._running and (self._thread is not None) and self._thread.is_alive()

    def status(self) -> Dict[str, Any]:
        """Return a dict describing the current state of the trading brain.

        Returns:
            Dict with keys: ``running``, ``symbol``, ``cycle_secs``,
            ``cycle_count``, ``last_decision``, ``last_cycle_ts``.
        """
        return {
            "running": self.running,
            "symbol": self.symbol,
            "interval": self.interval,
            "cycle_secs": self.cycle_secs,
            "cycle_count": self._cycle_count,
            "last_decision": self._last_decision,
            "last_cycle_ts": self._last_cycle_ts or "—",
            "binance_available": self._client is not None,
            "memory_available": self.memory is not None,
        }

    def switch_pair(self, symbol: str, interval: Optional[str] = None) -> Dict[str, Any]:
        """Switch the trading pair (and optionally the kline interval) at runtime.

        If the autonomous cycle is currently running it will be stopped,
        the symbol/interval updated, and the cycle restarted automatically.

        Args:
            symbol:   New trading symbol, e.g. ``"ETHUSDT"``.  Converted to
                      upper-case automatically.
            interval: New kline interval string (e.g. ``"5m"``).  When *None*
                      the current :attr:`interval` is kept.

        Returns:
            A dict with keys ``symbol``, ``interval``, and ``restarted``
            (``True`` when the autonomous cycle was restarted).
        """
        new_symbol = symbol.strip().upper()
        new_interval = interval.strip() if interval else self.interval

        was_running = self.running
        if was_running:
            self.stop()
            import time as _time
            # Give the background thread a moment to acknowledge the stop signal
            _time.sleep(0.2)

        old_symbol = self.symbol
        old_interval = self.interval
        self.symbol = new_symbol
        self.interval = new_interval

        log.info(
            "[TradingBrain] Switched pair: %s/%s → %s/%s",
            old_symbol, old_interval, new_symbol, new_interval,
        )

        if was_running:
            self.start()

        return {"symbol": self.symbol, "interval": self.interval, "restarted": was_running}

    def _autonomous_loop(self) -> None:
        """Internal: run cycle() in a loop until self._running is False."""
        import time as _time

        log.info("[TradingBrain] Background loop starting.")
        while self._running:
            try:
                decision = self.cycle()
                log.debug("[TradingBrain] Autonomous cycle → %s", decision)
            except Exception as exc:  # pragma: no cover
                log.error("[TradingBrain] Unexpected error in loop: %s", exc, exc_info=True)
            # Sleep in short increments so stop() is responsive
            for _ in range(self.cycle_secs):
                if not self._running:
                    break
                _time.sleep(1)
        log.info("[TradingBrain] Background loop stopped.")
