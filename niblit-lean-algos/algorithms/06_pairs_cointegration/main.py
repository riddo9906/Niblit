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


class PairsCointegration(QCAlgorithm):
    """
    Statistical Pairs Trading: SPY / QQQ.

    Spread:   log(SPY) - 1.0 * log(QQQ)   (fixed hedge ratio = 1.0)
    Z-score:  rolling mean/std over 60 bars.
    Entry:    |z| > 2.0  → trade spread back to mean.
    Exit:     |z| < 0.5  OR stop loss (z exceeds 3.5).
    Sizing:   50 / 50 equal notional split between legs.
    """

    _SYM_A       = "SPY"
    _SYM_B       = "QQQ"
    _HEDGE       = 1.0      # log-price ratio multiplier for leg B
    _WINDOW      = 60       # rolling z-score window
    _ENTRY_Z     = 2.0
    _EXIT_Z      = 0.5
    _STOP_Z      = 3.5      # z-score stop loss
    _NOTIONAL    = 0.45     # fraction of portfolio per leg

    def initialize(self) -> None:
        self.set_start_date(2018, 1, 1)
        self.set_end_date(2024, 1, 1)
        self.set_cash(100_000)

        if not self.live_mode:
            self.set_brokerage_model(BrokerageName.PAPER_BROKERAGE)

        self._sym_a = self.add_equity(self._SYM_A, Resolution.DAILY).symbol
        self._sym_b = self.add_equity(self._SYM_B, Resolution.DAILY).symbol

        self.set_warm_up(self._WINDOW + 5)

        self._spreads: deque = deque(maxlen=self._WINDOW)
        self._position: int  = 0    # +1 = long A / short B, -1 = short A / long B

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
        if self._sym_a not in data.bars or self._sym_b not in data.bars:
            return

        price_a = data.bars[self._sym_a].close
        price_b = data.bars[self._sym_b].close

        spread = math.log(price_a) - self._HEDGE * math.log(price_b)
        self._spreads.append(spread)

        if len(self._spreads) < self._WINDOW:
            return

        mean, std = self._rolling_stats()
        if std == 0:
            return
        z_score = (spread - mean) / std

        self.log(f"Spread={spread:.4f}  mean={mean:.4f}  std={std:.4f}  z={z_score:.2f}")

        # --- Stop loss: z-score diverging past threshold ---
        if self._position != 0 and abs(z_score) >= self._STOP_Z:
            self._flatten("Z-score stop loss")
            return

        # --- Exit: spread reverted ---
        if self._position != 0 and abs(z_score) <= self._EXIT_Z:
            self._flatten(f"Mean reversion exit  z={z_score:.2f}")
            return

        # --- Entry ---
        if self._position == 0:
            # Niblit veto
            niblit_allow = True
            if self._bridge is not None:
                try:
                    _sig_str = (self._bridge.get_signal() or "HOLD").upper()
                    self.log(f"Niblit SPY: {_sig_str}")
                except Exception as exc:
                    self.log(f"Niblit error: {exc}")

            if not niblit_allow:
                return

            if z_score > self._ENTRY_Z:
                # Spread too high: short A, long B
                self._open_pair(-1, price_a, price_b)
            elif z_score < -self._ENTRY_Z:
                # Spread too low: long A, short B
                self._open_pair(1, price_a, price_b)

    def _rolling_stats(self):
        vals = list(self._spreads)
        n    = len(vals)
        mean = sum(vals) / n
        variance = sum((v - mean) ** 2 for v in vals) / n
        return mean, math.sqrt(variance)

    def _open_pair(self, direction: int, price_a: float, price_b: float) -> None:
        """
        direction +1: long A, short B.
        direction -1: short A, long B.
        """
        equity    = self.portfolio.total_portfolio_value
        notional  = equity * self._NOTIONAL
        shares_a  = int(notional / price_a)
        shares_b  = int(notional / price_b)
        if shares_a == 0 or shares_b == 0:
            return

        self.market_order(self._sym_a,  shares_a * direction)
        self.market_order(self._sym_b, -shares_b * direction)
        self._position = direction
        label = "LONG A/SHORT B" if direction == 1 else "SHORT A/LONG B"
        self.log(f"Pair entry: {label}  A={shares_a}  B={shares_b}")

    def _flatten(self, reason: str) -> None:
        self.liquidate(self._sym_a)
        self.liquidate(self._sym_b)
        self._position = 0
        self.log(f"Flatten pairs: {reason}")

    def on_order_event(self, order_event: OrderEvent) -> None:
        self.log(str(order_event))

    def on_end_of_algorithm(self) -> None:
        self.log(f"Final value: {self.portfolio.total_portfolio_value:.2f}")
