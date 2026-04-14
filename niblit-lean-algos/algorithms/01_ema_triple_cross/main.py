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


class EmaTripleCross(QCAlgorithm):
    """
    EMA Triple Crossover Strategy.

    Entry:  Long  when EMA9 > EMA21 > EMA50 (all aligned bullish).
            Short when EMA9 < EMA21 < EMA50 (all aligned bearish).
    Filter: NiblitBridge signal used as confirmation when available.
    Risk:   Stop loss set at 1.5× ATR from entry.  Max 2% risk per trade.
    """

    # ------------------------------------------------------------------ #
    #  Constants                                                           #
    # ------------------------------------------------------------------ #
    _SYMBOL        = "SPY"
    _FAST_PERIOD   = 9
    _MED_PERIOD    = 21
    _SLOW_PERIOD   = 50
    _ATR_PERIOD    = 14
    _ATR_MULT      = 1.5        # stop-loss distance in ATR units
    _RISK_PCT      = 0.02       # 2% portfolio risk per trade
    _NIBLIT_WEIGHT = 0.3        # how much Niblit confirmation shifts sizing

    def initialize(self) -> None:
        self.set_start_date(2020, 1, 1)
        self.set_end_date(2024, 1, 1)
        self.set_cash(100_000)

        # Brokerage
        if not self.live_mode:
            self.set_brokerage_model(BrokerageName.PAPER_BROKERAGE)

        self._symbol = self.add_equity(self._SYMBOL, Resolution.DAILY).symbol

        # Indicators
        self._ema_fast = self.ema(self._symbol, self._FAST_PERIOD, Resolution.DAILY)
        self._ema_med  = self.ema(self._symbol, self._MED_PERIOD,  Resolution.DAILY)
        self._ema_slow = self.ema(self._symbol, self._SLOW_PERIOD, Resolution.DAILY)
        self._atr      = self.atr(self._symbol, self._ATR_PERIOD,  Resolution.DAILY)

        # Warm-up
        self.set_warm_up(self._SLOW_PERIOD + 10)

        # State
        self._stop_price: float = 0.0
        self._position    = 0       # +1 long, -1 short, 0 flat

        # Niblit bridge
        self._bridge = None
        if _NIBLIT_AVAILABLE and _NiblitBridge is not None:
            try:
                self._bridge = _NiblitBridge()
                self.log("NiblitBridge connected.")
            except Exception as exc:
                self.log(f"NiblitBridge init failed: {exc}")

    # ------------------------------------------------------------------ #
    #  Main trading logic                                                  #
    # ------------------------------------------------------------------ #
    def on_data(self, data: Slice) -> None:
        if self.is_warming_up:
            return
        if not (self._ema_fast.is_ready and self._ema_med.is_ready
                and self._ema_slow.is_ready and self._atr.is_ready):
            return
        if self._symbol not in data.bars:
            return

        price    = data.bars[self._symbol].close
        ema_fast = self._ema_fast.current.value
        ema_med  = self._ema_med.current.value
        ema_slow = self._ema_slow.current.value
        atr      = self._atr.current.value

        bull_aligned = ema_fast > ema_med > ema_slow
        bear_aligned = ema_fast < ema_med < ema_slow

        # ---- NiblitBridge confirmation ----
        niblit_bias = 0.0   # +1 buy, -1 sell, 0 neutral
        if self._bridge is not None:
            try:
                action = (self._bridge.get_signal() or "HOLD").upper()
                conf = self._bridge.get_confidence()
                niblit_bias = conf if action == "BUY" else (-conf if action == "SELL" else 0.0)
                self.log(f"Niblit signal: action={action} conf={conf:.3f}")
            except Exception as exc:
                self.log(f"Niblit signal error: {exc}")

        # ---- Check stop loss ----
        if self._position != 0 and self._stop_price > 0:
            stop_hit = (self._position == 1  and price <= self._stop_price) or \
                       (self._position == -1 and price >= self._stop_price)
            if stop_hit:
                self.liquidate(self._symbol)
                self._position  = 0
                self._stop_price = 0.0
                self.log(f"Stop loss triggered at {price:.2f}")
                return

        # ---- Generate signal ----
        want_long  = bull_aligned and niblit_bias >= -0.2
        want_short = bear_aligned and niblit_bias <=  0.2

        if want_long and self._position != 1:
            size = self._compute_size(price, atr)
            # Apply Niblit weight boost when bridge agrees
            size_adj = size * (1.0 + self._NIBLIT_WEIGHT * max(niblit_bias, 0.0))
            self._enter_position(1, price, atr, size_adj)

        elif want_short and self._position != -1:
            size = self._compute_size(price, atr)
            size_adj = size * (1.0 + self._NIBLIT_WEIGHT * max(-niblit_bias, 0.0))
            self._enter_position(-1, price, atr, size_adj)

        elif not want_long and not want_short and self._position != 0:
            self.liquidate(self._symbol)
            self._position   = 0
            self._stop_price = 0.0
            self.log("Signal neutral – flattened position.")

    def _compute_size(self, price: float, atr: float) -> float:
        """Risk-based position size: risk_pct of equity / (ATR_mult * ATR)."""
        equity = self.portfolio.total_portfolio_value
        dollar_risk = equity * self._RISK_PCT
        stop_dist   = self._ATR_MULT * atr
        if stop_dist == 0:
            return 0.0
        shares = dollar_risk / stop_dist
        # Clamp to max 30% of portfolio in this single name
        max_shares = (equity * 0.30) / price
        return min(shares, max_shares)

    def _enter_position(self, direction: int, price: float, atr: float,
                        shares: float) -> None:
        qty = int(shares) * direction
        if qty == 0:
            return
        self.market_order(self._symbol, qty)
        self._position   = direction
        self._stop_price = (price - self._ATR_MULT * atr) if direction == 1 \
                           else (price + self._ATR_MULT * atr)
        self.log(f"Entered {'LONG' if direction==1 else 'SHORT'} {abs(qty)} shares "
                 f"@ ~{price:.2f}  stop={self._stop_price:.2f}")

    # ------------------------------------------------------------------ #
    #  Event hooks                                                         #
    # ------------------------------------------------------------------ #
    def on_order_event(self, order_event: OrderEvent) -> None:
        self.log(str(order_event))

    def on_end_of_algorithm(self) -> None:
        self.log(f"Final value: {self.portfolio.total_portfolio_value:.2f}")
