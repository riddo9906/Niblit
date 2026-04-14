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


class MacdMomentum(QCAlgorithm):
    """
    MACD Momentum Strategy.

    Entry:  Long  when MACD line crosses above signal AND histogram is expanding
            AND price > SMA200 (regime filter).
            Short when MACD line crosses below signal AND histogram contracting
            AND price < SMA200.
    Niblit: Signal weight adjusts position size.
    Risk:   ATR-based stop loss; 2% max portfolio risk per trade.
    """

    _SYMBOL     = "SPY"
    _FAST       = 12
    _SLOW       = 26
    _SIGNAL     = 9
    _ATR_PERIOD = 14
    _ATR_MULT   = 1.8
    _RISK_PCT   = 0.02
    _SMA_PERIOD = 200

    def initialize(self) -> None:
        self.set_start_date(2020, 1, 1)
        self.set_end_date(2024, 1, 1)
        self.set_cash(100_000)

        if not self.live_mode:
            self.set_brokerage_model(BrokerageName.PAPER_BROKERAGE)

        self._sym = self.add_equity(self._SYMBOL, Resolution.DAILY).symbol

        self._macd = self.macd(self._sym, self._FAST, self._SLOW, self._SIGNAL,
                               MovingAverageType.EXPONENTIAL, Resolution.DAILY)
        self._sma  = self.sma(self._sym, self._SMA_PERIOD, Resolution.DAILY)
        self._atr  = self.atr(self._sym, self._ATR_PERIOD, Resolution.DAILY)

        self.set_warm_up(self._SMA_PERIOD + 10)

        # State
        self._prev_hist:  float = 0.0
        self._stop_price: float = 0.0
        self._position:   int   = 0

        # Niblit
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
        if not (self._macd.is_ready and self._sma.is_ready and self._atr.is_ready):
            return
        if self._sym not in data.bars:
            return

        price     = data.bars[self._sym].close
        macd_val  = self._macd.current.value          # MACD line
        signal_val= self._macd.signal.current.value   # Signal line
        histogram = self._macd.histogram.current.value
        sma200    = self._sma.current.value
        atr       = self._atr.current.value

        # Regime: only long above SMA200, only short below
        bull_regime = price > sma200
        bear_regime = price < sma200

        # MACD cross + histogram expansion
        macd_bull_cross  = macd_val > signal_val and self._prev_hist < 0 and histogram > 0
        macd_bear_cross  = macd_val < signal_val and self._prev_hist > 0 and histogram < 0
        hist_expanding   = abs(histogram) > abs(self._prev_hist)

        # Niblit weight
        niblit_mult = 1.0
        if self._bridge is not None:
            try:
                action = (self._bridge.get_signal() or "HOLD").upper()
                conf = self._bridge.get_confidence()
                self.log(f"Niblit: {action} conf={conf:.3f}")
                if action == "BUY":
                    niblit_mult = 1.0 + 0.25 * conf
                elif action == "SELL":
                    niblit_mult = max(0.5, 1.0 - 0.25 * conf)
            except Exception as exc:
                self.log(f"Niblit error: {exc}")

        # Stop loss check
        if self._position != 0 and self._stop_price > 0:
            stop_hit = (self._position ==  1 and price <= self._stop_price) or \
                       (self._position == -1 and price >= self._stop_price)
            if stop_hit:
                self.liquidate(self._sym)
                self._position   = 0
                self._stop_price = 0.0
                self.log(f"Stop triggered at {price:.2f}")
                self._prev_hist  = histogram
                return

        # Entry logic
        enter_long  = macd_bull_cross and hist_expanding and bull_regime and self._position != 1
        enter_short = macd_bear_cross and hist_expanding and bear_regime and self._position != -1

        # Exit stale positions on opposing signal
        if self._position == 1 and (macd_bear_cross or not bull_regime):
            self.liquidate(self._sym)
            self._position   = 0
            self._stop_price = 0.0
            self.log("Exit long: regime or MACD flip")

        if self._position == -1 and (macd_bull_cross or not bear_regime):
            self.liquidate(self._sym)
            self._position   = 0
            self._stop_price = 0.0
            self.log("Exit short: regime or MACD flip")

        if enter_long:
            self._open_trade(1, price, atr, niblit_mult)
        elif enter_short:
            self._open_trade(-1, price, atr, niblit_mult)

        self._prev_hist = histogram

    def _open_trade(self, direction: int, price: float, atr: float,
                    niblit_mult: float) -> None:
        equity     = self.portfolio.total_portfolio_value
        stop_dist  = self._ATR_MULT * atr
        if stop_dist == 0:
            return
        dollar_risk = equity * self._RISK_PCT * niblit_mult
        shares      = int(min(dollar_risk / stop_dist,
                              (equity * 0.30) / price))
        if shares == 0:
            return
        self.market_order(self._sym, shares * direction)
        self._stop_price = (price - stop_dist) if direction == 1 \
                           else (price + stop_dist)
        self._position   = direction
        label = "LONG" if direction == 1 else "SHORT"
        self.log(f"Open {label} {shares} @ ~{price:.2f}  stop={self._stop_price:.2f}")

    def on_order_event(self, order_event: OrderEvent) -> None:
        self.log(str(order_event))

    def on_end_of_algorithm(self) -> None:
        self.log(f"Final value: {self.portfolio.total_portfolio_value:.2f}")
