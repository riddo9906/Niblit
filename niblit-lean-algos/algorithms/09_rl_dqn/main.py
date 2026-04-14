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
#  Tabular Q-Learning with Experience Replay
# ──────────────────────────────────────────────────────────────────────────────
# State space: 18 = 3 RSI buckets × 2 MACD signs × 3 trend buckets
# Actions:     0=HOLD, 1=BUY, 2=SELL

_N_STATES  = 18
_N_ACTIONS = 3
_HOLD, _BUY, _SELL = 0, 1, 2


class _ReplayBuffer:
    def __init__(self, capacity: int = 1000) -> None:
        self._buf: deque = deque(maxlen=capacity)

    def add(self, s: int, a: int, r: float, s2: int, done: bool) -> None:
        self._buf.append((s, a, r, s2, done))

    def sample(self, n: int) -> List[Tuple]:
        n = min(n, len(self._buf))
        return random.sample(list(self._buf), n)

    def __len__(self) -> int:
        return len(self._buf)


class _TabularQAgent:
    """
    Tabular Q-learning with epsilon-greedy exploration.
    Q-table: _N_STATES × _N_ACTIONS.
    """

    def __init__(self, lr: float = 0.01, gamma: float = 0.95,
                 epsilon: float = 1.0, epsilon_decay: float = 0.995,
                 epsilon_min: float = 0.05) -> None:
        self._lr            = lr
        self._gamma         = gamma
        self._epsilon       = epsilon
        self._epsilon_decay = epsilon_decay
        self._epsilon_min   = epsilon_min
        # Q-table initialised to small random values
        random.seed(99)
        self._Q = [[random.uniform(-0.01, 0.01) for _ in range(_N_ACTIONS)]
                   for _ in range(_N_STATES)]
        self._replay = _ReplayBuffer(capacity=1000)

    def act(self, state: int) -> int:
        if random.random() < self._epsilon:
            return random.randint(0, _N_ACTIONS - 1)
        return max(range(_N_ACTIONS), key=lambda a: self._Q[state][a])

    def remember(self, s: int, a: int, r: float, s2: int, done: bool) -> None:
        self._replay.add(s, a, r, s2, done)

    def train(self, batch_size: int = 32) -> None:
        if len(self._replay) < batch_size:
            return
        for s, a, r, s2, done in self._replay.sample(batch_size):
            target = r if done else r + self._gamma * max(self._Q[s2])
            self._Q[s][a] += self._lr * (target - self._Q[s][a])
        self._epsilon = max(self._epsilon_min,
                            self._epsilon * self._epsilon_decay)

    def best_action(self, state: int) -> int:
        return max(range(_N_ACTIONS), key=lambda a: self._Q[state][a])


def _discretize_state(rsi: float, macd_hist: float,
                      ema_fast: float, ema_slow: float) -> int:
    """
    Encode (RSI bucket, MACD sign, trend bucket) → 0..17.
    RSI:   0=oversold(<35), 1=neutral, 2=overbought(>65)
    MACD:  0=negative, 1=positive
    Trend: 0=bear (<0.99), 1=flat (0.99-1.01), 2=bull (>1.01)
    """
    rsi_b = 0 if rsi < 35 else (2 if rsi > 65 else 1)
    macd_b = 1 if macd_hist >= 0 else 0
    ratio  = ema_fast / ema_slow if ema_slow != 0 else 1.0
    trend_b = 0 if ratio < 0.99 else (2 if ratio > 1.01 else 1)
    return rsi_b * 6 + macd_b * 3 + trend_b


