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
#  2-state Gaussian HMM via Baum-Welch (pure Python)
# ──────────────────────────────────────────────────────────────────────────────

class _GaussianHMM2State:
    """
    2-state Gaussian HMM trained with Baum-Welch EM.
    States: 0 = bear/volatile, 1 = bull/trending.
    Observations: normalised daily log-returns.
    """

    def __init__(self) -> None:
        # Transition matrix A[i][j] = P(j | i)
        self._A  = [[0.9, 0.1], [0.1, 0.9]]
        # Emission parameters  [mean, std]
        self._mu  = [-0.001, 0.001]
        self._sig = [ 0.015, 0.008]
        # Initial state distribution
        self._pi  = [0.5, 0.5]
        self._fitted = False

    @staticmethod
    def _gauss(x: float, mu: float, sig: float) -> float:
        sig = max(sig, 1e-8)
        return math.exp(-0.5 * ((x - mu) / sig) ** 2) / (sig * math.sqrt(2 * math.pi))

    def fit(self, obs: List[float], n_iter: int = 20) -> None:
        T = len(obs)
        if T < 10:
            return
        for _ in range(n_iter):
            # Forward pass
            alpha = [[0.0, 0.0] for _ in range(T)]
            for s in range(2):
                alpha[0][s] = self._pi[s] * self._gauss(obs[0], self._mu[s], self._sig[s])
            self._normalise(alpha[0])
            for t in range(1, T):
                for s in range(2):
                    alpha[t][s] = sum(alpha[t-1][r] * self._A[r][s]
                                      for r in range(2)) * \
                                   self._gauss(obs[t], self._mu[s], self._sig[s])
                self._normalise(alpha[t])

            # Backward pass
            beta = [[1.0, 1.0] for _ in range(T)]
            for t in range(T - 2, -1, -1):
                for s in range(2):
                    beta[t][s] = sum(self._A[s][r] *
                                     self._gauss(obs[t+1], self._mu[r], self._sig[r]) *
                                     beta[t+1][r]
                                     for r in range(2))
                self._normalise(beta[t])

            # Gamma and Xi
            gamma = [[0.0, 0.0] for _ in range(T)]
            for t in range(T):
                tot = sum(alpha[t][s] * beta[t][s] for s in range(2)) or 1e-300
                for s in range(2):
                    gamma[t][s] = alpha[t][s] * beta[t][s] / tot

            xi = [[[0.0, 0.0], [0.0, 0.0]] for _ in range(T - 1)]
            for t in range(T - 1):
                tot = sum(
                    alpha[t][r] * self._A[r][s] *
                    self._gauss(obs[t+1], self._mu[s], self._sig[s]) *
                    beta[t+1][s]
                    for r in range(2) for s in range(2)
                ) or 1e-300
                for r in range(2):
                    for s in range(2):
                        xi[t][r][s] = (alpha[t][r] * self._A[r][s] *
                                       self._gauss(obs[t+1], self._mu[s], self._sig[s]) *
                                       beta[t+1][s]) / tot

            # M-step
            self._pi = [max(gamma[0][s], 1e-10) for s in range(2)]
            self._normalise(self._pi)

            for r in range(2):
                denom = sum(gamma[t][r] for t in range(T - 1)) or 1e-300
                for s in range(2):
                    self._A[r][s] = sum(xi[t][r][s] for t in range(T - 1)) / denom
                self._normalise(self._A[r])

            for s in range(2):
                denom = sum(gamma[t][s] for t in range(T)) or 1e-300
                self._mu[s]  = sum(gamma[t][s] * obs[t] for t in range(T)) / denom
                self._sig[s] = math.sqrt(
                    sum(gamma[t][s] * (obs[t] - self._mu[s]) ** 2 for t in range(T)) / denom
                )

        self._fitted = True

    @staticmethod
    def _normalise(v: List[float]) -> None:
        s = sum(v)
        if s > 0:
            for i in range(len(v)):
                v[i] /= s

    def decode(self, obs: List[float]) -> List[int]:
        """Viterbi decoding – returns most likely state sequence."""
        T = len(obs)
        if T == 0 or not self._fitted:
            return [1] * T
        vit = [[0.0, 0.0] for _ in range(T)]
        ptr = [[0, 0]      for _ in range(T)]
        for s in range(2):
            vit[0][s] = math.log(max(self._pi[s], 1e-300)) + \
                        math.log(max(self._gauss(obs[0], self._mu[s], self._sig[s]), 1e-300))
        for t in range(1, T):
            for s in range(2):
                best_prev = max(range(2),
                                key=lambda r: vit[t-1][r] + math.log(max(self._A[r][s], 1e-300)))
                vit[t][s] = vit[t-1][best_prev] + \
                            math.log(max(self._A[best_prev][s], 1e-300)) + \
                            math.log(max(self._gauss(obs[t], self._mu[s], self._sig[s]), 1e-300))
                ptr[t][s] = best_prev
        states = [0] * T
        states[-1] = max(range(2), key=lambda s: vit[-1][s])
        for t in range(T - 2, -1, -1):
            states[t] = ptr[t + 1][states[t + 1]]
        return states


