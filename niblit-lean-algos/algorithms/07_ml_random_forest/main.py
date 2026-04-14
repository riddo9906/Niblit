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
#  Pure-Python Decision Tree (single feature, depth-1 stump)
# ──────────────────────────────────────────────────────────────────────────────
class _Stump:
    """Depth-1 decision tree (classification stump)."""

    def __init__(self) -> None:
        self.feature_idx: int   = 0
        self.threshold:   float = 0.0
        self.left_label:  int   = 0
        self.right_label: int   = 0

    def fit(self, X: List[List[float]], y: List[int],
            sample_weights: Optional[List[float]] = None) -> None:
        n_features = len(X[0])
        n          = len(X)
        if sample_weights is None:
            sample_weights = [1.0 / n] * n

        best_gini = float("inf")
        for fi in range(n_features):
            vals = sorted(set(row[fi] for row in X))
            for i in range(len(vals) - 1):
                thresh = (vals[i] + vals[i + 1]) / 2.0
                left_w  = {0: 0.0, 1: 0.0}
                right_w = {0: 0.0, 1: 0.0}
                for j, row in enumerate(X):
                    label = y[j]
                    if row[fi] <= thresh:
                        left_w[label]  += sample_weights[j]
                    else:
                        right_w[label] += sample_weights[j]
                gini = self._gini(left_w) + self._gini(right_w)
                if gini < best_gini:
                    best_gini         = gini
                    self.feature_idx  = fi
                    self.threshold    = thresh
                    # Majority label for each split
                    self.left_label   = 0 if left_w[0]  >= left_w[1]  else 1
                    self.right_label  = 0 if right_w[0] >= right_w[1] else 1

    @staticmethod
    def _gini(weights: dict) -> float:
        total = sum(weights.values())
        if total == 0:
            return 0.0
        p = weights[1] / total
        return total * (1.0 - p * p - (1.0 - p) ** 2)

    def predict(self, x: List[float]) -> int:
        return self.left_label if x[self.feature_idx] <= self.threshold \
               else self.right_label


# ──────────────────────────────────────────────────────────────────────────────
#  Random Forest (bagging of stumps)
# ──────────────────────────────────────────────────────────────────────────────
class _RandomForest:
    """Minimal Random Forest using stumps and bootstrap sampling."""

    def __init__(self, n_trees: int = 20, seed: int = 42) -> None:
        self._n_trees = n_trees
        self._trees: List[_Stump] = []
        random.seed(seed)

    def fit(self, X: List[List[float]], y: List[int]) -> None:
        n = len(X)
        self._trees = []
        for _ in range(self._n_trees):
            # Bootstrap sample
            indices    = [random.randint(0, n - 1) for _ in range(n)]
            X_boot     = [X[i] for i in indices]
            y_boot     = [y[i] for i in indices]
            stump = _Stump()
            stump.fit(X_boot, y_boot)
            self._trees.append(stump)

    def predict(self, x: List[float]) -> int:
        if not self._trees:
            return 0
        votes = sum(t.predict(x) for t in self._trees)
        return 1 if votes > len(self._trees) / 2 else 0

    def predict_proba(self, x: List[float]) -> float:
        """Return probability of class 1."""
        if not self._trees:
            return 0.5
        return sum(t.predict(x) for t in self._trees) / len(self._trees)


