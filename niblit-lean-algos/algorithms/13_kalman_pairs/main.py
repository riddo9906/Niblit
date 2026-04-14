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
from typing import List


# ──────────────────────────────────────────────────────────────────────────────
#  1-D Kalman Filter (pure Python) for dynamic hedge-ratio estimation
# ──────────────────────────────────────────────────────────────────────────────

class _KalmanFilter1D:
    """
    Tracks a single time-varying scalar via 1-D Kalman filter.

    State x_t = hedge ratio (beta).
    Observation y_t = price_A - x_t * price_B.
    Transition: x_t = x_{t-1} + w_t,  w_t ~ N(0, delta)
    Observation: y_t = x_t * price_B + v_t,  v_t ~ N(0, R)
    """

    def __init__(self, delta: float = 1e-4, R: float = 1e-2) -> None:
        self._delta = delta   # process noise variance
        self._R     = R       # observation noise variance
        self._x     = 1.0    # initial hedge ratio estimate
        self._P     = 1.0    # initial error covariance
        self._e     = 0.0    # last observation error (for z-score)
        self._Q     = 0.01   # observation variance estimate (running)

    def update(self, price_a: float, price_b: float) -> float:
        """Update Kalman filter with new prices. Returns updated hedge ratio."""
        # Predict
        P_pred = self._P + self._delta

        # Innovation
        y_hat = self._x * price_b
        e_t   = price_a - y_hat      # innovation / spread

        # Innovation variance
        S = P_pred * price_b ** 2 + self._R

        # Kalman gain
        K = P_pred * price_b / S

        # Update
        self._x += K * e_t
        self._P  = (1 - K * price_b) * P_pred

        # Update running Q (observation variance)
        self._Q = 0.99 * self._Q + 0.01 * e_t ** 2
        self._e = e_t
        return self._x

    @property
    def hedge_ratio(self) -> float:
        return self._x

    @property
    def spread_error(self) -> float:
        return self._e

    @property
    def spread_variance(self) -> float:
        return max(self._Q, 1e-8)


# ──────────────────────────────────────────────────────────────────────────────
#  Algorithm
# ──────────────────────────────────────────────────────────────────────────────
class KalmanPairs(QCAlgorithm):
    """
    Kalman Filter Pairs Trading: GLD / GDX.

    Kalman filter dynamically estimates the hedge ratio β.
    Spread = GLD - β * GDX.
    Z-score computed over rolling error history.
    Entry:   |z| > 2.0    Exit:   |z| < 0.5    Stop: |z| > 3.5
    """

    _SYM_A      = "GLD"
    _SYM_B      = "GDX"
    _ENTRY_Z    = 2.0
    _EXIT_Z     = 0.5
    _STOP_Z     = 3.5
    _Z_WINDOW   = 60
    _NOTIONAL   = 0.45      # fraction of portfolio per leg

    def initialize(self) -> None:
        self.set_start_date(2018, 1, 1)
        self.set_end_date(2024, 1, 1)
        self.set_cash(100_000)

        if not self.live_mode:
            self.set_brokerage_model(BrokerageName.PAPER_BROKERAGE)

        self._sym_a = self.add_equity(self._SYM_A, Resolution.DAILY).symbol
        self._sym_b = self.add_equity(self._SYM_B, Resolution.DAILY).symbol

        self.set_warm_up(self._Z_WINDOW + 5)

        self._kf         = _KalmanFilter1D(delta=1e-4, R=0.01)
        self._error_buf: deque = deque(maxlen=self._Z_WINDOW)
        self._position   = 0   # +1 = long A, short B;  -1 = short A, long B

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

        # Update Kalman filter
        beta = self._kf.update(price_a, price_b)
        e_t  = self._kf.spread_error
        self._error_buf.append(e_t)

        if len(self._error_buf) < 20:
            return

        # Compute z-score from rolling error buffer
        errors = list(self._error_buf)
        mu     = sum(errors) / len(errors)
        std    = math.sqrt(sum((v - mu) ** 2 for v in errors) / len(errors))
        z      = (e_t - mu) / std if std > 1e-8 else 0.0

        self.log(f"GLD/GDX  β={beta:.3f}  spread={e_t:.3f}  z={z:.2f}")

        # Stop loss
        if self._position != 0 and abs(z) >= self._STOP_Z:
            self._flatten(f"Stop: |z|={abs(z):.2f}")
            return

        # Mean reversion exit
        if self._position != 0 and abs(z) <= self._EXIT_Z:
            self._flatten(f"Exit: |z|={abs(z):.2f}")
            return

        # Entry
        if self._position == 0:
            niblit_allow = True
            if self._bridge is not None:
                try:
                    act = (self._bridge.get_signal() or "HOLD").upper()
                    self.log(f"Niblit GLD: {act}")
                except Exception as exc:
                    self.log(f"Niblit error: {exc}")

            if not niblit_allow:
                return

            if z > self._ENTRY_Z:
                # Spread too high: GLD expensive relative to GDX → short A, long B
                self._open_pair(-1, price_a, price_b, beta)
            elif z < -self._ENTRY_Z:
                # Spread too low: GLD cheap → long A, short B
                self._open_pair(1, price_a, price_b, beta)

    def _open_pair(self, direction: int, price_a: float, price_b: float,
                   beta: float) -> None:
        equity    = self.portfolio.total_portfolio_value
        notional  = equity * self._NOTIONAL
        shares_a  = int(notional / price_a)
        # Scale B shares by hedge ratio to equalise notional
        shares_b  = int((notional * beta) / price_b) if price_b != 0 else 0
        if shares_a == 0 or shares_b == 0:
            return
        self.market_order(self._sym_a,  shares_a * direction)
        self.market_order(self._sym_b, -shares_b * direction)
        self._position = direction
        label = "LONG GLD / SHORT GDX" if direction == 1 else "SHORT GLD / LONG GDX"
        self.log(f"Kalman pair entry: {label}  "
                 f"A={shares_a}  B={shares_b}  β={beta:.3f}")

    def _flatten(self, reason: str) -> None:
        self.liquidate(self._sym_a)
        self.liquidate(self._sym_b)
        self._position = 0
        self.log(f"Flatten Kalman pair: {reason}")

    def on_order_event(self, order_event: OrderEvent) -> None:
        self.log(str(order_event))

    def on_end_of_algorithm(self) -> None:
        self.log(f"Final value: {self.portfolio.total_portfolio_value:.2f}")
