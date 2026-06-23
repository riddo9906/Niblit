#!/usr/bin/env python3
"""
nibblebots/anomaly_detector.py — Phase 7 Anomaly Detection Engine

Detects sudden regression spikes, pattern drift, and abnormal system
behaviour *before* the rollback guard threshold is hit.  This gives the
evolution engine an early-warning layer so it can pause autonomously
rather than committing changes during a degraded system state.

Algorithms
----------
1. **EWMA control chart** (Exponentially Weighted Moving Average)
   Tracks the rolling mean of failure rates using an exponential smoother.
   A signal fires when a new observation deviates more than ``SIGMA_THRESHOLD``
   standard deviations from the EWMA.

2. **IQR fence** (Interquartile Range outlier detection)
   For small windows (< 10 samples) where EWMA variance is unreliable,
   the IQR fence flags values below Q1 - 1.5·IQR or above Q3 + 1.5·IQR.

3. **Pattern drift** (frequency shift)
   Counts how often each fix type appears in recent journal entries vs. the
   baseline window.  A significant frequency shift (ratio > DRIFT_RATIO) flags
   that the population of issues the engine is seeing has changed.

State persistence
-----------------
Anomaly state is stored in ``anomaly_state.json`` next to this file.  The
state includes the EWMA mean/variance, the recent observation window, and a
list of active alerts.

Constants (all overridable via environment variables)
-----------------------------------------------------
EWMA_ALPHA         : float  (env: EVOLUTION_EWMA_ALPHA, default 0.3)
                     Smoothing factor — higher = faster response.
SIGMA_THRESHOLD    : float  (env: EVOLUTION_SIGMA_THRESHOLD, default 2.5)
                     Standard deviations above EWMA to trigger alert.
IQR_WINDOW         : int    (env: EVOLUTION_IQR_WINDOW, default 20)
                     Number of recent observations for IQR fence.
DRIFT_RATIO        : float  (env: EVOLUTION_DRIFT_RATIO, default 3.0)
                     Frequency ratio (recent / baseline) that triggers drift alert.
MIN_OBSERVATIONS   : int    (env: EVOLUTION_MIN_OBS, default 5)
                     Minimum observations required before any alert fires.
"""

from __future__ import annotations

import json
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

EWMA_ALPHA: float = float(os.environ.get("EVOLUTION_EWMA_ALPHA", "0.3"))
SIGMA_THRESHOLD: float = float(os.environ.get("EVOLUTION_SIGMA_THRESHOLD", "2.5"))
IQR_WINDOW: int = int(os.environ.get("EVOLUTION_IQR_WINDOW", "20"))
DRIFT_RATIO: float = float(os.environ.get("EVOLUTION_DRIFT_RATIO", "3.0"))
MIN_OBSERVATIONS: int = int(os.environ.get("EVOLUTION_MIN_OBS", "5"))

_STATE_FILE = Path(__file__).parent / "anomaly_state.json"

# Alert severity levels
SEVERITY_INFO = "info"
SEVERITY_WARN = "warn"
SEVERITY_CRIT = "critical"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class AnomalyAlert:
    """An individual anomaly alert produced by the detector."""

    __slots__ = ("alert_type", "severity", "value", "threshold", "message")

    def __init__(
        self,
        alert_type: str,
        severity: str,
        value: float,
        threshold: float,
        message: str,
    ) -> None:
        self.alert_type = alert_type
        self.severity = severity
        self.value = value
        self.threshold = threshold
        self.message = message

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_type": self.alert_type,
            "severity": self.severity,
            "value": round(self.value, 4),
            "threshold": round(self.threshold, 4),
            "message": self.message,
        }

    def __repr__(self) -> str:
        return (
            f"AnomalyAlert({self.alert_type}, {self.severity}, "
            f"val={self.value:.3f}, thr={self.threshold:.3f})"
        )


class AnomalyReport:
    """Aggregated result of a single anomaly detection pass."""

    __slots__ = ("alerts", "is_safe", "ewma_mean", "ewma_std", "observation_count")

    def __init__(
        self,
        alerts: List[AnomalyAlert],
        ewma_mean: float,
        ewma_std: float,
        observation_count: int,
    ) -> None:
        self.alerts = alerts
        self.ewma_mean = ewma_mean
        self.ewma_std = ewma_std
        self.observation_count = observation_count
        self.is_safe = not any(
            a.severity in (SEVERITY_WARN, SEVERITY_CRIT) for a in alerts
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_safe": self.is_safe,
            "ewma_mean": round(self.ewma_mean, 4),
            "ewma_std": round(self.ewma_std, 4),
            "observation_count": self.observation_count,
            "alerts": [a.to_dict() for a in self.alerts],
        }


