#!/usr/bin/env python3
"""
nibblebots/signal_integrity_engine.py — Phase 8.5 Signal Integrity Engine

Validates that the "reality" signals the system is learning from are actually
trustworthy before the value_engine and causality_tracker act on them.

Problem
-------
Without signal integrity checks, the system can confidently optimise the
wrong thing:

* Trading bot gets lucky → win_rate spike → system reinforces bad logic
* Noisy CI data from flaky tests → misleading pass_rate trend
* Partial runtime health log → incomplete picture treated as ground truth

Solution
--------
Before any signal is fed into value_engine, we attach a *confidence score*
to each source.  Low-confidence signals are down-weighted or completely gated.

Public API
----------
``assess_ci(pass_rate_history)``
    Returns a [0, 1] confidence score for CI signal quality.
    Penalises high volatility.

``assess_trading(n_trades)``
    Returns a [0, 1] confidence score for trading signal quality.
    Penalises insufficient sample size.

``assess_runtime(health_log)``
    Returns a [0, 1] confidence score for runtime signal quality.
    Penalises sparse / missing health log entries.

``assess_snapshot(snapshot)``
    Returns a ``SignalConfidence`` dataclass with per-source scores and a
    weighted ``avg_confidence``.  This is the primary entry point for
    integration with reality_bridge.

Constants (overridable via env vars)
-------------------------------------
SIE_MIN_TRADE_SAMPLES   : int    (env: SIE_MIN_TRADE_SAMPLES, default 20)
                          Below this, trading confidence is penalised.
SIE_FULL_TRADE_SAMPLES  : int    (env: SIE_FULL_TRADE_SAMPLES, default 100)
                          At or above this, trading confidence saturates at 1.0.
SIE_MIN_CONFIDENCE_GATE : float  (env: SIE_MIN_CONFIDENCE_GATE, default 0.50)
                          avg_confidence below this is considered unreliable.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SIE_MIN_TRADE_SAMPLES: int = int(os.environ.get("SIE_MIN_TRADE_SAMPLES", "20"))
SIE_FULL_TRADE_SAMPLES: int = int(os.environ.get("SIE_FULL_TRADE_SAMPLES", "100"))
SIE_MIN_CONFIDENCE_GATE: float = float(
    os.environ.get("SIE_MIN_CONFIDENCE_GATE", "0.50")
)

# Source weights for computing avg_confidence
_CI_WEIGHT = 0.40
_TRADE_WEIGHT = 0.35
_RUNTIME_WEIGHT = 0.25


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class SignalConfidence:
    """Per-source and aggregate signal confidence scores.

    Attributes
    ----------
    ci_confidence       : [0, 1] how reliable the CI/pass_rate signal is
    trade_confidence    : [0, 1] how reliable the trading signal is
    runtime_confidence  : [0, 1] how reliable the runtime health signal is
    avg_confidence      : [0, 1] weighted average of all three sources
    is_reliable         : True when avg_confidence >= SIE_MIN_CONFIDENCE_GATE
    """

    ci_confidence: float
    trade_confidence: float
    runtime_confidence: float
    avg_confidence: float
    is_reliable: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ci_confidence": self.ci_confidence,
            "trade_confidence": self.trade_confidence,
            "runtime_confidence": self.runtime_confidence,
            "avg_confidence": self.avg_confidence,
            "is_reliable": self.is_reliable,
        }


# ---------------------------------------------------------------------------
# Per-source assessors
# ---------------------------------------------------------------------------

def assess_ci(pass_rate_history: List[float]) -> float:
    """Compute confidence score for CI signal based on pass_rate history.

    High volatility in pass_rate → low confidence (flaky tests / noisy CI).
    Returns [0, 1].

    Parameters
    ----------
    pass_rate_history : ordered list of pass_rate values (each in [0, 1])
    """
    if not pass_rate_history:
        return 0.5   # no data → neutral

    if len(pass_rate_history) < 3:
        return 0.6   # very little data → modest confidence

    mean = sum(pass_rate_history) / len(pass_rate_history)
    variance = sum((x - mean) ** 2 for x in pass_rate_history) / len(pass_rate_history)
    std = math.sqrt(variance)

    # High std → low confidence; cap at 0.5 so extreme volatility doesn't
    # destroy confidence below 0.5 (the lower bound for "maybe useful")
    volatility_penalty = min(std, 0.5)
    confidence = 1.0 - volatility_penalty

    return round(max(0.0, min(1.0, confidence)), 4)


def assess_trading(n_trades: int) -> float:
    """Compute confidence score for trading signal based on sample size.

    Fewer samples → lower confidence (not enough evidence to distinguish
    luck from skill).  Returns [0, 1].

    Parameters
    ----------
    n_trades : number of completed trades in the observation window
    """
    if n_trades <= 0:
        return 0.0

    if n_trades < SIE_MIN_TRADE_SAMPLES:
        # Linear ramp from 0.1 (1 trade) to 0.3 (SIE_MIN_TRADE_SAMPLES - 1)
        base = 0.3 * (n_trades / max(SIE_MIN_TRADE_SAMPLES, 1))
        return round(max(0.1, min(0.3, base)), 4)

    # Log-scale ramp from 0.3 → 1.0 between MIN and FULL sample counts
    t = (n_trades - SIE_MIN_TRADE_SAMPLES) / max(
        SIE_FULL_TRADE_SAMPLES - SIE_MIN_TRADE_SAMPLES, 1
    )
    confidence = 0.3 + 0.7 * min(1.0, t)
    return round(confidence, 4)


def assess_runtime(health_log: List[Dict[str, Any]]) -> float:
    """Compute confidence score for runtime signal based on log completeness.

    Sparse or missing health log → lower confidence.
    Returns [0, 1].

    Parameters
    ----------
    health_log : list of health snapshot dicts from system_health_monitor
    """
    if not health_log:
        return 0.4   # no log → below neutral but not zero (could just be new)

    required_fields = {"error_rate", "memory_pressure", "response_quality"}
    complete = sum(
        1 for snap in health_log
        if required_fields.issubset(snap.keys())
    )
    completeness = complete / len(health_log)

    # Scale: 10+ complete entries = full confidence; fewer = degraded
    size_factor = min(1.0, len(health_log) / 10.0)
    confidence = completeness * 0.7 + size_factor * 0.3

    return round(max(0.0, min(1.0, confidence)), 4)


# ---------------------------------------------------------------------------
# Primary entry point
# ---------------------------------------------------------------------------

def assess_snapshot(snapshot: Dict[str, Any]) -> SignalConfidence:
    """Assess signal integrity for a full RealitySnapshot.

    Derives per-source confidence from information already present in the
    snapshot dict (populated by reality_bridge.pull_snapshot()).

    Parameters
    ----------
    snapshot : RealitySnapshot dict from reality_bridge.pull_snapshot()

    Returns
    -------
    SignalConfidence with per-source scores and weighted avg_confidence.
    """
    # ── CI confidence ────────────────────────────────────────────────────────
    # Derive a mini pass_rate history from the snapshot.
    # We use pass_rate and ci_failure_trend as proxies.
    pass_rate = float(snapshot.get("pass_rate", 0.8))
    ci_trend = float(snapshot.get("ci_failure_trend", 0.0))
    n_entries = int(snapshot.get("n_journal_entries", 0))

    if n_entries > 0:
        # Reconstruct a short pseudo-history: current + implied prior
        # trend > 0 → pass_rate was lower before; trend < 0 → was higher
        prior_pass_rate = max(0.0, min(1.0, pass_rate - ci_trend))
        pseudo_history = [prior_pass_rate, pass_rate]
    else:
        pseudo_history = []

    ci_conf = assess_ci(pseudo_history)
    # Additional penalty when journal coverage is very thin
    if n_entries < 5:
        ci_conf *= 0.75
    ci_conf = round(max(0.0, min(1.0, ci_conf)), 4)

    # ── Trading confidence ───────────────────────────────────────────────────
    win_rate = snapshot.get("win_rate")
    if win_rate is not None:
        # Infer approximate n_trades from snapshot metadata if present,
        # otherwise use REALITY_TRADE_WINDOW default (50) scaled to n_entries
        n_trades = int(snapshot.get("n_trade_entries", SIE_MIN_TRADE_SAMPLES))
        trade_conf = assess_trading(n_trades)
    else:
        trade_conf = 0.3   # no trading data in snapshot

    # ── Runtime confidence ────────────────────────────────────────────────────
    runtime_score = snapshot.get("runtime_score")
    if runtime_score is not None:
        # runtime_score is already an aggregated health score [0, 1]
        # Use it as a proxy for completeness: high score + present = good
        runtime_conf = round(0.5 + float(runtime_score) * 0.5, 4)
        runtime_conf = max(0.0, min(1.0, runtime_conf))
    else:
        runtime_conf = assess_runtime([])

    # ── Weighted average ──────────────────────────────────────────────────────
    avg = (
        ci_conf * _CI_WEIGHT
        + trade_conf * _TRADE_WEIGHT
        + runtime_conf * _RUNTIME_WEIGHT
    )
    avg = round(avg, 4)

    return SignalConfidence(
        ci_confidence=ci_conf,
        trade_confidence=trade_conf,
        runtime_confidence=runtime_conf,
        avg_confidence=avg,
        is_reliable=avg >= SIE_MIN_CONFIDENCE_GATE,
    )


if __name__ == "__main__":
    print('Running signal_integrity_engine.py')
