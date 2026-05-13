#!/usr/bin/env python3
"""
modules/tft_forecast.py — Temporal Fusion Transformer market forecast adapter.

Provides a lightweight, optional second-opinion signal for TradingBrain by
predicting multi-horizon price quantiles.  When ``pytorch-forecasting`` and
``pytorch-lightning`` are available the module trains and runs a real TFT
model on the rolling price history.  When those libraries are absent it falls
back to a fast, dependency-free trend estimator (EWMA momentum) so the
integration is always active without requiring heavy installs.

The signal is intended to be used *alongside* the heuristic / RL policy in
``TradingBrain.decide_action()`` as an additional confirmation vote, not as
a replacement.

Architecture::

    Price history buffer (ring buffer of close prices)
          │
          ▼
    TFTForecastAdapter.predict_signal()
          │
          ├── pytorch-forecasting available?
          │       yes ──► TFT model (train on buffer, predict 3 horizons)
          │       no  ──► EWMA momentum fallback
          │
          ▼
    "BUY" | "SELL" | "HOLD"

Configuration (environment variables)::

    NIBLIT_TFT_ENABLED          — Set to "0" to disable TFT signal (default 1)
    NIBLIT_TFT_HISTORY_LEN      — Rolling window size (default 64)
    NIBLIT_TFT_FORECAST_HORIZON — Number of steps ahead to forecast (default 3)
    NIBLIT_TFT_BUY_THRESHOLD    — Fraction gain to trigger BUY (default 0.002)
    NIBLIT_TFT_SELL_THRESHOLD   — Fraction loss to trigger SELL (default -0.002)

Usage::

    from modules.tft_forecast import get_tft_adapter

    adapter = get_tft_adapter()
    adapter.push_price(close_price)
    signal = adapter.predict_signal()   # "BUY" | "SELL" | "HOLD"
"""

from __future__ import annotations

import collections
import logging
import math
import os
import threading
from typing import Deque, List, Optional

log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
_ENABLED: bool = os.getenv("NIBLIT_TFT_ENABLED", "1").strip() not in ("0", "false", "no")
_HISTORY_LEN: int = int(os.getenv("NIBLIT_TFT_HISTORY_LEN", "64"))
_FORECAST_HORIZON: int = int(os.getenv("NIBLIT_TFT_FORECAST_HORIZON", "3"))
_BUY_THRESHOLD: float = float(os.getenv("NIBLIT_TFT_BUY_THRESHOLD", "0.002"))
_SELL_THRESHOLD: float = float(os.getenv("NIBLIT_TFT_SELL_THRESHOLD", "-0.002"))

# Minimum price observations before any forecast is attempted
_MIN_HISTORY: int = max(8, _FORECAST_HORIZON + 2)

# ── Optional heavy imports (graceful degradation) ─────────────────────────────
_PTF_AVAILABLE = False
try:
    import torch  # noqa: F401
    import pytorch_forecasting  # noqa: F401
    import pytorch_lightning  # noqa: F401
    _PTF_AVAILABLE = True
    log.info("[TFTForecast] pytorch-forecasting available — TFT mode active")
except ImportError:
    log.debug(
        "[TFTForecast] pytorch-forecasting not installed — using EWMA fallback. "
        "Install with: pip install pytorch-forecasting pytorch-lightning"
    )


# ─────────────────────────────────────────────────────────────────────────────
# EWMA-based fallback forecast
# ─────────────────────────────────────────────────────────────────────────────

