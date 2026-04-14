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
from typing import List, Tuple


# ──────────────────────────────────────────────────────────────────────────────
#  Pure-Python single LSTM cell
# ──────────────────────────────────────────────────────────────────────────────
class _LSTMCell:
    """
    Minimal 1-layer LSTM cell, input_size=1, hidden_size=H.

    All weights are plain Python lists.  Forward pass + TBPTT gradient
    descent update (single step, no second-order).
    """

    def __init__(self, input_size: int = 1, hidden_size: int = 8,
                 lr: float = 0.001) -> None:
        self._H  = hidden_size
        self._I  = input_size
        self._lr = lr

        def _rand(rows: int, cols: int) -> List[List[float]]:
            import random
            return [[random.gauss(0, 0.1) for _ in range(cols)]
                    for _ in range(rows)]

        # Weights: [input gate, forget gate, output gate, cell gate]
        # Each gate: W_ih (H × I), W_hh (H × H), b (H,)
        self._Wi = _rand(hidden_size, input_size)
        self._Ui = _rand(hidden_size, hidden_size)
        self._bi = [0.0] * hidden_size

        self._Wf = _rand(hidden_size, input_size)
        self._Uf = _rand(hidden_size, hidden_size)
        self._bf = [1.0] * hidden_size  # bias=1 for forget gate

        self._Wo = _rand(hidden_size, input_size)
        self._Uo = _rand(hidden_size, hidden_size)
        self._bo = [0.0] * hidden_size

        self._Wg = _rand(hidden_size, input_size)
        self._Ug = _rand(hidden_size, hidden_size)
        self._bg = [0.0] * hidden_size

        # Output layer: H → 1
        self._V  = [0.1] * hidden_size
        self._bv = 0.0

        # State
        self._h = [0.0] * hidden_size
        self._c = [0.0] * hidden_size

    # ---- Activation helpers ----
    @staticmethod
    def _sigmoid(x: float) -> float:
        if x >  20: return 1.0
        if x < -20: return 0.0
        return 1.0 / (1.0 + math.exp(-x))

    @staticmethod
    def _tanh(x: float) -> float:
        return math.tanh(max(-20.0, min(20.0, x)))

    def _matvec(self, W: List[List[float]], v: List[float]) -> List[float]:
        return [sum(W[i][j] * v[j] for j in range(len(v))) for i in range(len(W))]

    def _addvec(self, a: List[float], b: List[float]) -> List[float]:
        return [a[i] + b[i] for i in range(len(a))]

    # ---- Forward pass ----
    def forward(self, x: float) -> float:
        xv  = [x]
        Wix = self._matvec(self._Wi, xv)
        Uih = self._matvec(self._Ui, self._h)
        i_g = [self._sigmoid(Wix[j] + Uih[j] + self._bi[j])
               for j in range(self._H)]

        Wfx = self._matvec(self._Wf, xv)
        Ufh = self._matvec(self._Uf, self._h)
        f_g = [self._sigmoid(Wfx[j] + Ufh[j] + self._bf[j])
               for j in range(self._H)]

        Wox = self._matvec(self._Wo, xv)
        Uoh = self._matvec(self._Uo, self._h)
        o_g = [self._sigmoid(Wox[j] + Uoh[j] + self._bo[j])
               for j in range(self._H)]

        Wgx = self._matvec(self._Wg, xv)
        Ugh = self._matvec(self._Ug, self._h)
        g_g = [self._tanh(Wgx[j] + Ugh[j] + self._bg[j])
               for j in range(self._H)]

        new_c = [f_g[j] * self._c[j] + i_g[j] * g_g[j] for j in range(self._H)]
        new_h = [o_g[j] * self._tanh(new_c[j])          for j in range(self._H)]

        self._c = new_c
        self._h = new_h

        # Linear output
        y_hat = sum(self._V[j] * new_h[j] for j in range(self._H)) + self._bv
        return self._sigmoid(y_hat)   # probability in (0,1)

    def update_output_layer(self, y_hat: float, target: float) -> None:
        """
        Single-step gradient descent on output layer only.
        Loss: binary cross-entropy.   dL/dy = y_hat - target.
        """
        grad = y_hat - target
        for j in range(self._H):
            self._V[j]  -= self._lr * grad * self._h[j]
        self._bv -= self._lr * grad

    def reset_state(self) -> None:
        self._h = [0.0] * self._H
        self._c = [0.0] * self._H