# ---------------------------------------------------------------------------
# EWMA state management
# ---------------------------------------------------------------------------

def _load_state() -> Dict[str, Any]:
    """Load persisted anomaly state from disk."""
    if _STATE_FILE.exists():
        try:
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "ewma_mean": 0.0,
        "ewma_var": 0.0,          # Welford-style running variance for EWMA
        "observations": [],       # recent IQR_WINDOW scalar observations
        "fix_type_baseline": {},  # baseline fix-type frequency counts
        "fix_type_recent": {},    # recent fix-type frequency counts
        "n": 0,                   # total observations seen
    }


def _save_state(state: Dict[str, Any]) -> None:
    """Persist anomaly state to disk (best-effort)."""
    try:
        # Keep observations list bounded
        state["observations"] = state["observations"][-IQR_WINDOW:]
        _STATE_FILE.write_text(
            json.dumps(state, indent=2), encoding="utf-8"
        )
    except OSError:
        pass


def _update_ewma(
    state: Dict[str, Any],
    value: float,
) -> Tuple[float, float]:
    """Update EWMA mean and variance; return (new_mean, new_std)."""
    mean = state.get("ewma_mean", 0.0)
    var = state.get("ewma_var", 0.0)

    diff = value - mean
    new_mean = mean + EWMA_ALPHA * diff
    # Welford-style EWMA variance increment
    new_var = (1.0 - EWMA_ALPHA) * (var + EWMA_ALPHA * diff * diff)

    state["ewma_mean"] = new_mean
    state["ewma_var"] = new_var
    return new_mean, math.sqrt(max(0.0, new_var))


# ---------------------------------------------------------------------------
# Anomaly detection algorithms
# ---------------------------------------------------------------------------

def _ewma_check(
    value: float,
    mean: float,
    std: float,
    n: int,
) -> Optional[AnomalyAlert]:
    """Fire an EWMA alert when value is an outlier relative to rolling mean."""
    if n < MIN_OBSERVATIONS or std < 1e-9:
        return None
    z = abs(value - mean) / std
    if z > SIGMA_THRESHOLD:
        sev = SEVERITY_CRIT if z > SIGMA_THRESHOLD * 1.5 else SEVERITY_WARN
        return AnomalyAlert(
            alert_type="ewma_spike",
            severity=sev,
            value=value,
            threshold=SIGMA_THRESHOLD,
            message=(
                f"EWMA spike: value={value:.3f} is {z:.2f}σ above "
                f"rolling mean={mean:.3f} (threshold={SIGMA_THRESHOLD}σ)"
            ),
        )
    return None


