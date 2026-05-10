#!/usr/bin/env python3
"""
modules/deliberative_planner.py — Phase 21 Deliberative Planning Layer

Enables Niblit to simulate 3–5 step future paths, estimate cumulative
risk, compare strategic branches, and choose the **lowest-regret path**.

This fills the long-horizon planning gap: existing modules handle
per-cycle decisions but cannot reason about multi-step consequence chains.

Algorithm
---------
1. **Generate branches** — expand *N* candidate action sequences from
   the current state using a configurable branching factor.
2. **Score each branch** — estimate cumulative expected value via a
   simple forward simulation using the self_model and TFT forecast.
3. **Regret minimisation** — select the branch with the highest
   ``expected_value − risk_penalty`` score.
4. **Return a** :class:`PlanBranch` — the chosen path with its full step
   sequence and risk assessment.

Output
------
:class:`PlanBranch`::

    steps          : list[str]     — ordered action labels
    expected_value : float 0.0–1.0 — estimated total return
    risk_estimate  : float 0.0–1.0 — cumulative risk
    regret_score   : float         — expected_value − risk_estimate
    chosen         : bool          — True for the selected branch

Configuration (env vars)
------------------------
    NIBLIT_DP_ENABLED         — "0" to disable (default 1)
    NIBLIT_DP_HORIZON         — max steps per branch (default 4)
    NIBLIT_DP_BRANCHES        — number of candidate branches (default 5)
    NIBLIT_DP_RISK_WEIGHT     — risk penalty weight in scoring (default 0.5)

Usage::

    from modules.deliberative_planner import get_deliberative_planner

    planner = get_deliberative_planner()
    plan = planner.plan(context={"intent": "trading", "forecast": "bullish"})
    print(plan.steps)
    print(plan.regret_score)
"""

from __future__ import annotations

import logging
import math
import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_ENABLED: bool = os.getenv("NIBLIT_DP_ENABLED", "1").strip() not in ("0", "false")
_HORIZON: int = int(os.getenv("NIBLIT_DP_HORIZON", "4"))
_BRANCHES: int = int(os.getenv("NIBLIT_DP_BRANCHES", "5"))
_RISK_WEIGHT: float = float(os.getenv("NIBLIT_DP_RISK_WEIGHT", "0.5"))

# ── Action palette (abstract action labels used in plan steps) ────────────────
_ACTION_POOL = [
    "retrieve_memory",
    "run_forecast",
    "call_tool",
    "validate_risk",
    "generate_response",
    "defer_to_user",
    "update_self_model",
    "compress_memory",
    "escalate_governance",
    "explore_alternative",
]

# Value and risk estimates per action (static priors; updated at runtime)
_ACTION_PRIORS: Dict[str, Dict[str, float]] = {
    "retrieve_memory":      {"value": 0.7, "risk": 0.05},
    "run_forecast":         {"value": 0.6, "risk": 0.15},
    "call_tool":            {"value": 0.75, "risk": 0.25},
    "validate_risk":        {"value": 0.5,  "risk": 0.02},
    "generate_response":    {"value": 0.8,  "risk": 0.05},
    "defer_to_user":        {"value": 0.4,  "risk": 0.01},
    "update_self_model":    {"value": 0.55, "risk": 0.03},
    "compress_memory":      {"value": 0.5,  "risk": 0.10},
    "escalate_governance":  {"value": 0.3,  "risk": 0.02},
    "explore_alternative":  {"value": 0.6,  "risk": 0.20},
}


# ── PlanBranch ────────────────────────────────────────────────────────────────

@dataclass
class PlanBranch:
    """A candidate multi-step execution plan."""
    steps: List[str]
    expected_value: float
    risk_estimate: float
    regret_score: float
    chosen: bool = False

    def to_dict(self) -> Dict:
        return {
            "steps": list(self.steps),
            "expected_value": round(self.expected_value, 4),
            "risk_estimate": round(self.risk_estimate, 4),
            "regret_score": round(self.regret_score, 4),
            "chosen": self.chosen,
        }


# ── DeliberativePlanner ───────────────────────────────────────────────────────

