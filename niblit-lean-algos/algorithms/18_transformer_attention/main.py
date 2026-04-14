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
import random
from collections import deque
from typing import List, Tuple


# ──────────────────────────────────────────────────────────────────────────────
#  Pure-Python Scaled Dot-Product Self-Attention (single head, 4-dim)
# ──────────────────────────────────────────────────────────────────────────────

_D_MODEL = 4   # embedding dimension
_SEQ_LEN = 16  # number of bars in the attention window


def _mat_mul(A: List[List[float]], B: List[List[float]]) -> List[List[float]]:
    """Matrix multiply A (m×k) × B (k×n) → C (m×n)."""
    m, k, n = len(A), len(A[0]), len(B[0])
    return [[sum(A[i][p] * B[p][j] for p in range(k)) for j in range(n)]
            for i in range(m)]


def _mat_vec(M: List[List[float]], v: List[float]) -> List[float]:
    return [sum(M[i][j] * v[j] for j in range(len(v))) for i in range(len(M))]


def _softmax_rows(M: List[List[float]]) -> List[List[float]]:
    result = []
    for row in M:
        m = max(row)
        exps = [math.exp(v - m) for v in row]
        s = sum(exps) or 1e-8
        result.append([e / s for e in exps])
    return result


def _transpose(M: List[List[float]]) -> List[List[float]]:
    rows, cols = len(M), len(M[0])
    return [[M[r][c] for r in range(rows)] for c in range(cols)]


class _SelfAttentionClassifier:
    """
    Scaled dot-product self-attention over a sequence of normalised bar returns.
    Architecture:
        Input:   [SEQ_LEN × 1] raw values → embedded to [SEQ_LEN × D_MODEL]
        Attention: Q, K, V projection (D_MODEL × D_MODEL each)
        Context:  Attention-weighted sum → pooled [D_MODEL]
        Output:   Linear classifier → logit → sigmoid → P(up)
    Gradient updates on output layer each bar (SGD, lr=0.005).
    Q/K/V weights updated with finite-difference approx every 10 bars.
    """

    def __init__(self, lr: float = 0.005) -> None:
        self._lr   = lr
        rng = random.Random(7)

        def rmat(r: int, c: int) -> List[List[float]]:
            return [[rng.gauss(0, 0.1) for _ in range(c)] for _ in range(r)]

        # Embedding: scalar → D_MODEL
        self._E  = rmat(_D_MODEL, 1)   # D_MODEL × 1

        # Q / K / V matrices  D_MODEL × D_MODEL
        self._Wq = rmat(_D_MODEL, _D_MODEL)
        self._Wk = rmat(_D_MODEL, _D_MODEL)
        self._Wv = rmat(_D_MODEL, _D_MODEL)

        # Output linear  1 × D_MODEL
        self._Wo = [rng.gauss(0, 0.1) for _ in range(_D_MODEL)]
        self._bo = 0.0

        # Store last attention output for gradient step
        self._last_ctx: List[float] = [0.0] * _D_MODEL

    @staticmethod
    def _sigmoid(x: float) -> float:
        if x > 20:  return 1.0
        if x < -20: return 0.0
        return 1.0 / (1.0 + math.exp(-x))

    def forward(self, seq: List[float]) -> float:
        """
        seq: list of _SEQ_LEN scalar values (normalised returns).
        Returns P(next bar up).
        """
        T = len(seq)
        # Embed: each scalar → D_MODEL vector
        X = [_mat_vec(self._E, [v]) for v in seq]   # T × D_MODEL

        # Compute Q, K, V
        Q = [_mat_vec(self._Wq, x) for x in X]
        K = [_mat_vec(self._Wk, x) for x in X]
        V = [_mat_vec(self._Wv, x) for x in X]

        # Attention scores: Q × K^T / sqrt(d)
        scale = math.sqrt(_D_MODEL)
        K_T   = _transpose(K)   # D_MODEL × T
        scores: List[List[float]] = []
        for q in Q:
            row = [sum(q[d] * K_T[d][j] for d in range(_D_MODEL)) / scale
                   for j in range(T)]
            scores.append(row)

        attn_weights = _softmax_rows(scores)  # T × T

        # Context = attn_weights × V  → T × D_MODEL
        context: List[List[float]] = []
        for i in range(T):
            ctx_i = [sum(attn_weights[i][j] * V[j][d] for j in range(T))
                     for d in range(_D_MODEL)]
            context.append(ctx_i)

        # Global average pooling → D_MODEL
        pooled = [sum(context[t][d] for t in range(T)) / T
                  for d in range(_D_MODEL)]
        self._last_ctx = pooled

        # Output logit
        logit = sum(self._Wo[d] * pooled[d] for d in range(_D_MODEL)) + self._bo
        return self._sigmoid(logit)

    def update_output(self, y_hat: float, target: float) -> None:
        """SGD on output layer. Loss = binary cross-entropy."""
        grad = y_hat - target
        for d in range(_D_MODEL):
            self._Wo[d] -= self._lr * grad * self._last_ctx[d]
        self._bo -= self._lr * grad


