#!/usr/bin/env python3
"""
modules/rl_trading_policy.py — Reinforcement Learning Trading Policy for Niblit.

Provides lightweight PPO, DQN, and Transformer-inspired RL policies that
integrate with TradingBrain's state vectors to produce BUY / SELL / HOLD
decisions.  All algorithms are implemented using only numpy (or stdlib
fallback) so no deep-learning framework is required at import time.

Algorithms
----------
DQN (Deep Q-Network)
    Discrete action Q-learning with an experience replay buffer and
    epsilon-greedy exploration.  Q-values are stored in a lightweight
    hash-table with vector quantisation (no neural network required).

PPO (Proximal Policy Optimisation)
    Actor-critic policy gradient with clipped surrogate objective and
    advantage estimation via a simple value baseline.  Uses a linear
    softmax policy over discretised state buckets.

Transformer
    Attention-weighted aggregation of the last N state vectors.
    Computes scaled dot-product self-attention across a rolling context
    window and produces a weighted signal for the decision boundary.

Usage
-----
    from modules.rl_trading_policy import get_rl_policy

    policy = get_rl_policy(algorithm="ppo")        # or "dqn", "transformer"
    action = policy.select_action(state_vector)    # "BUY" | "SELL" | "HOLD"
    policy.record_outcome(reward)                  # -1 / 0 / +1

Design notes
------------
* **Additive only** — does not modify TradingBrain or any other module.
* **No heavy dependencies** — works with numpy alone; gracefully degrades
  to stdlib math when numpy is absent.
* **Wired by TradingBrain** — :func:`get_rl_policy` returns a singleton
  that TradingBrain uses as an optional override in ``decide_action()``.

Configuration (environment variables)
--------------------------------------
    NIBLIT_RL_ALGORITHM   — one of ``ppo``, ``dqn``, ``transformer``.
                            Defaults to ``ppo``.
    NIBLIT_RL_EPSILON     — exploration rate for DQN (float, default ``0.15``).
    NIBLIT_RL_LR          — learning rate (float, default ``0.01``).
    NIBLIT_RL_GAMMA       — discount factor (float, default ``0.95``).
    NIBLIT_RL_CONTEXT     — history window for Transformer (int, default ``16``).
"""

from __future__ import annotations

import collections
import logging
import math
import os
import random
import threading
from typing import Any, Deque, Dict, List, Optional, Tuple

log = logging.getLogger("niblit_rl_policy")

# ── optional numpy ────────────────────────────────────────────────────────────
try:
    import numpy as np
    _NP = True
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]
    _NP = False

# ── constants ─────────────────────────────────────────────────────────────────
_ACTIONS: List[str] = ["BUY", "SELL", "HOLD"]
_N_ACTIONS: int = len(_ACTIONS)
_ACTION_IDX: Dict[str, int] = {a: i for i, a in enumerate(_ACTIONS)}

_DEFAULT_ALGORITHM = os.getenv("NIBLIT_RL_ALGORITHM", "ppo").lower()
_DEFAULT_EPSILON = float(os.getenv("NIBLIT_RL_EPSILON", "0.15"))
_DEFAULT_LR = float(os.getenv("NIBLIT_RL_LR", "0.01"))
_DEFAULT_GAMMA = float(os.getenv("NIBLIT_RL_GAMMA", "0.95"))
_DEFAULT_CONTEXT = int(os.getenv("NIBLIT_RL_CONTEXT", "16"))

# Max experience replay buffer size (DQN)
_REPLAY_CAPACITY = 2000
# Number of experience samples per DQN update
_BATCH_SIZE = 32
# Clip ratio for PPO surrogate objective
_PPO_CLIP = 0.2
# Number of "buckets" per state dimension for discretisation
_N_BUCKETS = 4


# ─────────────────────────────────────────────────────────────────────────────
# Helper utilities
# ─────────────────────────────────────────────────────────────────────────────

def _softmax(logits: List[float]) -> List[float]:
    """Numerically stable softmax over a list of floats."""
    max_l = max(logits)
    exps = [math.exp(v - max_l) for v in logits]
    total = sum(exps)
    return [e / total for e in exps]