# ──────────────────────────────────────────────────────────────────────────────
#  Algorithm
# ──────────────────────────────────────────────────────────────────────────────
class LstmPredictor(QCAlgorithm):
    """
    Pure-Python LSTM direction predictor.

    Input:    Normalised close-price changes over 20-bar rolling window.
    Output:   P(next bar up) ∈ (0, 1).
    Update:   Output layer gradient descent every bar (learning_rate=0.001).
    Trade:    Long when P > 0.6.  ATR stop + 2% risk.
    """

    _SYMBOL      = "SPY"
    _SEQ_LEN     = 20
    _HIDDEN      = 8
    _LR          = 0.001
    _PROB_THRESH = 0.60
    _RISK_PCT    = 0.02
    _ATR_MULT    = 1.5

    def initialize(self) -> None:
        self.set_start_date(2019, 1, 1)
        self.set_end_date(2024, 1, 1)
        self.set_cash(100_000)

        if not self.live_mode:
            self.set_brokerage_model(BrokerageName.PAPER_BROKERAGE)

        self._sym  = self.add_equity(self._SYMBOL, Resolution.DAILY).symbol
        self._atr  = self.atr(self._sym, 14, Resolution.DAILY)

        self.set_warm_up(30)

        self._price_buf: deque = deque(maxlen=self._SEQ_LEN + 2)
        self._lstm = _LSTMCell(input_size=1, hidden_size=self._HIDDEN, lr=self._LR)

        self._stop_price: float = 0.0
        self._position:   int   = 0

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
        if self._sym not in data.bars or not self._atr.is_ready:
            return

        price = data.bars[self._sym].close
        self._price_buf.append(price)

        if len(self._price_buf) < self._SEQ_LEN + 2:
            return

        # Build normalised return sequence
        prices   = list(self._price_buf)
        mu       = sum(prices) / len(prices)
        sigma    = math.sqrt(sum((p - mu) ** 2 for p in prices) / len(prices)) or 1e-8
        norm_seq = [(p - mu) / sigma for p in prices]

        # Run LSTM forward through the window
        y_hat = 0.5  # default neutral probability if sequence is empty
        self._lstm.reset_state()
        for val in norm_seq[:-1]:
            y_hat = self._lstm.forward(val)

        # Prediction = last output
        prob_up = y_hat

        # Online label: was the previous bar positive?
        actual_up = 1.0 if prices[-1] > prices[-2] else 0.0
        self._lstm.update_output_layer(prob_up, actual_up)

        atr = self._atr.current.value

        # Stop loss
        if self._position != 0 and self._stop_price > 0:
            if self._position == 1 and price <= self._stop_price:
                self.liquidate(self._sym)
                self._position   = 0
                self._stop_price = 0.0
                self.log(f"Stop triggered @ {price:.2f}")
                return

        # Niblit overlay
        niblit_adj = 0.0
        if self._bridge is not None:
            try:
                act = (self._bridge.get_signal() or "HOLD").upper()
                conf = self._bridge.get_confidence()
                niblit_adj = 0.05 * conf if act == "BUY" else \
                            -0.05 * conf if act == "SELL" else 0.0
                self.log(f"Niblit: {act} conf={conf:.3f}")
            except Exception as exc:
                self.log(f"Niblit error: {exc}")

        eff_prob = min(1.0, max(0.0, prob_up + niblit_adj))
        self.log(f"LSTM P(up)={prob_up:.3f} eff={eff_prob:.3f}")

        if eff_prob >= self._PROB_THRESH and self._position == 0:
            equity    = self.portfolio.total_portfolio_value
            stop_dist = self._ATR_MULT * atr
            if stop_dist > 0:
                shares = int(min((equity * self._RISK_PCT) / stop_dist,
                                  (equity * 0.30) / price))
                if shares > 0:
                    self.market_order(self._sym, shares)
                    self._stop_price = price - stop_dist
                    self._position   = 1
                    self.log(f"Buy {shares} @ {price:.2f}  P={eff_prob:.3f}")

        elif eff_prob < 0.45 and self._position == 1:
            self.liquidate(self._sym)
            self._position   = 0
            self._stop_price = 0.0
            self.log(f"Exit long  P={eff_prob:.3f}")

    def on_order_event(self, order_event: OrderEvent) -> None:
        self.log(str(order_event))

    def on_end_of_algorithm(self) -> None:
        self.log(f"Final value: {self.portfolio.total_portfolio_value:.2f}")
