#!/usr/bin/env python3
"""
modules/reflection_engine.py — Phase Ω Unified Reflection Layer

Niblit must continuously reason *about itself*:

    - What did it learn this session?
    - What failed, and why?
    - Which strategies drifted?
    - Which assumptions became stale?
    - Where is confidence falsely high?
    - Where did resonance cause instability?
    - Where did goals become incoherent?

Outputs
-------
    ``ReflectionReport`` — a structured self-critique::

        summary           : str   — plain English narrative
        failures_detected : list  — what went wrong
        strategy_drifts   : list  — which strategies diverged
        stale_assumptions : list  — outdated priors detected
        overconfident_areas: list — domains where confidence > evidence
        adaptation_proposals: list — concrete next-action suggestions
        governance_notes  : list  — flags for the constitutional layer
        overall_health    : float — 0.0–1.0 system health estimate

Downstream effects
------------------
Reflection influences (via event bus):
    governance        — raises flags when drift is detected
    memory            — marks stale memories for decay
    model trust       — reduces trust for consistently failing models
    exploration rate  — lowers exploration when health is poor
    objective updates — proposes re-alignment when goals incoherent

Configuration (env vars)
------------------------
    NIBLIT_RE_ENABLED       — "0" to disable (default 1)
    NIBLIT_RE_CADENCE       — number of turns between auto-reflections (default 20)

Usage::

    from modules.reflection_engine import get_reflection_engine

    re = get_reflection_engine()
    re.record_turn(quality=0.6, mode="analytical", intent="market_analysis",
                   model_used="llama3", tool_success=True)
    if re.should_reflect():
        report = re.reflect()
        print(report.summary)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional

log = logging.getLogger(__name__)

_ENABLED: bool = os.getenv("NIBLIT_RE_ENABLED", "1").strip() not in ("0", "false")
_CADENCE: int = int(os.getenv("NIBLIT_RE_CADENCE", "20"))
_REFLECTION_HEALTH_ESCALATION_THRESHOLD: float = 0.5

_EMA = 0.15


# ── TurnRecord ────────────────────────────────────────────────────────────────

@dataclass
class TurnRecord:
    quality: float
    mode: str
    intent: str
    model_used: str
    tool_success: Optional[bool]
    timestamp: float = field(default_factory=time.time)


# ── ReflectionReport ──────────────────────────────────────────────────────────

@dataclass
class ReflectionReport:
    """A structured self-critique produced by the reflection engine."""
    summary: str
    failures_detected: List[str]
    strategy_drifts: List[str]
    stale_assumptions: List[str]
    overconfident_areas: List[str]
    adaptation_proposals: List[str]
    governance_notes: List[str]
    overall_health: float     # 0.0–1.0
    timestamp: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())

    def to_dict(self) -> Dict:
        return {
            "summary": self.summary,
            "failures_detected": self.failures_detected,
            "strategy_drifts": self.strategy_drifts,
            "stale_assumptions": self.stale_assumptions,
            "overconfident_areas": self.overconfident_areas,
            "adaptation_proposals": self.adaptation_proposals,
            "governance_notes": self.governance_notes,
            "overall_health": round(self.overall_health, 4),
            "timestamp": self.timestamp,
        }


# ── ReflectionEngine ─────────────────────────────────────────────────────────

class ReflectionEngine:
    """Continuous self-reflective reasoning layer.

    Collects turn-level observations and periodically generates
    :class:`ReflectionReport` instances that propagate back into
    governance, memory, model trust, and planning.

    Thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._turns: Deque[TurnRecord] = deque(maxlen=200)
        self._turn_count: int = 0
        self._reflect_count: int = 0
        self._last_quality_ema: float = 0.7
        self._quality_history: Deque[float] = deque(maxlen=50)
        self._mode_counts: Dict[str, int] = defaultdict(int)
        self._model_failures: Dict[str, int] = defaultdict(int)
        self._model_calls: Dict[str, int] = defaultdict(int)
        self._recent_reports: Deque[ReflectionReport] = deque(maxlen=5)
        log.debug("[ReflectionEngine] initialised (cadence=%d)", _CADENCE)

    # ── Observation intake ────────────────────────────────────────────────────

    def record_turn(
        self,
        quality: float,
        mode: str = "",
        intent: str = "",
        model_used: str = "",
        tool_success: Optional[bool] = None,
    ) -> None:
        """Record the outcome of one interaction turn."""
        if not _ENABLED:
            return
        with self._lock:
            self._turn_count += 1
            self._last_quality_ema = _EMA * quality + (1 - _EMA) * self._last_quality_ema
            self._quality_history.append(quality)
            self._mode_counts[mode] += 1
            if model_used:
                self._model_calls[model_used] += 1
                if quality < 0.4:
                    self._model_failures[model_used] += 1
            self._turns.append(TurnRecord(
                quality=quality, mode=mode, intent=intent,
                model_used=model_used, tool_success=tool_success,
            ))

    def should_reflect(self) -> bool:
        """Return True if it is time for an automatic reflection cycle."""
        if not _ENABLED:
            return False
        with self._lock:
            return self._turn_count > 0 and (self._turn_count % _CADENCE == 0)

    # ── Reflection ────────────────────────────────────────────────────────────

    def reflect(self) -> ReflectionReport:
        """Generate a full :class:`ReflectionReport`.

        Analyses recent turns for quality trends, model failures, mode imbalance,
        and potential overconfidence.

        Returns:
            :class:`ReflectionReport`
        """
        if not _ENABLED:
            return ReflectionReport(
                summary="Reflection engine disabled.",
                failures_detected=[], strategy_drifts=[],
                stale_assumptions=[], overconfident_areas=[],
                adaptation_proposals=[], governance_notes=[],
                overall_health=1.0,
            )

        with self._lock:
            quality_ema = self._last_quality_ema
            history = list(self._quality_history)
            mode_counts = dict(self._mode_counts)
            model_failures = dict(self._model_failures)
            model_calls = dict(self._model_calls)
            self._reflect_count += 1

        failures: List[str] = []
        drifts: List[str] = []
        stale: List[str] = []
        overconfident: List[str] = []
        proposals: List[str] = []
        governance_notes: List[str] = []

        # Quality trend
        if len(history) >= 10:
            recent_avg = sum(history[-10:]) / 10
            older_avg = sum(history[-20:-10]) / 10 if len(history) >= 20 else recent_avg
            if recent_avg < 0.5:
                failures.append(f"low_recent_quality (avg={recent_avg:.2f})")
                proposals.append("review model selection or context quality")
            if older_avg - recent_avg > 0.15:
                drifts.append(f"quality_degradation (Δ={older_avg - recent_avg:.2f})")
                proposals.append("trigger memory compression to reduce context noise")

        # Model failure rates
        for mid, fail_count in model_failures.items():
            calls = model_calls.get(mid, 1)
            fail_rate = fail_count / calls
            if fail_rate > 0.35:
                failures.append(f"model_high_failure_rate:{mid} ({fail_rate:.0%})")
                proposals.append(f"reduce trust weight for {mid}")
                governance_notes.append(f"flag model {mid} for trust review")

        # Mode imbalance
        total_turns = sum(mode_counts.values()) or 1
        dominant_mode = max(mode_counts, key=mode_counts.get) if mode_counts else ""
        dominant_frac = (mode_counts.get(dominant_mode, 0) / total_turns)
        if dominant_frac > 0.8 and dominant_mode:
            drifts.append(f"mode_saturation:{dominant_mode} ({dominant_frac:.0%} of turns)")
            proposals.append(f"diversify away from {dominant_mode} mode")

        # Overconfidence proxy: low failure count but low quality
        if quality_ema < 0.5 and sum(model_failures.values()) < 2:
            overconfident.append("quality_below_threshold_with_low_error_detection")
            stale.append("error_detection_thresholds_may_be_too_permissive")

        # Governance escalation
        if quality_ema < 0.4:
            governance_notes.append("quality_below_governance_floor — recommend stability review")

        health = _compute_health(quality_ema, failures, drifts)
        summary = (
            f"Reflection cycle #{self._reflect_count}: "
            f"health={health:.2f}, quality_ema={quality_ema:.2f}, "
            f"failures={len(failures)}, drifts={len(drifts)}, "
            f"proposals={len(proposals)}."
        )

        report = ReflectionReport(
            summary=summary,
            failures_detected=failures,
            strategy_drifts=drifts,
            stale_assumptions=stale,
            overconfident_areas=overconfident,
            adaptation_proposals=proposals,
            governance_notes=governance_notes,
            overall_health=health,
        )
        self._store_governed_memory(report)
        with self._lock:
            self._recent_reports.append(report)

        self._propagate(report)
        log.info("[ReflectionEngine] %s", summary)
        return report

    def last_report(self) -> Optional[ReflectionReport]:
        """Return the most recent reflection report, or None."""
        with self._lock:
            return self._recent_reports[-1] if self._recent_reports else None

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> Dict:
        with self._lock:
            return {
                "enabled": _ENABLED,
                "turn_count": self._turn_count,
                "reflect_count": self._reflect_count,
                "quality_ema": round(self._last_quality_ema, 4),
                "cadence": _CADENCE,
                "model_calls": dict(self._model_calls),
                "model_failures": dict(self._model_failures),
            }

    # ── Downstream propagation ────────────────────────────────────────────────

    def _propagate(self, report: ReflectionReport) -> None:
        """Feed reflection outputs back into other subsystems."""
        # Update model trust in Model Ecology
        try:
            from modules.model_ecology import get_model_ecology
            eco = get_model_ecology()
            for note in report.governance_notes:
                if "flag model " in note:
                    mid = note.split("flag model ")[-1].split(" ")[0]
                    eco.record_outcome(mid, success=False, quality=0.3)
        except Exception:
            pass

    def _store_governed_memory(self, report: ReflectionReport) -> None:
        try:
            from niblit_memory.governed_qdrant_memory import get_governed_qdrant_memory_cluster

            cluster = get_governed_qdrant_memory_cluster()
            cluster.write_memory(
                report.summary,
                memory_type="reflection_memory",
                payload={
                    "summary": report.summary,
                    "reflection_summary": report.summary,
                    "coherence_score": report.overall_health,
                    "advisor_lineage": report.governance_notes,
                    "replay_metadata": {
                        "decision_lineage": report.adaptation_proposals,
                        "causal_references": report.failures_detected + report.strategy_drifts,
                    },
                },
            )
        except Exception:
            pass

        # ── Cognitive escalation on low health (additive) ────────────────────
        # When reflection health is below threshold, synthesise improvement
        # guidance through the governed RouterV2 → LocalBrain path.
        if report.overall_health < _REFLECTION_HEALTH_ESCALATION_THRESHOLD:
            try:
                from modules.knowledge_gap_cognition import (
                    get_cognition_escalation_layer,
                    KnowledgeGapSignal,
                    GAP_CLASS_REFLECTION,
                )
                _cel = get_cognition_escalation_layer()
                _gap = KnowledgeGapSignal(
                    gap_class=GAP_CLASS_REFLECTION,
                    topic="system_reflection_improvement",
                    reason="low_reflection_health",
                    context={
                        "health": report.overall_health,
                        "failures": report.failures_detected[:5],
                        "drifts": report.strategy_drifts[:3],
                        "proposals": report.adaptation_proposals[:3],
                    },
                    confidence=report.overall_health,
                    source_module="reflection_engine",
                )
                _cel.escalate(_gap)
            except Exception:
                pass

        # Emit event
        try:
            from modules.event_bus import get_event_bus, NiblitEvent, EVENT_REFLECTION_COMPLETE
            get_event_bus().publish(NiblitEvent(
                type=EVENT_REFLECTION_COMPLETE,
                source="reflection_engine",
                payload={
                    "health": report.overall_health,
                    "failures": len(report.failures_detected),
                    "trace_id": f"reflection-{int(time.time())}",
                    "runtime_id": "reflection_engine",
                    "cognition_id": "reflection",
                    "source_module": "reflection_engine",
                    "event_category": "reflection",
                    "event_priority": "normal",
                },
            ))
        except Exception:
            pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_health(quality_ema: float, failures: list, drifts: list) -> float:
    penalty = len(failures) * 0.08 + len(drifts) * 0.05
    return max(0.0, min(1.0, quality_ema - penalty))


# ── Singleton ─────────────────────────────────────────────────────────────────
_re: Optional[ReflectionEngine] = None
_re_lock = threading.Lock()


def get_reflection_engine() -> ReflectionEngine:
    """Return the module-level :class:`ReflectionEngine` singleton."""
    global _re
    with _re_lock:
        if _re is None:
            _re = ReflectionEngine()
    return _re


if __name__ == "__main__":
    print('Running reflection_engine.py')
