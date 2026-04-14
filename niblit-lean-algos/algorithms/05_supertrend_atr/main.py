# region imports
from AlgorithmImports import *
# endregion

# Optional Niblit bridge
try:
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.join(_os.path.dirname(__file__), '..', '..', 'niblit_bridge'))
    from connector import NiblitBridge as _NiblitBridge
    _NIBLIT_AVAILABLE = True
except Exception:
    _NIBLIT_AVAILABLE = False
    _NiblitBridge = None

import math
from collections import deque


class _SupertrendCalculator:
    """
    Pure-Python Supertrend implementation.

    Algorithm:
        Basic Upper Band = (High + Low) / 2 + multiplier * ATR
        Basic Lower Band = (High + Low) / 2 - multiplier * ATR
        Final Upper/Lower bands with carryover logic.
        Trend: +1 (bullish) when close > final lower band,
               -1 (bearish) when close < final upper band.
    """

    def __init__(self, period: int = 10, multiplier: float = 3.0) -> None:
        self._period     = period
        self._multiplier = multiplier
        # Rolling high, low, close for ATR calculation
        self._highs:  deque = deque(maxlen=period + 1)
        self._lows:   deque = deque(maxlen=period + 1)
        self._closes: deque = deque(maxlen=period + 1)
        self._atr:    float = 0.0
        self._prev_final_upper: float = float("inf")
        self._prev_final_lower: float = 0.0
        self._prev_close:       float = 0.0
        self._trend:            int   = 1   # +1 bullish, -1 bearish
        self._bars:             int   = 0

    def update(self, high: float, low: float, close: float) -> int:
        """Update with new bar. Returns current trend direction (+1/-1)."""
        self._highs.append(high)
        self._lows.append(low)
        self._closes.append(close)
        self._bars += 1

        if self._bars < self._period:
            self._prev_close = close
            return self._trend

        # Wilder ATR
        tr_vals = []
        closes_list = list(self._closes)
        highs_list  = list(self._highs)
        lows_list   = list(self._lows)
        for i in range(1, len(closes_list)):
            tr = max(highs_list[i] - lows_list[i],
                     abs(highs_list[i] - closes_list[i - 1]),
                     abs(lows_list[i]  - closes_list[i - 1]))
            tr_vals.append(tr)
        if tr_vals:
            self._atr = sum(tr_vals) / len(tr_vals)

        hl2 = (high + low) / 2.0
        basic_upper = hl2 + self._multiplier * self._atr
        basic_lower = hl2 - self._multiplier * self._atr

        # Carry-over logic
        final_upper = basic_upper if (basic_upper < self._prev_final_upper
                                      or self._prev_close > self._prev_final_upper) \
                                  else self._prev_final_upper
        final_lower = basic_lower if (basic_lower > self._prev_final_lower
                                      or self._prev_close < self._prev_final_lower) \
                                  else self._prev_final_lower

        # Trend determination
        if self._trend == -1 and close > final_upper:
            self._trend = 1
        elif self._trend == 1 and close < final_lower:
            self._trend = -1

        self._prev_final_upper = final_upper
        self._prev_final_lower = final_lower
        self._prev_close       = close
        return self._trend

    @property
    def is_ready(self) -> bool:
        return self._bars >= self._period