# ──────────────────────────────────────────────────────────────────────────────
#  Algorithm
# ──────────────────────────────────────────────────────────────────────────────
class RlDqn(QCAlgorithm):
    """
    DQN / Tabular Q-Learning Trader.

    State:    (RSI bucket, MACD sign, trend) → 18 discrete states.
    Actions:  BUY / SELL / HOLD.
    Reward:   Realised P&L of last trade (normalised).
    Update:   Batch update from replay buffer every bar.
    """

    _SYMBOL      = "SPY"
    _ATR_MULT    = 1.5
    _RISK_PCT    = 0.02
    _TRAIN_EVERY = 1     # train every N bars

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
        self._ema9  = self.ema(self._sym, 9,  Resolution.DAILY)
        self._ema50 = self.ema(self._sym, 50, Resolution.DAILY)
        self._atr   = self.atr(self._sym, 14, Resolution.DAILY)

        self.set_warm_up(60)

        self._agent = _TabularQAgent()

        self._prev_state:  Optional[int]   = None
        self._prev_action: int             = _HOLD
        self._prev_value:  float           = 0.0
        self._stop_price:  float           = 0.0
        self._position:    int             = 0
        self._bar_count:   int             = 0

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
        if not (self._rsi.is_ready and self._macd.is_ready
                and self._ema9.is_ready and self._ema50.is_ready
                and self._atr.is_ready):
            return
        if self._sym not in data.bars:
            return

        self._bar_count += 1
        price = data.bars[self._sym].close
        atr   = self._atr.current.value

        state = _discretize_state(
            self._rsi.current.value,
            self._macd.histogram.current.value,
            self._ema9.current.value,
            self._ema50.current.value,
        )

        # ---- Compute reward from last step ----
        curr_value = self.portfolio.total_portfolio_value
        reward = (curr_value - self._prev_value) / max(self._prev_value, 1.0) * 100
        if self._prev_state is not None:
            done = False
            self._agent.remember(self._prev_state, self._prev_action,
                                 reward, state, done)
        self._prev_value = curr_value
        self._prev_state = state

        # Train
        if self._bar_count % self._TRAIN_EVERY == 0:
            self._agent.train(batch_size=32)

        # Stop loss check
        if self._position != 0 and self._stop_price > 0:
            stop_hit = (self._position == 1  and price <= self._stop_price) or \
                       (self._position == -1 and price >= self._stop_price)
            if stop_hit:
                self.liquidate(self._sym)
                self._position   = 0
                self._stop_price = 0.0
                self._prev_action = _HOLD
                self.log(f"Stop triggered @ {price:.2f}")
                return

        # Agent action
        action = self._agent.act(state)
        self.log(f"State={state}  Action={['HOLD','BUY','SELL'][action]}  "
                 f"eps={self._agent._epsilon:.3f}")

        # Niblit override (soft)
        if self._bridge is not None:
            try:
                act = (self._bridge.get_signal() or "HOLD").upper()
                conf = self._bridge.get_confidence()
                if conf > 0.8:
                    action = _BUY if act == "BUY" else (_SELL if act == "SELL" else action)
                    self.log(f"Niblit override: {act}")
            except Exception as exc:
                self.log(f"Niblit error: {exc}")

        equity    = self.portfolio.total_portfolio_value
        stop_dist = self._ATR_MULT * atr

        if action == _BUY and self._position != 1:
            if self._position == -1:
                self.liquidate(self._sym)
            if stop_dist > 0:
                shares = int(min((equity * self._RISK_PCT) / stop_dist,
                                  (equity * 0.30) / price))
                if shares > 0:
                    self.market_order(self._sym, shares)
                    self._stop_price = price - stop_dist
                    self._position   = 1
                    self.log(f"DQN BUY {shares} @ {price:.2f}")

        elif action == _SELL and self._position != -1:
            if self._position == 1:
                self.liquidate(self._sym)
            # No short selling equities in this version
            self._position   = 0
            self._stop_price = 0.0
            self.log(f"DQN SELL/FLAT @ {price:.2f}")

        elif action == _HOLD and self._position != 0:
            # Maintain existing position
            pass

        self._prev_action = action

    def on_order_event(self, order_event: OrderEvent) -> None:
        self.log(str(order_event))

    def on_end_of_algorithm(self) -> None:
        self.log(f"Final value: {self.portfolio.total_portfolio_value:.2f}")
