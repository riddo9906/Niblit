#!/usr/bin/env python3
"""Phase Ω.5 Reality Validation Engine."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_STATE_PATH = Path(__file__).resolve().parent.parent / "reality_validation_state.json"


@dataclass
class RealityValidationReport:
    reality_alignment: float
    prediction_accuracy: float
    calibration_error: float
    synthetic_feedback_risk: float
    resonance_contamination: float
    confidence_reliability: float
    rationale: str
    confidence: float
    stability_impact: float
    coherence_impact: float
    causal_trace_metadata: dict[str, Any]
    explanation: str
    epoch: int
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reality_alignment": round(self.reality_alignment, 4),
            "prediction_accuracy": round(self.prediction_accuracy, 4),
            "calibration_error": round(self.calibration_error, 4),
            "synthetic_feedback_risk": round(self.synthetic_feedback_risk, 4),
            "resonance_contamination": round(self.resonance_contamination, 4),
            "confidence_reliability": round(self.confidence_reliability, 4),
            "rationale": self.rationale,
            "confidence": round(self.confidence, 4),
            "stability_impact": round(self.stability_impact, 4),
            "coherence_impact": round(self.coherence_impact, 4),
            "causal_trace_metadata": dict(self.causal_trace_metadata),
            "explanation": self.explanation,
            "epoch": self.epoch,
            "timestamp": self.timestamp,
        }


class RealityValidationEngine:
    """Prevent recursive self-delusion by grounding predictions to outcomes."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._samples: list[dict[str, float]] = []
        self._last_report: RealityValidationReport | None = None
        self._run_count = 0
        self._load_state()

    def verify_predictions(
        self,
        prediction: float,
        outcome: float,
        confidence: float,
        resonance_weight: float = 0.0,
    ) -> dict[str, float]:
        err = abs(float(prediction) - float(outcome))
        rec = {
            "prediction": float(prediction),
            "outcome": float(outcome),
            "confidence": max(0.0, min(1.0, float(confidence))),
            "error": err,
            "resonance_weight": max(0.0, min(1.0, float(resonance_weight))),
            "ts": time.time(),
        }
        with self._lock:
            self._samples.append(rec)
            if len(self._samples) > 1000:
                self._samples = self._samples[-1000:]
        return self.compare_expectation_vs_outcome(prediction, outcome)

    def verify_prediction(
        self, prediction: float, outcome: float, confidence: float, resonance_weight: float = 0.0
    ) -> dict[str, float]:
        return self.verify_predictions(prediction, outcome, confidence, resonance_weight)

    def compare_expectation_vs_outcome(self, prediction: float, outcome: float) -> dict[str, float]:
        err = abs(float(prediction) - float(outcome))
        return {"absolute_error": err, "alignment": max(0.0, 1.0 - err)}

    def calibrate_confidence(self, rows: list[dict[str, float]]) -> float:
        if not rows:
            return 0.5
        return min(1.0, sum(abs(r["confidence"] - max(0.0, 1.0 - r["error"])) for r in rows) / len(rows))

    def detect_synthetic_feedback(self, rows: list[dict[str, float]]) -> float:
        if not rows:
            return 0.0
        outcomes = [round(r["outcome"], 5) for r in rows]
        dominant = max(outcomes.count(v) for v in set(outcomes))
        return min(1.0, dominant / len(outcomes))

    def detect_resonance_contamination(self, rows: list[dict[str, float]]) -> float:
        if not rows:
            return 0.0
        return min(1.0, sum(r["resonance_weight"] for r in rows) / len(rows))

    def validate_cycle(self) -> RealityValidationReport:
        with self._lock:
            rows = list(self._samples[-120:])
            self._run_count += 1

        if not rows:
            report = RealityValidationReport(
                reality_alignment=0.5,
                prediction_accuracy=0.5,
                calibration_error=0.5,
                synthetic_feedback_risk=0.0,
                resonance_contamination=0.0,
                confidence_reliability=0.5,
                rationale="Insufficient grounded observations.",
                confidence=0.4,
                stability_impact=0.4,
                coherence_impact=0.4,
                causal_trace_metadata={"sample_count": 0},
                explanation="No recent prediction/outcome pairs.",
                epoch=_safe_epoch(),
            )
        else:
            mean_error = sum(r["error"] for r in rows) / len(rows)
            prediction_accuracy = max(0.0, 1.0 - mean_error)
            calibration_error = self.calibrate_confidence(rows)
            synthetic_risk = self.detect_synthetic_feedback(rows)
            resonance_risk = self.detect_resonance_contamination(rows)
            reality_alignment = max(
                0.0, min(1.0, 1.0 - (0.45 * calibration_error + 0.25 * synthetic_risk + 0.3 * resonance_risk))
            )
            confidence_reliability = max(0.0, 1.0 - calibration_error)
            report = RealityValidationReport(
                reality_alignment=reality_alignment,
                prediction_accuracy=prediction_accuracy,
                calibration_error=calibration_error,
                synthetic_feedback_risk=synthetic_risk,
                resonance_contamination=resonance_risk,
                confidence_reliability=confidence_reliability,
                rationale=self._rationale(reality_alignment, calibration_error, synthetic_risk, resonance_risk),
                confidence=max(0.0, min(1.0, confidence_reliability)),
                stability_impact=max(0.0, min(1.0, reality_alignment)),
                coherence_impact=max(0.0, min(1.0, reality_alignment)),
                causal_trace_metadata={"sample_count": len(rows), "mean_error": round(mean_error, 4)},
                explanation="Prediction/Outcome verification with contamination and calibration checks.",
                epoch=_safe_epoch(),
            )

        with self._lock:
            self._last_report = report
            self._save_state()
        self._emit(report)
        return report

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "run_count": self._run_count,
                "pair_count": len(self._samples),
                "last_report": self._last_report.to_dict() if self._last_report else None,
                "confidence": self._last_report.confidence if self._last_report else 0.0,
                "stability_impact": self._last_report.stability_impact if self._last_report else 0.0,
                "coherence_impact": self._last_report.coherence_impact if self._last_report else 0.0,
                "causal_trace_metadata": self._last_report.causal_trace_metadata if self._last_report else {},
                "rationale": self._last_report.rationale if self._last_report else "not_initialized",
            }

    @staticmethod
    def _rationale(alignment: float, calibration: float, synthetic: float, resonance: float) -> str:
        if alignment < 0.45:
            return (
                f"Low reality alignment calibration={calibration:.2f} "
                f"synthetic={synthetic:.2f} resonance={resonance:.2f}"
            )
        return f"Reality alignment stable calibration={calibration:.2f}"

    def _emit(self, report: RealityValidationReport) -> None:
        try:
            from modules.event_bus import EVENT_REALITY_VALIDATED, NiblitEvent, get_event_bus

            get_event_bus().publish(
                NiblitEvent(
                    type=EVENT_REALITY_VALIDATED,
                    source="reality_validation_engine",
                    payload={
                        "reality_alignment": report.reality_alignment,
                        "prediction_accuracy": report.prediction_accuracy,
                        "confidence": report.confidence,
                        "stability_impact": report.stability_impact,
                        "coherence_impact": report.coherence_impact,
                        "causal_trace_metadata": report.causal_trace_metadata,
                        "rationale": report.rationale,
                        "epoch": report.epoch,
                    },
                )
            )
        except Exception:
            pass

    def _save_state(self) -> None:
        try:
            data = {
                "run_count": self._run_count,
                "sample_count": len(self._samples),
                "last_report": self._last_report.to_dict() if self._last_report else None,
            }
            tmp = _STATE_PATH.with_suffix(".json.tmp")
            with tmp.open("w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            tmp.replace(_STATE_PATH)
        except Exception:
            pass

    def _load_state(self) -> None:
        try:
            if not _STATE_PATH.exists():
                return
            with _STATE_PATH.open(encoding="utf-8") as fh:
                data = json.load(fh)
            self._run_count = int(data.get("run_count", 0))
        except Exception:
            pass


def _safe_epoch() -> int:
    try:
        from modules.unified_cognitive_state import get_unified_state

        return int(get_unified_state().status().get("epoch", 0))
    except Exception:
        return 0


_rve: RealityValidationEngine | None = None
_rve_lock = threading.Lock()


def get_reality_validation_engine() -> RealityValidationEngine:
    global _rve
    with _rve_lock:
        if _rve is None:
            _rve = RealityValidationEngine()
    return _rve
