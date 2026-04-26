"""
algorithms/21_niblit_freqtrade/NiblitSignalStrategy.py
——————————————————————————————————————————————————————
A Freqtrade strategy that delegates entry/exit decisions to Niblit's
HTTP signal API (POST /trade/signal) and feeds outcomes back so Niblit
can learn from each closed trade (POST /trade/feedback).

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

# Indicator columns forwarded to Niblit — richer set improves KB learning.
_INDICATOR_COLS = (
    "open", "high", "low", "close", "volume",
    "rsi", "macd", "macdsignal", "macdhist",
    "ema_fast", "ema_slow", "ema_200",
    "atr", "bb_upper", "bb_lower", "bb_mid",
    "adx", "cci", "stoch_k", "stoch_d",
)


class NiblitSignalStrategy(IStrategy):
    """Freqtrade strategy that uses Niblit's /trade/signal endpoint.

    Configuration via environment variables:
        NIBLIT_API_URL          — Niblit base URL (default: http://127.0.0.1:8000)
        NIBLIT_API_KEY          — optional API key (leave blank if no auth)
        NIBLIT_SIGNAL_TIMEOUT   — HTTP timeout in seconds (default: 5)
        NIBLIT_SIGNAL_RETRIES   — retry count on failure (default: 2)
        NIBLIT_MIN_CONFIDENCE   — minimum confidence to act on (default: 0.55)
        NIBLIT_FEEDBACK_ON_EXIT — send feedback with indicators on exit (default: 1)

    Fallback behaviour:
        When Niblit is unreachable ALL signals default to "hold" so no trades
        are entered or exited.  A warning is logged on each failure.

    Learning loop:
        After every confirmed trade exit, the strategy sends:
          POST /trade/feedback  { pair, action, outcome, pnl_pct, timeframe, features }
        Niblit stores the indicator pattern + outcome in the KB so the next
        /trade/signal for the same conditions returns a KB-enriched confidence.
        Over time, Niblit learns which indicator combinations lead to profitable
        trades and adjusts its recommendations accordingly.
    """

    # ── Freqtrade required settings ───────────────────────────────────────────
    INTERFACE_VERSION = 3
    timeframe = os.environ.get("NIBLIT_TIMEFRAME", "1h")
    can_short = False
    minimal_roi = {"0": 0.05}
    stoploss = -0.03
    trailing_stop = False

    _min_confidence: float = float(os.environ.get("NIBLIT_MIN_CONFIDENCE", "0.55"))
    _feedback_on_exit: bool = os.environ.get("NIBLIT_FEEDBACK_ON_EXIT", "1") != "0"

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
        """Add technical indicators so Niblit gets richer market context."""
        try:
            import pandas_ta as ta  # type: ignore[import]
            dataframe["rsi"] = ta.rsi(dataframe["close"], length=14)
            macd = ta.macd(dataframe["close"])
            if macd is not None:
                dataframe["macd"] = macd.get("MACD_12_26_9", 0.0)
                dataframe["macdsignal"] = macd.get("MACDs_12_26_9", 0.0)
                dataframe["macdhist"] = macd.get("MACDh_12_26_9", 0.0)
            dataframe["ema_fast"] = ta.ema(dataframe["close"], length=9)
            dataframe["ema_slow"] = ta.ema(dataframe["close"], length=21)
            dataframe["ema_200"] = ta.ema(dataframe["close"], length=200)
            dataframe["atr"] = ta.atr(dataframe["high"], dataframe["low"], dataframe["close"])
            bb = ta.bbands(dataframe["close"])
            if bb is not None:
                dataframe["bb_upper"] = bb.get("BBU_5_2.0", None)
                dataframe["bb_lower"] = bb.get("BBL_5_2.0", None)
                dataframe["bb_mid"]   = bb.get("BBM_5_2.0", None)
            adx_df = ta.adx(dataframe["high"], dataframe["low"], dataframe["close"])
            if adx_df is not None:
                dataframe["adx"] = adx_df.get("ADX_14", None)
            stoch = ta.stoch(dataframe["high"], dataframe["low"], dataframe["close"])
            if stoch is not None:
                dataframe["stoch_k"] = stoch.get("STOCHk_14_3_3", None)
                dataframe["stoch_d"] = stoch.get("STOCHd_14_3_3", None)
            cci_s = ta.cci(dataframe["high"], dataframe["low"], dataframe["close"])
            if cci_s is not None:
                dataframe["cci"] = cci_s
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

    # ── Feedback hook (sends outcome + indicator snapshot so Niblit can learn) ──

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
        """Send trade outcome + indicator snapshot to Niblit after a trade closes.

        Niblit stores the pattern in the KB so future signals for the same
        indicator conditions have KB-informed confidence.
        """
        if self._niblit is not None and self._feedback_on_exit:
            pnl_pct: Optional[float] = None
            try:
                pnl_pct = float(getattr(trade, "profit_ratio", 0.0)) * 100
            except Exception:
                pass
            outcome = "profit" if (pnl_pct or 0) >= 0 else "loss"

            # Gather the most recent indicator snapshot from the live dataframe
            # if it is available in the trade object (Freqtrade >= 2023.7).
            features: Dict[str, float] = {}
            try:
                df = getattr(trade, "dataframe", None) or getattr(trade, "_candle_cache", None)
                if df is not None and hasattr(df, "iloc") and len(df) > 0:
                    last = df.iloc[-1]
                    for col in _INDICATOR_COLS:
                        if col in last.index:
                            try:
                                features[col] = float(last[col])
                            except (TypeError, ValueError):
                                pass
            except Exception:
                pass

            self._niblit.send_feedback(
                pair=pair,
                action="sell",
                outcome=outcome,
                pnl_pct=pnl_pct,
                features=features or None,
                timeframe=self.timeframe,
            )
        return True  # allow the exit

    # ── internal ──────────────────────────────────────────────────────────────

    def _get_signal(self, pair: str, dataframe: DataFrame) -> tuple:
        """Return (action, confidence) from Niblit, or ('hold', 0.5) on error."""
        if self._niblit is None:
            return "hold", 0.5
        try:
            result = self._niblit.get_signal_with_meta(
                pair=pair,
                dataframe=dataframe,
                timeframe=self.timeframe,
            )
            action = result.get("action", "hold")
            confidence = float(result.get("confidence", 0.5))
            meta = result.get("metadata", {})
            if meta.get("reason"):
                log.debug(
                    "[NiblitSignalStrategy] %s reason: %s",
                    pair, meta["reason"],
                )
            return action, confidence
        except Exception as exc:
            log.warning("[NiblitSignalStrategy] signal request failed: %s", exc)
            return "hold", 0.5
