#!/usr/bin/env python3
"""
nibblebots/impact_engine.py — Phase 3/4 Impact Scoring Engine

Estimates *what will improve* if a given SemanticIssue is fixed, before any
change is made.  This is the core intelligence upgrade from Phase 2 — moving
from "apply everything that matches" to "apply what matters most".

Phase 4 upgrade: Regression prediction model
---------------------------------------------
After ≥ ``REGRESSION_MIN_SAMPLES`` outcome journal entries are available, the
engine fits a lightweight Ordinary Least Squares regression:

    predicted_outcome_delta = β₀ + β₁ * net_score

Coefficients are stored in ``impact_regression.json`` alongside the weights
file.  On the next run the engine loads them and adjusts ``net_score`` using:

    adjusted_net_score = net_score * (1 + β₁ * clamp(net_score, 0, 1))

This makes the engine *predict* likely improvement rather than just estimate
it from static priors.  Falls back silently to rule-based scoring when
insufficient history exists.

ImpactScore fields
------------------
expected_gain   : 0.0–1.0  weighted sum of positive impact dimensions
risk_level      : 0.0–1.0  weighted sum of risk dimensions
net_score       : expected_gain * confidence - risk_level  (decision metric)
confidence      : inherited from the SemanticIssue
dimensions      : dict of individual impact dimension scores (debuggability, …)

Weight learning
---------------
Weights start from a built-in prior (_BASE_WEIGHTS).  After each commit the
FeedbackLearner updates a JSON file (impact_weights.json, next to this script)
with observed outcomes.  On the next run the engine loads those weights so it
gradually learns which fix types actually produce results.

To reset the learned weights, delete impact_weights.json.
To reset the regression model, delete impact_regression.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

from nibblebots.semantic_engine import SemanticIssue


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_WEIGHTS_FILE = Path(__file__).parent / "impact_weights.json"
_REGRESSION_FILE = Path(__file__).parent / "impact_regression.json"

# Minimum outcome journal entries before fitting the regression model
REGRESSION_MIN_SAMPLES: int = int(
    os.environ.get("EVOLUTION_REGRESSION_MIN_SAMPLES", "20")
)

# ---------------------------------------------------------------------------
# ImpactScore data structure
# ---------------------------------------------------------------------------

class ImpactScore(NamedTuple):
    expected_gain: float
    risk_level: float
    net_score: float
    confidence: float
    dimensions: dict   # dimension_name → score


# ---------------------------------------------------------------------------
# Built-in weight priors
#
# Each fix type has a dict of (dimension → value).
# Positive values → gain dimensions (higher is better)
# Negative keys start with "risk_" → risk dimensions
# ---------------------------------------------------------------------------

_BASE_WEIGHTS: Dict[str, Dict[str, float]] = {
    "bare_except": {
        "debuggability":     0.70,
        "crash_visibility":  0.65,
        "system_stability":  0.30,
        "sdal_observability": 0.40,
        "risk_logic_change": 0.10,   # low risk — only the clause header changes
    },
    "bare_except_pass": {
        "debuggability":     0.50,
        "crash_visibility":  0.40,
        "auditability":      0.60,
        "risk_logic_change": 0.05,
    },
    "trailing_whitespace": {
        "diff_cleanliness":  0.50,
        "ci_compliance":     0.40,
        "risk_logic_change": 0.00,
    },
    "double_blank_lines": {
        "readability":       0.30,
        "ci_compliance":     0.25,
        "risk_logic_change": 0.00,
    },
    "eof_newline": {
        "posix_compliance":  0.40,
        "diff_cleanliness":  0.20,
        "risk_logic_change": 0.00,
    },
}

# Subsystem risk multiplier — fixes in high-stakes subsystems carry more risk
_SUBSYSTEM_RISK_MULT: dict = {
    "decision":  1.5,
    "meta":      1.4,
    "policy":    1.4,
    "trading":   1.6,
    "evaluation": 1.2,
    "learning":  1.1,
    "feedback":  1.1,
    "knowledge": 1.0,
    "agents":    0.9,
    "evolution": 0.7,
    "core":      1.0,
    "other":     0.8,
}

# Gain multiplier when a fix is in a high-priority subsystem
_SUBSYSTEM_GAIN_MULT: dict = {
    "decision":  1.4,
    "meta":      1.3,
    "trading":   1.5,
    "evaluation": 1.2,
    "learning":  1.1,
    "feedback":  1.1,
    "knowledge": 1.0,
    "core":      1.0,
    "agents":    0.9,
    "evolution": 0.8,
    "other":     0.7,
}


# ---------------------------------------------------------------------------
# Weight loading / saving
# ---------------------------------------------------------------------------

def _load_weights() -> Dict[str, Dict[str, float]]:
    """Load learned weights from disk, falling back to built-in priors."""
    if _WEIGHTS_FILE.exists():
        try:
            stored = json.loads(_WEIGHTS_FILE.read_text(encoding="utf-8"))
            # Merge stored weights over the priors so new fix types still work
            merged: Dict[str, Dict[str, float]] = {}
            for fix_type, base in _BASE_WEIGHTS.items():
                merged[fix_type] = dict(base)
                if fix_type in stored:
                    merged[fix_type].update(stored[fix_type])
            return merged
        except (json.JSONDecodeError, OSError):
            pass
    return {k: dict(v) for k, v in _BASE_WEIGHTS.items()}


def save_weights(weights: Dict[str, Dict[str, float]]) -> None:
    """Persist learned weights to disk so future runs benefit."""
    try:
        _WEIGHTS_FILE.write_text(
            json.dumps(weights, indent=2, sort_keys=True), encoding="utf-8"
        )
    except OSError as exc:
        import sys
        print(f"  ⚠ Could not save impact weights: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Core scoring function
# ---------------------------------------------------------------------------

def score(issue: SemanticIssue) -> ImpactScore:
    """Compute the ImpactScore for a SemanticIssue.

    The net_score is the primary decision metric:
        net_score = expected_gain * confidence - risk_level

    A fix is considered worth applying when:
        net_score > RISK_THRESHOLD   (see evolution_planner.py)
    """
    weights = _load_weights()
    dims = weights.get(issue.fix_type, {})

    gain_mult = _SUBSYSTEM_GAIN_MULT.get(issue.subsystem, 1.0)
    risk_mult = _SUBSYSTEM_RISK_MULT.get(issue.subsystem, 1.0)

    raw_gain = 0.0
    raw_risk = 0.0
    scored_dims: dict = {}

    for dim, val in dims.items():
        if dim.startswith("risk_"):
            adjusted = val * risk_mult
            raw_risk += adjusted
            scored_dims[dim] = round(adjusted, 3)
        else:
            adjusted = val * gain_mult
            raw_gain += adjusted
            scored_dims[dim] = round(adjusted, 3)

    # Normalise gain and risk to [0, 1]
    n_gain = len([d for d in dims if not d.startswith("risk_")])
    n_risk = len([d for d in dims if d.startswith("risk_")])
    expected_gain = (raw_gain / max(n_gain, 1)) if n_gain else 0.0
    risk_level = (raw_risk / max(n_risk, 1)) if n_risk else 0.0

    # Scale by instance count: more instances → slightly higher urgency
    urgency = min(1.0, 0.5 + 0.05 * issue.count)
    expected_gain = min(1.0, expected_gain * urgency)

    net_score = expected_gain * issue.confidence - risk_level

    return ImpactScore(
        expected_gain=round(expected_gain, 3),
        risk_level=round(risk_level, 3),
        net_score=round(net_score, 3),
        confidence=issue.confidence,
        dimensions=scored_dims,
    )


def score_batch(issues: List[SemanticIssue]) -> List[ImpactScore]:
    """Score a list of SemanticIssues."""
    return [score(issue) for issue in issues]


# ---------------------------------------------------------------------------
# Weight update (called by FeedbackLearner after a commit)
# ---------------------------------------------------------------------------

def update_weights(
    fix_type: str,
    outcome: dict,
    learning_rate: float = 0.10,
) -> None:
    """Adjust stored weights based on a real commit outcome.

    outcome keys (all optional):
        tests_passed       : bool   — did tests pass after this commit?
        error_count_change : int    — negative = errors reduced (good)
        ci_failure_change  : int    — negative = fewer CI failures (good)
        runtime_stable     : bool   — no new runtime errors observed?

    Phase 18.5 — causality-trust-modulated learning rate
    -----------------------------------------------------
    The raw ``learning_rate`` is scaled by a factor derived from the
    causality tracker's trust score for this fix type:

        effective_lr = learning_rate × (0.5 + 0.5 × causal_trust)

    This means:
    * **High causal trust** (track record of real-world improvement):
      effective_lr ≈ learning_rate × 1.0  → confident weight updates.
    * **Neutral / no data** (trust = 0.5):
      effective_lr ≈ learning_rate × 0.75 → moderate updates.
    * **Low causal trust** (inconsistent or negative outcomes):
      effective_lr ≈ learning_rate × 0.5  → cautious, dampened updates
      so that a noisy signal cannot rapidly corrupt learned priors.

    The update follows a simple rule-based adjustment:
        if outcome is positive → nudge gain weights up
        if outcome is negative → nudge risk weights up
    """
    weights = _load_weights()
    if fix_type not in weights:
        return

    tests_passed = outcome.get("tests_passed", None)
    error_delta = outcome.get("error_count_change", 0)
    ci_delta = outcome.get("ci_failure_change", 0)
    runtime_stable = outcome.get("runtime_stable", None)

    # Aggregate signal: +1 = positive, -1 = negative, 0 = neutral
    signal = 0
    n_signals = 0
    if tests_passed is not None:
        signal += 1 if tests_passed else -1
        n_signals += 1
    if error_delta != 0:
        signal += 1 if error_delta < 0 else -1
        n_signals += 1
    if ci_delta != 0:
        signal += 1 if ci_delta < 0 else -1
        n_signals += 1
    if runtime_stable is not None:
        signal += 1 if runtime_stable else -1
        n_signals += 1

    if n_signals == 0:
        return

    direction = signal / n_signals   # -1.0 → 1.0

    # Phase 18.5: modulate learning rate by causality trust
    effective_lr = learning_rate
    try:
        from nibblebots import causality_tracker as _ct  # noqa: PLC0415
        causal_trust = _ct.get_fix_type_trust(fix_type)
        # Scale: trust=0 → 0.5×lr, trust=0.5 → 0.75×lr, trust=1 → 1.0×lr
        effective_lr = learning_rate * (0.5 + 0.5 * causal_trust)
    except Exception:  # noqa: BLE001
        pass

    for dim in list(weights[fix_type].keys()):
        if dim == "risk_flag":      # skip the rollback guard flag
            continue
        current = weights[fix_type][dim]
        if not isinstance(current, (int, float)):
            continue
        if dim.startswith("risk_"):
            # Positive outcome → risk was overstated → nudge down
            delta = -direction * effective_lr * current
        else:
            # Positive outcome → gain was correct or understated → nudge up
            delta = direction * effective_lr * current
        weights[fix_type][dim] = round(
            max(0.0, min(2.0, current + delta)), 4
        )

    save_weights(weights)


# ---------------------------------------------------------------------------
# Phase 4: Regression model — predict outcome from net_score
# ---------------------------------------------------------------------------

def _load_regression() -> Optional[Dict[str, float]]:
    """Load regression coefficients from disk.  Returns None if unavailable."""
    if _REGRESSION_FILE.exists():
        try:
            data: Any = json.loads(_REGRESSION_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "beta_0" in data and "beta_1" in data:
                return data
        except (OSError, json.JSONDecodeError):
            pass
    return None


def _save_regression(beta_0: float, beta_1: float, n_samples: int) -> None:
    """Persist regression coefficients to disk."""
    try:
        _REGRESSION_FILE.write_text(
            json.dumps(
                {"beta_0": round(beta_0, 6), "beta_1": round(beta_1, 6),
                 "n_samples": n_samples},
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError as exc:
        import sys
        print(f"  ⚠ Could not save regression model: {exc}", file=sys.stderr)


def fit_regression_from_journal(journal_entries: List[Dict[str, Any]]) -> bool:
    """Fit a simple OLS regression from outcome journal entries.

    Maps: net_score → outcome_delta  (positive = improvement)

    Parameters
    ----------
    journal_entries : list of dicts from feedback_learner.read_journal()

    Returns True if the model was fitted and saved, False if insufficient data.
    """
    xs: List[float] = []
    ys: List[float] = []

    for entry in journal_entries:
        net = entry.get("impact_net_score")
        outcome = entry.get("outcome", {})
        if net is None:
            continue
        # Construct scalar outcome_delta from multi-signal outcome dict
        tests_ok = outcome.get("tests_passed")
        ci_delta = outcome.get("ci_failure_change", 0)
        y = 0.0
        if tests_ok is True:
            y += 0.5
        elif tests_ok is False:
            y -= 0.5
        y -= ci_delta * 0.25   # fewer failures → better
        xs.append(float(net))
        ys.append(y)

    if len(xs) < REGRESSION_MIN_SAMPLES:
        return False

    # OLS: β₁ = Σ(xi - x̄)(yi - ȳ) / Σ(xi - x̄)²
    n = len(xs)
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    numerator = sum((xi - x_mean) * (yi - y_mean) for xi, yi in zip(xs, ys))
    denominator = sum((xi - x_mean) ** 2 for xi in xs)
    beta_1 = numerator / denominator if denominator != 0 else None
    if beta_1 is None:
        return False   # insufficient variance — all net_scores are identical
    beta_0 = y_mean - beta_1 * x_mean
    _save_regression(beta_0, beta_1, n)
    return True


def regression_adjusted_net_score(net_score: float) -> float:
    """Return a regression-adjusted net_score if a model is available.

    When the regression model is available:
        adjusted = net_score * (1 + clamp(β₁ * net_score, -0.5, +0.5))

    Falls back to the original net_score when no model exists.
    """
    model = _load_regression()
    if model is None:
        return net_score
    beta_1 = float(model.get("beta_1", 0.0))
    adjustment = max(-0.5, min(0.5, beta_1 * net_score))
    return round(net_score * (1.0 + adjustment), 4)


# ---------------------------------------------------------------------------
# Phase 8: Objective-blended scoring
# ---------------------------------------------------------------------------

def objective_blended_net_score(
    net_score: float,
    after_snapshot: Optional[Dict[str, Any]] = None,
    before_snapshot: Optional[Dict[str, Any]] = None,
    blend_alpha: float = 0.50,
) -> float:
    """Blend regression-adjusted net_score with objective value delta.

    Phase 8 formula:
        regression_score = regression_adjusted_net_score(net_score)
        blended = regression_score * (1 - α) + value_blend * α

    When no reality snapshots are provided, falls back to regression score.

    Parameters
    ----------
    net_score       : raw net_score from impact_engine.score()
    after_snapshot  : RealitySnapshot from reality_bridge (post-fix)
    before_snapshot : RealitySnapshot from reality_bridge (pre-fix)
    blend_alpha     : weight given to objective value side [0, 1]
    """
    reg_score = regression_adjusted_net_score(net_score)
    if after_snapshot is None:
        return reg_score

    try:
        from nibblebots import value_engine  # noqa: PLC0415 — lazy import avoids circular deps
        return value_engine.blend_net_score(
            impact_net_score=reg_score,
            after_snapshot=after_snapshot,
            before_snapshot=before_snapshot,
        )
    except Exception:  # noqa: BLE001
        return reg_score


if __name__ == "__main__":
    print('Running impact_engine.py')
