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
#  Pure-Python PPO (linear policy + value function, 3 actions, 6 features)
# ──────────────────────────────────────────────────────────────────────────────

_N_FEATS   = 6
_N_ACTIONS = 3   # 0=HOLD, 1=BUY, 2=SELL


def _softmax(logits: List[float]) -> List[float]:
    m = max(logits)
    exps = [math.exp(v - m) for v in logits]
    s = sum(exps)
    return [e / s for e in exps]


class _LinearPPO:
    """
    Actor-Critic with:
      Policy:  softmax(W_pi @ state + b_pi),    W_pi: N_ACTIONS × N_FEATS
      Value:   W_v @ state + b_v,               W_v: 1 × N_FEATS
    Clipped PPO update + GAE advantage estimation.
    """

    def __init__(self, lr: float = 3e-4, gamma: float = 0.99,
                 lam: float = 0.95, clip: float = 0.2,
                 n_epochs: int = 4) -> None:
        self._lr      = lr
        self._gamma   = gamma
        self._lam     = lam
        self._clip    = clip
        self._epochs  = n_epochs

        rng = random.Random(42)
        self._W_pi = [[rng.gauss(0, 0.01) for _ in range(_N_FEATS)]
                      for _ in range(_N_ACTIONS)]
        self._b_pi = [0.0] * _N_ACTIONS
        self._W_v  = [rng.gauss(0, 0.01) for _ in range(_N_FEATS)]
        self._b_v  = 0.0

        # Trajectory buffer
        self._states:   List[List[float]] = []
        self._actions:  List[int]         = []
        self._rewards:  List[float]       = []
        self._log_probs:List[float]       = []
        self._values:   List[float]       = []
        self._dones:    List[bool]        = []

    # -- Forward passes -------------------------------------------------------
    def policy(self, s: List[float]) -> Tuple[List[float], List[float]]:
        logits = [sum(self._W_pi[a][i] * s[i] for i in range(_N_FEATS)) + self._b_pi[a]
                  for a in range(_N_ACTIONS)]
        probs = _softmax(logits)
        return probs, logits

    def value(self, s: List[float]) -> float:
        return sum(self._W_v[i] * s[i] for i in range(_N_FEATS)) + self._b_v

    def act(self, s: List[float]) -> Tuple[int, float]:
        """Sample action; return (action, log_prob)."""
        probs, _ = self.policy(s)
        r = random.random()
        cum = 0.0
        action = _N_ACTIONS - 1
        for a, p in enumerate(probs):
            cum += p
            if r <= cum:
                action = a
                break
        lp = math.log(max(probs[action], 1e-8))
        return action, lp

    def remember(self, s: List[float], a: int, r: float,
                 lp: float, v: float, done: bool) -> None:
        self._states.append(s)
        self._actions.append(a)
        self._rewards.append(r)
        self._log_probs.append(lp)
        self._values.append(v)
        self._dones.append(done)

    def update(self) -> None:
        """Run PPO update on collected trajectory then clear buffer."""
        T = len(self._rewards)
        if T < 4:
            return

        # GAE advantages
        advantages = [0.0] * T
        last_adv   = 0.0
        last_val   = 0.0
        for t in reversed(range(T)):
            nv = last_val if not self._dones[t] else 0.0
            delta      = self._rewards[t] + self._gamma * nv - self._values[t]
            last_adv   = delta + self._gamma * self._lam * last_adv * (not self._dones[t])
            advantages[t] = last_adv
            last_val   = self._values[t]

        returns = [advantages[t] + self._values[t] for t in range(T)]

        # Normalise advantages
        mu_a = sum(advantages) / T
        sd_a = math.sqrt(sum((a - mu_a) ** 2 for a in advantages) / T) or 1e-8
        advantages = [(a - mu_a) / sd_a for a in advantages]

        for _ in range(self._epochs):
            for t in range(T):
                s  = self._states[t]
                a  = self._actions[t]
                adv = advantages[t]
                ret = returns[t]
                old_lp = self._log_probs[t]

                probs, _ = self.policy(s)
                new_lp   = math.log(max(probs[a], 1e-8))
                ratio    = math.exp(new_lp - old_lp)
                surr1    = ratio * adv
                surr2    = max(min(ratio, 1 + self._clip), 1 - self._clip) * adv
                policy_loss = -min(surr1, surr2)

                # Value loss
                v_pred    = self.value(s)
                value_loss = (v_pred - ret) ** 2

                # Gradient update (analytical)
                # Policy gradient
                for aa in range(_N_ACTIONS):
                    p = probs[aa]
                    d_logit = p - (1.0 if aa == a else 0.0)
                    policy_grad = d_logit * (-policy_loss)   # chain rule simplified
                    for i in range(_N_FEATS):
                        self._W_pi[aa][i] -= self._lr * policy_grad * s[i]
                    self._b_pi[aa] -= self._lr * policy_grad

                # Value gradient
                d_v = 2.0 * (v_pred - ret)
                for i in range(_N_FEATS):
                    self._W_v[i] -= self._lr * d_v * s[i]
                self._b_v -= self._lr * d_v

        # Clear trajectory
        self._states.clear()
        self._actions.clear()
        self._rewards.clear()
        self._log_probs.clear()
        self._values.clear()
        self._dones.clear()


