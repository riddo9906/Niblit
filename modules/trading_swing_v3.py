#!/usr/bin/env python3
"""
modules/trading_swing_v3.py — Niblit Filtered Swing Trend Signals v3
─────────────────────────────────────────────────────────────────────
Implements a *Continuous Trend Re-entry* model inspired by the open-source
"Filtered Swing Trend Signals v3" TradingView Pine Script.

Key design principles (matching the original script's intent):
  • After a TP is hit the strategy is NOT locked out — if the Supertrend
    is still active and price crosses back above/below EMA-13 (pullback over)
    with valid MACD fuel, a new leg is entered.
  • State Reset: entryBar and entryPrice reset on every new leg so the
    minimum hold rule applies cleanly to each individual leg.
  • Multi-leg tracking: unlimited legs per trend direction (analogous to
    max_labels_count=500 in TradingView).
  • All signals (entry, TP, re-entry, stop) are stored as KnowledgeItems in
    Niblit's memory/KB for AI introspection and autonomous learning.
  • Notification bus integration: every state change is pushed to the
    process-wide NotificationQueue (non-blocking, Termux-safe).
  • CLI-explorable: FilteredSwingTraderV3.status() and .get_legs() are
    plain-text / JSON summaries exposed via niblit_router commands.

Architecture wiring (see niblit_core.py and niblit_router.py):
  core.swing_trader_v3  → FilteredSwingTraderV3 singleton
  router 'trading swing …' prefix → _handle_trading_swing()

ADDITIVE ONLY — original TradingBrain and all other trading modules
are fully preserved; this module adds alongside them.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("SwingTraderV3")

# ── Hard limits ───────────────────────────────────────────────────────────────
_MAX_LEGS: int = 500            # analogous to max_labels_count=500
_MIN_HOLD_BARS: int = 5         # minimum bars before a TP exit is valid
_DEFAULT_TP_PCT: float = 0.015  # 1.5 % take-profit default
_DEFAULT_SL_PCT: float = 0.008  # 0.8 % stop-loss default


# ══════════════════════════════════════════════════════════════════════════════
# Lightweight technical indicator helpers (no external deps beyond stdlib/math)
# ══════════════════════════════════════════════════════════════════════════════

def _ema(values: List[float], period: int) -> Optional[float]:
    """Return the exponential moving average of *values* with *period* smoothing.

    Returns None if there are fewer than period values.
    """
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema


def _supertrend(
    closes: List[float],
    highs: List[float],
    lows: List[float],
    atr_period: int = 10,
    multiplier: float = 3.0,
) -> Optional[bool]:
    """Minimal Supertrend direction indicator.

    Returns True (bullish / long), False (bearish / short), or None if there
    is insufficient data.  This is a simplified implementation suitable for
    educational and AI introspection use.
    """
    n = len(closes)
    if n < atr_period + 1:
        return None

    # True Range and ATR
    trs = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    atr = sum(trs[-atr_period:]) / atr_period

    mid = (highs[-1] + lows[-1]) / 2
    upper = mid + multiplier * atr
    lower = mid - multiplier * atr

    # Simple trend detection: close above lower band → bullish
    return closes[-1] > lower


def _macd_signal(
    closes: List[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Optional[Dict[str, float]]:
    """Return a dict with 'macd', 'signal', and 'histogram' or None.

    'bullish' key is True when histogram > 0.
    """
    if len(closes) < slow + signal:
        return None
    fast_ema = _ema(closes, fast)
    slow_ema = _ema(closes, slow)
    if fast_ema is None or slow_ema is None:
        return None
    macd_line = fast_ema - slow_ema

    # Build a series of MACD values from successive sub-windows so we can
    # compute a proper EMA signal line.  We need at least (slow + signal)
    # closes to do this; if we have exactly slow+1 we fall back to zero-
    # histogram (neutral) rather than producing a misleading value.
    min_len = slow + signal
    if len(closes) < min_len:
        return {"macd": macd_line, "signal": macd_line, "histogram": 0.0, "bullish": False}

    # Build a list of (slow+1) MACD values using a sliding window so the
    # signal line EMA has signal-many data points to work with.
    macd_series: List[float] = []
    for offset in range(signal, 0, -1):
        window = closes[: len(closes) - offset + 1]
        fe = _ema(window, fast)
        se = _ema(window, slow)
        if fe is not None and se is not None:
            macd_series.append(fe - se)
    macd_series.append(macd_line)  # current MACD as last element

    sig_val = _ema(macd_series, signal) if len(macd_series) >= signal else macd_line
    if sig_val is None:
        sig_val = macd_line
    histogram = macd_line - sig_val
    return {
        "macd": macd_line,
        "signal": sig_val,
        "histogram": histogram,
        "bullish": histogram > 0,
    }


# ══════════════════════════════════════════════════════════════════════════════
# TradeLeg — one complete trade entry/exit record
# ══════════════════════════════════════════════════════════════════════════════

class TradeLeg:
    """Records a single entry→exit leg of a multi-leg trend trade."""

    __slots__ = (
        "leg_id", "direction", "entry_bar", "entry_price",
        "exit_bar", "exit_price", "pnl_pct",
        "exit_reason", "entry_ts", "exit_ts",
        "context_snapshot",
    )

    def __init__(
        self,
        leg_id: int,
        direction: str,   # 'long' or 'short'
        entry_bar: int,
        entry_price: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.leg_id = leg_id
        self.direction = direction
        self.entry_bar = entry_bar
        self.entry_price = entry_price
        self.exit_bar: Optional[int] = None
        self.exit_price: Optional[float] = None
        self.pnl_pct: Optional[float] = None
        self.exit_reason: Optional[str] = None
        self.entry_ts: float = time.time()
        self.exit_ts: Optional[float] = None
        self.context_snapshot: Dict[str, Any] = context or {}

    def close(self, exit_bar: int, exit_price: float, reason: str) -> None:
        self.exit_bar = exit_bar
        self.exit_price = exit_price
        self.exit_ts = time.time()
        self.exit_reason = reason
        if self.direction == "long":
            self.pnl_pct = (exit_price - self.entry_price) / self.entry_price
        else:
            self.pnl_pct = (self.entry_price - exit_price) / self.entry_price

    def to_dict(self) -> Dict[str, Any]:
        return {
            "leg_id": self.leg_id,
            "direction": self.direction,
            "entry_bar": self.entry_bar,
            "entry_price": self.entry_price,
            "exit_bar": self.exit_bar,
            "exit_price": self.exit_price,
            "pnl_pct": round(self.pnl_pct * 100, 3) if self.pnl_pct is not None else None,
            "exit_reason": self.exit_reason,
            "entry_ts": self.entry_ts,
            "exit_ts": self.exit_ts,
            "context_snapshot": self.context_snapshot,
        }


# ══════════════════════════════════════════════════════════════════════════════
# FilteredSwingTraderV3 — main strategy class
# ══════════════════════════════════════════════════════════════════════════════

class FilteredSwingTraderV3:
    """
    Continuous Trend Re-entry swing trading strategy.

    Wires into Niblit's ecosystem:
      • *memory*:  NiblitMemory (or any object with .store_learning())
      • *notify*:  callable(msg: str) — defaults to core.notification_queue.push
      • *knowledge_db*:  KnowledgeDB — stores each leg as a knowledge fact

    All external dependencies are optional; the strategy works in isolation.

    Thread safety: on_new_bar() is protected by an internal lock so it can
    be called from any background thread (e.g. the TradingBrain loop).
    """

    def __init__(
        self,
        memory: Optional[Any] = None,
        notify: Optional[Any] = None,
        knowledge_db: Optional[Any] = None,
        tp_pct: float = _DEFAULT_TP_PCT,
        sl_pct: float = _DEFAULT_SL_PCT,
        ema_period: int = 13,
        min_hold_bars: int = _MIN_HOLD_BARS,
        max_legs: int = _MAX_LEGS,
        paper_mode: bool = True,
    ) -> None:
        # ── External wiring ───────────────────────────────────────────────
        self.memory = memory
        self.notify_fn = notify      # callable or None
        self.knowledge_db = knowledge_db

        # ── Strategy parameters ───────────────────────────────────────────
        self.tp_pct = tp_pct
        self.sl_pct = sl_pct
        self.ema_period = ema_period
        self.min_hold_bars = min_hold_bars
        self.max_legs = max_legs
        self.paper_mode = paper_mode  # True = never send real orders

        # ── State ─────────────────────────────────────────────────────────
        self.active_leg: Optional[TradeLeg] = None
        self.legs: List[TradeLeg] = []
        self._bar_number: int = 0
        self._lock = threading.Lock()

        # ── Price buffer for indicator computation ─────────────────────────
        # Keeps last 200 bars for EMA/MACD/Supertrend computation.
        self._closes: List[float] = []
        self._highs: List[float] = []
        self._lows: List[float] = []
        self._bar_buf_max: int = 200

        log.info(
            "[SwingV3] Initialized — tp=%.1f%% sl=%.1f%% ema=%d paper=%s",
            tp_pct * 100, sl_pct * 100, ema_period, paper_mode,
        )

    # ── Core bar-by-bar processing ────────────────────────────────────────

    def on_new_bar(self, bar: Dict[str, Any]) -> Optional[str]:
        """
        Process a new OHLCV bar and execute strategy logic.

        *bar* must contain at least:
            close (float), high (float), low (float), open (float)

        Optional keys:
            number (int) — bar index, auto-incremented if absent
            volume (float)

        Returns an action string ('enter_long', 'exit_tp', 're-entry', …)
        or None if no action taken.
        """
        with self._lock:
            return self._process_bar(bar)

    def _process_bar(self, bar: Dict[str, Any]) -> Optional[str]:
        close = float(bar.get("close", 0))
        high = float(bar.get("high", close))
        low = float(bar.get("low", close))
        bar_num = bar.get("number", self._bar_number)
        self._bar_number = bar_num + 1

        # ── Update price buffer ───────────────────────────────────────────
        self._closes.append(close)
        self._highs.append(high)
        self._lows.append(low)
        if len(self._closes) > self._bar_buf_max:
            self._closes = self._closes[-self._bar_buf_max:]
            self._highs = self._highs[-self._bar_buf_max:]
            self._lows = self._lows[-self._bar_buf_max:]

        # ── Compute indicators ────────────────────────────────────────────
        ctx = self._compute_context()

        # ── If we have an active leg, check for exit ───────────────────────
        if self.active_leg is not None:
            action = self._check_exit(bar_num, close, ctx)
            if action:
                return action
            # Not exited — check for nothing more to do
            return None

        # ── No active leg — check for entry ──────────────────────────────
        return self._check_entry(bar_num, close, ctx)

    def _compute_context(self) -> Dict[str, Any]:
        """Compute current indicator context from buffered prices."""
        ema13 = _ema(self._closes, self.ema_period)
        macd = _macd_signal(self._closes)
        supertrend = _supertrend(self._closes, self._highs, self._lows)
        return {
            "ema13": ema13,
            "macd": macd,
            "supertrend": supertrend,
            "supertrend_bullish": supertrend is True,
            "supertrend_bearish": supertrend is False,
            "macd_bullish": macd["bullish"] if macd else False,
            "macd_bearish": (not macd["bullish"]) if macd else False,
            "close": self._closes[-1] if self._closes else 0,
        }

    def _entry_conditions_long(self, close: float, ctx: Dict) -> bool:
        """True when all conditions for a LONG entry are met."""
        ema = ctx.get("ema13")
        if ema is None:
            return False
        return (
            ctx["supertrend_bullish"]          # trend is up
            and close > ema                    # price above EMA-13 (pullback over)
            and ctx["macd_bullish"]            # MACD fuel present
        )

    def _entry_conditions_short(self, close: float, ctx: Dict) -> bool:
        """True when all conditions for a SHORT entry are met."""
        ema = ctx.get("ema13")
        if ema is None:
            return False
        return (
            ctx["supertrend_bearish"]          # trend is down
            and close < ema                    # price below EMA-13
            and ctx["macd_bearish"]            # MACD fuel for short
        )

    def _check_entry(
        self, bar_num: int, close: float, ctx: Dict
    ) -> Optional[str]:
        """Enter a long or short leg if conditions are met."""
        if self._entry_conditions_long(close, ctx):
            return self._enter(bar_num, close, "long", ctx)
        if self._entry_conditions_short(close, ctx):
            return self._enter(bar_num, close, "short", ctx)
        return None

    def _enter(
        self, bar_num: int, close: float, direction: str, ctx: Dict
    ) -> str:
        """Open a new trade leg.  State reset as per v3 spec."""
        leg_id = len(self.legs) + 1
        leg = TradeLeg(
            leg_id=leg_id,
            direction=direction,
            entry_bar=bar_num,
            entry_price=close,
            context=ctx.copy(),
        )
        self.active_leg = leg
        if len(self.legs) >= self.max_legs:
            # Keep only the most recent max_legs legs
            self.legs = self.legs[-(self.max_legs - 1):]
        self.legs.append(leg)

        is_reentry = leg_id > 1
        action = "re-entry" if is_reentry else "enter_long" if direction == "long" else "enter_short"
        msg = (
            f"[SwingV3] Leg #{leg_id} {'RE-ENTRY' if is_reentry else 'ENTRY'} "
            f"{direction.upper()} @ {close:.6f} | bar={bar_num} | "
            f"supertrend={'UP' if ctx['supertrend_bullish'] else 'DOWN'} "
            f"macd={'bull' if ctx['macd_bullish'] else 'bear'} "
            f"ema13={ctx['ema13']:.6f if ctx['ema13'] else 'n/a'}"
        )
        log.info(msg)
        self._notify(msg)
        self._store_leg_entry(leg)
        return action

    def _check_exit(
        self, bar_num: int, close: float, ctx: Dict
    ) -> Optional[str]:
        """Check take-profit, stop-loss, and trend-reversal exit conditions."""
        leg = self.active_leg
        if leg is None:
            return None

        bars_held = bar_num - leg.entry_bar

        # ── Take Profit ───────────────────────────────────────────────────
        tp_triggered = False
        if leg.direction == "long":
            tp_price = leg.entry_price * (1 + self.tp_pct)
            tp_triggered = close >= tp_price
        else:
            tp_price = leg.entry_price * (1 - self.tp_pct)
            tp_triggered = close <= tp_price

        if tp_triggered and bars_held >= self.min_hold_bars:
            self._exit_leg(bar_num, close, "take_profit")
            # After TP: check for immediate re-entry (continuous trend model)
            reentry = self._check_entry(bar_num, close, ctx)
            return f"exit_tp{'_reentry' if reentry else ''}"

        # ── Stop Loss ─────────────────────────────────────────────────────
        sl_triggered = False
        if leg.direction == "long":
            sl_price = leg.entry_price * (1 - self.sl_pct)
            sl_triggered = close <= sl_price
        else:
            sl_price = leg.entry_price * (1 + self.sl_pct)
            sl_triggered = close >= sl_price

        if sl_triggered:
            self._exit_leg(bar_num, close, "stop_loss")
            return "exit_sl"

        # ── Trend reversal exit ───────────────────────────────────────────
        if leg.direction == "long" and ctx["supertrend_bearish"]:
            self._exit_leg(bar_num, close, "trend_reversal")
            return "exit_reversal"
        if leg.direction == "short" and ctx["supertrend_bullish"]:
            self._exit_leg(bar_num, close, "trend_reversal")
            return "exit_reversal"

        return None

    def _exit_leg(self, bar_num: int, close: float, reason: str) -> None:
        """Close the active leg and persist to memory/KB."""
        if self.active_leg is None:
            return
        self.active_leg.close(bar_num, close, reason)
        leg = self.active_leg
        self.active_leg = None

        msg = (
            f"[SwingV3] Leg #{leg.leg_id} EXIT ({reason}) "
            f"{leg.direction.upper()} @ {close:.6f} | "
            f"PnL: {leg.pnl_pct * 100:+.3f}% | bars held: {bar_num - leg.entry_bar}"
        )
        log.info(msg)
        self._notify(msg)
        self._store_leg_exit(leg)

    # ── Persistence / KB integration ──────────────────────────────────────

    def _store_leg_entry(self, leg: TradeLeg) -> None:
        """Store leg entry as a knowledge fact for AI learning."""
        fact = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "input": f"swing_v3:leg:{leg.leg_id}:entry",
            "value": {
                "leg_id": leg.leg_id,
                "direction": leg.direction,
                "entry_price": leg.entry_price,
                "entry_bar": leg.entry_bar,
                "context": leg.context_snapshot,
            },
            "source": "trading_swing_v3",
        }
        self._persist(f"swing_v3:leg:{leg.leg_id}:entry", fact)

    def _store_leg_exit(self, leg: TradeLeg) -> None:
        """Store leg exit as a knowledge fact for AI learning."""
        fact = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "input": f"swing_v3:leg:{leg.leg_id}:exit",
            "value": leg.to_dict(),
            "source": "trading_swing_v3",
        }
        self._persist(f"swing_v3:leg:{leg.leg_id}:exit", fact)

        # Also store in KnowledgeDB with tags for easy recall
        if self.knowledge_db is not None:
            try:
                tag_set = [
                    "trading", "swing_v3", leg.direction, leg.exit_reason or "unknown"
                ]
                self.knowledge_db.store(
                    f"swing_v3:leg:{leg.leg_id}",
                    str(leg.to_dict()),
                    tags=tag_set,
                )
            except Exception as exc:
                log.debug("[SwingV3] KnowledgeDB store failed: %s", exc)

    def _persist(self, key: str, fact: Dict) -> None:
        """Persist a fact to the memory store if available."""
        if self.memory is None:
            return
        try:
            if hasattr(self.memory, "store_learning"):
                self.memory.store_learning(fact)
        except Exception as exc:
            log.debug("[SwingV3] memory persist failed for %s: %s", key, exc)

    def _notify(self, msg: str) -> None:
        """Push a notification via the wired notify callable or notification_queue."""
        if self.notify_fn is not None:
            try:
                self.notify_fn(msg)
                return
            except Exception as exc:
                log.debug("[SwingV3] notify_fn failed: %s", exc)
        # Fallback: push to global notification queue
        try:
            from core.notification_queue import notif_queue
            notif_queue.push(msg)
        except Exception:
            pass

    # ── Public status / introspection API ─────────────────────────────────

    def status(self) -> str:
        """Return a CLI-friendly status string."""
        with self._lock:
            total = len(self.legs)
            closed = [l for l in self.legs if l.exit_price is not None]
            wins = [l for l in closed if (l.pnl_pct or 0) > 0]
            win_rate = len(wins) / len(closed) if closed else 0
            avg_pnl = (
                sum((l.pnl_pct or 0) for l in closed) / len(closed) * 100
                if closed else 0
            )
            active_info = "none"
            if self.active_leg:
                al = self.active_leg
                active_info = (
                    f"#{al.leg_id} {al.direction.upper()} "
                    f"entry={al.entry_price:.6f} bar={al.entry_bar}"
                )

        return (
            f"[FilteredSwingTraderV3]\n"
            f"  Paper mode:     {'YES (no real orders)' if self.paper_mode else 'LIVE'}\n"
            f"  Total legs:     {total}\n"
            f"  Closed legs:    {len(closed)}\n"
            f"  Win rate:       {win_rate * 100:.1f}%\n"
            f"  Avg PnL:        {avg_pnl:+.3f}%\n"
            f"  Active leg:     {active_info}\n"
            f"  TP:             {self.tp_pct * 100:.2f}%\n"
            f"  SL:             {self.sl_pct * 100:.2f}%\n"
            f"  EMA period:     {self.ema_period}\n"
            f"  Min hold bars:  {self.min_hold_bars}"
        )

    def get_legs(self, last_n: int = 10) -> List[Dict[str, Any]]:
        """Return the last *last_n* trade legs as dicts."""
        with self._lock:
            return [l.to_dict() for l in self.legs[-last_n:]]

    def explain_last_entry(self) -> str:
        """Plain-text explanation of the last entry signal for AI introspection."""
        with self._lock:
            recent = [l for l in self.legs if l.entry_price is not None]
            if not recent:
                return "No trades recorded yet."
            leg = recent[-1]
        ctx = leg.context_snapshot
        lines = [
            f"Last entry: Leg #{leg.leg_id} ({leg.direction.upper()})",
            f"  Entry price:  {leg.entry_price:.6f}",
            f"  Supertrend:   {'BULLISH' if ctx.get('supertrend_bullish') else 'BEARISH'}",
            f"  MACD:         {'bullish' if ctx.get('macd_bullish') else 'bearish'}",
        ]
        if ctx.get("ema13") is not None:
            lines.append(f"  EMA-13:       {ctx['ema13']:.6f}")
        if leg.exit_price is not None:
            lines.append(f"  Exit price:   {leg.exit_price:.6f}")
            lines.append(f"  Exit reason:  {leg.exit_reason}")
            lines.append(f"  PnL:          {(leg.pnl_pct or 0) * 100:+.3f}%")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# Module self-test
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import random
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("=== FilteredSwingTraderV3 self-test ===")

    trader = FilteredSwingTraderV3(tp_pct=0.01, sl_pct=0.005, paper_mode=True)

    # Simulate 100 bars of a rising market
    price = 100.0
    for i in range(100):
        price *= 1 + random.uniform(-0.003, 0.005)
        bar = {
            "number": i,
            "close": price,
            "high": price * 1.002,
            "low": price * 0.998,
            "open": price * 0.999,
        }
        action = trader.on_new_bar(bar)
        if action:
            print(f"  Bar {i:3d}: {action}")

    print(trader.status())
    print(trader.explain_last_entry())
    print("FilteredSwingTraderV3 OK")