# ──────────────────────────────────────────────────────────────────────────────
#  Algorithm
# ──────────────────────────────────────────────────────────────────────────────
class RegimeHmm(QCAlgorithm):
    """
    Regime Detection via 2-state Gaussian HMM (Baum-Welch).

    Regime 1 (bull / low-vol):   EMA crossover trend-following strategy.
    Regime 0 (bear / high-vol):  RSI mean-reversion strategy.
    Refit HMM every 20 bars on rolling 120-bar window of log-returns.
    """

    _SYMBOL     = "SPY"
    _WINDOW     = 120
    _REFIT_N    = 20
    _RISK_PCT   = 0.02
    _ATR_MULT   = 1.5

    def initialize(self) -> None:
        self.set_start_date(2018, 1, 1)
        self.set_end_date(2024, 1, 1)
        self.set_cash(100_000)

        if not self.live_mode:
            self.set_brokerage_model(BrokerageName.PAPER_BROKERAGE)

        self._sym  = self.add_equity(self._SYMBOL, Resolution.DAILY).symbol

        self._ema9  = self.ema(self._sym, 9,  Resolution.DAILY)
        self._ema21 = self.ema(self._sym, 21, Resolution.DAILY)
        self._rsi   = self.rsi(self._sym, 14, Resolution.DAILY)
        self._atr   = self.atr(self._sym, 14, Resolution.DAILY)

        self.set_warm_up(self._WINDOW + 10)

        self._price_buf: deque = deque(maxlen=self._WINDOW + 1)
        self._hmm       = _GaussianHMM2State()
        self._regime    = 1       # 1=bull, 0=bear
        self._bar_count = 0
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
        if self._sym not in data.bars:
            return
        if not (self._ema9.is_ready and self._ema21.is_ready
                and self._rsi.is_ready and self._atr.is_ready):
            return

        price = data.bars[self._sym].close
        self._price_buf.append(price)
        self._bar_count += 1

        # Build log-return series and refit HMM periodically
        if self._bar_count % self._REFIT_N == 0 and len(self._price_buf) > 10:
            prices  = list(self._price_buf)
            returns = [math.log(prices[i] / prices[i-1])
                       for i in range(1, len(prices))]
            self._hmm.fit(returns, n_iter=10)
            if self._hmm._fitted and returns:
                states = self._hmm.decode(returns)
                # State with higher mean → bull
                mu0, mu1 = self._hmm._mu
                bull_state = 1 if mu1 > mu0 else 0
                self._regime = bull_state if states[-1] == bull_state else 1 - bull_state
            self.log(f"HMM refit: regime={self._regime}  "
                     f"mu0={self._hmm._mu[0]:.5f}  mu1={self._hmm._mu[1]:.5f}")

        atr = self._atr.current.value

        # Stop loss check
        if self._position != 0 and self._stop_price > 0:
            stop_hit = (self._position == 1  and price <= self._stop_price) or \
                       (self._position == -1 and price >= self._stop_price)
            if stop_hit:
                self.liquidate(self._sym)
                self._position   = 0
                self._stop_price = 0.0
                self.log(f"Stop triggered @ {price:.2f}")
                return

        # Niblit optional log
        if self._bridge is not None:
            try:
                _sig_str = (self._bridge.get_signal() or "HOLD").upper()
                self.log(f"Niblit: {_sig_str}")
            except Exception:
                pass

        equity    = self.portfolio.total_portfolio_value
        stop_dist = self._ATR_MULT * atr

        if self._regime == 1:
            # Bull: EMA crossover trend-following
            bull_signal = self._ema9.current.value > self._ema21.current.value
            if bull_signal and self._position == 0:
                shares = int(min((equity * self._RISK_PCT) / (stop_dist or 1),
                                  (equity * 0.30) / price))
                if shares > 0:
                    self.market_order(self._sym, shares)
                    self._stop_price = price - stop_dist
                    self._position   = 1
                    self.log(f"Bull regime BUY {shares} @ {price:.2f}")
            elif not bull_signal and self._position == 1:
                self.liquidate(self._sym)
                self._position   = 0
                self._stop_price = 0.0
                self.log("Bull exit – EMA flip")

        else:
            # Bear: RSI mean-reversion (long-only for safety)
            rsi = self._rsi.current.value
            if rsi < 30 and self._position == 0:
                shares = int(min((equity * self._RISK_PCT) / (stop_dist or 1),
                                  (equity * 0.20) / price))
                if shares > 0:
                    self.market_order(self._sym, shares)
                    self._stop_price = price - stop_dist
                    self._position   = 1
                    self.log(f"Bear mean-rev BUY {shares} @ {price:.2f}  RSI={rsi:.1f}")
            elif rsi > 55 and self._position == 1:
                self.liquidate(self._sym)
                self._position   = 0
                self._stop_price = 0.0
                self.log(f"Bear exit – RSI={rsi:.1f}")

    def on_order_event(self, order_event: OrderEvent) -> None:
        self.log(str(order_event))

    def on_end_of_algorithm(self) -> None:
        self.log(f"Final value: {self.portfolio.total_portfolio_value:.2f}")