# ──────────────────────────────────────────────────────────────────────────────
#  Algorithm
# ──────────────────────────────────────────────────────────────────────────────
class RlPpo(QCAlgorithm):
    """
    PPO Actor-Critic Trader.

    State (6):  [RSI/100, MACD_hist/price, EMA_ratio-1, BB_%B,
                 ATR/price, vol_change_1d]
    Actions:    HOLD / BUY / SELL.
    Update:     Every 20 bars (collect then optimise).
    """

    _SYMBOL     = "SPY"
    _UPDATE_N   = 20
    _RISK_PCT   = 0.02
    _ATR_MULT   = 1.5

    def initialize(self) -> None:
        self.set_start_date(2019, 1, 1)
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

        self.set_warm_up(60)

        self._agent      = _LinearPPO()
        self._prev_value = 0.0
        self._prev_state: List[float] = [0.0] * _N_FEATS
        self._prev_action = 0
        self._prev_lp     = 0.0
        self._prev_v      = 0.0
        self._bar_count   = 0
        self._stop_price  = 0.0
        self._position    = 0
        self._prev_price  = 0.0

        self._bridge = None
        if _NIBLIT_AVAILABLE and _NiblitBridge is not None:
            try:
                self._bridge = _NiblitBridge()
                self.log("NiblitBridge connected.")
            except Exception as exc:
                self.log(f"NiblitBridge init failed: {exc}")

    def _build_state(self, price: float) -> List[float]:
        if not (self._rsi.is_ready and self._macd.is_ready and self._ema9.is_ready
                and self._ema50.is_ready and self._bb.is_ready and self._atr.is_ready):
            return [0.5, 0.0, 0.0, 0.5, 0.0, 0.0]
        atr   = self._atr.current.value
        bbu   = self._bb.upper_band.current.value
        bbl   = self._bb.lower_band.current.value
        bbrng = (bbu - bbl) or 1e-8
        pct_b = (price - bbl) / bbrng
        ema_ratio = (self._ema9.current.value / self._ema50.current.value
                     if self._ema50.current.value != 0 else 1.0) - 1.0
        vol_chg = (price - self._prev_price) / self._prev_price \
                   if self._prev_price != 0 else 0.0
        return [
            self._rsi.current.value / 100.0,
            self._macd.histogram.current.value / price,
            ema_ratio,
            max(0.0, min(1.0, pct_b)),
            atr / price,
            vol_chg,
        ]

    def on_data(self, data: Slice) -> None:
        if self.is_warming_up:
            return
        if self._sym not in data.bars:
            return

        price = data.bars[self._sym].close
        state = self._build_state(price)
        atr   = self._atr.current.value if self._atr.is_ready else 0.01 * price

        # Reward from previous step
        curr_v  = self.portfolio.total_portfolio_value
        reward  = (curr_v - self._prev_value) / max(self._prev_value, 1.0) * 100
        if self._bar_count > 0:
            self._agent.remember(self._prev_state, self._prev_action,
                                 reward, self._prev_lp, self._prev_v, False)
        self._prev_value = curr_v

        # Periodic update
        self._bar_count += 1
        if self._bar_count % self._UPDATE_N == 0:
            self._agent.update()
            self.log("PPO policy updated.")

        # Stop loss
        if self._position != 0 and self._stop_price > 0:
            stop_hit = (self._position == 1  and price <= self._stop_price) or \
                       (self._position == -1 and price >= self._stop_price)
            if stop_hit:
                self.liquidate(self._sym)
                self._position   = 0
                self._stop_price = 0.0
                self.log(f"Stop triggered @ {price:.2f}")

        action, log_prob = self._agent.act(state)
        v_est = self._agent.value(state)
        self.log(f"PPO action={['HOLD','BUY','SELL'][action]}  v={v_est:.4f}")

        # Niblit soft override
        if self._bridge is not None:
            try:
                act = (self._bridge.get_signal() or "HOLD").upper()
                conf = self._bridge.get_confidence()
                if conf > 0.75:
                    if act == "BUY":
                        action = 1
                    elif act == "SELL":
                        action = 2
                    self.log(f"Niblit override: {act}")
            except Exception as exc:
                self.log(f"Niblit error: {exc}")

        equity    = self.portfolio.total_portfolio_value
        stop_dist = self._ATR_MULT * atr

        if action == 1 and self._position != 1:  # BUY
            if self._position == -1:
                self.liquidate(self._sym)
            if stop_dist > 0:
                shares = int(min((equity * self._RISK_PCT) / stop_dist,
                                  (equity * 0.30) / price))
                if shares > 0:
                    self.market_order(self._sym, shares)
                    self._stop_price = price - stop_dist
                    self._position   = 1
                    self.log(f"PPO BUY {shares} @ {price:.2f}")

        elif action == 2 and self._position == 1:  # SELL / FLAT
            self.liquidate(self._sym)
            self._position   = 0
            self._stop_price = 0.0
            self.log(f"PPO SELL/FLAT @ {price:.2f}")

        self._prev_state  = state
        self._prev_action = action
        self._prev_lp     = log_prob
        self._prev_v      = v_est
        self._prev_price  = price

    def on_order_event(self, order_event: OrderEvent) -> None:
        self.log(str(order_event))

    def on_end_of_algorithm(self) -> None:
        self.log(f"Final value: {self.portfolio.total_portfolio_value:.2f}")
