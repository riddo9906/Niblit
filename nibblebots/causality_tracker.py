#!/usr/bin/env python3
"""
nibblebots/causality_tracker.py — Phase 8 Causality Tracker

Tracks *what actually caused* improvements — not just correlation, but
longitudinal cause-effect evidence accumulated over many cycles.

Core insight
------------
The earlier phases learned *that* certain fix types are correlated with
better CI outcomes.  Phase 8 asks a deeper question:

    "Which fix types actually move the objective score — i.e., produce
     improvements that matter in real-world terms?"

Method
------
For each fix type we maintain a rolling window of (net_score, value_delta)
pairs from past commits.  We compute:

1. **Pearson correlation** between the impact_engine net_score and the
   objective value_delta.  High correlation means the engine's predictions
   are aligned with real-world outcomes.

2. **Mean value delta** per fix type — the average real-world improvement
   a fix type produces per application.

3. **Consistency score** — 1 - (std_dev / mean_abs_delta) so fix types
   with wildly inconsistent outcomes get a lower trust score.

These three numbers combine into a ``CausalityProfile`` per fix type.

The ``get_correlations()`` output can be used by:
* ``strategic_planner`` to raise/lower exploration rate for unreliable types
* ``confidence_decay`` to apply faster decay to inconsistent fix types
* ``impact_engine`` to adjust gain priors for proven-valuable types

State persistence
-----------------
Causality state stored in ``causality_state.json`` next to this file.

Constants
---------
CAUSALITY_WINDOW    : int  (env: CAUSALITY_WINDOW, default 30)
                      Sliding window size per fix type.
CAUSALITY_MIN_OBS   : int  (env: CAUSALITY_MIN_OBS, default 5)
                      Minimum observations before producing estimates.
"""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CAUSALITY_WINDOW: int = int(os.environ.get("CAUSALITY_WINDOW", "30"))
CAUSALITY_MIN_OBS: int = int(os.environ.get("CAUSALITY_MIN_OBS", "5"))

_STATE_FILE = Path(__file__).parent / "causality_state.json"


# ---------------------------------------------------------------------------
# Internal math helpers
# ---------------------------------------------------------------------------

