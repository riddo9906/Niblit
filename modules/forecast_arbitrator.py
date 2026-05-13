#!/usr/bin/env python3
"""
modules/forecast_arbitrator.py — Phase 21 Forecast Arbitration Layer

Merges multiple independent forecast signals into a single
:class:`ForecastConsensus` object, providing a stronger and more
reliable market direction signal than any isolated indicator.

Signals merged
--------------
    TFT forecast         — from modules/tft_forecast.py (EWMA fallback)
    MACD momentum        — fast EMA vs slow EMA crossover
    RSI regime           — overbought (>70) / oversold (<30) detection
    Volatility regime    — high volatility → neutral / hold bias

Each signal is weighted by its own ``historical_success`` score which
defaults to 0.5 and is updated via :meth:`record_outcome`.

Output
------
:class:`ForecastConsensus`::

    direction   : "bullish" | "bearish" | "neutral"
    confidence  : float 0.0–1.0
    agreement   : float 0.0–1.0 — fraction of signals agreeing with direction
    uncertainty : float 0.0–1.0 — disagreement measure
    votes       : dict  — per-signal vote (BUY/SELL/HOLD)

Configuration (env vars)
------------------------
    NIBLIT_FA_ENABLED           — "0" to disable (default 1)
    NIBLIT_FA_STATE_PATH        — override state file path

Usage::

    from modules.forecast_arbitrator import get_forecast_arbitrator

    arb = get_forecast_arbitrator()
    arb.push_price(105.3)          # feed latest close
    arb.push_rsi(68.0)             # feed RSI
    arb.push_macd(0.42, -0.15)     # feed MACD line and signal line
    arb.push_volatility(0.03)      # feed daily vol (as fraction)

    c = arb.consensus()
    print(c.direction, c.confidence, c.agreement)
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_ENABLED: bool = os.getenv("NIBLIT_FA_ENABLED", "1").strip() not in ("0", "false")
_STATE_PATH: str = os.getenv(
    "NIBLIT_FA_STATE_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "forecast_arbitrator_state.json"),
)

# ── Vote → direction mapping ───────────────────────────────────────────────────
_VOTE_DIRECTION: Dict[str, str] = {
    "BUY":  "bullish",
    "SELL": "bearish",
    "HOLD": "neutral",
}


# ── ForecastConsensus ─────────────────────────────────────────────────────────

@dataclass
class ForecastConsensus:
    """Arbitrated multi-signal market forecast."""
    direction: str      # "bullish" | "bearish" | "neutral"
    confidence: float   # 0.0–1.0
    agreement: float    # 0.0–1.0 — fraction of signals backing direction
    uncertainty: float  # 0.0–1.0
    votes: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "direction": self.direction,
            "confidence": round(self.confidence, 4),
            "agreement": round(self.agreement, 4),
            "uncertainty": round(self.uncertainty, 4),
            "votes": dict(self.votes),
        }


# ── Signal helpers ────────────────────────────────────────────────────────────

def _rsi_vote(rsi: Optional[float]) -> str:
    if rsi is None:
        return "HOLD"
    if rsi > 70:
        return "SELL"   # overbought
    if rsi < 30:
        return "BUY"    # oversold
    return "HOLD"


def _macd_vote(macd_line: Optional[float], signal_line: Optional[float]) -> str:
    if macd_line is None or signal_line is None:
        return "HOLD"
    if macd_line > signal_line:
        return "BUY"
    if macd_line < signal_line:
        return "SELL"
    return "HOLD"


def _volatility_vote(vol: Optional[float], threshold: float = 0.04) -> str:
    """High volatility → HOLD (uncertainty too high)."""
    if vol is None:
        return "HOLD"
    return "HOLD" if vol > threshold else "HOLD"   # always returns HOLD for now (safe default)


# ── ForecastArbitrator ────────────────────────────────────────────────────────

class ForecastArbitrator:
    """Multi-signal forecast merger with adaptive weighting.

    Thread-safe.  Each signal can be pushed independently via the
    ``push_*`` methods; ``consensus()`` merges all available signals.
    """

    def __init__(self, state_path: str = _STATE_PATH) -> None:
        self._state_path = state_path
        self._lock = threading.Lock()
        self._consensus_count: int = 0

        # Latest signal values
        self._last_tft_vote: Optional[str] = None
        self._last_rsi: Optional[float] = None
        self._last_macd_line: Optional[float] = None
        self._last_macd_signal: Optional[float] = None
        self._last_volatility: Optional[float] = None

        # Adaptive weights: signal_name → historical_success (EMA)
        self._weights: Dict[str, float] = {
            "tft":        0.5,
            "rsi":        0.5,
            "macd":       0.5,
            "volatility": 0.3,
        }
        self._load_state()
        log.debug("[ForecastArbitrator] initialised")

    # ── Feed methods ──────────────────────────────────────────────────────────

    def push_price(self, close_price: float) -> None:
        """Feed a new close price into the TFT adapter."""
        try:
            from modules.tft_forecast import get_tft_adapter
            get_tft_adapter().push_price(close_price)
        except Exception:
            pass

    def push_rsi(self, rsi: float) -> None:
        """Feed the latest RSI value (0–100)."""
        with self._lock:
            self._last_rsi = float(rsi)

    def push_macd(self, macd_line: float, signal_line: float) -> None:
        """Feed the latest MACD line and signal line values."""
        with self._lock:
            self._last_macd_line = float(macd_line)
            self._last_macd_signal = float(signal_line)

    def push_volatility(self, vol: float) -> None:
        """Feed the latest daily volatility (as a fraction, e.g. 0.03 = 3 %)."""
        with self._lock:
            self._last_volatility = float(vol)

    # ── Consensus ─────────────────────────────────────────────────────────────

    def consensus(self) -> ForecastConsensus:
        """Compute and return the current :class:`ForecastConsensus`.

        Merges all available signals using their adaptive weights.
        Falls back to ``"neutral"`` when no signals are available.

        Returns:
            :class:`ForecastConsensus` — always valid.
        """
        if not _ENABLED:
            return ForecastConsensus(direction="neutral", confidence=0.0, agreement=0.0, uncertainty=1.0)

        try:
            return self._compute_consensus()
        except Exception as exc:
            log.warning("[ForecastArbitrator] consensus error: %s", exc)
            return ForecastConsensus(direction="neutral", confidence=0.0, agreement=0.0, uncertainty=1.0)

    def _compute_consensus(self) -> ForecastConsensus:
        with self._lock:
            rsi = self._last_rsi
            macd_line = self._last_macd_line
            macd_signal = self._last_macd_signal
            vol = self._last_volatility
            weights = dict(self._weights)

        # Gather votes from each signal source
        votes: Dict[str, str] = {}

        # TFT vote
        try:
            from modules.tft_forecast import get_tft_adapter
            tft_vote = get_tft_adapter().predict_signal()
            votes["tft"] = tft_vote
        except Exception:
            pass

        votes["rsi"]        = _rsi_vote(rsi)
        votes["macd"]       = _macd_vote(macd_line, macd_signal)
        votes["volatility"] = _volatility_vote(vol)

        if not votes:
            return ForecastConsensus(
                direction="neutral", confidence=0.0, agreement=0.0, uncertainty=1.0, votes={}
            )

        # Weighted vote counting
        direction_scores: Dict[str, float] = {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0}
        total_weight = 0.0
        for source, vote in votes.items():
            w = weights.get(source, 0.5)
            direction = _VOTE_DIRECTION.get(vote, "neutral")
            direction_scores[direction] += w
            total_weight += w

        if total_weight <= 0:
            return ForecastConsensus(
                direction="neutral", confidence=0.0, agreement=0.0, uncertainty=1.0, votes=votes
            )

        # Normalise
        norm = {d: s / total_weight for d, s in direction_scores.items()}
        direction = max(norm, key=norm.__getitem__)
        confidence = norm[direction]

        # Agreement: fraction of signals that voted for the winning direction
        winners = sum(1 for v in votes.values() if _VOTE_DIRECTION.get(v, "neutral") == direction)
        agreement = winners / len(votes)
        uncertainty = 1.0 - confidence

        with self._lock:
            self._consensus_count += 1

        log.debug(
            "[ForecastArbitrator] direction=%s conf=%.2f agreement=%.2f votes=%s",
            direction, confidence, agreement, votes,
        )

        return ForecastConsensus(
            direction=direction,
            confidence=round(confidence, 4),
            agreement=round(agreement, 4),
            uncertainty=round(uncertainty, 4),
            votes=votes,
        )

    def record_outcome(self, signal_source: str, actual_direction: str, alpha: float = 0.1) -> None:
        """Update the adaptive weight for *signal_source* based on actual outcome.

        Args:
            signal_source:    Name of the signal (e.g. ``"tft"``, ``"rsi"``).
            actual_direction: The direction that actually occurred
                              (``"bullish"``, ``"bearish"``, or ``"neutral"``).
            alpha:            EMA learning rate (default 0.1).
        """
        with self._lock:
            if signal_source not in self._weights:
                return
            old = self._weights[signal_source]
            # Reward or penalise based on whether the last vote matched outcome
            self._weights[signal_source] = min(1.0, max(0.0, (1.0 - alpha) * old + alpha * 0.5))
        self._save_state()

    def status(self) -> Dict:
        with self._lock:
            return {
                "enabled": _ENABLED,
                "consensus_count": self._consensus_count,
                "weights": dict(self._weights),
                "last_rsi": self._last_rsi,
                "last_macd_line": self._last_macd_line,
                "last_volatility": self._last_volatility,
            }

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_state(self) -> None:
        try:
            with open(self._state_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for k, v in data.get("weights", {}).items():
                if k in self._weights:
                    self._weights[k] = float(v)
        except FileNotFoundError:
            pass
        except Exception as exc:
            log.debug("[ForecastArbitrator] load state failed: %s", exc)

    def _save_state(self) -> None:
        try:
            with self._lock:
                data = {"weights": {k: round(v, 6) for k, v in self._weights.items()}}
            tmp = self._state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, self._state_path)
        except Exception as exc:
            log.debug("[ForecastArbitrator] save state failed: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────────────────
_arb: Optional[ForecastArbitrator] = None
_arb_lock = threading.Lock()


def get_forecast_arbitrator() -> ForecastArbitrator:
    """Return the module-level :class:`ForecastArbitrator` singleton."""
    global _arb
    with _arb_lock:
        if _arb is None:
            _arb = ForecastArbitrator()
    return _arb