def _ewma_signal(prices: List[float], horizon: int) -> str:
    """Compute a trend signal using exponential weighted moving averages.

    Uses a short EWMA (fast) vs. long EWMA (slow) crossover to predict the
    price direction over *horizon* steps.

    Returns:
        "BUY", "SELL", or "HOLD"
    """
    n = len(prices)
    if n < 4:
        return "HOLD"

    # Fast α ≈ 2/(short_period+1), slow α ≈ 2/(long_period+1)
    short_period = max(3, n // 4)
    long_period = max(short_period + 1, n // 2)

    def _ewma(data: List[float], period: int) -> float:
        alpha = 2.0 / (period + 1)
        val = data[0]
        for p in data[1:]:
            val = alpha * p + (1.0 - alpha) * val
        return val

    fast = _ewma(prices, short_period)
    slow = _ewma(prices, long_period)
    last = prices[-1]

    if last == 0.0:
        return "HOLD"

    # MACD-like crossover projected forward by a simple momentum extrapolation
    macd = (fast - slow) / abs(slow) if slow != 0.0 else 0.0
    # Scale MACD by horizon to estimate multi-step return
    projected_return = macd * math.sqrt(horizon)

    if projected_return >= _BUY_THRESHOLD:
        return "BUY"
    if projected_return <= _SELL_THRESHOLD:
        return "SELL"
    return "HOLD"


# ─────────────────────────────────────────────────────────────────────────────
# TFT-based forecast (requires pytorch-forecasting)
# ─────────────────────────────────────────────────────────────────────────────

def _tft_signal(prices: List[float], horizon: int) -> str:
    """Run a minimal TFT model on the price buffer and return a signal.

    Trains a compact TemporalFusionTransformer on the rolling history buffer
    and predicts *horizon*-step-ahead quantiles (10th, 50th, 90th).

    The decision rule:
    * If the 10th-percentile forecast > current price by _BUY_THRESHOLD  → BUY
    * If the 90th-percentile forecast < current price by _SELL_THRESHOLD → SELL
    * Otherwise → HOLD

    Returns:
        "BUY", "SELL", or "HOLD"
    """
    try:
        import numpy as np
        import pandas as pd
        import torch
        from pytorch_forecasting import TimeSeriesDataSet, TemporalFusionTransformer
        from pytorch_forecasting.metrics import QuantileLoss
        import pytorch_lightning as pl

        n = len(prices)
        current_price = prices[-1]

        # Build a minimal single-series dataframe
        df = pd.DataFrame({
            "time_idx": list(range(n)),
            "series": ["price"] * n,
            "value": [float(p) for p in prices],
            "group": [0] * n,
        })

        max_encoder = max(4, n - horizon - 1)
        training_cutoff = n - horizon - 1

        if training_cutoff < 2:
            log.debug("[TFTForecast] Not enough data for TFT — falling back to EWMA")
            return _ewma_signal(prices, horizon)

        training = TimeSeriesDataSet(
            df[df.time_idx <= training_cutoff],
            time_idx="time_idx",
            target="value",
            group_ids=["group"],
            min_encoder_length=min(max_encoder // 2, 2),
            max_encoder_length=max_encoder,
            min_prediction_length=1,
            max_prediction_length=horizon,
            static_categoricals=["group"],
            time_varying_unknown_reals=["value"],
            target_normalizer=None,
        )

        validation = TimeSeriesDataSet.from_dataset(
            training,
            df,
            predict=True,
            stop_randomization=True,
        )

        train_loader = training.to_dataloader(train=True, batch_size=max(4, n // 4), num_workers=0)
        val_loader = validation.to_dataloader(train=False, batch_size=1, num_workers=0)

        tft = TemporalFusionTransformer.from_dataset(
            training,
            learning_rate=0.03,
            hidden_size=8,
            attention_head_size=1,
            dropout=0.1,
            hidden_continuous_size=4,
            output_size=3,  # 3 quantiles: 10th, 50th, 90th
            loss=QuantileLoss(),
            log_interval=10,
            reduce_on_plateau_patience=4,
        )

        trainer = pl.Trainer(
            max_epochs=5,
            enable_progress_bar=False,
            enable_model_summary=False,
            logger=False,
            accelerator="cpu",
        )
        trainer.fit(tft, train_dataloaders=train_loader, val_dataloaders=val_loader)

        predictions = tft.predict(val_loader, return_y=False, trainer_kwargs={"logger": False})
        # predictions shape: (batch, horizon, quantiles)
        pred_arr = predictions.numpy() if hasattr(predictions, "numpy") else np.array(predictions)
        if pred_arr.ndim == 3:
            # Take last horizon step, all quantiles
            q10 = float(pred_arr[0, -1, 0])
            q90 = float(pred_arr[0, -1, 2])
        elif pred_arr.ndim == 2:
            q10 = float(pred_arr[0, 0])
            q90 = float(pred_arr[0, -1])
        else:
            return _ewma_signal(prices, horizon)

        if current_price <= 0:
            return "HOLD"

        if (q10 - current_price) / current_price >= _BUY_THRESHOLD:
            return "BUY"
        if (q90 - current_price) / current_price <= _SELL_THRESHOLD:
            return "SELL"
        return "HOLD"

    except Exception as exc:
        log.warning("[TFTForecast] TFT model error — falling back to EWMA: %s", exc)
        return _ewma_signal(prices, horizon)


# ─────────────────────────────────────────────────────────────────────────────
# TFTForecastAdapter
# ─────────────────────────────────────────────────────────────────────────────

class TFTForecastAdapter:
    """Rolling price buffer + TFT (or EWMA fallback) market forecast.

    Thread-safe: ``push_price`` and ``predict_signal`` may be called from
    different threads concurrently.

    Args:
        history_len:       Maximum number of close-price observations to keep.
        forecast_horizon:  Number of future steps to predict.
    """

    def __init__(
        self,
        history_len: int = _HISTORY_LEN,
        forecast_horizon: int = _FORECAST_HORIZON,
    ) -> None:
        self._history: Deque[float] = collections.deque(maxlen=history_len)
        self._horizon = max(1, forecast_horizon)
        self._lock = threading.Lock()
        self._last_signal: str = "HOLD"
        self._signal_count: int = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def push_price(self, close_price: float) -> None:
        """Append a new close price to the rolling history buffer."""
        with self._lock:
            self._history.append(float(close_price))

    def predict_signal(self) -> str:
        """Compute and return a BUY / SELL / HOLD forecast signal.

        Uses TFT when pytorch-forecasting is installed, otherwise uses the
        EWMA momentum fallback.  Returns ``"HOLD"`` if the buffer contains
        fewer than ``_MIN_HISTORY`` observations.

        Returns:
            One of ``"BUY"``, ``"SELL"``, or ``"HOLD"``.
        """
        if not _ENABLED:
            return "HOLD"

        with self._lock:
            prices = list(self._history)

        if len(prices) < _MIN_HISTORY:
            return "HOLD"

        if _PTF_AVAILABLE:
            signal = _tft_signal(prices, self._horizon)
        else:
            signal = _ewma_signal(prices, self._horizon)

        with self._lock:
            self._last_signal = signal
            self._signal_count += 1

        log.debug(
            "[TFTForecast] signal=%s  history=%d  horizon=%d  backend=%s",
            signal, len(prices), self._horizon,
            "TFT" if _PTF_AVAILABLE else "EWMA",
        )
        return signal

    def status(self) -> dict:
        """Return a status dict suitable for logging / monitoring."""
        with self._lock:
            return {
                "enabled": _ENABLED,
                "backend": "TFT" if _PTF_AVAILABLE else "EWMA",
                "history_len": len(self._history),
                "history_capacity": self._history.maxlen,
                "forecast_horizon": self._horizon,
                "last_signal": self._last_signal,
                "signal_count": self._signal_count,
            }


# ── Module-level singleton ────────────────────────────────────────────────────
_adapter: Optional[TFTForecastAdapter] = None
_adapter_lock = threading.Lock()


def get_tft_adapter() -> TFTForecastAdapter:
    """Return the module-level :class:`TFTForecastAdapter` singleton."""
    global _adapter
    with _adapter_lock:
        if _adapter is None:
            _adapter = TFTForecastAdapter()
    return _adapter


if __name__ == "__main__":
    print('Running tft_forecast.py')