def _mean(vals: List[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _std(vals: List[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = _mean(vals)
    variance = sum((x - m) ** 2 for x in vals) / (len(vals) - 1)
    return math.sqrt(variance)


def _pearson(xs: List[float], ys: List[float]) -> float:
    """Pearson correlation coefficient between xs and ys."""
    n = min(len(xs), len(ys))
    if n < 2:
        return 0.0
    xs, ys = xs[:n], ys[:n]
    mx, my = _mean(xs), _mean(ys)
    sx, sy = _std(xs), _std(ys)
    if sx == 0 or sy == 0:
        return 0.0
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (n - 1)
    return round(cov / (sx * sy), 4)


# ---------------------------------------------------------------------------
# State serialisation
# ---------------------------------------------------------------------------

def _load_state() -> Dict[str, List[Tuple[float, float]]]:
    """Load the per-fix-type observation window lists.

    Supports both legacy 2-tuple (net_score, value_delta) entries and the
    Phase 8.5 3-tuple (net_score, value_delta, confidence) entries.
    """
    if not _STATE_FILE.exists():
        return {}
    try:
        raw = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        # Normalise to tuples regardless of length (2 or 3 elements)
        return {
            ft: [tuple(pair) for pair in pairs]  # type: ignore[misc]
            for ft, pairs in raw.items()
        }
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _save_state(state: Dict[str, List[Tuple[float, float]]]) -> None:
    try:
        serialisable = {
            ft: [list(pair) for pair in pairs]
            for ft, pairs in state.items()
        }
        _STATE_FILE.write_text(
            json.dumps(serialisable, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def record(
    fix_types: List[str],
    impact_net_score: float,
    value_delta: float,
    signal_confidence: float = 1.0,
) -> None:
    """Record a (net_score, value_delta) observation for each fix_type.

    Parameters
    ----------
    fix_types          : list of fix types applied in this commit
    impact_net_score   : average net_score from impact_engine for this commit
    value_delta        : objective value delta from value_engine for this commit
    signal_confidence  : Phase 8.5 — avg_confidence from signal_integrity_engine
                         (1.0 = fully trusted; low values down-weight this obs)

    Phase 8.5 note
    --------------
    Observations with low ``signal_confidence`` are stored with a down-weighted
    ``value_delta`` so the causality tracker does not learn from garbage signals.
    The stored tuple is (net_score, confidence_weighted_value_delta, confidence).
    """
    confidence = max(0.0, min(1.0, float(signal_confidence)))
    weighted_delta = value_delta * confidence
    state = _load_state()
    for ft in fix_types:
        window = list(state.get(ft, []))
        # Store 3-tuple for new entries; older 2-tuples remain readable
        window.append((float(impact_net_score), weighted_delta, confidence))
        # Maintain rolling window
        if len(window) > CAUSALITY_WINDOW:
            window = window[-CAUSALITY_WINDOW:]
        state[ft] = window  # type: ignore[assignment]
    _save_state(state)


def get_correlations() -> Dict[str, Dict[str, Any]]:
    """Return causality profiles for all fix types with sufficient data.

    Returns
    -------
    dict mapping fix_type → {
        "pearson_r"       : float  — correlation between net_score & value_delta
        "mean_value_delta": float  — average real-world improvement
        "consistency"     : float  — 0–1, higher = more consistent outcomes
        "n_obs"           : int    — number of observations
        "reliable"        : bool   — True when n_obs ≥ CAUSALITY_MIN_OBS
    }
    """
    state = _load_state()
    result: Dict[str, Dict[str, Any]] = {}
    for ft, pairs in state.items():
        n = len(pairs)
        net_scores = [p[0] for p in pairs]
        value_deltas = [p[1] for p in pairs]
        reliable = n >= CAUSALITY_MIN_OBS
        mean_delta = round(_mean(value_deltas), 4)
        std_delta = _std(value_deltas)
        mean_abs = _mean([abs(d) for d in value_deltas])
        consistency = round(
            1.0 - min(1.0, std_delta / max(mean_abs, 1e-6)), 4
        ) if reliable else 0.0

        result[ft] = {
            "pearson_r": _pearson(net_scores, value_deltas) if reliable else 0.0,
            "mean_value_delta": mean_delta,
            "consistency": consistency,
            "n_obs": n,
            "reliable": reliable,
        }
    return result


def get_fix_type_trust(fix_type: str) -> float:
    """Return a trust score [0, 1] for a given fix type.

    Score combines reliability (enough data), correlation, and consistency.
    Returns 0.5 when there is insufficient data (neutral trust).
    """
    profiles = get_correlations()
    p = profiles.get(fix_type)
    if p is None or not p["reliable"]:
        return 0.5

    # Map pearson_r from [-1,1] to [0,1]
    r_normalised = (p["pearson_r"] + 1.0) / 2.0
    # mean_value_delta: positive is better, scale with tanh to [0,1]
    delta_normalised = (math.tanh(p["mean_value_delta"] * 5) + 1.0) / 2.0
    consistency = p["consistency"]

    trust = (r_normalised * 0.35 + delta_normalised * 0.40 + consistency * 0.25)
    return round(min(1.0, max(0.0, trust)), 4)


def get_top_causal_types(top_n: int = 5) -> List[Dict[str, Any]]:
    """Return the top-N fix types ranked by mean_value_delta (descending)."""
    profiles = get_correlations()
    ranked = sorted(
        [
            {"fix_type": ft, **info}
            for ft, info in profiles.items()
            if info["reliable"]
        ],
        key=lambda x: x["mean_value_delta"],
        reverse=True,
    )
    return ranked[:top_n]


def print_report() -> None:
    """Print a human-readable causality report to stdout."""
    correlations = get_correlations()
    if not correlations:
        print("  📊 CausalityTracker: no data yet")
        return
    print("  📊 Causality Report:")
    for ft, info in sorted(
        correlations.items(),
        key=lambda x: x[1]["mean_value_delta"],
        reverse=True,
    ):
        marker = "✅" if info["reliable"] else "○ "
        print(
            f"    {marker} {ft:<25} "
            f"Δvalue={info['mean_value_delta']:+.4f}  "
            f"r={info['pearson_r']:+.3f}  "
            f"consist={info['consistency']:.2f}  "
            f"n={info['n_obs']}"
        )


if __name__ == "__main__":
    print('Running causality_tracker.py')
