#!/usr/bin/env python3
"""
nibblebots/value_engine.py — Phase 8 Value Engine

Translates system changes into real-world value using the ObjectiveEngine.

The core question this module answers:

    "Did this evolution commit actually make things better in a way that
     matters for our real-world goals — not just in terms of code cleanliness?"

Formula
-------
    value_delta = objective_score(after_snapshot) - objective_score(before_snapshot)

A ``ValueAssessment`` is produced for each commit.  It carries:

* ``delta``        — signed improvement score in [-1, 1]
* ``confidence``   — how reliable this estimate is (based on signal coverage)
* ``source``       — which signals drove the score (ci / trading / runtime)
* ``passes_gate``  — whether the delta clears ``MIN_REAL_WORLD_GAIN``

Integration with evolution_planner
------------------------------------
``evolution_planner.build_plan()`` will skip a fix if:

    value_assessment.passes_gate is False

This implements the Phase 8 requirement: "if value_score < MIN_REAL_WORLD_GAIN:
skip_fix()"

Constants (overridable via env vars)
-------------------------------------
MIN_REAL_WORLD_GAIN : float  (env: VALUE_MIN_GAIN, default 0.02)
                      Minimum objective-score improvement required for a fix
                      to be considered genuinely valuable.
VALUE_BLEND_ALPHA   : float  (env: VALUE_BLEND_ALPHA, default 0.50)
                      How much to weight objective value vs impact_engine score
                      when blending (0 = impact only, 1 = objective only).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from nibblebots import objective_engine

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MIN_REAL_WORLD_GAIN: float = float(os.environ.get("VALUE_MIN_GAIN", "0.02"))
VALUE_BLEND_ALPHA: float = float(os.environ.get("VALUE_BLEND_ALPHA", "0.50"))

_HISTORY_FILE = Path(__file__).parent / "value_history.jsonl"
_MAX_HISTORY = 200


# ---------------------------------------------------------------------------
# ValueAssessment
# ---------------------------------------------------------------------------

class ValueAssessment:
    """Result of evaluating a single evolution commit against the objective."""

    __slots__ = ("delta", "confidence", "source", "passes_gate",
                 "before_score", "after_score")

    def __init__(
        self,
        delta: float,
        confidence: float,
        source: str,
        before_score: float,
        after_score: float,
    ) -> None:
        self.delta = round(delta, 4)
        self.confidence = round(min(1.0, max(0.0, confidence)), 4)
        self.source = source
        self.before_score = round(before_score, 4)
        self.after_score = round(after_score, 4)
        self.passes_gate = self.delta >= MIN_REAL_WORLD_GAIN

    def to_dict(self) -> Dict[str, Any]:
        return {
            "delta": self.delta,
            "confidence": self.confidence,
            "source": self.source,
            "before_score": self.before_score,
            "after_score": self.after_score,
            "passes_gate": self.passes_gate,
            "min_gain_threshold": MIN_REAL_WORLD_GAIN,
        }

    def __repr__(self) -> str:
        gate = "✅" if self.passes_gate else "⛔"
        return (
            f"ValueAssessment({gate} delta={self.delta:+.4f}, "
            f"conf={self.confidence:.2f}, src={self.source!r})"
        )


# ---------------------------------------------------------------------------
# Confidence estimation
# ---------------------------------------------------------------------------

def _estimate_confidence(
    before: Dict[str, Any],
    after: Dict[str, Any],
) -> tuple[float, str]:
    """Estimate how reliable a value assessment is.

    Returns (confidence, dominant_source).
    Higher confidence when more signal sources are present in both snapshots.
    """
    sources: List[str] = []
    n_before = before.get("n_journal_entries", 0)
    n_after = after.get("n_journal_entries", 0)

    if n_before >= 3 and n_after >= 3:
        sources.append("ci")
    if before.get("win_rate") is not None or after.get("win_rate") is not None:
        sources.append("trading")
    if before.get("runtime_score") is not None and after.get("runtime_score") is not None:
        sources.append("runtime")

    # More signal sources → higher confidence
    confidence = min(1.0, 0.3 + 0.25 * len(sources))

    # Scale down when journal coverage is thin
    if n_before < 5 or n_after < 5:
        confidence *= 0.7

    source = "+".join(sources) if sources else "ci_only"
    return round(confidence, 3), source


# ---------------------------------------------------------------------------
# Core evaluation
# ---------------------------------------------------------------------------

def evaluate(
    before_snapshot: Dict[str, Any],
    after_snapshot: Dict[str, Any],
) -> ValueAssessment:
    """Compare two RealitySnapshots and produce a ValueAssessment.

    Parameters
    ----------
    before_snapshot : RealitySnapshot captured before the evolution commit
    after_snapshot  : RealitySnapshot captured after the evolution commit

    Returns a ValueAssessment with delta, confidence, and gate result.

    Phase 8.5 upgrade
    -----------------
    * ``confidence`` is now taken directly from ``avg_confidence`` in the
      snapshot if signal_integrity_engine populated it; otherwise falls back
      to the internal heuristic.
    * ``delta`` is weighted by confidence (confidence-weighted delta), so
      noisy signals produce smaller apparent improvements.
    * When ``avg_confidence < SIE_MIN_CONFIDENCE_GATE`` (0.50), the assessment
      is forced to ``passes_gate = False`` regardless of raw delta.
    """
    before_score = objective_engine.score_outcome(before_snapshot)
    after_score = objective_engine.score_outcome(after_snapshot)
    raw_delta = after_score - before_score
    heuristic_confidence, source = _estimate_confidence(before_snapshot, after_snapshot)

    # Phase 8.5: prefer signal-integrity-derived confidence when available
    avg_conf_before = float(before_snapshot.get("avg_confidence", -1))
    avg_conf_after = float(after_snapshot.get("avg_confidence", -1))
    if avg_conf_before >= 0 and avg_conf_after >= 0:
        confidence = round((avg_conf_before + avg_conf_after) / 2.0, 4)
    else:
        confidence = heuristic_confidence

    # Phase 8.5: confidence-weighted delta — noisy signals shrink apparent gain
    weighted_delta = raw_delta * confidence

    assessment = ValueAssessment(
        delta=weighted_delta,
        confidence=confidence,
        source=source,
        before_score=before_score,
        after_score=after_score,
    )

    # Phase 8.5: hard gate — below minimum confidence, never passes
    try:
        from nibblebots.signal_integrity_engine import SIE_MIN_CONFIDENCE_GATE  # noqa: PLC0415
        if confidence < SIE_MIN_CONFIDENCE_GATE:
            assessment.passes_gate = False
    except Exception:  # noqa: BLE001
        pass

    return assessment


def evaluate_single(after_snapshot: Dict[str, Any]) -> ValueAssessment:
    """Evaluate improvement when we only have the 'after' snapshot.

    Phase 18.5 upgrade
    ------------------
    When value history exists, we use the rolling average of recent
    ``before_score`` values as the warm baseline instead of a static 0.5.
    This produces more accurate assessments when there is prior context —
    for example, if the last 10 cycles averaged 0.62, a new score of 0.65
    correctly registers as a modest improvement rather than a large one
    against the naive 0.5 baseline.

    Confidence is still halved (reflecting the absence of a true before
    snapshot) but the half-life is taken against the richer baseline.
    """
    # Phase 18.5: attempt to build a warm baseline from history
    warm_before: Optional[Dict[str, Any]] = None
    try:
        history = read_history(last_n=20)
        if len(history) >= 3:
            before_scores = [
                h["before_score"]
                for h in history
                if "before_score" in h
            ]
            if len(before_scores) >= 3:
                avg_before = sum(before_scores) / len(before_scores)
                # Build a synthetic snapshot that reflects the historical mean
                warm_before = {
                    "pass_rate": max(0.0, min(1.0, avg_before)),
                    "ci_failure_trend": 0.0,
                    "runtime_score": avg_before,
                    "real_world_score": avg_before,
                    "drawdown": 0.0,
                    "n_journal_entries": len(before_scores),
                }
    except Exception:  # noqa: BLE001
        pass

    if warm_before is None:
        warm_before = {
            "pass_rate": 0.5,
            "ci_failure_trend": 0.0,
            "runtime_score": 0.5,
            "real_world_score": 0.5,
            "drawdown": 0.0,
            "n_journal_entries": 0,
        }

    assessment = evaluate(warm_before, after_snapshot)
    # Halve confidence since we have no true before snapshot
    assessment.confidence = round(assessment.confidence * 0.5, 3)
    # Re-evaluate gate with the reduced confidence
    assessment.passes_gate = assessment.delta >= MIN_REAL_WORLD_GAIN
    try:
        from nibblebots.signal_integrity_engine import SIE_MIN_CONFIDENCE_GATE  # noqa: PLC0415
        if assessment.confidence < SIE_MIN_CONFIDENCE_GATE * 0.5:
            assessment.passes_gate = False
    except Exception:  # noqa: BLE001
        pass
    return assessment


def blend_net_score(
    impact_net_score: float,
    after_snapshot: Dict[str, Any],
    before_snapshot: Optional[Dict[str, Any]] = None,
) -> float:
    """Blend impact_engine net_score with objective value score.

    Phase 8 formula:
        final_score = impact_net_score * (1 - α) + objective_delta * α

    Parameters
    ----------
    impact_net_score  : raw net_score from impact_engine
    after_snapshot    : snapshot after the proposed fix
    before_snapshot   : snapshot before the fix (None → uses neutral baseline)

    Returns the blended score.
    """
    if before_snapshot is not None:
        assessment = evaluate(before_snapshot, after_snapshot)
    else:
        assessment = evaluate_single(after_snapshot)

    # Normalise delta to [0, 1] scale (delta is in [-1, 1])
    normalised_delta = (assessment.delta + 1.0) / 2.0

    alpha = VALUE_BLEND_ALPHA * assessment.confidence  # scale by confidence
    blended = (impact_net_score * (1.0 - alpha) + normalised_delta * alpha)
    return round(blended, 4)


# ---------------------------------------------------------------------------
# History persistence (for causality_tracker and delayed analysis)
# ---------------------------------------------------------------------------

def record_assessment(
    assessment: ValueAssessment,
    commit_sha: str = "",
    fix_types: Optional[List[str]] = None,
) -> None:
    """Append a ValueAssessment to the history file."""
    entry = assessment.to_dict()
    entry["commit_sha"] = commit_sha
    entry["fix_types"] = fix_types or []
    try:
        with _HISTORY_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def read_history(last_n: int = _MAX_HISTORY) -> List[Dict[str, Any]]:
    """Read the most recent value assessment history entries."""
    if not _HISTORY_FILE.exists():
        return []
    try:
        lines = [
            json.loads(ln)
            for ln in _HISTORY_FILE.read_text(encoding="utf-8").splitlines()
            if ln.strip()
        ]
        return lines[-last_n:]
    except (OSError, json.JSONDecodeError):
        return []


if __name__ == "__main__":
    print('Running value_engine.py')