# ──────────────────────────────────────────────────────────────────────────────
#  Algorithm
# ──────────────────────────────────────────────────────────────────────────────
class MlRandomForest(QCAlgorithm):
    """
    Pure-Python Random Forest trading strategy.

    Features per bar: RSI(14), MACD_hist, EMA_ratio(9/50), BB_%B, ATR_norm.
    Label:            1 if next bar return > 0, else 0.
    Training window:  200 bars, retrained every 50 bars.
    Trade:            Long when P(up) > 0.6, flat otherwise.
    """

    _SYMBOL      = "SPY"
    _TRAIN_BARS  = 200
    _RETRAIN_N   = 50
    _RISK_PCT    = 0.02
    _ATR_MULT    = 1.5
    _PROB_THRESH = 0.60

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
        self._ema9 = self.ema(self._sym, 9,  Resolution.DAILY)
        self._ema50= self.ema(self._sym, 50, Resolution.DAILY)
        self._bb   = self.bb(self._sym, 20, 2.0, Resolution.DAILY)
        self._atr  = self.atr(self._sym, 14, Resolution.DAILY)

        self.set_warm_up(210)

        self._feature_buf: deque = deque(maxlen=self._TRAIN_BARS + 1)
        self._price_buf:   deque = deque(maxlen=self._TRAIN_BARS + 2)
        self._forest = _RandomForest(n_trees=20)
        self._trained      = False
        self._bar_count    = 0
        self._stop_price   = 0.0
        self._position     = 0

        self._bridge = None
        if _NIBLIT_AVAILABLE and _NiblitBridge is not None:
            try:
                self._bridge = _NiblitBridge()
                self.log("NiblitBridge connected.")
            except Exception as exc:
                self.log(f"NiblitBridge init failed: {exc}")

    def _extract_features(self, price: float) -> Optional[List[float]]:
        """Return feature vector or None if indicators not ready."""
        if not (self._rsi.is_ready and self._macd.is_ready
                and self._ema9.is_ready and self._ema50.is_ready
                and self._bb.is_ready and self._atr.is_ready):
            return None
        atr = self._atr.current.value
        if atr == 0 or price == 0:
            return None
        bb_upper = self._bb.upper_band.current.value
        bb_lower = self._bb.lower_band.current.value
        bb_range = bb_upper - bb_lower
        pct_b    = ((price - bb_lower) / bb_range) if bb_range != 0 else 0.5
        ema_ratio = self._ema9.current.value / self._ema50.current.value if self._ema50.current.value != 0 else 1.0
        return [
            self._rsi.current.value / 100.0,
            self._macd.histogram.current.value / price,
            ema_ratio - 1.0,
            pct_b,
            atr / price,
        ]

    def _retrain(self) -> None:
        """Build training dataset from buffer and fit the forest."""
        buf   = list(self._feature_buf)
        pbuf  = list(self._price_buf)
        if len(buf) < 20 or len(pbuf) < len(buf) + 1:
            return
        X, y = [], []
        for i in range(len(buf) - 1):
            feats = buf[i]
            if feats is None:
                continue
            label = 1 if pbuf[i + 1] > pbuf[i] else 0
            X.append(feats)
            y.append(label)
        if len(X) < 10:
            return
        self._forest.fit(X, y)
        self._trained = True
        self.log(f"Random Forest retrained on {len(X)} samples.")

    def on_data(self, data: Slice) -> None:
        if self.is_warming_up:
            return
        if self._sym not in data.bars:
            return

        price = data.bars[self._sym].close
        self._price_buf.append(price)
        feats = self._extract_features(price)
        self._feature_buf.append(feats)
        self._bar_count += 1

        # Retrain periodically
        if self._bar_count % self._RETRAIN_N == 0:
            self._retrain()

        if not self._trained or feats is None:
            return

        prob_up = self._forest.predict_proba(feats)
        atr     = self._atr.current.value

        # Stop loss
        if self._position != 0 and self._stop_price > 0:
            if self._position == 1 and price <= self._stop_price:
                self.liquidate(self._sym)
                self._position   = 0
                self._stop_price = 0.0
                self.log(f"Stop triggered @ {price:.2f}")
                return

        # Niblit overlay
        niblit_prob_adj = 0.0
        if self._bridge is not None:
            try:
                act = (self._bridge.get_signal() or "HOLD").upper()
                conf = self._bridge.get_confidence()
                if act == "BUY":
                    niblit_prob_adj = 0.05 * conf
                elif act == "SELL":
                    niblit_prob_adj = -0.05 * conf
            except Exception as exc:
                self.log(f"Niblit error: {exc}")

        effective_prob = prob_up + niblit_prob_adj
        self.log(f"RF prob_up={prob_up:.3f}  adj={effective_prob:.3f}")

        if effective_prob >= self._PROB_THRESH and self._position == 0:
            equity    = self.portfolio.total_portfolio_value
            stop_dist = self._ATR_MULT * atr
            shares    = int(min((equity * self._RISK_PCT) / stop_dist,
                                 (equity * 0.30) / price)) if stop_dist > 0 else 0
            if shares > 0:
                self.market_order(self._sym, shares)
                self._stop_price = price - stop_dist
                self._position   = 1
                self.log(f"Buy {shares} @ {price:.2f}  prob={effective_prob:.3f}")

        elif effective_prob < 0.5 and self._position == 1:
            self.liquidate(self._sym)
            self._position   = 0
            self._stop_price = 0.0
            self.log(f"Exit long  prob={effective_prob:.3f}")

    def on_order_event(self, order_event: OrderEvent) -> None:
        self.log(str(order_event))

    def on_end_of_algorithm(self) -> None:
        self.log(f"Final value: {self.portfolio.total_portfolio_value:.2f}")
