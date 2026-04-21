"""
algorithms/21_niblit_freqtrade/NiblitSignalStrategy.py
——————————————————————————————————————————————————————
A minimal Freqtrade strategy that delegates entry/exit decisions to Niblit's
HTTP signal API (POST /trade/signal).

Setup
-----
1. Start Niblit in niblit-env:
       cd ~/projects/Niblit
       source ~/niblit-env/bin/activate
       export NIBLIT_PROFILE=android
       uvicorn app:app --host 127.0.0.1 --port 8000

2. In niblit-py311 (Freqtrade venv):
       export NIBLIT_API_URL=http://127.0.0.1:8000
       freqtrade backtesting --strategy NiblitSignalStrategy \
           --strategy-path ~/projects/niblit-lean-algos/algorithms/21_niblit_freqtrade \
           -c user_data/config.json

On any connectivity error the strategy falls back to "hold" (no trade),
so a Niblit outage never crashes a live backtest or dry-run.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Dict, Optional

import pandas as pd

# ── Niblit bridge import ───────────────────────────────────────────────────────
_BRIDGE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "niblit_bridge")
if _BRIDGE_DIR not in sys.path:
    sys.path.insert(0, _BRIDGE_DIR)

try:
    from freqtrade_adapter import NiblitHTTPAdapter  # type: ignore[import]
    _NIBLIT_AVAILABLE = True
except ImportError:
    NiblitHTTPAdapter = None  # type: ignore[assignment, misc]
    _NIBLIT_AVAILABLE = False

# ── Freqtrade import (available only inside freqtrade venv) ──────────────────
try:
    from freqtrade.strategy import IStrategy, merge_informative_pair
    from pandas import DataFrame
except ImportError:
    # Allow import outside Freqtrade for linting / tests
    IStrategy = object  # type: ignore[assignment, misc]
    DataFrame = pd.DataFrame  # type: ignore[assignment]

log = logging.getLogger(__name__)


class NiblitSignalStrategy(IStrategy):
    """Freqtrade strategy that uses Niblit's /trade/signal endpoint.

    Configuration via environment variables:
        NIBLIT_API_URL          — Niblit base URL (default: http://127.0.0.1:8000)
        NIBLIT_API_KEY          — optional API key (leave blank if no auth)
        NIBLIT_SIGNAL_TIMEOUT   — HTTP timeout in seconds (default: 5)
        NIBLIT_SIGNAL_RETRIES   — retry count on failure (default: 2)
        NIBLIT_MIN_CONFIDENCE   — minimum confidence to act on (default: 0.55)

    Fallback behaviour:
        When Niblit is unreachable ALL signals default to "hold" so no trades
        are entered or exited.  A warning is logged on each failure.
    """

    # ── Freqtrade required settings ───────────────────────────────────────────
    INTERFACE_VERSION = 3
    timeframe = os.environ.get("NIBLIT_TIMEFRAME", "1h")
    can_short = False
    minimal_roi = {"0": 0.05}
    stoploss = -0.03
    trailing_stop = False

    _min_confidence: float = float(os.environ.get("NIBLIT_MIN_CONFIDENCE", "0.55"))

    def __init__(self, config: Dict) -> None:
        super().__init__(config)
        if _NIBLIT_AVAILABLE:
            self._niblit = NiblitHTTPAdapter()
            log.info(
                "[NiblitSignalStrategy] HTTP adapter initialised → %s",
                self._niblit.api_url,
            )
        else:
            self._niblit = None
            log.warning(
                "[NiblitSignalStrategy] niblit_bridge not found; "
                "all signals will default to 'hold'"
            )

    # ── Indicators ────────────────────────────────────────────────────────────

    def populate_indicators(self, dataframe: DataFrame, metadata: Dict) -> DataFrame:
        """Add basic indicators so Niblit gets richer market context."""
        try:
            import pandas_ta as ta  # type: ignore[import]
            dataframe["rsi"] = ta.rsi(dataframe["close"], length=14)
            macd = ta.macd(dataframe["close"])
            if macd is not None:
                dataframe["macd"] = macd["MACD_12_26_9"]
                dataframe["macdsignal"] = macd["MACDs_12_26_9"]
            dataframe["ema_fast"] = ta.ema(dataframe["close"], length=9)
            dataframe["ema_slow"] = ta.ema(dataframe["close"], length=21)
            dataframe["atr"] = ta.atr(dataframe["high"], dataframe["low"], dataframe["close"])
        except ImportError:
            # pandas_ta not installed — Niblit will receive raw OHLCV only
            pass
        except Exception as exc:
            log.debug("[NiblitSignalStrategy] indicator error: %s", exc)
        return dataframe

    # ── Entry signal ─────────────────────────────────────────────────────────

    def populate_entry_trend(self, dataframe: DataFrame, metadata: Dict) -> DataFrame:
        """Ask Niblit for a signal; enter long when action=='buy'."""
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = ""

        signal, confidence = self._get_signal(metadata["pair"], dataframe)
        if signal == "buy" and confidence >= self._min_confidence:
            dataframe.loc[dataframe.index[-1], "enter_long"] = 1
            dataframe.loc[dataframe.index[-1], "enter_tag"] = (
                f"niblit_buy_{confidence:.2f}"
            )
            log.info(
                "[NiblitSignalStrategy] BUY signal for %s (confidence=%.2f)",
                metadata["pair"], confidence,
            )
        return dataframe

    # ── Exit signal ───────────────────────────────────────────────────────────

    def populate_exit_trend(self, dataframe: DataFrame, metadata: Dict) -> DataFrame:
        """Ask Niblit for a signal; exit long when action=='sell'."""
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = ""

        signal, confidence = self._get_signal(metadata["pair"], dataframe)
        if signal == "sell" and confidence >= self._min_confidence:
            dataframe.loc[dataframe.index[-1], "exit_long"] = 1
            dataframe.loc[dataframe.index[-1], "exit_tag"] = (
                f"niblit_sell_{confidence:.2f}"
            )
            log.info(
                "[NiblitSignalStrategy] SELL signal for %s (confidence=%.2f)",
                metadata["pair"], confidence,
            )
        return dataframe

    # ── Feedback hook (optional — call after trade close) ─────────────────────

    def confirm_trade_exit(
        self,
        pair: str,
        trade: object,
        order_type: str,
        amount: float,
        rate: float,
        time_in_force: str,
        exit_reason: str,
        current_time: object,
        **kwargs,
    ) -> bool:
        """Send trade outcome feedback to Niblit after a trade closes."""
        if self._niblit is not None:
            pnl_pct: Optional[float] = None
            try:
                pnl_pct = float(getattr(trade, "profit_ratio", 0.0)) * 100
            except Exception:
                pass
            outcome = "profit" if (pnl_pct or 0) >= 0 else "loss"
            self._niblit.send_feedback(
                pair=pair,
                action="sell",
                outcome=outcome,
                pnl_pct=pnl_pct,
            )
        return True  # allow the exit

    # ── internal ──────────────────────────────────────────────────────────────

    def _get_signal(self, pair: str, dataframe: DataFrame) -> tuple:
        """Return (action, confidence) from Niblit, or ('hold', 0.5) on error."""
        if self._niblit is None:
            return "hold", 0.5
        try:
            # NiblitHTTPAdapter.get_signal returns just the action string.
            # We call the lower-level _call_signal to also get confidence.
            payload = {
                "pair": pair,
                "timeframe": self.timeframe,
            }
            try:
                last = dataframe.iloc[-1]
                candle = {}
                for col in ("open", "high", "low", "close", "volume",
                            "rsi", "macd", "macdsignal", "ema_fast", "ema_slow", "atr"):
                    if col in last.index:
                        try:
                            candle[col] = float(last[col])
                        except (TypeError, ValueError):
                            pass
                if candle:
                    payload["last_candle"] = candle
            except Exception:
                pass

            import json
            import urllib.request
            body = json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if self._niblit.api_key:
                headers["X-API-Key"] = self._niblit.api_key
            req = urllib.request.Request(
                self._niblit._signal_url, data=body, headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=self._niblit.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            action = data.get("action", "hold")
            confidence = float(data.get("confidence", 0.5))
            return action, confidence
        except Exception as exc:
            log.warning("[NiblitSignalStrategy] signal request failed: %s", exc)
            return "hold", 0.5
