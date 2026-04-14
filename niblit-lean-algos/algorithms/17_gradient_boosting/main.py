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
from typing import List, Tuple, Optional


# ──────────────────────────────────────────────────────────────────────────────
#  Pure-Python Gradient Boosting Machine (GBM with depth-1 stumps)
# ──────────────────────────────────────────────────────────────────────────────

class _Stump:
    """Depth-1 decision tree for regression (least-squares residuals)."""

    def __init__(self) -> None:
        self.feature_idx: int   = 0
        self.threshold:   float = 0.0
        self.left_val:    float = 0.0
        self.right_val:   float = 0.0

    def fit(self, X: List[List[float]], residuals: List[float]) -> None:
        n_feats = len(X[0])
        best_loss = float("inf")

        for fi in range(n_feats):
            vals = sorted(set(row[fi] for row in X))
            for i in range(len(vals) - 1):
                thresh = (vals[i] + vals[i + 1]) / 2.0
                left_r  = [residuals[j] for j, row in enumerate(X) if row[fi] <= thresh]
                right_r = [residuals[j] for j, row in enumerate(X) if row[fi] >  thresh]
                if not left_r or not right_r:
                    continue
                lv = sum(left_r)  / len(left_r)
                rv = sum(right_r) / len(right_r)
                loss = sum((r - lv) ** 2 for r in left_r) + \
                       sum((r - rv) ** 2 for r in right_r)
                if loss < best_loss:
                    best_loss = loss
                    self.feature_idx = fi
                    self.threshold   = thresh
                    self.left_val    = lv
                    self.right_val   = rv

    def predict(self, x: List[float]) -> float:
        return self.left_val if x[self.feature_idx] <= self.threshold \
               else self.right_val


class _GBM:
    """
    Gradient Boosting Machine: ensemble of `n_stumps` regression stumps.
    Binary classification via logit link:  P(y=1) = sigmoid(F(x)).
    Loss: binary cross-entropy.
    """

    def __init__(self, n_stumps: int = 50, lr: float = 0.1) -> None:
        self._n     = n_stumps
        self._lr    = lr
        self._trees: List[_Stump] = []
        self._F0    = 0.0   # initial prediction (log-odds)

    @staticmethod
    def _sigmoid(x: float) -> float:
        if x >  20: return 1.0
        if x < -20: return 0.0
        return 1.0 / (1.0 + math.exp(-x))

    def fit(self, X: List[List[float]], y: List[int]) -> None:
        n = len(y)
        if n == 0:
            return
        p_mean = max(1e-6, min(1 - 1e-6, sum(y) / n))
        self._F0 = math.log(p_mean / (1.0 - p_mean))   # initial log-odds

        F = [self._F0] * n
        self._trees = []

        for _ in range(self._n):
            # Negative gradient = residuals for log-loss
            probs     = [self._sigmoid(f) for f in F]
            residuals = [y[i] - probs[i] for i in range(n)]

            stump = _Stump()
            stump.fit(X, residuals)
            self._trees.append(stump)

            # Update F
            preds = [stump.predict(X[i]) for i in range(n)]
            F = [F[i] + self._lr * preds[i] for i in range(n)]

    def predict_proba(self, x: List[float]) -> float:
        """Return P(y=1)."""
        if not self._trees:
            return 0.5
        F = self._F0 + self._lr * sum(t.predict(x) for t in self._trees)
        return self._sigmoid(F)