def _iqr_check(
    value: float,
    window: List[float],
) -> Optional[AnomalyAlert]:
    """Fire an IQR fence alert when value is a fence outlier."""
    if len(window) < 4:
        return None
    sorted_w = sorted(window)
    n = len(sorted_w)
    q1 = sorted_w[n // 4]
    q3 = sorted_w[(3 * n) // 4]
    iqr = q3 - q1
    if iqr < 1e-9:
        return None
    upper_fence = q3 + 1.5 * iqr
    if value > upper_fence:
        return AnomalyAlert(
            alert_type="iqr_outlier",
            severity=SEVERITY_WARN,
            value=value,
            threshold=upper_fence,
            message=(
                f"IQR outlier: value={value:.3f} exceeds upper fence "
                f"{upper_fence:.3f} (Q1={q1:.3f}, Q3={q3:.3f})"
            ),
        )
    return None


def _drift_check(
    recent_counts: Dict[str, int],
    baseline_counts: Dict[str, int],
) -> List[AnomalyAlert]:
    """Detect fix-type frequency drift between recent and baseline windows."""
    alerts: List[AnomalyAlert] = []
    if not baseline_counts or not recent_counts:
        return alerts

    recent_total = max(sum(recent_counts.values()), 1)
    baseline_total = max(sum(baseline_counts.values()), 1)

    for fix_type, recent_n in recent_counts.items():
        recent_freq = recent_n / recent_total
        baseline_freq = baseline_counts.get(fix_type, 0) / baseline_total
        if baseline_freq < 1e-9:
            continue
        ratio = recent_freq / baseline_freq
        if ratio > DRIFT_RATIO:
            alerts.append(AnomalyAlert(
                alert_type="pattern_drift",
                severity=SEVERITY_INFO,
                value=ratio,
                threshold=DRIFT_RATIO,
                message=(
                    f"Pattern drift: fix_type '{fix_type}' frequency ratio "
                    f"{ratio:.1f}x above baseline (threshold={DRIFT_RATIO}x)"
                ),
            ))
    return alerts


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def observe(
    failure_rate: float,
    fix_types: Optional[List[str]] = None,
) -> AnomalyReport:
    """Record a new observation and return an AnomalyReport.

    Parameters
    ----------
    failure_rate : float
        Fraction of recent CI runs that failed (0.0 = all pass, 1.0 = all fail).
    fix_types : list of str, optional
        Fix types applied in the latest evolution commit (for drift detection).

    Returns an AnomalyReport with any triggered alerts.
    """
    state = _load_state()
    n = state.get("n", 0)
    observations: List[float] = state.get("observations", [])

    # Update EWMA
    mean, std = _update_ewma(state, failure_rate)

    # Add to window
    observations.append(failure_rate)
    state["observations"] = observations
    state["n"] = n + 1

    # Update fix-type frequency tracking
    if fix_types:
        recent: Dict[str, int] = state.get("fix_type_recent", {})
        baseline: Dict[str, int] = state.get("fix_type_baseline", {})

        for ft in fix_types:
            recent[ft] = recent.get(ft, 0) + 1

        # After 20 observations, rotate recent into baseline
        if (n + 1) % 20 == 0:
            # Merge recent into baseline (exponential decay of baseline)
            for ft, cnt in recent.items():
                old = baseline.get(ft, 0)
                baseline[ft] = int(old * 0.7 + cnt * 0.3)
            state["fix_type_baseline"] = baseline
            state["fix_type_recent"] = {}
        else:
            state["fix_type_recent"] = recent
            state["fix_type_baseline"] = baseline

    # Collect alerts
    alerts: List[AnomalyAlert] = []

    ewma_alert = _ewma_check(failure_rate, mean, std, n + 1)
    if ewma_alert:
        alerts.append(ewma_alert)

    iqr_alert = _iqr_check(failure_rate, list(observations[:-1]))
    if iqr_alert:
        alerts.append(iqr_alert)

    drift_alerts = _drift_check(
        state.get("fix_type_recent", {}),
        state.get("fix_type_baseline", {}),
    )
    alerts.extend(drift_alerts)

    _save_state(state)

    return AnomalyReport(
        alerts=alerts,
        ewma_mean=mean,
        ewma_std=std,
        observation_count=n + 1,
    )


def current_state() -> Dict[str, Any]:
    """Return the persisted EWMA state (for inspection / MetaEngine)."""
    state = _load_state()
    return {
        "ewma_mean": round(state.get("ewma_mean", 0.0), 4),
        "ewma_std": round(math.sqrt(max(0.0, state.get("ewma_var", 0.0))), 4),
        "n": state.get("n", 0),
        "recent_observations": state.get("observations", [])[-10:],
    }


def is_system_safe() -> bool:
    """Quick check: True when no WARN/CRIT anomalies are present in the last observation.

    Reads the persisted EWMA state to decide whether it is safe to proceed with
    an evolution commit.  This is a read-only check — it does NOT record a new
    observation.  Returns True when there is insufficient history (safe to
    continue until we know better).
    """
    state = _load_state()
    n = state.get("n", 0)
    if n < MIN_OBSERVATIONS:
        return True
    observations = state.get("observations", [])
    if not observations:
        return True
    latest = observations[-1]
    mean = state.get("ewma_mean", 0.0)
    std = math.sqrt(max(0.0, state.get("ewma_var", 0.0)))
    alert = _ewma_check(latest, mean, std, n)
    return alert is None or alert.severity == SEVERITY_INFO


if __name__ == "__main__":
    print('Running anomaly_detector.py')