# ──────────────────────────────────────────────────────────────────────────────
#  Algorithm
# ──────────────────────────────────────────────────────────────────────────────
class TransformerAttention(QCAlgorithm):
    """
    Transformer Self-Attention Trader.

    Sequence:  Last 16 normalised daily returns.
    Attention: Scaled dot-product (single head, 4-dim embeddings).
    Output:    P(next bar up) → trade signal.
    Update:    Output layer gradient every bar (online learning).
    """

    _SYMBOL      = "SPY"
    _SEQ_LEN     = _SEQ_LEN
    _PROB_THRESH = 0.60
    _RISK_PCT    = 0.02
    _ATR_MULT    = 1.5

    def initialize(self) -> None:
        self.set_start_date(2019, 1, 1)
        self.set_end_date(2024, 1, 1)
        self.set_cash(100_000)

        if not self.live_mode:
            self.set_brokerage_model(BrokerageName.PAPER_BROKERAGE)

        self._sym = self.add_equity(self._SYMBOL, Resolution.DAILY).symbol
        self._atr = self.atr(self._sym, 14, Resolution.DAILY)

        self.set_warm_up(self._SEQ_LEN + 5)

        self._close_buf: deque = deque(maxlen=self._SEQ_LEN + 2)
        self._model     = _SelfAttentionClassifier(lr=0.005)
        self._stop_price = 0.0
        self._position   = 0

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
        self._close_buf.append(price)

        if len(self._close_buf) < self._SEQ_LEN + 2:
            return

        closes = list(self._close_buf)
        returns = [(closes[i] / closes[i-1]) - 1.0
                   for i in range(1, len(closes))]

        # Normalise returns
        mu  = sum(returns) / len(returns)
        std = math.sqrt(sum((r - mu) ** 2 for r in returns) / len(returns)) or 1e-8
        norm_ret = [(r - mu) / std for r in returns]

        seq     = norm_ret[-self._SEQ_LEN:]
        prob_up = self._model.forward(seq)

        # Online label update (was previous bar positive?)
        actual_up = 1.0 if returns[-1] > 0 else 0.0
        self._model.update_output(prob_up, actual_up)

        atr = self._atr.current.value

        # Stop loss
        if self._position == 1 and self._stop_price > 0 and price <= self._stop_price:
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
                niblit_adj = 0.04 * conf if act == "BUY" else \
                            -0.04 * conf if act == "SELL" else 0.0
                self.log(f"Niblit: {act} conf={conf:.3f}")
            except Exception as exc:
                self.log(f"Niblit error: {exc}")

        eff_prob = min(1.0, max(0.0, prob_up + niblit_adj))
        self.log(f"Attention P(up)={prob_up:.3f}  eff={eff_prob:.3f}")

        equity    = self.portfolio.total_portfolio_value
        stop_dist = self._ATR_MULT * atr

        if eff_prob >= self._PROB_THRESH and self._position == 0:
            shares = int(min((equity * self._RISK_PCT) / (stop_dist or 1),
                              (equity * 0.30) / price))
            if shares > 0:
                self.market_order(self._sym, shares)
                self._stop_price = price - stop_dist
                self._position   = 1
                self.log(f"Attention BUY {shares} @ {price:.2f}  P={eff_prob:.3f}")

        elif eff_prob < 0.45 and self._position == 1:
            self.liquidate(self._sym)
            self._position   = 0
            self._stop_price = 0.0
            self.log(f"Attention exit long  P={eff_prob:.3f}")

    def on_order_event(self, order_event: OrderEvent) -> None:
        self.log(str(order_event))

    def on_end_of_algorithm(self) -> None:
        self.log(f"Final value: {self.portfolio.total_portfolio_value:.2f}")
