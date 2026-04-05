#!/usr/bin/env python3
"""
REALTIME STREAM — Binance WebSocket real-time intelligence pipeline.

Upgrades Niblit from polling → real-time streaming:

    Binance WebSocket
            │
            ▼
    Stream Handler
            │
            ▼
    Live Candle Builder
            │
            ▼
    Feature Engine
            │
            ▼
    Vector Builder
            │
            ▼
    Memory (SQLite + Qdrant)
            │
            ▼
    Decision Engine (triggered live)

Usage
-----
    import asyncio
    from modules.realtime_stream import RealtimeStream
    stream = RealtimeStream()
    asyncio.run(stream.start())

    # Or from CLI:
    #   python run_realtime.py

Control
-------
    stream.stop()     — signal graceful shutdown
    stream.running    — True while stream is active
    stream.stats()    — dict with cycle counts / last decision

Dependencies
------------
    python-binance  — pip install python-binance
    pandas          — pip install pandas
    websockets      — pip install websockets  (pulled in by python-binance)
"""

import asyncio
import logging
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

log = logging.getLogger("RealtimeStream")
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][%(name)s][%(levelname)s] %(message)s",
)

# ── tuneable constants ────────────────────────────────────────────────────────
_DEFAULT_SYMBOL: str = "btcusdt"
_DEFAULT_INTERVAL: str = "1m"
_MAX_CANDLE_BUFFER: int = 200        # keep last N closed candles
_RECONNECT_DELAY: float = 5.0        # seconds before reconnect on error
_INTRA_CANDLE: bool = False          # True → process every tick, not just close