class SupertrendAtr(QCAlgorithm):
    """
    Supertrend ATR Strategy (crypto-optimized, minute resolution).

    Uses pure-Python Supertrend (period=10, mult=3).
    NiblitBridge used as confirmation filter.
    Risk: 1.5× ATR stop; 2% portfolio risk per trade.
    """

    _SYMBOL    = "BTCUSD"
    _ST_PERIOD = 10
    _ST_MULT   = 3.0
    _ATR_MULT  = 1.5
    _RISK_PCT  = 0.015

    def initialize(self) -> None:
        self.set_start_date(2022, 1, 1)
        self.set_end_date(2024, 1, 1)
        self.set_cash(100_000)

        if not self.live_mode:
            self.set_brokerage_model(BrokerageName.PAPER_BROKERAGE)

        crypto = self.add_crypto(self._SYMBOL, Resolution.MINUTE)
        self._sym = crypto.symbol

        self._atr       = self.atr(self._sym, 14, Resolution.MINUTE)
        self._supertrend = _SupertrendCalculator(self._ST_PERIOD, self._ST_MULT)

        self.set_warm_up(self._ST_PERIOD + 5, Resolution.MINUTE)

        # Consolidate to 1-hour bars for cleaner signals
        self.consolidate(self._sym, timedelta(hours=1), self._on_hourly_bar)

        self._trend:       int   = 0   # +1 or -1
        self._stop_price:  float = 0.0
        self._position:    int   = 0

        self._bridge = None
        if _NIBLIT_AVAILABLE and _NiblitBridge is not None:
            try:
                self._bridge = _NiblitBridge()
                self.log("NiblitBridge connected.")
            except Exception as exc:
                self.log(f"NiblitBridge init failed: {exc}")

    def _on_hourly_bar(self, bar: TradeBar) -> None:
        """Process consolidated hourly bars through Supertrend."""
        self._trend = self._supertrend.update(bar.high, bar.low, bar.close)

    def on_data(self, data: Slice) -> None:
        if self.is_warming_up or not self._supertrend.is_ready:
            return
        if self._sym not in data.bars:
            return
        if not self._atr.is_ready:
            return

        price = data.bars[self._sym].close
        atr   = self._atr.current.value

        # Stop loss check
        if self._position != 0 and self._stop_price > 0:
            stop_hit = (self._position ==  1 and price <= self._stop_price) or \
                       (self._position == -1 and price >= self._stop_price)
            if stop_hit:
                self.liquidate(self._sym)
                self._position   = 0
                self._stop_price = 0.0
                self.log(f"Stop triggered @ {price:.2f}")
                return

        # Trend flip = entry / exit signal
        want_long  = self._trend == 1
        want_short = self._trend == -1

        # Niblit confirmation
        niblit_ok = True
        if self._bridge is not None:
            try:
                act = (self._bridge.get_signal() or "HOLD").upper()
                conf = self._bridge.get_confidence()
                self.log(f"Niblit: {act} conf={conf:.3f}")
                if want_long  and act == "SELL" and conf > 0.7:
                    niblit_ok = False
                if want_short and act == "BUY"  and conf > 0.7:
                    niblit_ok = False
            except Exception as exc:
                self.log(f"Niblit error: {exc}")

        if not niblit_ok:
            return

        if want_long and self._position != 1:
            if self._position == -1:
                self.liquidate(self._sym)
            self._open_trade(1, price, atr)

        elif want_short and self._position != -1:
            if self._position == 1:
                self.liquidate(self._sym)
            self._open_trade(-1, price, atr)

    def _open_trade(self, direction: int, price: float, atr: float) -> None:
        equity    = self.portfolio.total_portfolio_value
        stop_dist = self._ATR_MULT * atr
        if stop_dist == 0 or price == 0:
            return
        dollar_risk = equity * self._RISK_PCT
        qty_float   = dollar_risk / stop_dist
        # Crypto allows fractional positions
        qty = round(qty_float, 6)
        if qty <= 0:
            return
        self.market_order(self._sym, qty * direction)
        self._stop_price = (price - stop_dist) if direction == 1 \
                           else (price + stop_dist)
        self._position   = direction
        label = "LONG" if direction == 1 else "SHORT"
        self.log(f"Supertrend {label} {qty:.6f} @ ~{price:.2f} "
                 f"trend={self._trend}  stop={self._stop_price:.2f}")

    def on_order_event(self, order_event: OrderEvent) -> None:
        self.log(str(order_event))

    def on_end_of_algorithm(self) -> None:
        self.log(f"Final value: {self.portfolio.total_portfolio_value:.2f}")
