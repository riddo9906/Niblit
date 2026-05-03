#!/usr/bin/env python3
"""
nibblebots/strategic_planner.py — Phase 7 Strategic Intelligence Layer

Moves the evolution engine from purely reactive ("apply what the impact scorer
recommends right now") to strategically aware ("apply what makes sense given
where the system is heading").

The strategic planner answers four questions before any evolution cycle:

1. **Is it safe to act at all?**
   Consults the anomaly detector.  If the system is in a degraded state,
   recommend "do nothing" regardless of the impact scores.

2. **Is the expected gain worth acting?**
   If the best available net_score is below ``MIN_GAIN_THRESHOLD``, recommend
   "do nothing".  This is the "maturity check" — a system that acts only when
   it has something meaningful to offer.

3. **Should this cycle explore or exploit?**
   Epsilon-greedy policy: with probability ``EXPLORATION_RATE`` the planner
   promotes higher-risk, higher-uncertainty fixes to discover new patterns.
   Otherwise it picks the highest net_score safe options.

4. **What are the system-level goals for this cycle?**
   Derives a priority objective from the long-term outcome trend:
   * ``maximize_stability``  — when recent pass rate < STABILITY_TARGET
   * ``minimize_regression`` — when rolling average failures are rising
   * ``improve_learning``    — otherwise (system is stable, push for knowledge)

The planner does NOT replace the impact scorer — it wraps it with strategic
context and can override individual fix selection.

Constants (all overridable via environment variables)
-----------------------------------------------------
MIN_GAIN_THRESHOLD  : float  (env: EVOLUTION_MIN_GAIN, default 0.03)
EXPLORATION_RATE    : float  (env: EVOLUTION_EXPLORE_RATE, default 0.20)
STABILITY_TARGET    : float  (env: EVOLUTION_STABILITY_TARGET, default 0.85)
REGRESSION_WINDOW   : int    (env: EVOLUTION_REGRESS_WINDOW, default 10)
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from nibblebots import objective_engine, goal_adaptation_engine


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MIN_GAIN_THRESHOLD: float = float(os.environ.get("EVOLUTION_MIN_GAIN", "0.03"))
EXPLORATION_RATE: float = float(os.environ.get("EVOLUTION_EXPLORE_RATE", "0.20"))
STABILITY_TARGET: float = float(os.environ.get("EVOLUTION_STABILITY_TARGET", "0.85"))
REGRESSION_WINDOW: int = int(os.environ.get("EVOLUTION_REGRESS_WINDOW", "10"))

_STRATEGY_FILE = Path(__file__).parent / "strategic_state.json"


# ---------------------------------------------------------------------------
# Goal types
# ---------------------------------------------------------------------------

GOAL_MAXIMIZE_STABILITY = "maximize_stability"
GOAL_MINIMIZE_REGRESSION = "minimize_regression"
GOAL_IMPROVE_LEARNING = "improve_learning"

_ALL_GOALS = (GOAL_MAXIMIZE_STABILITY, GOAL_MINIMIZE_REGRESSION, GOAL_IMPROVE_LEARNING)


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def _load_state() -> Dict[str, Any]:
    if _STRATEGY_FILE.exists():
        try:
            return json.loads(_STRATEGY_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "current_goal": GOAL_IMPROVE_LEARNING,
        "cycle_count": 0,
        "do_nothing_streak": 0,
        "exploration_history": [],  # list of bool (True = exploited, False = explored)
        "pass_rate_history": [],    # list of float
    }


def _save_state(state: Dict[str, Any]) -> None:
    # Keep histories bounded
    state["exploration_history"] = state.get("exploration_history", [])[-50:]
    state["pass_rate_history"] = state.get("pass_rate_history", [])[-REGRESSION_WINDOW * 2:]
    try:
        _STRATEGY_FILE.write_text(
            json.dumps(state, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Goal derivation
# ---------------------------------------------------------------------------

def _derive_goal(
    pass_rate_history: List[float],
) -> str:
    """Choose the current system-level goal from recent pass rate history."""
    if not pass_rate_history:
        return GOAL_IMPROVE_LEARNING

    recent = pass_rate_history[-REGRESSION_WINDOW:]
    avg = sum(recent) / len(recent)

    if avg < STABILITY_TARGET:
        return GOAL_MAXIMIZE_STABILITY

    # Detect rising failure trend (pass rate trending down)
    if len(recent) >= 3:
        first_half = recent[: len(recent) // 2]
        second_half = recent[len(recent) // 2 :]
        avg_first = sum(first_half) / len(first_half)
        avg_second = sum(second_half) / len(second_half)
        if avg_second < avg_first - 0.05:   # significant downward trend
            return GOAL_MINIMIZE_REGRESSION

    return GOAL_IMPROVE_LEARNING


# ---------------------------------------------------------------------------
# Strategic decision types
# ---------------------------------------------------------------------------

class StrategicDecision:
    """The planner's output for one evolution cycle."""

    __slots__ = (
        "action",        # "proceed" | "do_nothing"
        "mode",          # "exploit" | "explore"
        "goal",          # current system-level goal
        "reason",        # human-readable explanation
        "risk_budget",   # float: max allowed avg risk_level for this cycle
        "recommended_batch_size",  # Phase 10: optional batch-size hint from CSE
    )

    def __init__(
        self,
        action: str,
        mode: str,
        goal: str,
        reason: str,
        risk_budget: float,
        recommended_batch_size: Optional[int] = None,
    ) -> None:
        self.action = action
        self.mode = mode
        self.goal = goal
        self.reason = reason
        self.risk_budget = risk_budget
        self.recommended_batch_size = recommended_batch_size

    def should_proceed(self) -> bool:
        return self.action == "proceed"

    def is_exploring(self) -> bool:
        return self.mode == "explore"

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "action": self.action,
            "mode": self.mode,
            "goal": self.goal,
            "reason": self.reason,
            "risk_budget": self.risk_budget,
        }
        if self.recommended_batch_size is not None:
            d["recommended_batch_size"] = self.recommended_batch_size
        return d

    def __repr__(self) -> str:
        return (
            f"StrategicDecision(action={self.action!r}, mode={self.mode!r}, "
            f"goal={self.goal!r})"
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def decide(
    best_net_score: float,
    system_safe: bool = True,
    pass_rate: Optional[float] = None,
    rng_seed: Optional[int] = None,
    reality_snapshot: Optional[Dict[str, Any]] = None,
) -> "StrategicDecision":
    """Produce a StrategicDecision for the current evolution cycle.

    Parameters
    ----------
    best_net_score    : the highest net_score available from the impact scorer
    system_safe       : False when anomaly_detector says system is degraded
    pass_rate         : latest CI pass rate (0.0–1.0); used for goal derivation
    rng_seed          : optional seed for deterministic testing
    reality_snapshot  : Phase 8 — RealitySnapshot from reality_bridge; when
                        provided the objective_engine score is used to gate and
                        the goal_adaptation_engine may update the primary goal.

    Returns a StrategicDecision with action, mode, goal, and risk_budget.
    """
    state = _load_state()
    state["cycle_count"] = state.get("cycle_count", 0) + 1

    # Record pass rate for goal derivation
    if pass_rate is not None:
        history: List[float] = state.get("pass_rate_history", [])
        history.append(float(pass_rate))
        state["pass_rate_history"] = history

    # Phase 8: let goal_adaptation_engine override the goal if we have a snapshot
    if reality_snapshot is not None:
        goal = goal_adaptation_engine.evaluate(reality_snapshot)
        # Map goal_adaptation goal names to internal strategic goal constants
        _goal_map = {
            "stability": GOAL_MAXIMIZE_STABILITY,
            "learning": GOAL_IMPROVE_LEARNING,
            "profitability": GOAL_IMPROVE_LEARNING,  # treated as improve_learning internally
        }
        goal = _goal_map.get(goal, goal)
    else:
        goal = _derive_goal(state.get("pass_rate_history", []))
    state["current_goal"] = goal

    # -----------------------------------------------------------------------
    # Check 1: System safety
    # -----------------------------------------------------------------------
    if not system_safe:
        state["do_nothing_streak"] = state.get("do_nothing_streak", 0) + 1
        _save_state(state)
        return StrategicDecision(
            action="do_nothing",
            mode="exploit",
            goal=goal,
            reason="anomaly_detector reports system is not safe — pausing evolution",
            risk_budget=0.0,
        )

    # -----------------------------------------------------------------------
    # Check 2: Minimum gain threshold (Phase 7 + Phase 8 objective gate)
    # -----------------------------------------------------------------------
    min_gain = MIN_GAIN_THRESHOLD
    gain_reason = f"best_net_score={best_net_score:.4f}"

    # Phase 8: if we have an objective score, use it as additional gate
    if reality_snapshot is not None:
        obj_score = objective_engine.score_outcome(reality_snapshot)
        gain_reason += f" | obj_score={obj_score:.4f}"
        # If objective score is very low, tighten the minimum gain requirement
        if obj_score < 0.40:
            min_gain = max(min_gain, 0.06)  # require stronger gain when system is struggling
        elif obj_score > 0.85:
            min_gain = min(min_gain, 0.01)  # relax gate when system is healthy

    if best_net_score < min_gain:
        state["do_nothing_streak"] = state.get("do_nothing_streak", 0) + 1
        _save_state(state)
        return StrategicDecision(
            action="do_nothing",
            mode="exploit",
            goal=goal,
            reason=(
                f"{gain_reason} < min_gain={min_gain:.4f} — nothing worth fixing"
            ),
            risk_budget=0.0,
        )

    # Reset do-nothing streak
    state["do_nothing_streak"] = 0

    # -----------------------------------------------------------------------
    # Check 3: Exploration vs exploitation
    # -----------------------------------------------------------------------
    rng = random.Random(rng_seed)   # isolated RNG; None seeds from system time (non-deterministic)
    exploring = rng.random() < EXPLORATION_RATE

    history_list: List[bool] = state.get("exploration_history", [])
    history_list.append(not exploring)   # True = exploited
    state["exploration_history"] = history_list

    # Risk budget depends on goal and mode
    if goal == GOAL_MAXIMIZE_STABILITY:
        # Stability focus → very low risk budget regardless of mode
        risk_budget = 0.10
    elif goal == GOAL_MINIMIZE_REGRESSION:
        risk_budget = 0.15 if not exploring else 0.20
    else:
        # Learning focus → more relaxed
        risk_budget = 0.25 if not exploring else 0.40

    mode = "explore" if exploring else "exploit"

    # Phase 9: apply stability controller — mode locking + hysteresis + penalty
    # Phase 9.5: pass signal_conf + intent_score for contextual mode memory
    avg_confidence: float = 1.0
    signal_conf: float = 1.0
    intent_score: float = 1.0
    if reality_snapshot is not None:
        avg_confidence = float(reality_snapshot.get("avg_confidence", 1.0))
        signal_conf = avg_confidence  # avg_confidence is the primary signal reliability measure
    try:
        from nibblebots import intent_anchor_engine as _iae  # noqa: PLC0415
        intent_score = float(_iae.get_rolling_score())
    except Exception:  # noqa: BLE001
        pass
    try:
        from nibblebots import stability_controller as _sc  # noqa: PLC0415
        _momentum = _sc.get_momentum(best_net_score)
        mode = _sc.resolve_mode(
            mode,
            confidence=avg_confidence,
            momentum=_momentum,
            signal_conf=signal_conf,
            intent_score=intent_score,
        )
    except Exception:  # noqa: BLE001
        pass

    # Phase 10: Causal Strategy Engine — context-aware parameter adjustments.
    # Query after resolve_mode so the CSE sees the controller-resolved mode.
    _cse_batch_size: Optional[int] = None
    try:
        from nibblebots import causal_strategy_engine as _cse  # noqa: PLC0415
        _advice = _cse.query_strategy({
            "confidence": avg_confidence,
            "signal_conf": signal_conf,
            "variance": 0.0,
            "mode": mode,
        })
        if _advice.confidence > 0.6:
            _eff_rate = max(0.05, EXPLORATION_RATE + _advice.exploration_rate_delta)
            _cse_exploring = random.random() < _eff_rate  # noqa: S311
            if _cse_exploring != exploring:
                exploring = _cse_exploring
                mode = "explore" if exploring else "exploit"
            _cse_batch_size = _advice.recommended_batch_size
    except Exception:  # noqa: BLE001
        pass

    reason_parts = [
        f"goal={goal}",
        f"best_net_score={best_net_score:.4f}",
        f"mode={mode}",
        f"risk_budget={risk_budget:.2f}",
    ]
    if exploring:
        reason_parts.append("(epsilon-greedy exploration triggered)")
    if reality_snapshot is not None:
        reason_parts.append(
            f"obj_score={objective_engine.score_outcome(reality_snapshot):.4f}"
        )
    if _cse_batch_size is not None:
        reason_parts.append(f"cse_batch={_cse_batch_size}")

    _save_state(state)

    return StrategicDecision(
        action="proceed",
        mode=mode,
        goal=goal,
        reason=" | ".join(reason_parts),
        risk_budget=risk_budget,
        recommended_batch_size=_cse_batch_size,
    )


def record_pass_rate(pass_rate: float) -> None:
    """Record a CI pass rate observation without making a strategic decision.

    Use this when the evolution cycle did not run (do_nothing) but a CI result
    is still available, so the goal-derivation history stays current.
    """
    state = _load_state()
    history: List[float] = state.get("pass_rate_history", [])
    history.append(float(pass_rate))
    state["pass_rate_history"] = history
    state["current_goal"] = _derive_goal(history)
    _save_state(state)


def current_goal() -> str:
    """Return the current system-level goal (no side effects)."""
    return _load_state().get("current_goal", GOAL_IMPROVE_LEARNING)


def exploration_stats() -> Dict[str, Any]:
    """Return exploration/exploitation statistics for inspection."""
    state = _load_state()
    history: List[bool] = state.get("exploration_history", [])
    if not history:
        return {"exploit_rate": 1.0, "explore_rate": 0.0, "total_cycles": 0}
    exploits = sum(1 for h in history if h)
    return {
        "exploit_rate": round(exploits / len(history), 3),
        "explore_rate": round(1.0 - exploits / len(history), 3),
        "total_cycles": len(history),
        "do_nothing_streak": state.get("do_nothing_streak", 0),
        "current_goal": state.get("current_goal", GOAL_IMPROVE_LEARNING),
    }
