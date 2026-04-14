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


class BollingerSqueeze(QCAlgorithm):
    """
    Bollinger Band Squeeze Strategy.

    Squeeze: Bollinger Bands (20, 2σ) are *inside* the Keltner Channel (20, 1.5×ATR).
    Entry:   On squeeze release, enter in the direction of momentum (close vs midpoint).
    Score:   BB-width percentile over rolling 50 bars – lower percentile = tighter squeeze.
    Risk:    1.5× ATR stop; 2% portfolio risk per trade.
    """

    _SYMBOL    = "SPY"
    _BB_PERIOD = 20
    _BB_STD    = 2.0
    _KC_MULT   = 1.5
    _ATR_PER   = 14
    _LOOKBACK  = 50     # percentile window for squeeze intensity
    _RISK_PCT  = 0.02
    _ATR_MULT  = 1.5

    def initialize(self) -> None:
        self.set_start_date(2018, 1, 1)
        self.set_end_date(2024, 1, 1)
        self.set_cash(100_000)

        if not self.live_mode:
            self.set_brokerage_model(BrokerageName.PAPER_BROKERAGE)

        self._sym = self.add_equity(self._SYMBOL, Resolution.DAILY).symbol

        self._bb  = self.bb(self._sym, self._BB_PERIOD, self._BB_STD,
                            Resolution.DAILY)
        self._atr = self.atr(self._sym, self._ATR_PER, Resolution.DAILY)
        self._sma = self.sma(self._sym, self._BB_PERIOD, Resolution.DAILY)  # KC midline

        self.set_warm_up(self._LOOKBACK + self._BB_PERIOD)

        # Rolling BB-width history for percentile
        self._bb_widths: deque = deque(maxlen=self._LOOKBACK)

        self._in_squeeze:  bool  = False
        self._stop_price:  float = 0.0
        self._position:    int   = 0

        self._bridge = None
        if _NIBLIT_AVAILABLE and _NiblitBridge is not None:
            try:
                self._bridge = _NiblitBridge()
                self.log("NiblitBridge connected.")
            except Exception as exc:
                self.log(f"NiblitBridge init failed: {exc}")

    def on_data(self, data: Slice) -> None:
        if self.is_warming_up:
            return
        if not (self._bb.is_ready and self._atr.is_ready and self._sma.is_ready):
            return
        if self._sym not in data.bars:
            return

        price = data.bars[self._sym].close
        bb_upper = self._bb.upper_band.current.value
        bb_lower = self._bb.lower_band.current.value
        bb_mid   = self._bb.middle_band.current.value
        atr      = self._atr.current.value
        sma      = self._sma.current.value

        # Keltner Channel bands
        kc_upper = sma + self._KC_MULT * atr
        kc_lower = sma - self._KC_MULT * atr

        bb_width = bb_upper - bb_lower
        self._bb_widths.append(bb_width)

        # Squeeze: BB completely inside KC
        squeeze_now = bb_upper < kc_upper and bb_lower > kc_lower

        # Squeeze intensity percentile (lower = more extreme)
        squeeze_pct = self._percentile_rank(bb_width)

        # Stop loss check
        if self._position != 0 and self._stop_price > 0:
            stop_hit = (self._position ==  1 and price <= self._stop_price) or \
                       (self._position == -1 and price >= self._stop_price)
            if stop_hit:
                self.liquidate(self._sym)
                self._position   = 0
                self._stop_price = 0.0
                self.log(f"Stop triggered @ {price:.2f}")

        # Exit if price reaches BB opposite band
        if self._position == 1 and price >= bb_upper:
            self.liquidate(self._sym)
            self._position   = 0
            self._stop_price = 0.0
            self.log(f"Target hit – exit long @ {price:.2f}")
        elif self._position == -1 and price <= bb_lower:
            self.liquidate(self._sym)
            self._position   = 0
            self._stop_price = 0.0
            self.log(f"Target hit – exit short @ {price:.2f}")

        # Breakout: squeeze just released
        squeeze_released = self._in_squeeze and not squeeze_now
        self._in_squeeze  = squeeze_now

        if squeeze_released and self._position == 0:
            # Breakout direction = price vs midpoint
            direction = 1 if price > bb_mid else -1
            # Niblit confirmation
            niblit_ok = True
            if self._bridge is not None:
                try:
                    act = (self._bridge.get_signal() or "HOLD").upper()
                    if direction == 1 and act == "SELL":
                        niblit_ok = False
                    if direction == -1 and act == "BUY":
                        niblit_ok = False
                    self.log(f"Niblit: {act}")
                except Exception as exc:
                    self.log(f"Niblit error: {exc}")

            if niblit_ok:
                # Scale size: tighter squeeze (lower pct) → bigger trade
                scale = 1.0 + (1.0 - squeeze_pct) * 0.5
                self._open_trade(direction, price, atr, squeeze_pct, scale)

    def _percentile_rank(self, value: float) -> float:
        """Return 0-1 rank of value within stored history."""
        if len(self._bb_widths) < 5:
            return 0.5
        below = sum(1 for w in self._bb_widths if w < value)
        return below / len(self._bb_widths)

    def _open_trade(self, direction: int, price: float, atr: float,
                    squeeze_pct: float, scale: float) -> None:
        equity    = self.portfolio.total_portfolio_value
        stop_dist = self._ATR_MULT * atr
        if stop_dist == 0:
            return
        shares = int(min((equity * self._RISK_PCT * scale) / stop_dist,
                          (equity * 0.30) / price))
        if shares == 0:
            return
        self.market_order(self._sym, shares * direction)
        self._stop_price = (price - stop_dist) if direction == 1 \
                           else (price + stop_dist)
        self._position   = direction
        label = "LONG" if direction == 1 else "SHORT"
        self.log(f"Squeeze breakout {label} {shares} @ ~{price:.2f} "
                 f"pct={squeeze_pct:.2f}  stop={self._stop_price:.2f}")

    def on_order_event(self, order_event: OrderEvent) -> None:
        self.log(str(order_event))

    def on_end_of_algorithm(self) -> None:
        self.log(f"Final value: {self.portfolio.total_portfolio_value:.2f}")