class DeliberativePlanner:
    """Multi-step forward simulation planner with regret minimisation.

    Thread-safe.  Each ``plan()`` call is stateless — results depend only
    on the supplied context and the current self_model state.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._plan_count: int = 0
        self._total_steps_simulated: int = 0
        log.debug("[DeliberativePlanner] initialised")

    # ── Public API ────────────────────────────────────────────────────────────

    def plan(
        self,
        context: Optional[Dict[str, Any]] = None,
        horizon: int = _HORIZON,
        n_branches: int = _BRANCHES,
    ) -> PlanBranch:
        """Generate candidate plans and return the lowest-regret branch.

        Args:
            context:    Current execution context (intent, forecast, etc.).
            horizon:    Number of steps per branch.
            n_branches: Number of candidate branches to evaluate.

        Returns:
            The chosen :class:`PlanBranch` (``chosen=True``).
        """
        if not _ENABLED:
            return self._trivial_plan()

        try:
            ctx = dict(context or {})
            branches = [
                self._simulate_branch(ctx, horizon)
                for _ in range(n_branches)
            ]
            best = max(branches, key=lambda b: b.regret_score)
            best.chosen = True

            with self._lock:
                self._plan_count += 1
                self._total_steps_simulated += sum(len(b.steps) for b in branches)

            log.debug(
                "[DeliberativePlanner] plan complete: chosen=%s EV=%.3f risk=%.3f",
                best.steps, best.expected_value, best.risk_estimate,
            )
            return best
        except Exception as exc:
            log.warning("[DeliberativePlanner] plan error: %s", exc)
            return self._trivial_plan()

    def plan_all(
        self,
        context: Optional[Dict[str, Any]] = None,
        horizon: int = _HORIZON,
        n_branches: int = _BRANCHES,
    ) -> List[PlanBranch]:
        """Return all candidate branches (sorted by regret score, descending)."""
        if not _ENABLED:
            return [self._trivial_plan()]
        try:
            ctx = dict(context or {})
            branches = [self._simulate_branch(ctx, horizon) for _ in range(n_branches)]
            branches.sort(key=lambda b: b.regret_score, reverse=True)
            if branches:
                branches[0].chosen = True
            return branches
        except Exception as exc:
            log.warning("[DeliberativePlanner] plan_all error: %s", exc)
            return [self._trivial_plan()]

    # ── Branch simulation ─────────────────────────────────────────────────────

    def _simulate_branch(self, ctx: Dict, horizon: int) -> PlanBranch:
        """Sample a random action sequence and score it."""
        # Bias action selection based on context
        action_pool = self._context_biased_pool(ctx)
        steps = random.sample(action_pool, min(horizon, len(action_pool)))

        # Fetch self-model state for score adjustment
        reasoning_quality = 0.7
        tool_reliability = 0.8
        try:
            from modules.self_model import get_self_model
            state = get_self_model().snapshot()
            reasoning_quality = state.reasoning_quality
            tool_reliability = state.tool_reliability
        except Exception:
            pass

        # Accumulate expected value and risk across steps
        cumulative_value = 0.0
        cumulative_risk = 0.0
        discount = 1.0
        gamma = 0.9  # temporal discount factor

        for step in steps:
            priors = _ACTION_PRIORS.get(step, {"value": 0.5, "risk": 0.1})
            step_value = priors["value"]
            step_risk  = priors["risk"]

            # Adjust by self-model quality scores
            if step == "call_tool":
                step_value *= tool_reliability
            elif step in ("retrieve_memory", "generate_response", "update_self_model"):
                step_value *= reasoning_quality

            cumulative_value += discount * step_value
            cumulative_risk  += discount * step_risk
            discount *= gamma

        # Normalise to [0, 1]
        max_v = sum(gamma**i for i in range(len(steps)))
        if max_v > 0:
            cumulative_value /= max_v
            cumulative_risk /= max_v

        regret = cumulative_value - _RISK_WEIGHT * cumulative_risk

        return PlanBranch(
            steps=steps,
            expected_value=round(min(1.0, max(0.0, cumulative_value)), 4),
            risk_estimate=round(min(1.0, max(0.0, cumulative_risk)), 4),
            regret_score=round(regret, 4),
        )

    def _context_biased_pool(self, ctx: Dict) -> List[str]:
        """Return an action pool biased by context intent/mode."""
        pool = list(_ACTION_POOL)
        intent = ctx.get("intent", "") or ""
        forecast = ctx.get("forecast_signal", "") or ctx.get("forecast", "") or ""

        # Prioritise forecast-related actions for forecasting intent
        if intent in ("forecasting", "trading"):
            pool = ["run_forecast", "validate_risk", "call_tool"] + pool

        # Deprioritise heavy actions when context is conversational
        if intent == "conversational":
            pool = [a for a in pool if a not in ("run_forecast", "compress_memory")]

        # If forecast is bullish/bearish, add tool calls
        if forecast in ("bullish", "BUY", "bearish", "SELL"):
            if "call_tool" not in pool[:3]:
                pool.insert(0, "call_tool")

        # Deduplicate while preserving order
        seen = set()
        return [a for a in pool if not (a in seen or seen.add(a))]  # type: ignore[func-returns-value]

    def _trivial_plan(self) -> PlanBranch:
        return PlanBranch(
            steps=["retrieve_memory", "generate_response"],
            expected_value=0.5,
            risk_estimate=0.1,
            regret_score=0.45,
            chosen=True,
        )

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> Dict:
        with self._lock:
            return {
                "enabled": _ENABLED,
                "plan_count": self._plan_count,
                "total_steps_simulated": self._total_steps_simulated,
                "horizon": _HORIZON,
                "branches": _BRANCHES,
                "risk_weight": _RISK_WEIGHT,
            }


# ── Singleton ─────────────────────────────────────────────────────────────────
_planner: Optional[DeliberativePlanner] = None
_planner_lock = threading.Lock()


def get_deliberative_planner() -> DeliberativePlanner:
    """Return the module-level :class:`DeliberativePlanner` singleton."""
    global _planner
    with _planner_lock:
        if _planner is None:
            _planner = DeliberativePlanner()
    return _planner
