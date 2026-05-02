#!/usr/bin/env python3
"""
nibblebots/impact_engine.py — Phase 3 Impact Scoring Engine

Estimates *what will improve* if a given SemanticIssue is fixed, before any
change is made.  This is the core intelligence upgrade from Phase 2 — moving
from "apply everything that matches" to "apply what matters most".

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
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional

from nibblebots.semantic_engine import SemanticIssue


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_WEIGHTS_FILE = Path(__file__).parent / "impact_weights.json"

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

    for dim in list(weights[fix_type].keys()):
        current = weights[fix_type][dim]
        if dim.startswith("risk_"):
            # Positive outcome → risk was overstated → nudge down
            delta = -direction * learning_rate * current
        else:
            # Positive outcome → gain was correct or understated → nudge up
            delta = direction * learning_rate * current
        weights[fix_type][dim] = round(
            max(0.0, min(2.0, current + delta)), 4
        )

    save_weights(weights)