def _argmax(values: List[float]) -> int:
    return max(range(len(values)), key=lambda i: values[i])


def _dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _discretise(vector: List[float], n_buckets: int = _N_BUCKETS) -> Tuple[int, ...]:
    """Map a float vector to a tuple of bucket indices for use as a dict key."""
    result = []
    for v in vector:
        # Clamp to [-3, 3] (z-score range) then bucket
        clamped = max(-3.0, min(3.0, v))
        bucket = int((clamped + 3.0) / 6.0 * n_buckets)
        result.append(min(bucket, n_buckets - 1))
    return tuple(result)


# ─────────────────────────────────────────────────────────────────────────────
# Base policy
# ─────────────────────────────────────────────────────────────────────────────

class RLTradingPolicy:
    """Abstract base class for RL trading policies.

    Subclasses must implement :meth:`select_action` and
    :meth:`record_outcome`.

    Parameters
    ----------
    algorithm:  Name of the RL algorithm (``"dqn"``, ``"ppo"``,
                ``"transformer"``).
    lr:         Learning rate for weight updates.
    gamma:      Discount factor applied to future rewards.
    """

    algorithm: str = "base"

    def __init__(
        self,
        lr: float = _DEFAULT_LR,
        gamma: float = _DEFAULT_GAMMA,
    ) -> None:
        self.lr = lr
        self.gamma = gamma
        self._lock = threading.Lock()
        # Running statistics
        self._total_decisions: int = 0
        self._action_counts: Dict[str, int] = {a: 0 for a in _ACTIONS}
        self._cumulative_reward: float = 0.0
        self._last_action: str = "HOLD"
        self._last_state: Optional[List[float]] = None

    # ── public API ────────────────────────────────────────────────────────────

    def select_action(self, state: List[float]) -> str:
        """Return ``"BUY"``, ``"SELL"``, or ``"HOLD"`` for the given state.

        Args:
            state: Normalised float vector from TradingBrain.build_state_vector().

        Returns:
            A trade action string.
        """
        raise NotImplementedError

    def record_outcome(self, reward: float) -> None:
        """Record the reward received after the last action.

        Args:
            reward: Numeric reward signal.  Convention: ``+1`` for profitable
                    BUY/SELL, ``-1`` for loss, ``0`` for neutral/HOLD.
        """
        raise NotImplementedError

    # ── status ────────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        """Return a human-readable status dict."""
        with self._lock:
            return {
                "algorithm": self.algorithm,
                "total_decisions": self._total_decisions,
                "action_counts": dict(self._action_counts),
                "cumulative_reward": round(self._cumulative_reward, 4),
                "last_action": self._last_action,
                "lr": self.lr,
                "gamma": self.gamma,
            }

    # ── internal helpers ──────────────────────────────────────────────────────

    def _record_action(self, action: str) -> None:
        with self._lock:
            self._total_decisions += 1
            self._action_counts[action] = self._action_counts.get(action, 0) + 1
            self._last_action = action


# ─────────────────────────────────────────────────────────────────────────────
# DQN Policy
# ─────────────────────────────────────────────────────────────────────────────

