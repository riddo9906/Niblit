#!/usr/bin/env python3
"""
modules/position_sizer.py — Kelly Criterion Position Sizer for Niblit
======================================================================
Provides position-sizing utilities for TradingBrain and other execution
layers, implementing:

  * **Kelly Criterion** — f* = (p·b − q) / b
  * **Fractional Kelly** — scale f* by a safety fraction (default ½-Kelly)
  * **Max-drawdown circuit breaker** — suspends trading when the
    portfolio equity drops more than a configurable threshold from its
    peak, preventing runaway losses on adverse market regimes.

Usage::

    from modules.position_sizer import PositionSizer

    sizer = PositionSizer(kelly_fraction=0.5, max_fraction=0.25,
                          max_drawdown_pct=0.15)

    # Compute a position-size fraction (0–max_fraction)
    fraction = sizer.position_fraction(
        win_rate=0.55,
        avg_win_pct=0.02,
        avg_loss_pct=0.01,
    )

    # Update equity peak and check circuit breaker
    sizer.update_equity(current_equity=9500.0)
    if sizer.circuit_breaker_open:
        print("Trading halted — drawdown exceeded threshold")

Singleton via ``get_position_sizer()``.

Configuration (environment variables)::

    NIBLIT_KELLY_FRACTION     — Fractional-Kelly multiplier (default 0.5)
    NIBLIT_MAX_POSITION_FRAC  — Hard cap on any single position (default 0.25)
    NIBLIT_MAX_DRAWDOWN_PCT   — Max drawdown before circuit breaker trips
                                (default 0.20, i.e. 20 %)
"""

from __future__ import annotations

import logging
import math
import os
import threading
from typing import Optional

log = logging.getLogger(__name__)

# ── module-level defaults (overridable via env) ───────────────────────────────
_DEFAULT_KELLY_FRACTION = float(os.getenv("NIBLIT_KELLY_FRACTION", "0.5"))
_DEFAULT_MAX_POSITION_FRAC = float(os.getenv("NIBLIT_MAX_POSITION_FRAC", "0.25"))
_DEFAULT_MAX_DRAWDOWN_PCT = float(os.getenv("NIBLIT_MAX_DRAWDOWN_PCT", "0.20"))


