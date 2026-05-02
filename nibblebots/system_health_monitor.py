#!/usr/bin/env python3
"""
nibblebots/system_health_monitor.py — Phase 6 System Health Monitor

Connects the evolution loop to the existing Niblit runtime modules.  Produces
a ``SystemHealthSnapshot`` by reading:

  * ``modules/evaluation_engine.py``  — recent outcome scores
  * ``modules/quality_feedback.py``   — reward signal averages
  * ``niblit_self_heal.log``          — self-healing event counts
  * ``fortress_metrics.json``         — fortress execution metrics

The snapshot is fed into ``observation_collector.py`` as a real-time domain
signal so the Observe step of the improvement loop is grounded in runtime
reality, not just static code analysis.

``SystemHealthSnapshot`` fields
--------------------------------
error_rate        : 0.0–1.0  estimated recent error frequency
response_quality  : 0.0–1.0  average quality score from QualityFeedback
memory_pressure   : 0.0–1.0  estimated memory usage ratio
learning_velocity : 0.0–1.0  learning-cycle completion rate
timestamp         : ISO-8601 time the snapshot was taken
source_signals    : dict of individual raw signal values (for debuggability)

Public API
----------
``take_snapshot(workspace) → SystemHealthSnapshot``
    Collect a fresh snapshot from all available sources.

``delta(before, after) → Dict[str, float]``
    Compute field-by-field delta between two snapshots (+ = improvement).

``as_observation(snapshot) → Observation``
    Convert a snapshot into a standard ``Observation`` for the collector.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, NamedTuple, Optional


# ---------------------------------------------------------------------------
# Snapshot data structure
# ---------------------------------------------------------------------------

class SystemHealthSnapshot(NamedTuple):
    error_rate: float        # 0.0 = no errors, 1.0 = all errors
    response_quality: float  # 0.0 = poor, 1.0 = excellent
    memory_pressure: float   # 0.0 = low, 1.0 = critical
    learning_velocity: float # 0.0 = stalled, 1.0 = fast
    timestamp: str
    source_signals: Dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers for reading existing runtime module state
# ---------------------------------------------------------------------------

def _read_fortress_metrics(workspace: Path) -> Dict[str, Any]:
    path = workspace / "fortress_metrics.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _read_self_heal_log(workspace: Path) -> Dict[str, int]:
    """Count log levels in niblit_self_heal.log."""
    path = workspace / "niblit_self_heal.log"
    counts: Dict[str, int] = {"error": 0, "warning": 0, "info": 0, "total": 0}
    if not path.exists():
        return counts
    _level_re = re.compile(r"\[(ERROR|WARNING|INFO|CRITICAL)\]", re.IGNORECASE)
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            m = _level_re.search(line)
            if m:
                level = m.group(1).lower()
                if level == "critical":
                    level = "error"
                counts[level] = counts.get(level, 0) + 1
                counts["total"] += 1
    except OSError:
        pass
    return counts


def _get_evaluation_engine_score() -> Optional[float]:
    """Try to read the last outcome score from evaluation_engine singleton."""
    try:
        from modules.evaluation_engine import get_evaluation_engine  # noqa: PLC0415
        eng = get_evaluation_engine()
        history = getattr(eng, "_outcome_history", None) or []
        if history:
            recent = history[-min(10, len(history)):]
            return sum(r.get("score", 0.5) for r in recent) / len(recent)
    except Exception:  # noqa: BLE001
        pass
    return None


def _get_quality_feedback_score() -> Optional[float]:
    """Try to read the average reward from the QualityFeedback singleton."""
    try:
        from modules.quality_feedback import get_quality_feedback  # noqa: PLC0415
        qf = get_quality_feedback()
        history = getattr(qf, "_score_history", None) or []
        if history:
            recent = history[-min(10, len(history)):]
            return sum(recent) / len(recent)
    except Exception:  # noqa: BLE001
        pass
    return None


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------

def take_snapshot(workspace: Optional[Path] = None) -> SystemHealthSnapshot:
    """Collect a fresh SystemHealthSnapshot from all available sources.

    Gracefully handles missing modules / files — every sub-component falls
    back to a neutral 0.5 value if unavailable.
    """
    import os  # noqa: PLC0415
    ws = workspace or Path(os.environ.get("GITHUB_WORKSPACE", "."))
    signals: Dict[str, Any] = {}

    # ── Error rate from self-heal log ─────────────────────────────────────
    heal_counts = _read_self_heal_log(ws)
    signals["self_heal_errors"] = heal_counts.get("error", 0)
    signals["self_heal_total"] = heal_counts.get("total", 1)
    if heal_counts["total"] > 0:
        error_rate = heal_counts["error"] / heal_counts["total"]
    else:
        error_rate = 0.0

    # ── Response quality from evaluation/quality_feedback ────────────────
    eval_score = _get_evaluation_engine_score()
    qf_score = _get_quality_feedback_score()
    signals["eval_score"] = eval_score
    signals["qf_score"] = qf_score

    available_quality = [s for s in [eval_score, qf_score] if s is not None]
    response_quality = (
        sum(available_quality) / len(available_quality)
        if available_quality else 0.5
    )

    # ── Memory pressure from fortress metrics ─────────────────────────────
    fortress = _read_fortress_metrics(ws)
    signals["fortress"] = fortress
    mem_ratio = fortress.get("memory_ratio", fortress.get("memory_pressure", None))
    memory_pressure = float(mem_ratio) if mem_ratio is not None else 0.3

    # ── Learning velocity from outcome journal pass rate ──────────────────
    try:
        from nibblebots.feedback_learner import journal_summary  # noqa: PLC0415
        summary = journal_summary()
        learning_velocity = float(summary.get("pass_rate", 0.5))
        signals["journal_pass_rate"] = learning_velocity
    except Exception:  # noqa: BLE001
        learning_velocity = 0.5
        signals["journal_pass_rate"] = None

    return SystemHealthSnapshot(
        error_rate=round(min(1.0, max(0.0, error_rate)), 3),
        response_quality=round(min(1.0, max(0.0, response_quality)), 3),
        memory_pressure=round(min(1.0, max(0.0, memory_pressure)), 3),
        learning_velocity=round(min(1.0, max(0.0, learning_velocity)), 3),
        timestamp=datetime.now(timezone.utc).isoformat(),
        source_signals=signals,
    )


# ---------------------------------------------------------------------------
# Delta computation
# ---------------------------------------------------------------------------

def delta(before: SystemHealthSnapshot, after: SystemHealthSnapshot) -> Dict[str, float]:
    """Compute field-by-field delta (positive = improvement in the after snapshot).

    For error_rate and memory_pressure a *decrease* is an improvement, so the
    sign is inverted so that a positive delta always means "better".
    """
    return {
        "error_rate_delta":        round(before.error_rate - after.error_rate, 4),
        "response_quality_delta":  round(after.response_quality - before.response_quality, 4),
        "memory_pressure_delta":   round(before.memory_pressure - after.memory_pressure, 4),
        "learning_velocity_delta": round(after.learning_velocity - before.learning_velocity, 4),
    }


# ---------------------------------------------------------------------------
# Adapter: SystemHealthSnapshot → Observation
# ---------------------------------------------------------------------------

def as_observation(snapshot: SystemHealthSnapshot) -> "Any":
    """Convert a SystemHealthSnapshot into a standard Observation namedtuple."""
    try:
        from nibblebots.observation_collector import Observation  # noqa: PLC0415
    except ImportError:
        return snapshot   # fallback: return raw snapshot

    # Overall severity = max of error_rate and memory_pressure
    severity = round(max(snapshot.error_rate, snapshot.memory_pressure), 3)
    signal_type = (
        "system_health_critical" if severity >= 0.70
        else "system_health_warning" if severity >= 0.40
        else "system_health_ok"
    )

    import json as _json  # noqa: PLC0415
    return Observation(
        domain="system_health",
        signal_type=signal_type,
        severity=severity,
        timestamp=snapshot.timestamp,
        raw=_json.dumps({
            "error_rate": snapshot.error_rate,
            "response_quality": snapshot.response_quality,
            "memory_pressure": snapshot.memory_pressure,
            "learning_velocity": snapshot.learning_velocity,
        })[:512],
    )