class DQNPolicy(RLTradingPolicy):
    """Deep Q-Network inspired Q-table policy with epsilon-greedy exploration.

    Uses vector quantisation (discretisation) to map continuous state vectors
    to Q-table keys, avoiding a neural network dependency.  Supports an
    experience replay buffer for off-policy updates.

    Parameters
    ----------
    epsilon:    Initial exploration probability (decays over time).
    epsilon_min: Minimum exploration rate.
    epsilon_decay: Multiplicative decay applied after each update step.
    replay_capacity: Max size of the experience replay buffer.
    batch_size: Number of transitions sampled per training step.
    """

    algorithm = "dqn"

    def __init__(
        self,
        lr: float = _DEFAULT_LR,
        gamma: float = _DEFAULT_GAMMA,
        epsilon: float = _DEFAULT_EPSILON,
        epsilon_min: float = 0.01,
        epsilon_decay: float = 0.995,
        replay_capacity: int = _REPLAY_CAPACITY,
        batch_size: int = _BATCH_SIZE,
    ) -> None:
        super().__init__(lr=lr, gamma=gamma)
        self.epsilon = epsilon
        self.epsilon_min = epsilon_min
        self.epsilon_decay = epsilon_decay
        self.batch_size = batch_size
        # Q-table: state_key → [Q(BUY), Q(SELL), Q(HOLD)]
        self._q_table: Dict[Tuple[int, ...], List[float]] = {}
        # Experience replay buffer: (state_key, action_idx, reward, next_key)
        self._replay: Deque[Tuple] = collections.deque(maxlen=replay_capacity)
        self._pending_state: Optional[Tuple[int, ...]] = None
        self._pending_action_idx: Optional[int] = None

    def _get_q(self, key: Tuple[int, ...]) -> List[float]:
        """Return Q-values for a state key, initialising to zeros if absent."""
        if key not in self._q_table:
            self._q_table[key] = [0.0] * _N_ACTIONS
        return self._q_table[key]

    def select_action(self, state: List[float]) -> str:
        state_key = _discretise(state)

        # Epsilon-greedy exploration
        if random.random() < self.epsilon:
            action_idx = random.randrange(_N_ACTIONS)
        else:
            q_vals = self._get_q(state_key)
            action_idx = _argmax(q_vals)

        action = _ACTIONS[action_idx]

        with self._lock:
            self._pending_state = state_key
            self._pending_action_idx = action_idx

        self._record_action(action)
        self._last_state = list(state)
        log.debug("[DQN] state_key=%s q=%s → %s (ε=%.3f)",
                  state_key[:3], [round(v, 3) for v in self._get_q(state_key)],
                  action, self.epsilon)
        return action

    def record_outcome(self, reward: float) -> None:
        with self._lock:
            s = self._pending_state
            a = self._pending_action_idx
            self._cumulative_reward += reward

        if s is None or a is None:
            return

        # We need a next state; use same state as placeholder (single-step update)
        # A real next-state would be provided by the trading loop; this is safe
        # because the Q-table will be updated again when the next state arrives.
        next_key = s  # conservative: assume state unchanged for now

        self._replay.append((s, a, reward, next_key))

        # Decay epsilon
        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

        # Mini-batch update from replay buffer
        self._update_from_replay()

    def _update_from_replay(self) -> None:
        if len(self._replay) < self.batch_size:
            return
        batch = random.sample(list(self._replay), self.batch_size)
        for (s_key, a_idx, rwd, ns_key) in batch:
            q_s = self._get_q(s_key)
            q_ns = self._get_q(ns_key)
            target = rwd + self.gamma * max(q_ns)
            q_s[a_idx] += self.lr * (target - q_s[a_idx])


# ─────────────────────────────────────────────────────────────────────────────
# PPO Policy
# ─────────────────────────────────────────────────────────────────────────────

