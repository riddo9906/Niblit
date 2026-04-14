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


class RsiMeanReversion(QCAlgorithm):
    """
    RSI Mean-Reversion Strategy.

    Entry:  Buy  when RSI < 30 AND price > EMA50 (uptrend context).
            Sell when RSI > 70 AND price < EMA50 (downtrend context).
    Sizing: Position size scales with RSI distance from 50.
            Further from 50 → larger bet (more extreme = more likely to revert).
    Exit:   RSI returns to 50 OR stop loss (1.5× ATR).
    """

    _SYMBOL     = "SPY"
    _RSI_PERIOD = 14
    _EMA_SLOW   = 50
    _EMA_TREND  = 200
    _ATR_PERIOD = 14
    _ATR_MULT   = 1.5
    _BASE_RISK  = 0.02      # base 2% risk – scaled by RSI extreme
    _RSI_ENTRY_LO  = 30
    _RSI_ENTRY_HI  = 70
    _RSI_EXIT      = 50     # mean-reversion target

    def initialize(self) -> None:
        self.set_start_date(2018, 1, 1)
        self.set_end_date(2024, 1, 1)
        self.set_cash(100_000)

        if not self.live_mode:
            self.set_brokerage_model(BrokerageName.PAPER_BROKERAGE)

        self._sym = self.add_equity(self._SYMBOL, Resolution.DAILY).symbol

        self._rsi     = self.rsi(self._sym, self._RSI_PERIOD, Resolution.DAILY)
        self._ema50   = self.ema(self._sym, self._EMA_SLOW,  Resolution.DAILY)
        self._ema200  = self.ema(self._sym, self._EMA_TREND, Resolution.DAILY)
        self._atr     = self.atr(self._sym, self._ATR_PERIOD, Resolution.DAILY)

        self.set_warm_up(self._EMA_TREND + 10)

        self._stop_price: float = 0.0
        self._position:   int   = 0   # +1 long, -1 short

        # Niblit bridge (used for optional logging/override)
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
        if not (self._rsi.is_ready and self._ema50.is_ready
                and self._ema200.is_ready and self._atr.is_ready):
            return
        if self._sym not in data.bars:
            return

        price   = data.bars[self._sym].close
        rsi     = self._rsi.current.value
        ema50   = self._ema50.current.value
        ema200  = self._ema200.current.value
        atr     = self._atr.current.value

        uptrend   = ema50 > ema200
        downtrend = ema50 < ema200

        # Stop loss check
        if self._position != 0 and self._stop_price > 0:
            stop_hit = (self._position ==  1 and price <= self._stop_price) or \
                       (self._position == -1 and price >= self._stop_price)
            if stop_hit:
                self.liquidate(self._sym)
                self._position   = 0
                self._stop_price = 0.0
                self.log(f"Stop triggered at {price:.2f}  RSI={rsi:.1f}")
                return

        # Mean-reversion exit: RSI crosses 50
        if self._position == 1 and rsi >= self._RSI_EXIT:
            self.liquidate(self._sym)
            self._position   = 0
            self._stop_price = 0.0
            self.log(f"Exit long – RSI crossed 50 ({rsi:.1f})")
            return
        if self._position == -1 and rsi <= self._RSI_EXIT:
            self.liquidate(self._sym)
            self._position   = 0
            self._stop_price = 0.0
            self.log(f"Exit short – RSI crossed 50 ({rsi:.1f})")
            return

        # Niblit optional veto
        niblit_allow = True
        if self._bridge is not None:
            try:
                action = (self._bridge.get_signal() or "HOLD").upper()
                self.log(f"Niblit: {action}")
                # Hard veto only when bridge says strongly opposite
                if rsi < self._RSI_ENTRY_LO and action == "SELL":
                    niblit_allow = False
                if rsi > self._RSI_ENTRY_HI and action == "BUY":
                    niblit_allow = False
            except Exception as exc:
                self.log(f"Niblit error: {exc}")

        # Entry signals
        oversold   = rsi < self._RSI_ENTRY_LO and uptrend   and self._position == 0
        overbought = rsi > self._RSI_ENTRY_HI and downtrend and self._position == 0

        if oversold and niblit_allow:
            self._open_trade(1, price, atr, rsi)
        elif overbought and niblit_allow:
            self._open_trade(-1, price, atr, rsi)

    def _rsi_size_scale(self, rsi: float) -> float:
        """Scale factor from RSI distance from 50: further → larger (capped at 2×)."""
        dist = abs(rsi - 50.0)   # 0–50 range
        return min(1.0 + dist / 50.0, 2.0)

    def _open_trade(self, direction: int, price: float, atr: float,
                    rsi: float) -> None:
        equity    = self.portfolio.total_portfolio_value
        stop_dist = self._ATR_MULT * atr
        if stop_dist == 0:
            return
        scale        = self._rsi_size_scale(rsi)
        dollar_risk  = equity * self._BASE_RISK * scale
        shares       = int(min(dollar_risk / stop_dist,
                               (equity * 0.35) / price))
        if shares == 0:
            return
        self.market_order(self._sym, shares * direction)
        self._stop_price = (price - stop_dist) if direction == 1 \
                           else (price + stop_dist)
        self._position   = direction
        label = "LONG" if direction == 1 else "SHORT"
        self.log(f"Open {label} {shares} shares @ ~{price:.2f} "
                 f"RSI={rsi:.1f}  stop={self._stop_price:.2f}  scale={scale:.2f}")

    def on_order_event(self, order_event: OrderEvent) -> None:
        self.log(str(order_event))

    def on_end_of_algorithm(self) -> None:
        self.log(f"Final value: {self.portfolio.total_portfolio_value:.2f}")