class RealtimeStream:
    """Real-time Binance kline stream → feature engine → fused memory → decision."""

    def __init__(
        self,
        symbol: str = _DEFAULT_SYMBOL,
        interval: str = _DEFAULT_INTERVAL,
        intra_candle: bool = _INTRA_CANDLE,
        trading_brain=None,
    ):
        """
        Parameters
        ----------
        symbol:        Binance symbol (lower-case), e.g. "btcusdt".
        interval:      Kline interval, e.g. "1m", "5m", "1h".
        intra_candle:  When True, process every tick; when False (default),
                       only act on closed candles.
        trading_brain: Injected TradingBrain instance.  If None the class
                       lazy-imports it from modules.trading_brain.
        """
        self.symbol = symbol
        self.interval = interval
        self.intra_candle = intra_candle
        self._brain = trading_brain

        # State
        self.running: bool = False
        self._stop_event = asyncio.Event() if False else None  # created in start()
        self._candle_buffer: Deque[Dict[str, Any]] = deque(maxlen=_MAX_CANDLE_BUFFER)

        # Metrics
        self._tick_count: int = 0
        self._close_count: int = 0
        self._last_decision: str = "HOLD"
        self._last_price: float = 0.0
        self._last_ts: str = ""

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _get_brain(self):
        """Lazy-import TradingBrain to avoid circular imports at module level."""
        if self._brain is not None:
            return self._brain
        try:
            from modules.trading_brain import TradingBrain
            self._brain = TradingBrain()
            log.info("✅ [RealtimeStream] TradingBrain lazy-initialised")
        except Exception as exc:
            log.warning("[RealtimeStream] TradingBrain unavailable: %s", exc)
        return self._brain

    # ─────────────────────────────────────────────────────────────────────────
    # Kline message → candle dict
    # ─────────────────────────────────────────────────────────────────────────

    def process_kline(self, msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Extract a structured candle dict from a raw Binance kline message.

        Returns None when the message does not contain kline data.
        """
        k = msg.get("k")
        if not k:
            return None
        return {
            "time":   k["t"],
            "open":   float(k["o"]),
            "high":   float(k["h"]),
            "low":    float(k["l"]),
            "close":  float(k["c"]),
            "volume": float(k["v"]),
            "closed": bool(k["x"]),
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Candle → feature pipeline → memory → decision
    # ─────────────────────────────────────────────────────────────────────────

    def handle_closed_candle(self, candle: Dict[str, Any]) -> str:
        """Run the full feature-engine pipeline on a closed (or intra) candle.

        Pipeline
        --------
        1. Append candle to buffer.
        2. Build pandas DataFrame from buffer.
        3. Compute indicators via TradingBrain.compute_indicators().
        4. Build state vector via TradingBrain.build_state_vector().
        5. Store (vector, metadata) into fused memory (SQLite + Qdrant).
        6. Retrieve similar past states for context.
        7. Call TradingBrain.decide_action() → BUY / SELL / HOLD.

        Returns the decision string.
        """
        brain = self._get_brain()
        if brain is None:
            log.warning("[RealtimeStream] TradingBrain not available, skipping pipeline")
            return "HOLD"

        self._candle_buffer.append(candle)
        self._close_count += 1
        self._last_price = candle["close"]
        self._last_ts = datetime.utcnow().isoformat()

        # Need at least a few candles to compute indicators
        if len(self._candle_buffer) < 5:
            return "HOLD"

        try:
            import pandas as pd
            df = pd.DataFrame(list(self._candle_buffer))

            # Compute technical indicators (RSI, MACD, EMA, …)
            if hasattr(brain, "compute_indicators"):
                df = brain.compute_indicators(df)

            if df is None or df.empty:
                return "HOLD"

            latest = df.iloc[-1]

            # Build the state vector for embedding
            vector: List[float] = []
            if hasattr(brain, "build_state_vector"):
                vector = brain.build_state_vector(latest)

            # Metadata stored alongside the vector
            metadata: Dict[str, Any] = {
                "timestamp": self._last_ts,
                "symbol":    self.symbol.upper(),
                "price":     float(candle["close"]),
                "source":    "websocket",
            }
            # Add indicator values when available
            for col in ("rsi", "macd", "ema", "volume"):
                try:
                    metadata[col] = float(latest[col])
                except (KeyError, TypeError, ValueError):
                    pass

            # Persist to fused memory (SQLite + Qdrant)
            if vector and hasattr(brain, "store_market_state"):
                try:
                    brain.store_market_state(vector, metadata)
                except Exception as exc:
                    log.debug("[RealtimeStream] store_market_state failed: %s", exc)

            # Decision
            decision = "HOLD"
            if hasattr(brain, "decide_action") and vector:
                try:
                    decision = brain.decide_action(vector) or "HOLD"
                except Exception as exc:
                    log.debug("[RealtimeStream] decide_action failed: %s", exc)

            self._last_decision = str(decision)
            log.info(
                "[LIVE] price=%.2f → %s  (buffer=%d, closes=%d)",
                candle["close"], decision,
                len(self._candle_buffer), self._close_count,
            )
            return self._last_decision

        except Exception as exc:
            log.error("[RealtimeStream] pipeline error: %s", exc)
            return "HOLD"

    # ─────────────────────────────────────────────────────────────────────────
    # Status
    # ─────────────────────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Return a snapshot of current stream metrics."""
        return {
            "running":        self.running,
            "symbol":         self.symbol,
            "interval":       self.interval,
            "intra_candle":   self.intra_candle,
            "tick_count":     self._tick_count,
            "close_count":    self._close_count,
            "buffer_size":    len(self._candle_buffer),
            "last_price":     self._last_price,
            "last_decision":  self._last_decision,
            "last_ts":        self._last_ts,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Main async stream loop
    # ─────────────────────────────────────────────────────────────────────────

    def stop(self) -> None:
        """Signal the stream to shut down gracefully."""
        self.running = False
        if self._stop_event and not self._stop_event.is_set():
            self._stop_event.set()
        log.info("[RealtimeStream] Stop signal received")

    async def start(self) -> None:
        """Connect to Binance WebSocket and run the kline stream until stopped.

        Reconnects automatically on network errors with a short backoff.
        Requires *python-binance* to be installed:
            pip install python-binance
        """
        try:
            from binance import AsyncClient, BinanceSocketManager
        except ImportError:
            log.error(
                "[RealtimeStream] python-binance is not installed. "
                "Run: pip install python-binance"
            )
            return

        self.running = True
        self._stop_event = asyncio.Event()
        log.info(
            "🚀 [RealtimeStream] Starting stream  symbol=%s  interval=%s  intra=%s",
            self.symbol, self.interval, self.intra_candle,
        )

        while self.running:
            client: Optional[Any] = None
            try:
                client = await AsyncClient.create()
                bm = BinanceSocketManager(client)
                socket = bm.kline_socket(self.symbol, interval=self.interval)

                async with socket as stream:
                    while self.running:
                        try:
                            msg = await asyncio.wait_for(stream.recv(), timeout=30.0)
                        except asyncio.TimeoutError:
                            log.debug("[RealtimeStream] recv timeout — heartbeat")
                            continue
                        except Exception as recv_exc:
                            log.warning("[RealtimeStream] recv error: %s", recv_exc)
                            await asyncio.sleep(_RECONNECT_DELAY)
                            break

                        if not msg or "k" not in msg:
                            continue

                        self._tick_count += 1
                        candle = self.process_kline(msg)
                        if candle is None:
                            continue

                        # Decide whether to process this tick
                        if self.intra_candle or candle["closed"]:
                            self.handle_closed_candle(candle)

            except Exception as exc:
                if self.running:
                    log.warning(
                        "[RealtimeStream] Connection error: %s — reconnecting in %.0fs",
                        exc, _RECONNECT_DELAY,
                    )
                    await asyncio.sleep(_RECONNECT_DELAY)
            finally:
                if client:
                    try:
                        await client.close_connection()
                    except Exception:
                        pass

        log.info(
            "✅ [RealtimeStream] Stopped  ticks=%d  closes=%d",
            self._tick_count, self._close_count,
        )