class PPOPolicy(RLTradingPolicy):
    """Proximal Policy Optimisation (PPO) inspired policy.

    Implements a linear softmax actor with a state-value baseline to compute
    advantages, and applies the PPO clipped surrogate loss for stable updates.
    State vectors are discretised to string keys; the "neural network" is a
    lightweight weight table indexed by (state_bucket, action) pairs.

    Parameters
    ----------
    clip_ratio:  PPO ε clip ratio (default 0.2).
    n_epochs:    Number of gradient steps per update.
    """

    algorithm = "ppo"

    def __init__(
        self,
        lr: float = _DEFAULT_LR,
        gamma: float = _DEFAULT_GAMMA,
        clip_ratio: float = _PPO_CLIP,
        n_epochs: int = 4,
    ) -> None:
        super().__init__(lr=lr, gamma=gamma)
        self.clip_ratio = clip_ratio
        self.n_epochs = n_epochs
        # Policy weights: state_key → [logit_BUY, logit_SELL, logit_HOLD]
        self._policy_weights: Dict[Tuple[int, ...], List[float]] = {}
        # Value baseline: state_key → scalar
        self._value_table: Dict[Tuple[int, ...], float] = {}
        # Trajectory buffer: list of (state_key, action_idx, reward, old_prob)
        self._trajectory: List[Tuple[Tuple[int, ...], int, float, float]] = []
        self._pending_state: Optional[Tuple[int, ...]] = None
        self._pending_action_idx: Optional[int] = None
        self._pending_prob: float = 1.0 / _N_ACTIONS

    def _get_logits(self, key: Tuple[int, ...]) -> List[float]:
        if key not in self._policy_weights:
            self._policy_weights[key] = [0.0] * _N_ACTIONS
        return self._policy_weights[key]

    def _get_value(self, key: Tuple[int, ...]) -> float:
        return self._value_table.get(key, 0.0)

    def select_action(self, state: List[float]) -> str:
        state_key = _discretise(state)
        logits = self._get_logits(state_key)
        probs = _softmax(logits)

        # Sample from the policy distribution
        r = random.random()
        cumulative = 0.0
        action_idx = _N_ACTIONS - 1
        for i, p in enumerate(probs):
            cumulative += p
            if r <= cumulative:
                action_idx = i
                break

        action = _ACTIONS[action_idx]

        with self._lock:
            self._pending_state = state_key
            self._pending_action_idx = action_idx
            self._pending_prob = probs[action_idx]

        self._record_action(action)
        self._last_state = list(state)
        log.debug("[PPO] state_key=%s probs=%s → %s",
                  state_key[:3], [round(p, 3) for p in probs], action)
        return action

    def record_outcome(self, reward: float) -> None:
        with self._lock:
            s = self._pending_state
            a = self._pending_action_idx
            old_prob = self._pending_prob
            self._cumulative_reward += reward

        if s is None or a is None:
            return

        self._trajectory.append((s, a, reward, old_prob))

        # Update every N steps (mini-episode)
        if len(self._trajectory) >= self.n_epochs * 4:
            self._ppo_update()
            self._trajectory.clear()

    def _ppo_update(self) -> None:
        """Apply PPO clipped surrogate update over the current trajectory."""
        # Compute advantages using simple value baseline
        for (s_key, a_idx, rwd, old_prob) in self._trajectory:
            v = self._get_value(s_key)
            advantage = rwd + self.gamma * 0.0 - v  # 0 for terminal

            # Update value baseline (TD-0)
            self._value_table[s_key] = v + self.lr * advantage

            # Update policy
            logits = self._get_logits(s_key)
            probs = _softmax(logits)
            new_prob = max(probs[a_idx], 1e-8)
            ratio = new_prob / max(old_prob, 1e-8)

            # Clipped surrogate objective gradient (sign-based)
            clipped_ratio = max(_PPO_CLIP_MIN, min(ratio, 1.0 + self.clip_ratio))
            effective_ratio = min(ratio, clipped_ratio)
            grad = effective_ratio * advantage

            # Gradient ascent on selected action, gradient descent on others
            for i in range(_N_ACTIONS):
                if i == a_idx:
                    logits[i] += self.lr * grad
                else:
                    logits[i] -= self.lr * grad * probs[i]


_PPO_CLIP_MIN = 1.0 - _PPO_CLIP


# ─────────────────────────────────────────────────────────────────────────────
# Transformer Policy
# ─────────────────────────────────────────────────────────────────────────────

