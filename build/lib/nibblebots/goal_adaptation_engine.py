#!/usr/bin/env python3
"""
nibblebots/goal_adaptation_engine.py — Phase 8 Goal Adaptation Engine

Automatically adjusts the ObjectiveProfile primary_goal based on current
system state and trend signals from the RealityBridge.

This closes the Phase 8 adaptation loop:

    RealityBridge → GoalAdaptationEngine → ObjectiveEngine.update_goal()
                                              ↓
                                       StrategicPlanner uses new goal
                                              ↓
                                       EvolutionPlanner selects fixes

Adaptation rules
----------------
The engine evaluates three dimensions:

1. **CI stability** (pass_rate + ci_failure_trend)
   If currently unstable → force goal = "stability"

2. **Trading health** (win_rate, drawdown, real_world_score)
   If stable CI and good trading → switch to "profitability"

3. **Learning velocity** (from system_health_monitor)
   If everything stable but learning is slow → switch to "learning"

The engine also publishes its reasoning to a log file so the system has an
audit trail of why it changed goals.

Hysteresis
----------
Goal changes are subject to hysteresis: a condition must be true for
``HYSTERESIS_WINDOW`` consecutive evaluations before the goal switches.
This prevents thrashing.

Constants (overridable via env vars)
-------------------------------------
GOAL_STABILITY_THRESHOLD   : float  (env: GOAL_STABILITY_THRESHOLD, default 0.80)
                             pass_rate below this → force "stability" mode
GOAL_PROFIT_THRESHOLD      : float  (env: GOAL_PROFIT_THRESHOLD, default 0.90)
                             pass_rate above this AND real_world_score > 0.55
                             → switch to "profitability"
GOAL_LEARN_THRESHOLD       : float  (env: GOAL_LEARN_THRESHOLD, default 0.92)
                             pass_rate above this AND real_world stable
                             → switch to "learning"
HYSTERESIS_WINDOW          : int    (env: GOAL_HYSTERESIS, default 3)
                             Number of consecutive matching evaluations before
                             goal switches.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from nibblebots import objective_engine

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GOAL_STABILITY_THRESHOLD: float = float(
    os.environ.get("GOAL_STABILITY_THRESHOLD", "0.80")
)
GOAL_PROFIT_THRESHOLD: float = float(
    os.environ.get("GOAL_PROFIT_THRESHOLD", "0.90")
)
GOAL_LEARN_THRESHOLD: float = float(
    os.environ.get("GOAL_LEARN_THRESHOLD", "0.92")
)
HYSTERESIS_WINDOW: int = int(os.environ.get("GOAL_HYSTERESIS", "3"))

_STATE_FILE = Path(__file__).parent / "goal_adaptation_state.json"
_LOG_FILE = Path(__file__).parent / "goal_adaptation_log.jsonl"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def _load_state() -> Dict[str, Any]:
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"pending_goal": None, "pending_count": 0, "current_goal": "stability",
            "last_goal": None, "cycles_in_goal": 0}


def _save_state(state: Dict[str, Any]) -> None:
    try:
        _STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        pass


def _log_change(
    old_goal: str,
    new_goal: str,
    reason: str,
    snapshot: Dict[str, Any],
) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "old_goal": old_goal,
        "new_goal": new_goal,
        "reason": reason,
        "snapshot_summary": {
            k: snapshot.get(k)
            for k in ("pass_rate", "ci_failure_trend", "win_rate",
                       "real_world_score", "runtime_score", "drawdown")
        },
    }
    try:
        with _LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Core adaptation logic
# ---------------------------------------------------------------------------

def _derive_desired_goal(snapshot: Dict[str, Any]) -> tuple[str, str]:
    """Compute the goal the system *should* have given this snapshot.

    Returns (goal, reason).

    Phase 8.5 guard
    ---------------
    When the snapshot carries ``avg_confidence < SIE_MIN_CONFIDENCE_GATE``
    (populated by signal_integrity_engine via reality_bridge), the signals
    are too noisy to drive goal changes.  We force ``"stability"`` to avoid
    optimising toward an unreliable picture of reality.
    """
    # Phase 8.5: if signal integrity is low, default to stability
    avg_confidence = snapshot.get("avg_confidence")
    if avg_confidence is not None:
        try:
            from nibblebots.signal_integrity_engine import SIE_MIN_CONFIDENCE_GATE  # noqa: PLC0415
            gate = SIE_MIN_CONFIDENCE_GATE
        except Exception:  # noqa: BLE001
            gate = 0.50
        if float(avg_confidence) < gate:
            return (
                "stability",
                f"avg_confidence={float(avg_confidence):.3f} < {gate} "
                "(signal integrity too low for goal adaptation)",
            )

    pass_rate = float(snapshot.get("pass_rate", 0.8))
    trend = float(snapshot.get("ci_failure_trend", 0.0))
    real_world_score = float(snapshot.get("real_world_score", 0.5))
    win_rate = snapshot.get("win_rate")
    drawdown = float(snapshot.get("drawdown", 0.0))
    runtime_score = float(snapshot.get("runtime_score", 0.7))

    # Rule 1: system is unstable → must stabilise first
    if pass_rate < GOAL_STABILITY_THRESHOLD:
        return "stability", f"pass_rate={pass_rate:.2f} < threshold={GOAL_STABILITY_THRESHOLD}"

    if trend < -0.10:   # rapidly declining pass rate
        return "stability", f"ci_failure_trend={trend:+.3f} (rapid decline)"

    if runtime_score < 0.50:
        return "stability", f"runtime_score={runtime_score:.2f} < 0.50"

    # Rule 2: CI is solid and trading is healthy → push for profitability
    if pass_rate >= GOAL_PROFIT_THRESHOLD:
        trading_healthy = (
            real_world_score > 0.55
            and drawdown < 0.10
            and (win_rate is None or win_rate > 0.45)
        )
        if trading_healthy:
            return (
                "profitability",
                f"pass_rate={pass_rate:.2f}, real_world={real_world_score:.2f}, "
                f"drawdown={drawdown:.2f}",
            )

    # Rule 3: everything stable, push for learning velocity
    if pass_rate >= GOAL_LEARN_THRESHOLD and real_world_score >= 0.50:
        return (
            "learning",
            f"pass_rate={pass_rate:.2f}, stable enough to prioritise learning",
        )

    # Default: maintain stability
    return "stability", f"no strong signal for goal change (pass_rate={pass_rate:.2f})"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate(snapshot: Dict[str, Any]) -> str:
    """Evaluate current reality and potentially update the objective goal.

    Uses hysteresis: the desired goal must appear ``HYSTERESIS_WINDOW`` times
    in a row before the actual goal switches.

    Parameters
    ----------
    snapshot : RealitySnapshot dict from reality_bridge.pull_snapshot()

    Returns
    -------
    str : the current goal (may be unchanged)
    """
    desired_goal, reason = _derive_desired_goal(snapshot)
    state = _load_state()
    current_goal = state.get("current_goal", "stability")

    if desired_goal == current_goal:
        # Goal confirmed — reset hysteresis counter
        state["pending_goal"] = None
        state["pending_count"] = 0
        # Track cycles in current goal (for stability_controller awareness)
        state["cycles_in_goal"] = state.get("cycles_in_goal", 0) + 1
    elif desired_goal == state.get("pending_goal"):
        # Same pending goal as before — increment counter
        state["pending_count"] = state.get("pending_count", 0) + 1
        if state["pending_count"] >= HYSTERESIS_WINDOW:
            # Commit the goal change
            _log_change(current_goal, desired_goal, reason, snapshot)
            print(
                f"  🎯 GoalAdaptation: {current_goal!r} → {desired_goal!r}  "
                f"({reason})"
            )
            objective_engine.update_goal(desired_goal)
            state["last_goal"] = current_goal
            state["current_goal"] = desired_goal
            state["pending_goal"] = None
            state["pending_count"] = 0
            state["cycles_in_goal"] = 1
    else:
        # New pending goal, start counting
        state["pending_goal"] = desired_goal
        state["pending_count"] = 1
        state["cycles_in_goal"] = state.get("cycles_in_goal", 0) + 1

    _save_state(state)
    return state["current_goal"]


def get_current_goal() -> str:
    """Return the current adapted goal without triggering a re-evaluation."""
    return _load_state().get("current_goal", "stability")


def get_cycles_in_goal() -> int:
    """Return the number of consecutive cycles the current goal has been active."""
    return int(_load_state().get("cycles_in_goal", 0))


def get_last_goal() -> Optional[str]:
    """Return the goal that preceded the current one (None if unchanged since init)."""
    return _load_state().get("last_goal")


def get_adaptation_log(last_n: int = 20) -> List[Dict[str, Any]]:
    """Return the most recent goal adaptation events."""
    if not _LOG_FILE.exists():
        return []
    try:
        lines = [
            json.loads(ln)
            for ln in _LOG_FILE.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        return lines[-last_n:]
    except (OSError, json.JSONDecodeError):
        return []


def force_goal(goal: str, reason: str = "manual override") -> None:
    """Force a goal immediately, bypassing hysteresis.  Use in emergencies."""
    state = _load_state()
    old = state.get("current_goal", "stability")
    state["current_goal"] = goal
    state["pending_goal"] = None
    state["pending_count"] = 0
    _save_state(state)
    objective_engine.update_goal(goal)
    _log_change(old, goal, reason, {})
    print(f"  🎯 GoalAdaptation (forced): {old!r} → {goal!r}  ({reason})")


if __name__ == "__main__":
    print('Running goal_adaptation_engine.py')
