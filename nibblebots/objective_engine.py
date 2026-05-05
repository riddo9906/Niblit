#!/usr/bin/env python3
"""
nibblebots/objective_engine.py — Phase 8 Objective Engine

Defines what "success" actually means for the evolution system.

This is the **top-authority layer** above strategic_planner.  While the
strategic planner answers *how* to act, the objective engine answers *why* to
act — it grounds every improvement decision in the system's real-world goals.

Architecture
------------
The engine holds an ``ObjectiveProfile`` that specifies:

* ``primary_goal``  — the single most important objective right now
  (``"stability"``, ``"profitability"``, ``"learning"``)
* ``constraints``   — hard limits that must never be violated
* ``weights``       — how much each signal dimension contributes to the
  composite objective score (0.0–1.0, must sum to ≤ 1.0)

``score_outcome(snapshot)`` maps a ``RealitySnapshot`` to a single float
in [0, 1] called the **objective score**.  This score is used by:

1. ``strategic_planner.decide()`` — to determine mode (stabilize vs optimize)
2. ``impact_engine`` — to blend real-world value into net_score
3. ``evolution_planner`` — to gate fixes whose value delta is too small

State persistence
-----------------
Profile is stored in ``objective_state.json`` next to this file.

Constants (overridable via env vars)
-------------------------------------
OBJ_CI_WEIGHT         : float  (env: OBJ_CI_WEIGHT, default 0.30)
OBJ_RUNTIME_WEIGHT    : float  (env: OBJ_RUNTIME_WEIGHT, default 0.30)
OBJ_REALWORLD_WEIGHT  : float  (env: OBJ_REALWORLD_WEIGHT, default 0.40)
OBJ_MIN_PASS_RATE     : float  (env: OBJ_MIN_PASS_RATE, default 0.90)
OBJ_MAX_DRAWDOWN      : float  (env: OBJ_MAX_DRAWDOWN, default 0.15)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OBJ_CI_WEIGHT: float = float(os.environ.get("OBJ_CI_WEIGHT", "0.30"))
OBJ_RUNTIME_WEIGHT: float = float(os.environ.get("OBJ_RUNTIME_WEIGHT", "0.30"))
OBJ_REALWORLD_WEIGHT: float = float(os.environ.get("OBJ_REALWORLD_WEIGHT", "0.40"))
OBJ_MIN_PASS_RATE: float = float(os.environ.get("OBJ_MIN_PASS_RATE", "0.90"))
OBJ_MAX_DRAWDOWN: float = float(os.environ.get("OBJ_MAX_DRAWDOWN", "0.15"))

_VALID_GOALS = frozenset({"stability", "profitability", "learning"})
_STATE_FILE = Path(__file__).parent / "objective_state.json"


# ---------------------------------------------------------------------------
# ObjectiveProfile
# ---------------------------------------------------------------------------

class ObjectiveProfile:
    """Mutable profile that defines the system's current success criteria.

    Fields
    ------
    primary_goal    : "stability" | "profitability" | "learning"
    constraints     : hard limits dict (min_pass_rate, max_drawdown)
    weights         : dimension weights dict (ci_stability, runtime_quality,
                      real_world_outcome)
    """

    __slots__ = ("primary_goal", "constraints", "weights")

    def __init__(
        self,
        primary_goal: str = "stability",
        constraints: Optional[Dict[str, float]] = None,
        weights: Optional[Dict[str, float]] = None,
    ) -> None:
        if primary_goal not in _VALID_GOALS:
            primary_goal = "stability"
        self.primary_goal = primary_goal
        self.constraints = constraints or {
            "min_pass_rate": OBJ_MIN_PASS_RATE,
            "max_drawdown": OBJ_MAX_DRAWDOWN,
        }
        self.weights = weights or {
            "ci_stability": OBJ_CI_WEIGHT,
            "runtime_quality": OBJ_RUNTIME_WEIGHT,
            "real_world_outcome": OBJ_REALWORLD_WEIGHT,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "primary_goal": self.primary_goal,
            "constraints": self.constraints,
            "weights": self.weights,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ObjectiveProfile":
        return cls(
            primary_goal=d.get("primary_goal", "stability"),
            constraints=d.get("constraints"),
            weights=d.get("weights"),
        )


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def _load_profile() -> ObjectiveProfile:
    if _STATE_FILE.exists():
        try:
            return ObjectiveProfile.from_dict(
                json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            )
        except (OSError, json.JSONDecodeError, KeyError):
            pass
    return ObjectiveProfile()


def _save_profile(profile: ObjectiveProfile) -> None:
    try:
        _STATE_FILE.write_text(
            json.dumps(profile.to_dict(), indent=2), encoding="utf-8"
        )
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_outcome(snapshot: Dict[str, Any]) -> float:
    """Compute a composite objective score [0, 1] from a RealitySnapshot dict.

    Parameters
    ----------
    snapshot : dict with optional keys:
        pass_rate       : float 0–1  (CI test pass rate)
        runtime_score   : float 0–1  (derived from latency + error rate)
        real_world_score: float 0–1  (profit_delta normalised, win_rate, etc.)
        drawdown        : float 0–1  (portfolio drawdown; low is good)

    Returns
    -------
    float : weighted composite score in [0, 1].
        1.0 = everything is perfect
        0.0 = everything is broken
    """
    profile = _load_profile()

    # Constraint violation check — hard floor
    pass_rate = snapshot.get("pass_rate", 1.0)
    drawdown = snapshot.get("drawdown", 0.0)
    if pass_rate < profile.constraints.get("min_pass_rate", OBJ_MIN_PASS_RATE):
        # Below minimum pass rate → penalise heavily
        pass_rate *= 0.5
    if drawdown > profile.constraints.get("max_drawdown", OBJ_MAX_DRAWDOWN):
        drawdown_penalty = (drawdown - OBJ_MAX_DRAWDOWN) / max(OBJ_MAX_DRAWDOWN, 1e-9)
        pass_rate = max(0.0, pass_rate - min(0.3, drawdown_penalty * 0.3))

    ci_score = float(pass_rate)
    runtime_score = float(snapshot.get("runtime_score", 0.5))
    real_world_score = float(snapshot.get("real_world_score", 0.5))

    w = profile.weights
    composite = (
        ci_score * w.get("ci_stability", OBJ_CI_WEIGHT)
        + runtime_score * w.get("runtime_quality", OBJ_RUNTIME_WEIGHT)
        + real_world_score * w.get("real_world_outcome", OBJ_REALWORLD_WEIGHT)
    )

    # Normalise to [0, 1] — total weight may not sum to exactly 1.0
    total_weight = sum(w.values()) or 1.0
    return round(min(1.0, max(0.0, composite / total_weight)), 4)


def score_delta(before: Dict[str, Any], after: Dict[str, Any]) -> float:
    """Compute the change in objective score between two snapshots.

    Returns a value in [-1, 1]; positive means improvement.
    """
    return round(score_outcome(after) - score_outcome(before), 4)


# ---------------------------------------------------------------------------
# Goal management
# ---------------------------------------------------------------------------

def update_goal(new_goal: str) -> None:
    """Change the primary_goal and persist the updated profile."""
    if new_goal not in _VALID_GOALS:
        return
    profile = _load_profile()
    profile.primary_goal = new_goal
    _save_profile(profile)


def get_active_weights() -> Dict[str, float]:
    """Return the current weight dict (copy)."""
    return dict(_load_profile().weights)


def get_primary_goal() -> str:
    """Return the current primary goal string."""
    return _load_profile().primary_goal


def update_weights(new_weights: Dict[str, float]) -> None:
    """Replace weight dict and persist."""
    profile = _load_profile()
    profile.weights = {k: float(v) for k, v in new_weights.items()}
    _save_profile(profile)


def update_constraints(new_constraints: Dict[str, float]) -> None:
    """Replace constraints and persist."""
    profile = _load_profile()
    profile.constraints = {k: float(v) for k, v in new_constraints.items()}
    _save_profile(profile)


def current_profile() -> Dict[str, Any]:
    """Return the full profile as a plain dict (no side effects)."""
    return _load_profile().to_dict()