class TransformerPolicy(RLTradingPolicy):
    """Attention-weighted state aggregation policy (Transformer-inspired).

    Maintains a rolling context window of the last N state vectors.  At each
    step, computes scaled dot-product self-attention over the window to produce
    a weighted representation, then applies a linear decision boundary to
    determine the action.

    This provides the core Transformer insight — attending over temporal
    context — without requiring a deep-learning framework.

    Parameters
    ----------
    context_len:  Number of past state vectors to attend over (default 16).
    """

    algorithm = "transformer"

    def __init__(
        self,
        lr: float = _DEFAULT_LR,
        gamma: float = _DEFAULT_GAMMA,
        context_len: int = _DEFAULT_CONTEXT,
    ) -> None:
        super().__init__(lr=lr, gamma=gamma)
        self.context_len = context_len
        # Rolling context window: deque of state vectors
        self._context: Deque[List[float]] = collections.deque(maxlen=context_len)
        # Decision weights: [w_BUY, w_SELL, w_HOLD] per feature dimension
        # Initialised to small random values (or zeros when numpy absent)
        self._weights: Optional[List[List[float]]] = None
        self._pending_action_idx: Optional[int] = None
        self._pending_attended: Optional[List[float]] = None

    def _init_weights(self, dim: int) -> None:
        """Lazy-initialise decision weight matrix [n_actions × dim]."""
        if self._weights is not None:
            return
        if _NP:
            rng = np.random.default_rng(42)
            w = rng.normal(0.0, 0.01, (dim, _N_ACTIONS)).tolist()
            self._weights = [[row[a] for a in range(_N_ACTIONS)] for row in w]
        else:
            self._weights = [[random.gauss(0.0, 0.01) for _ in range(_N_ACTIONS)]
                             for _ in range(dim)]

    def _attend(self, context: List[List[float]]) -> List[float]:
        """Compute attended context vector via scaled dot-product attention."""
        if not context:
            return []

        query = context[-1]  # Most recent state as query
        dim = len(query)
        scale = math.sqrt(dim) if dim > 0 else 1.0

        # Attention scores: query · key / sqrt(dim) for each context state
        scores: List[float] = []
        for key_vec in context:
            s = _dot(query, key_vec) / scale
            scores.append(s)

        # Softmax over scores
        attn_weights = _softmax(scores)

        # Weighted sum of values (value = state vector itself)
        attended = [0.0] * dim
        for w, val_vec in zip(attn_weights, context):
            for j in range(dim):
                attended[j] += w * val_vec[j]

        return attended

    def select_action(self, state: List[float]) -> str:
        self._context.append(list(state))
        context = list(self._context)
        dim = len(state)

        self._init_weights(dim)
        attended = self._attend(context)

        if not attended or self._weights is None:
            # Not enough context yet — default to HOLD
            self._record_action("HOLD")
            return "HOLD"

        # Linear projection of attended vector → action logits
        logits: List[float] = []
        for a_idx in range(_N_ACTIONS):
            logit = sum(attended[j] * self._weights[j][a_idx]
                        for j in range(min(dim, len(self._weights))))
            logits.append(logit)

        probs = _softmax(logits)
        action_idx = _argmax(probs)
        action = _ACTIONS[action_idx]

        with self._lock:
            self._pending_action_idx = action_idx
            self._pending_attended = attended

        self._record_action(action)
        self._last_state = list(state)
        log.debug("[Transformer] ctx_len=%d attended_norm=%.4f → %s",
                  len(context), math.sqrt(sum(x ** 2 for x in attended)), action)
        return action

    def record_outcome(self, reward: float) -> None:
        with self._lock:
            a_idx = self._pending_action_idx
            attended = self._pending_attended
            self._cumulative_reward += reward

        if a_idx is None or attended is None or self._weights is None:
            return

        # Gradient update: reward-weighted learning on decision weights
        dim = len(attended)
        for j in range(min(dim, len(self._weights))):
            self._weights[j][a_idx] += self.lr * reward * attended[j]


# ─────────────────────────────────────────────────────────────────────────────
# Singleton factory
# ─────────────────────────────────────────────────────────────────────────────

_policy_singleton: Optional[RLTradingPolicy] = None
_policy_lock = threading.Lock()


def get_rl_policy(
    algorithm: Optional[str] = None,
    **kwargs: Any,
) -> RLTradingPolicy:
    """Return the process-wide RL trading policy singleton.

    Args:
        algorithm: One of ``"ppo"``, ``"dqn"``, ``"transformer"``.
                   Defaults to the ``NIBLIT_RL_ALGORITHM`` env var (``"ppo"``).
        **kwargs:  Extra keyword arguments forwarded to the policy constructor.

    Returns:
        The singleton :class:`RLTradingPolicy` instance.
    """
    global _policy_singleton
    with _policy_lock:
        if _policy_singleton is None:
            algo = (algorithm or _DEFAULT_ALGORITHM).lower()
            if algo == "dqn":
                _policy_singleton = DQNPolicy(**kwargs)
            elif algo == "transformer":
                _policy_singleton = TransformerPolicy(**kwargs)
            else:
                # Default to PPO
                _policy_singleton = PPOPolicy(**kwargs)
            log.info("[RLPolicy] Initialised %s policy", _policy_singleton.algorithm)
    return _policy_singleton
