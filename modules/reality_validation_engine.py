#!/usr/bin/env python3
"""Phase Ω.5 Reality Validation Engine."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RealityValidationReport:
    reality_score: float
    calibration_error: float
    synthetic_feedback_risk: float
    resonance_contamination_risk: float
    causal_verification_score: float
    findings: List[str]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reality_score": round(self.reality_score, 4),
            "calibration_error": round(self.calibration_error, 4),
            "synthetic_feedback_risk": round(self.synthetic_feedback_risk, 4),
            "resonance_contamination_risk": round(self.resonance_contamination_risk, 4),
            "causal_verification_score": round(self.causal_verification_score, 4),
            "findings": list(self.findings),
            "timestamp": self.timestamp,
        }


class RealityValidationEngine:
    """Separates true learning from self-reinforced false certainty."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pairs: List[Dict[str, float]] = []
        self._last_report: Optional[RealityValidationReport] = None
        self._run_count = 0

    def verify_prediction(
        self,
        prediction: float,
        outcome: float,
        confidence: float,
        resonance_weight: float = 0.0,
    ) -> Dict[str, float]:
        err = abs(float(prediction) - float(outcome))
        pair = {
            "prediction": float(prediction),
            "outcome": float(outcome),
            "confidence": max(0.0, min(1.0, float(confidence))),
            "error": err,
            "resonance_weight": max(0.0, min(1.0, float(resonance_weight))),
            "ts": time.time(),
        }
        with self._lock:
            self._pairs.append(pair)
            if len(self._pairs) > 500:
                self._pairs = self._pairs[-500:]
        return {"error": err, "calibrated_confidence": max(0.0, 1.0 - err)}

    def validate_cycle(self) -> RealityValidationReport:
        with self._lock:
            pairs = list(self._pairs[-100:])
            self._run_count += 1
        if not pairs:
            report = RealityValidationReport(
                reality_score=0.5,
                calibration_error=0.5,
                synthetic_feedback_risk=0.0,
                resonance_contamination_risk=0.0,
                causal_verification_score=0.5,
                findings=["insufficient_data"],
            )
            self._last_report = report
            self._emit(report)
            return report
        calibration = self._confidence_vs_reality_calibration(pairs)
        synthetic_risk = self._detect_synthetic_feedback(pairs)
        resonance_risk = self._resonance_contamination_risk(pairs)
        causal_score = max(0.0, 1.0 - (sum(p["error"] for p in pairs) / len(pairs)))
        findings: List[str] = []
        if calibration > 0.25:
            findings.append("confidence_reality_miscalibration")
        if synthetic_risk > 0.6:
            findings.append("synthetic_feedback_pattern_detected")
        if resonance_risk > 0.6:
            findings.append("resonance_contamination_risk")
        reality_score = max(
            0.0,
            min(1.0, 1.0 - calibration * 0.6 - synthetic_risk * 0.2 - resonance_risk * 0.2),
        )
        report = RealityValidationReport(
            reality_score=reality_score,
            calibration_error=calibration,
            synthetic_feedback_risk=synthetic_risk,
            resonance_contamination_risk=resonance_risk,
            causal_verification_score=causal_score,
            findings=findings,
        )
        with self._lock:
            self._last_report = report
        self._emit(report)
        return report

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "run_count": self._run_count,
                "pair_count": len(self._pairs),
                "last_report": self._last_report.to_dict() if self._last_report else None,
            }

    @staticmethod
    def _confidence_vs_reality_calibration(pairs: List[Dict[str, float]]) -> float:
        return min(
            1.0,
            sum(abs(p["confidence"] - max(0.0, 1.0 - p["error"])) for p in pairs) / len(pairs),
        )

    @staticmethod
    def _detect_synthetic_feedback(pairs: List[Dict[str, float]]) -> float:
        outcomes = [round(p["outcome"], 6) for p in pairs]
        if not outcomes:
            return 0.0
        dominant = max(outcomes.count(v) for v in set(outcomes))
        return min(1.0, dominant / len(outcomes))

    @staticmethod
    def _resonance_contamination_risk(pairs: List[Dict[str, float]]) -> float:
        if not pairs:
            return 0.0
        return min(1.0, sum(p["resonance_weight"] for p in pairs) / len(pairs))

    def _emit(self, report: RealityValidationReport) -> None:
        try:
            from modules.event_bus import EVENT_REALITY_VALIDATED, NiblitEvent, get_event_bus

            get_event_bus().publish(
                NiblitEvent(
                    type=EVENT_REALITY_VALIDATED,
                    source="reality_validation_engine",
                    payload={
                        "reality_score": report.reality_score,
                        "findings": list(report.findings),
                    },
                )
            )
        except Exception:
            pass


_rve: Optional[RealityValidationEngine] = None
_rve_lock = threading.Lock()


def get_reality_validation_engine() -> RealityValidationEngine:
    global _rve
    with _rve_lock:
        if _rve is None:
            _rve = RealityValidationEngine()
    return _rve

