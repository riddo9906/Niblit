#!/usr/bin/env python3
"""
nibblebots/causality_tracker.py — Phase 8 / Phase 18.5 Causality Tracker

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
For each fix type we maintain a rolling window of (net_score, value_delta,
confidence) tuples from past commits.  We compute:

1. **Recency-weighted Pearson correlation** between the impact_engine
   net_score and the objective value_delta.  Recent observations carry
   exponentially more weight (decay constant ``CAUSALITY_RECENCY_DECAY``),
   so the tracker adapts when fix-type effectiveness changes over time.

2. **Confidence-weighted mean value delta** per fix type — high-confidence
   observations (those recorded when signal_integrity_engine reported
   avg_confidence > 0.7) count more than noisy low-confidence ones.

3. **Consistency score** — 1 - (weighted_std_dev / weighted_mean_abs_delta)
   so fix types with wildly inconsistent outcomes get a lower trust score.
   Weighting follows the same recency × confidence product as above.

These three numbers combine into a ``CausalityProfile`` per fix type.

The ``get_correlations()`` output can be used by:
* ``strategic_planner`` to raise/lower exploration rate for unreliable types
* ``confidence_decay`` to apply faster decay to inconsistent fix types
* ``impact_engine`` to modulate the weight-update learning rate
* ``evolution_planner`` to apply a per-fix-type confidence modifier

Phase 18.5 upgrades
--------------------
* Recency weighting throughout (``CAUSALITY_RECENCY_DECAY``, default 15).
  Older observations exponentially down-weighted so that stale evidence
  from past conditions does not corrupt current decision-making.
* Confidence weighting: each 3-tuple's stored confidence multiplies its
  recency weight, so high-signal observations drive statistics more strongly.
* ``get_fix_type_trust()`` now includes an explicit *n_obs confidence*
  factor that grows from 0 → 1 over the first ``CAUSALITY_MIN_OBS`` to
  ``CAUSALITY_WINDOW`` observations, preventing a single lucky result from
  producing deceptively high trust early on.

State persistence
-----------------
Causality state stored in ``causality_state.json`` next to this file.

Constants
---------
CAUSALITY_WINDOW         : int   (env: CAUSALITY_WINDOW,          default 30)
                           Sliding window size per fix type.
CAUSALITY_MIN_OBS        : int   (env: CAUSALITY_MIN_OBS,         default 5)
                           Minimum observations before producing estimates.
CAUSALITY_RECENCY_DECAY  : float (env: CAUSALITY_RECENCY_DECAY,   default 15.0)
                           Exponential decay half-life (in observations).
                           Lower → heavier recency emphasis.
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
# Phase 18.5: half-life for recency weighting (number of observations).
# At distance D from the most-recent observation, weight = exp(-D / DECAY).
CAUSALITY_RECENCY_DECAY: float = float(
    os.environ.get("CAUSALITY_RECENCY_DECAY", "15.0")
)

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
    """Pearson correlation coefficient between xs and ys (unweighted)."""
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


# Phase 18.5: recency × confidence composite weights --------------------------

def _observation_weights(
    pairs: List[tuple],
    recency_decay: float = CAUSALITY_RECENCY_DECAY,
) -> List[float]:
    """Return a normalised weight per observation (most-recent = index -1).

    Weight = exp(-distance / recency_decay) × stored_confidence

    where ``distance`` counts backwards from the newest observation and
    ``stored_confidence`` is the third element of the 3-tuple (1.0 for
    legacy 2-tuples that lack it).
    """
    n = len(pairs)
    if n == 0:
        return []
    weights: List[float] = []
    for i, pair in enumerate(pairs):
        distance = n - 1 - i          # 0 for newest, n-1 for oldest
        recency_w = math.exp(-distance / max(recency_decay, 1e-6))
        stored_conf = float(pair[2]) if len(pair) >= 3 else 1.0
        conf_w = max(0.0, min(1.0, stored_conf))
        weights.append(recency_w * max(conf_w, 0.10))  # floor at 0.10
    total = sum(weights)
    if total <= 0:
        return [1.0 / n] * n
    return [w / total for w in weights]


def _weighted_mean(vals: List[float], weights: List[float]) -> float:
    """Weighted mean of vals using normalised weights."""
    if not vals:
        return 0.0
    return sum(v * w for v, w in zip(vals, weights))


def _weighted_std(vals: List[float], weights: List[float]) -> float:
    """Weighted standard deviation (population, denominator = 1)."""
    if len(vals) < 2:
        return 0.0
    wm = _weighted_mean(vals, weights)
    variance = sum(w * (v - wm) ** 2 for v, w in zip(vals, weights))
    return math.sqrt(variance)


def _weighted_pearson(
    xs: List[float],
    ys: List[float],
    weights: List[float],
) -> float:
    """Weighted Pearson r.  Returns 0.0 when insufficient data."""
    n = min(len(xs), len(ys), len(weights))
    if n < 2:
        return 0.0
    xs, ys, weights = xs[:n], ys[:n], weights[:n]
    total_w = sum(weights)
    if total_w <= 0:
        return 0.0
    weights = [w / total_w for w in weights]
    mx = _weighted_mean(xs, weights)
    my = _weighted_mean(ys, weights)
    sx = _weighted_std(xs, weights)
    sy = _weighted_std(ys, weights)
    if sx == 0 or sy == 0:
        return 0.0
    cov = sum(w * (x - mx) * (y - my) for x, y, w in zip(xs, ys, weights))
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

    Phase 18.5: all statistics are now recency-weighted (exponential decay)
    and confidence-weighted (stored per-observation confidence from the
    signal_integrity_engine).  This prevents stale or noisy observations
    from corrupting current decision-making.

    Returns
    -------
    dict mapping fix_type → {
        "pearson_r"       : float  — weighted correlation net_score ↔ value_delta
        "mean_value_delta": float  — weighted average real-world improvement
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

        # Phase 18.5: compute recency × confidence weights once per fix type
        weights = _observation_weights(pairs)

        if reliable:
            wmean_delta = _weighted_mean(value_deltas, weights)
            wstd_delta = _weighted_std(value_deltas, weights)
            mean_abs = _weighted_mean([abs(d) for d in value_deltas], weights)
            consistency = round(
                1.0 - min(1.0, wstd_delta / max(mean_abs, 1e-6)), 4
            )
            pearson_r = _weighted_pearson(net_scores, value_deltas, weights)
        else:
            wmean_delta = _weighted_mean(value_deltas, weights) if weights else 0.0
            consistency = 0.0
            pearson_r = 0.0

        result[ft] = {
            "pearson_r": pearson_r,
            "mean_value_delta": round(wmean_delta, 4),
            "consistency": consistency,
            "n_obs": n,
            "reliable": reliable,
        }
    return result


def get_fix_type_trust(fix_type: str) -> float:
    """Return a trust score [0, 1] for a given fix type.

    Phase 18.5 formula
    ------------------
    Score combines four factors:

    1. **Reliability (n_obs)** — grows from 0 toward 1 as observations
       accumulate, preventing a single lucky result from producing high trust.
       ``n_obs_factor = min(1.0, n_obs / CAUSALITY_WINDOW)``

    2. **Correlation (pearson_r)** — weighted r mapped from [-1, 1] to [0, 1].

    3. **Mean value delta** — positive delta is better; mapped via tanh to [0, 1].

    4. **Consistency** — higher when outcomes are stable across observations.

    Final score (when reliable):
        trust = n_obs_factor × (r_norm × 0.30 + delta_norm × 0.40 + consist × 0.30)

    Returns 0.5 when there is insufficient data (neutral trust).
    """
    profiles = get_correlations()
    p = profiles.get(fix_type)
    if p is None or not p["reliable"]:
        # Partial data: scale towards neutral (0.5) based on n_obs collected
        n = p["n_obs"] if p is not None else 0
        partial_factor = min(1.0, n / max(CAUSALITY_MIN_OBS, 1))
        # Nudge slightly based on mean_value_delta even before reaching minimum
        if p is not None and p["mean_value_delta"] != 0.0:
            delta_hint = (math.tanh(p["mean_value_delta"] * 5) + 1.0) / 2.0
            return round(0.4 + 0.1 * partial_factor * delta_hint, 4)
        return 0.5

    # n_obs confidence factor: matures from 0 → 1 over CAUSALITY_WINDOW obs
    n_obs_factor = min(1.0, p["n_obs"] / max(CAUSALITY_WINDOW, 1))

    # Map pearson_r from [-1,1] to [0,1]
    r_normalised = (p["pearson_r"] + 1.0) / 2.0
    # mean_value_delta: positive is better, scale with tanh to [0,1]
    delta_normalised = (math.tanh(p["mean_value_delta"] * 5) + 1.0) / 2.0
    consistency = p["consistency"]

    raw_trust = r_normalised * 0.30 + delta_normalised * 0.40 + consistency * 0.30
    # Multiply by the n_obs maturity factor so trust builds gradually
    trust = n_obs_factor * raw_trust
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