class PositionSizer:
    """Kelly Criterion position sizer with a max-drawdown circuit breaker.

    Args:
        kelly_fraction:   Safety multiplier applied to the raw Kelly fraction.
                          ``1.0`` = full Kelly, ``0.5`` = half Kelly (safer
                          default), ``0.0`` disables Kelly sizing entirely.
        max_fraction:     Hard cap on the returned position fraction regardless
                          of the Kelly calculation (e.g. 0.25 = never risk
                          more than 25 % of capital on one trade).
        max_drawdown_pct: Portfolio drawdown threshold that trips the circuit
                          breaker (e.g. 0.20 = halt when equity falls 20 %
                          from its recorded peak).
        initial_equity:   Optional starting equity for peak tracking.
    """

    def __init__(
        self,
        kelly_fraction: float = _DEFAULT_KELLY_FRACTION,
        max_fraction: float = _DEFAULT_MAX_POSITION_FRAC,
        max_drawdown_pct: float = _DEFAULT_MAX_DRAWDOWN_PCT,
        initial_equity: float = 0.0,
    ) -> None:
        self._kelly_fraction = max(0.0, min(float(kelly_fraction), 1.0))
        self._max_fraction = max(0.0, min(float(max_fraction), 1.0))
        self._max_drawdown_pct = max(0.0, float(max_drawdown_pct))

        self._peak_equity: float = max(0.0, float(initial_equity))
        self._current_equity: float = self._peak_equity
        self._circuit_breaker_open: bool = False

        self._lock = threading.Lock()

        log.info(
            "[PositionSizer] Initialised — kelly_fraction=%.2f max_fraction=%.2f "
            "max_drawdown=%.1f%%",
            self._kelly_fraction,
            self._max_fraction,
            self._max_drawdown_pct * 100,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Kelly Criterion
    # ─────────────────────────────────────────────────────────────────────────

    def compute_kelly(
        self,
        win_rate: float,
        avg_win_pct: float,
        avg_loss_pct: float,
    ) -> float:
        """Compute the raw full-Kelly fraction.

        Formula: ``f* = (p·b − q) / b``

        where ``p`` = win_rate, ``q`` = 1 − p,
        and   ``b`` = avg_win_pct / avg_loss_pct (the payoff ratio).

        Args:
            win_rate:     Historical win rate in [0, 1] (e.g. 0.55 for 55 %).
            avg_win_pct:  Average winning return as a positive fraction
                          (e.g. 0.02 for 2 %).
            avg_loss_pct: Average losing return as a *positive* fraction
                          (e.g. 0.01 for 1 %).

        Returns:
            Raw Kelly fraction clamped to ``[0, 1]``.  Returns ``0.0`` for
            degenerate inputs (zero win-rate, zero or negative return values).
        """
        if avg_loss_pct <= 0 or avg_win_pct <= 0:
            return 0.0
        if not (0.0 < win_rate < 1.0):
            return 0.0

        b = avg_win_pct / avg_loss_pct
        p = win_rate
        q = 1.0 - p
        raw = (p * b - q) / b
        return round(max(0.0, min(raw, 1.0)), 6)

    def position_fraction(
        self,
        win_rate: float,
        avg_win_pct: float,
        avg_loss_pct: float,
    ) -> float:
        """Return the recommended position size fraction for a new trade.

        Applies the fractional-Kelly multiplier and the hard ``max_fraction``
        cap.  Returns ``0.0`` when the circuit breaker is open.

        Args:
            win_rate:     Historical win rate (e.g. 0.55).
            avg_win_pct:  Average winning trade return (e.g. 0.02).
            avg_loss_pct: Average losing trade return, positive (e.g. 0.01).

        Returns:
            Position size fraction in ``[0, max_fraction]``.
        """
        with self._lock:
            if self._circuit_breaker_open:
                log.debug(
                    "[PositionSizer] Circuit breaker OPEN — returning 0.0 fraction"
                )
                return 0.0

        raw_kelly = self.compute_kelly(win_rate, avg_win_pct, avg_loss_pct)
        fractional = raw_kelly * self._kelly_fraction
        capped = min(fractional, self._max_fraction)
        result = round(capped, 4)
        log.debug(
            "[PositionSizer] kelly=%.4f fractional=%.4f capped=%.4f",
            raw_kelly, fractional, result,
        )
        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Max-Drawdown Circuit Breaker
    # ─────────────────────────────────────────────────────────────────────────

    def update_equity(self, current_equity: float) -> bool:
        """Update the current equity and check the drawdown circuit breaker.

        The peak equity is updated whenever ``current_equity`` exceeds the
        previous recorded peak.  The circuit breaker trips — and stays open
        until :meth:`reset_circuit_breaker` is called — when the drawdown
        from the peak exceeds ``max_drawdown_pct``.

        Args:
            current_equity: Current portfolio value (same unit as
                             ``initial_equity``).

        Returns:
            ``True`` if the circuit breaker has tripped or was already open,
            ``False`` if the portfolio is within acceptable drawdown limits.
        """
        with self._lock:
            equity = float(current_equity)
            self._current_equity = equity

            # Update peak
            if equity > self._peak_equity:
                self._peak_equity = equity

            # Calculate drawdown
            if self._peak_equity > 0:
                drawdown = (self._peak_equity - equity) / self._peak_equity
            else:
                drawdown = 0.0

            # Trip the circuit breaker if drawdown exceeds threshold
            if drawdown >= self._max_drawdown_pct and not self._circuit_breaker_open:
                self._circuit_breaker_open = True
                log.warning(
                    "[PositionSizer] ⚡ Circuit breaker TRIPPED — drawdown=%.2f%% "
                    "(peak=%.2f current=%.2f threshold=%.2f%%)",
                    drawdown * 100,
                    self._peak_equity,
                    equity,
                    self._max_drawdown_pct * 100,
                )

            return self._circuit_breaker_open

    def reset_circuit_breaker(self) -> None:
        """Manually reset the circuit breaker, allowing trading to resume.

        Should only be called after a deliberate human review of the portfolio
        state, or when a new trading session begins with a fresh equity baseline.
        """
        with self._lock:
            if self._circuit_breaker_open:
                log.info(
                    "[PositionSizer] Circuit breaker RESET — trading may resume. "
                    "peak=%.2f current=%.2f",
                    self._peak_equity,
                    self._current_equity,
                )
            self._circuit_breaker_open = False

    @property
    def circuit_breaker_open(self) -> bool:
        """``True`` when the drawdown circuit breaker is active."""
        with self._lock:
            return self._circuit_breaker_open

    @property
    def current_drawdown(self) -> float:
        """Current drawdown fraction from peak (0.0 = no drawdown)."""
        with self._lock:
            if self._peak_equity <= 0:
                return 0.0
            return round(
                max(0.0, (self._peak_equity - self._current_equity) / self._peak_equity),
                6,
            )

    def status(self) -> dict:
        """Return a status dict describing the current sizer state."""
        with self._lock:
            if self._peak_equity > 0:
                drawdown_pct = round(
                    max(0.0, (self._peak_equity - self._current_equity) / self._peak_equity) * 100,
                    2,
                )
            else:
                drawdown_pct = 0.0
            return {
                "kelly_fraction": self._kelly_fraction,
                "max_fraction": self._max_fraction,
                "max_drawdown_pct": self._max_drawdown_pct,
                "peak_equity": self._peak_equity,
                "current_equity": self._current_equity,
                "current_drawdown_pct": drawdown_pct,
                "circuit_breaker_open": self._circuit_breaker_open,
            }


# ── Singleton ─────────────────────────────────────────────────────────────────
_sizer: Optional[PositionSizer] = None
_sizer_lock = threading.Lock()


def get_position_sizer(**kwargs) -> PositionSizer:
    """Return the process-level :class:`PositionSizer` singleton.

    On first call, a new instance is created using module-level defaults
    (which can be overridden via environment variables or *kwargs*).
    Subsequent calls return the same instance; *kwargs* are ignored after
    first creation.
    """
    global _sizer  # pylint: disable=global-statement
    with _sizer_lock:
        if _sizer is None:
            _sizer = PositionSizer(**kwargs)
        return _sizer