# ──────────────────────────────────────────────────────────────────────────────
#  Algorithm
# ──────────────────────────────────────────────────────────────────────────────
class GradientBoosting(QCAlgorithm):
    """
    Gradient Boosting Signal Generator.

    Features (per bar):
        return[1..5]: last 1..5-bar returns (5 features)
        volatility:   20-bar rolling std of returns
        RSI(14) / 100
        MACD histogram / price
        volume ratio:  vol[0] / avg_vol[20]
    Total: 10 features.

    Label:    1 if next bar close > current close, else 0.
    Training: Rolling 200-bar window; retrain every 50 bars.
    Trade:    Long when P(up) > 0.6; exit when P(up) < 0.48.
    """

    _SYMBOL      = "SPY"
    _TRAIN_BARS  = 200
    _RETRAIN_N   = 50
    _PROB_THRESH = 0.60
    _RISK_PCT    = 0.02
    _ATR_MULT    = 1.5
    _N_STUMPS    = 50

    def initialize(self) -> None:
        self.set_start_date(2018, 1, 1)
        self.set_end_date(2024, 1, 1)
        self.set_cash(100_000)

        if not self.live_mode:
            self.set_brokerage_model(BrokerageName.PAPER_BROKERAGE)

        self._sym  = self.add_equity(self._SYMBOL, Resolution.DAILY).symbol
        self._rsi  = self.rsi(self._sym, 14, Resolution.DAILY)
        self._macd = self.macd(self._sym, 12, 26, 9,
                               MovingAverageType.EXPONENTIAL, Resolution.DAILY)
        self._atr  = self.atr(self._sym, 14, Resolution.DAILY)

        self.set_warm_up(220)

        self._close_buf:  deque = deque(maxlen=self._TRAIN_BARS + 10)
        self._vol_buf:    deque = deque(maxlen=self._TRAIN_BARS + 10)
        self._rsi_buf:    deque = deque(maxlen=self._TRAIN_BARS + 10)
        self._macd_buf:   deque = deque(maxlen=self._TRAIN_BARS + 10)

        self._gbm        = _GBM(n_stumps=self._N_STUMPS, lr=0.1)
        self._trained    = False
        self._bar_count  = 0
        self._stop_price = 0.0
        self._position   = 0

        self._bridge = None
        if _NIBLIT_AVAILABLE and _NiblitBridge is not None:
            try:
                self._bridge = _NiblitBridge()
                self.log("NiblitBridge connected.")
            except Exception as exc:
                self.log(f"NiblitBridge init failed: {exc}")

    def _build_features(self, idx: int,
                         closes: List[float],
                         vols: List[float],
                         rsis: List[float],
                         macds: List[float]) -> Optional[List[float]]:
        if idx < 22:
            return None
        c = closes[idx]
        if c == 0:
            return None
        # 5-bar returns
        ret_feats = [(c / closes[idx - k] - 1.0) for k in range(1, 6)
                     if idx - k >= 0]
        if len(ret_feats) < 5:
            return None
        # Volatility: 20-bar std of returns
        rets20 = [closes[i] / closes[i-1] - 1.0
                  for i in range(max(1, idx - 19), idx + 1)
                  if closes[i-1] != 0]
        mu  = sum(rets20) / len(rets20) if rets20 else 0.0
        vol = math.sqrt(sum((r - mu) ** 2 for r in rets20) / len(rets20)) if rets20 else 0.0
        # Volume ratio
        avg_vol20 = (sum(vols[max(0, idx-19):idx+1]) /
                     len(vols[max(0, idx-19):idx+1])) if vols else 1.0
        vol_ratio = vols[idx] / avg_vol20 if avg_vol20 != 0 else 1.0

        return ret_feats + [vol, rsis[idx] / 100.0, macds[idx] / c, vol_ratio]

    def _retrain(self) -> None:
        closes = list(self._close_buf)
        vols   = list(self._vol_buf)
        rsis   = list(self._rsi_buf)
        macds  = list(self._macd_buf)
        n = len(closes)
        if n < 30:
            return
        X, y = [], []
        for i in range(22, n - 1):
            feats = self._build_features(i, closes, vols, rsis, macds)
            if feats is None:
                continue
            label = 1 if closes[i + 1] > closes[i] else 0
            X.append(feats)
            y.append(label)
        if len(X) < 10:
            return
        self._gbm.fit(X, y)
        self._trained = True
        self.log(f"GBM retrained on {len(X)} samples.")

    def on_data(self, data: Slice) -> None:
        if self.is_warming_up:
            return
        if self._sym not in data.bars:
            return
        if not (self._rsi.is_ready and self._macd.is_ready and self._atr.is_ready):
            return

        bar   = data.bars[self._sym]
        price = bar.close
        self._close_buf.append(price)
        self._vol_buf.append(bar.volume)
        self._rsi_buf.append(self._rsi.current.value)
        self._macd_buf.append(self._macd.histogram.current.value)
        self._bar_count += 1

        if self._bar_count % self._RETRAIN_N == 0:
            self._retrain()

        if not self._trained:
            return

        closes = list(self._close_buf)
        vols   = list(self._vol_buf)
        rsis   = list(self._rsi_buf)
        macds  = list(self._macd_buf)
        idx    = len(closes) - 1

        feats = self._build_features(idx, closes, vols, rsis, macds)
        if feats is None:
            return

        prob_up = self._gbm.predict_proba(feats)
        atr     = self._atr.current.value

        # Stop loss
        if self._position == 1 and self._stop_price > 0 and price <= self._stop_price:
            self.liquidate(self._sym)
            self._position   = 0
            self._stop_price = 0.0
            self.log(f"Stop triggered @ {price:.2f}")
            return

        # Niblit boost
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
        self.log(f"GBM P(up)={prob_up:.3f}  eff={eff_prob:.3f}")

        equity    = self.portfolio.total_portfolio_value
        stop_dist = self._ATR_MULT * atr

        if eff_prob >= self._PROB_THRESH and self._position == 0:
            shares = int(min((equity * self._RISK_PCT) / (stop_dist or 1),
                              (equity * 0.30) / price))
            if shares > 0:
                self.market_order(self._sym, shares)
                self._stop_price = price - stop_dist
                self._position   = 1
                self.log(f"GBM BUY {shares} @ {price:.2f}  P={eff_prob:.3f}")

        elif eff_prob < 0.48 and self._position == 1:
            self.liquidate(self._sym)
            self._position   = 0
            self._stop_price = 0.0
            self.log(f"GBM exit long  P={eff_prob:.3f}")

    def on_order_event(self, order_event: OrderEvent) -> None:
        self.log(str(order_event))

    def on_end_of_algorithm(self) -> None:
        self.log(f"Final value: {self.portfolio.total_portfolio_value:.2f}")
