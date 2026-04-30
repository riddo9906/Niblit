#!/usr/bin/env python3
"""modules/meta_engine.py — Meta-Cognition Layer for Niblit.

The MetaEngine sits *above* the EvaluationEngine and DecisionEngine.  It
periodically examines the system's own decision history and asks:

    "Why am I making these decisions?"
    "Should I change how I decide, not just what I decide?"

It operates at the level of *behavioral patterns*, not individual outcomes,
giving Niblit the ability to:

1. **Detect over-reliance** — when one advisor wins >70 % of the time, the
   MetaEngine nudges competing advisors' weights upward to restore diversity.

2. **Detect low-confidence drift** — a falling rolling-average quality score
   triggers a conservative reset (decay LLM weight, reinforce memory).

3. **Detect coherence drift** — if outcome variance is high and the dominant
   advisor keeps changing, flag as "unstable" and tighten exploration.

4. **Trajectory scoring** — compute a linear quality *slope* over the last
   ``_TRAJECTORY_WINDOW`` decisions; a positive slope → reward diversity,
   negative slope → tighten weights.

5. **Diagnostics** — write a human-readable ``decision_diagnosis`` string to
   ``NiblitState.identity["meta_diagnosis"]`` so any status endpoint can
   surface the reason for current behavior.

6. **Coherence enforcement** — penalise the weight of an advisor that recently
   produced a contradictory outcome (win followed by poor) to reduce
   flip-flopping.

Public API
----------
``MetaInsight``
    Immutable snapshot produced by one ``analyze()`` call.

``MetaEngine.analyze() → MetaInsight``
    Run one meta-analysis cycle and apply any resulting weight adjustments.

``MetaEngine.on_response_complete(event)``
    EventBus listener — call ``analyze()`` every ``_ANALYZE_EVERY`` events.

``get_meta_engine(**kwargs) → MetaEngine``
    Process-level singleton.

Configuration (environment variables)::

    NIBLIT_META_ANALYZE_EVERY   — analyze every N response.complete events
                                  (default 10)
    NIBLIT_META_RELIANCE_THRESH — advisor dominance ratio that triggers
                                  rebalancing (default 0.70)
    NIBLIT_META_NUDGE_DELTA     — weight delta applied during rebalancing
                                  (default 0.03)
    NIBLIT_META_TRAJECTORY_WIN  — rolling window for quality slope calculation
                                  (default 20)
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("MetaEngine")

# ── Configuration ─────────────────────────────────────────────────────────────

_ANALYZE_EVERY      = int(float(os.environ.get("NIBLIT_META_ANALYZE_EVERY",   "10")))
_RELIANCE_THRESH    = float(os.environ.get("NIBLIT_META_RELIANCE_THRESH",     "0.70"))
_NUDGE_DELTA        = float(os.environ.get("NIBLIT_META_NUDGE_DELTA",         "0.03"))
_TRAJECTORY_WINDOW  = int(float(os.environ.get("NIBLIT_META_TRAJECTORY_WIN",  "20")))

# ── Optional dependency imports ───────────────────────────────────────────────

try:
    from modules.event_bus import (
        get_event_bus as _get_event_bus,
        NiblitEvent as _NiblitEvent,
        EVENT_RESPONSE_COMPLETE,
        EVENT_META_ANALYSIS_COMPLETE,
    )
    _EVENT_BUS_AVAILABLE = True
except ImportError:
    _get_event_bus = None  # type: ignore[assignment]
    _NiblitEvent = None  # type: ignore[assignment,misc]
    EVENT_RESPONSE_COMPLETE = "response.complete"
    EVENT_META_ANALYSIS_COMPLETE = "meta.analysis.complete"
    _EVENT_BUS_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# MetaInsight
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MetaInsight:
    """Immutable snapshot of one MetaEngine analysis cycle.

    Attributes
    ----------
    diagnosis:          Human-readable summary of current behavior.
    patterns_detected:  List of detected pattern names.
    quality_slope:      Linear quality trend over last N decisions.
                        Positive → improving; Negative → degrading.
    dominant_advisor:   Which advisor won most in the analysis window.
    dominance_ratio:    Fraction of wins held by dominant_advisor.
    weight_adjustments: Per-advisor delta applied this cycle.
    ts:                 UNIX timestamp of the analysis.
    """

    diagnosis: str
    patterns_detected: List[str] = field(default_factory=list)
    quality_slope: float = 0.0
    dominant_advisor: str = "unknown"
    dominance_ratio: float = 0.0
    weight_adjustments: Dict[str, float] = field(default_factory=dict)
    ts: int = field(default_factory=lambda: int(time.time()))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "diagnosis": self.diagnosis,
            "patterns_detected": self.patterns_detected,
            "quality_slope": round(self.quality_slope, 4),
            "dominant_advisor": self.dominant_advisor,
            "dominance_ratio": round(self.dominance_ratio, 3),
            "weight_adjustments": {k: round(v, 4) for k, v in self.weight_adjustments.items()},
            "ts": self.ts,
        }


# ─────────────────────────────────────────────────────────────────────────────
# MetaEngine
# ─────────────────────────────────────────────────────────────────────────────

class MetaEngine:
    """Meta-cognition layer — analyzes behavioral patterns, not individual outcomes.

    Subscribes to ``response.complete`` events and runs an analysis cycle
    every ``_ANALYZE_EVERY`` events.  Adjusts advisor weights via the
    EvaluationEngine's ``reinforce()`` method so corrections flow through
    the same learning loop as regular feedback.

    Args:
        evaluation_engine:  :class:`~modules.evaluation_engine.EvaluationEngine`
                            instance to query history and adjust weights.
        niblit_state:       :class:`~modules.niblit_state.NiblitState` instance
                            where diagnostic strings are written.
        cognitive_identity: :class:`~modules.cognitive_identity.CognitiveIdentity`
                            instance to read/apply the decision_policy.
    """

    def __init__(
        self,
        evaluation_engine: Optional[Any] = None,
        niblit_state: Optional[Any] = None,
        cognitive_identity: Optional[Any] = None,
    ) -> None:
        self._eval = evaluation_engine
        self._state = niblit_state
        self._identity = cognitive_identity
        self._lock = threading.Lock()
        self._event_counter = 0
        self._last_insight: Optional[MetaInsight] = None
        self._analysis_count = 0

        # Subscribe to response.complete events.
        if _EVENT_BUS_AVAILABLE and _get_event_bus is not None:
            try:
                _get_event_bus().subscribe(
                    EVENT_RESPONSE_COMPLETE,
                    self.on_response_complete,
                )
                log.info("[MetaEngine] Subscribed to response.complete events")
            except Exception as exc:
                log.debug("[MetaEngine] Event subscription failed: %s", exc)

        log.info(
            "[MetaEngine] Initialised — meta-cognition active (analyze every %d)",
            _ANALYZE_EVERY,
        )

    # ── Event listener ────────────────────────────────────────────────────────

    def on_response_complete(self, event: Any) -> None:
        """Called by EventBus after each decision cycle.

        Increments the event counter and triggers ``analyze()`` every
        ``_ANALYZE_EVERY`` events.
        """
        with self._lock:
            self._event_counter += 1
            should_analyze = (self._event_counter % _ANALYZE_EVERY == 0)

        if should_analyze:
            try:
                self.analyze()
            except Exception as exc:
                log.debug("[MetaEngine] analyze() failed: %s", exc)

    # ── Primary API ───────────────────────────────────────────────────────────

    def analyze(self) -> MetaInsight:
        """Run one meta-analysis cycle.

        Examines decision history from the EvaluationEngine, detects
        behavioral patterns, applies corrective weight adjustments, updates
        the identity decision_policy, and writes a diagnosis to NiblitState.

        Returns:
            :class:`MetaInsight` with the analysis results.
        """
        history = self._get_history()
        if not history:
            insight = MetaInsight(
                diagnosis="Insufficient history for meta-analysis.",
                quality_slope=0.0,
            )
            self._publish(insight)
            return insight

        patterns: List[str] = []
        weight_adjustments: Dict[str, float] = {}

        # ── 1. Dominance analysis ─────────────────────────────────────────────
        dominant_advisor, dominance_ratio = self._detect_dominance(history)
        if dominance_ratio >= _RELIANCE_THRESH:
            patterns.append(f"over_reliance:{dominant_advisor}")
            # Nudge all other advisors upward to restore competition.
            adjustments = self._rebalance_weights(dominant_advisor)
            weight_adjustments.update(adjustments)

        # ── 2. Quality trajectory ─────────────────────────────────────────────
        scores = [r["quality_score"] for r in history]
        slope = self._linear_slope(scores[-_TRAJECTORY_WINDOW:])
        if slope < -0.005:
            patterns.append("quality_degradation")
            # Conservative correction: reinforce memory, decay LLM.
            adj = self._apply_conservative_correction()
            weight_adjustments.update(adj)
        elif slope > 0.005:
            patterns.append("quality_improving")

        # ── 3. Coherence drift ────────────────────────────────────────────────
        coherence_ok, flip_advisor = self._detect_coherence_drift(history)
        if not coherence_ok:
            patterns.append(f"coherence_drift:{flip_advisor}")
            # Penalise the flip-flopping advisor.
            if self._eval is not None and flip_advisor:
                self._eval.reinforce(flip_advisor, -_NUDGE_DELTA)
                weight_adjustments[flip_advisor] = (
                    weight_adjustments.get(flip_advisor, 0.0) - _NUDGE_DELTA
                )

        # ── 4. Low-confidence plateau ─────────────────────────────────────────
        recent_window = scores[-10:] if len(scores) >= 10 else scores
        avg_recent = sum(recent_window) / len(recent_window) if recent_window else 0.5
        if avg_recent < 0.40:
            patterns.append("low_confidence_plateau")
            # Boost memory + reasoning to reduce LLM over-dependence.
            if self._eval is not None:
                for advisor in ("memory", "reasoning"):
                    self._eval.reinforce(advisor, _NUDGE_DELTA)
                    weight_adjustments[advisor] = (
                        weight_adjustments.get(advisor, 0.0) + _NUDGE_DELTA
                    )

        # ── 5. Update decision_policy in CognitiveIdentity ───────────────────
        self._update_decision_policy(patterns, slope, avg_recent)

        # ── 6. Build diagnosis string ─────────────────────────────────────────
        diagnosis = self._build_diagnosis(
            patterns, dominant_advisor, dominance_ratio, slope, avg_recent
        )

        insight = MetaInsight(
            diagnosis=diagnosis,
            patterns_detected=patterns,
            quality_slope=slope,
            dominant_advisor=dominant_advisor,
            dominance_ratio=dominance_ratio,
            weight_adjustments=weight_adjustments,
        )

        # Write diagnosis to shared state.
        if self._state is not None and hasattr(self._state, "update_identity"):
            try:
                self._state.update_identity(
                    meta_diagnosis=diagnosis,
                    meta_patterns=patterns,
                    meta_quality_slope=round(slope, 4),
                    meta_ts=insight.ts,
                )
            except Exception:
                pass

        with self._lock:
            self._last_insight = insight
            self._analysis_count += 1

        self._publish(insight)

        log.info(
            "[MetaEngine] cycle=%d diagnosis=%r patterns=%s slope=%.4f",
            self._analysis_count, diagnosis[:60], patterns, slope,
        )
        return insight

    def get_last_insight(self) -> Optional[MetaInsight]:
        """Return the most recent :class:`MetaInsight`, or ``None``."""
        with self._lock:
            return self._last_insight

    def status(self) -> Dict[str, Any]:
        """Return serialisable status for health/status endpoints."""
        with self._lock:
            return {
                "analysis_count": self._analysis_count,
                "event_counter": self._event_counter,
                "last_insight": self._last_insight.to_dict() if self._last_insight else None,
            }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_history(self) -> List[Dict[str, Any]]:
        """Fetch the rolling decision history from EvaluationEngine."""
        if self._eval is None:
            return []
        try:
            with self._eval._lock:  # pylint: disable=protected-access
                return [r.to_dict() for r in self._eval._history]  # pylint: disable=protected-access
        except Exception:
            return []

    def _detect_dominance(
        self, history: List[Dict[str, Any]]
    ) -> Tuple[str, float]:
        """Return (dominant_advisor, dominance_ratio) for *history*."""
        counts: Dict[str, int] = {}
        for r in history:
            adv = r.get("chosen_advisor", "unknown")
            counts[adv] = counts.get(adv, 0) + 1
        if not counts:
            return "unknown", 0.0
        dominant = max(counts, key=counts.get)  # type: ignore[arg-type]
        ratio = counts[dominant] / len(history)
        return dominant, ratio

    def _rebalance_weights(self, dominant_advisor: str) -> Dict[str, float]:
        """Nudge all non-dominant advisors upward.  Returns deltas applied."""
        if self._eval is None:
            return {}
        adjustments: Dict[str, float] = {}
        current_weights = self._eval.get_weights()
        for advisor in current_weights:
            if advisor != dominant_advisor:
                self._eval.reinforce(advisor, _NUDGE_DELTA)
                adjustments[advisor] = _NUDGE_DELTA
        log.debug(
            "[MetaEngine] Rebalanced weights — dominant=%s (nudged %d advisors)",
            dominant_advisor, len(adjustments),
        )
        return adjustments

    def _linear_slope(self, values: List[float]) -> float:
        """Estimate the linear slope of *values* using least-squares.

        Returns 0.0 when fewer than 2 data points are available.
        """
        n = len(values)
        if n < 2:
            return 0.0
        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / n
        num = sum((i - x_mean) * (v - y_mean) for i, v in enumerate(values))
        den = sum((i - x_mean) ** 2 for i in range(n))
        return num / den if den != 0 else 0.0

    def _detect_coherence_drift(
        self, history: List[Dict[str, Any]]
    ) -> Tuple[bool, str]:
        """Detect whether one advisor frequently flip-flops (win then poor).

        Returns (coherent: bool, flip_advisor: str).
        A flip is defined as the same advisor winning in decision N but
        having outcome ``"poor"`` in decision N+1.
        """
        flip_counts: Dict[str, int] = {}
        for i in range(len(history) - 1):
            curr = history[i]
            nxt = history[i + 1]
            if (
                curr.get("chosen_advisor") == nxt.get("chosen_advisor")
                and nxt.get("outcome") == "poor"
            ):
                adv = curr.get("chosen_advisor", "")
                flip_counts[adv] = flip_counts.get(adv, 0) + 1

        if not flip_counts:
            return True, ""

        worst = max(flip_counts, key=flip_counts.get)  # type: ignore[arg-type]
        # Flag as incoherent if flip rate > 30 % of history.
        flip_rate = flip_counts[worst] / max(len(history) - 1, 1)
        if flip_rate > 0.30:
            return False, worst
        return True, ""

    def _apply_conservative_correction(self) -> Dict[str, float]:
        """Reinforce memory; decay LLM — called during quality degradation."""
        if self._eval is None:
            return {}
        self._eval.reinforce("memory", _NUDGE_DELTA)
        self._eval.reinforce("reasoning", _NUDGE_DELTA)
        self._eval.reinforce("llm", -_NUDGE_DELTA)
        return {"memory": _NUDGE_DELTA, "reasoning": _NUDGE_DELTA, "llm": -_NUDGE_DELTA}

    def _update_decision_policy(
        self,
        patterns: List[str],
        slope: float,
        avg_quality: float,
    ) -> None:
        """Evolve the CognitiveIdentity decision_policy from detected patterns."""
        if self._identity is None or not hasattr(self._identity, "update_decision_policy"):
            return
        try:
            # Over-reliance → increase exploration to restore diversity.
            exploration_nudge = 0.0
            if any("over_reliance" in p for p in patterns):
                exploration_nudge = +0.02
            elif "quality_improving" in patterns:
                exploration_nudge = -0.01  # shrink exploration when going well

            # Quality direction → risk_preference.
            if slope < -0.005:
                risk_pref = "conservative"
            elif slope > 0.005 and avg_quality > 0.55:
                risk_pref = "bold"
            else:
                risk_pref = "balanced"

            # Priority mode from current identity decision_style.
            style = ""
            if self._identity is not None and hasattr(self._identity, "get_decision_style"):
                style = self._identity.get_decision_style()
            priority_mode = {
                "goal-focused":     "goal_first",
                "analytical":       "quality_first",
                "language-centric": "balanced",
            }.get(style, "balanced")

            self._identity.update_decision_policy(
                exploration_nudge=exploration_nudge,
                risk_preference=risk_pref,
                priority_mode=priority_mode,
            )
        except Exception as exc:
            log.debug("[MetaEngine] update_decision_policy failed: %s", exc)

    @staticmethod
    def _build_diagnosis(
        patterns: List[str],
        dominant: str,
        ratio: float,
        slope: float,
        avg: float,
    ) -> str:
        """Produce a human-readable one-line diagnosis."""
        if not patterns:
            return (
                f"System stable. Dominant={dominant} ({ratio:.0%}), "
                f"slope={slope:+.4f}, avg_quality={avg:.2f}"
            )
        parts = []
        for p in patterns:
            if p.startswith("over_reliance:"):
                adv = p.split(":", 1)[1]
                parts.append(f"⚠️ Over-reliance on {adv!r} ({ratio:.0%} wins)")
            elif p == "quality_degradation":
                parts.append(f"📉 Quality declining (slope={slope:+.4f})")
            elif p == "quality_improving":
                parts.append(f"📈 Quality improving (slope={slope:+.4f})")
            elif p.startswith("coherence_drift:"):
                adv = p.split(":", 1)[1]
                parts.append(f"🔄 Coherence drift in {adv!r}")
            elif p == "low_confidence_plateau":
                parts.append(f"😶 Low-confidence plateau (avg={avg:.2f})")
        return " | ".join(parts)

    def _publish(self, insight: MetaInsight) -> None:
        """Emit meta.analysis.complete event."""
        if _EVENT_BUS_AVAILABLE and _get_event_bus is not None:
            try:
                _get_event_bus().publish(_NiblitEvent(
                    type=EVENT_META_ANALYSIS_COMPLETE,
                    source="meta_engine",
                    payload=insight.to_dict(),
                ))
            except Exception:
                pass


# ── Singleton ─────────────────────────────────────────────────────────────────

_meta_engine: Optional[MetaEngine] = None
_meta_lock = threading.Lock()


def get_meta_engine(**kwargs: Any) -> MetaEngine:
    """Return the process-level :class:`MetaEngine` singleton.

    Note: kwargs are only applied on first call.
    """
    global _meta_engine  # pylint: disable=global-statement
    with _meta_lock:
        if _meta_engine is None:
            _meta_engine = MetaEngine(**kwargs)
        return _meta_engine


if __name__ == "__main__":
    from modules.evaluation_engine import get_evaluation_engine
    from modules.cognitive_identity import get_cognitive_identity

    ident = get_cognitive_identity()
    eval_eng = get_evaluation_engine(identity=ident)
    meta = get_meta_engine(evaluation_engine=eval_eng, cognitive_identity=ident)

    # Simulate 15 scoring cycles to fill history.
    from modules.evaluation_engine import EvaluationRecord
    import time as _t
    for i in range(15):
        rec = eval_eng.score_outcome(
            user_input="test query",
            response="A decent response about the topic." if i % 3 != 0 else "",
        )

    insight = meta.analyze()
    print("Diagnosis:", insight.diagnosis)
    print("Patterns:", insight.patterns_detected)
    print("Quality slope:", insight.quality_slope)
    print("Weight adjustments:", insight.weight_adjustments)
