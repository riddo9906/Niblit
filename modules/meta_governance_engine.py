#!/usr/bin/env python3
"""Phase Ω.5 Meta-Governance Engine."""

from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_STATE_PATH = Path(__file__).resolve().parent.parent / "meta_governance_state.json"


@dataclass
class MetaGovernanceReport:
    influence_distribution: dict[str, float]
    authority_pressure: float
    governance_entropy: float
    adaptation_override_attempts: int
    governance_capture_risk: float
    constitutional_compliance: float
    confidence: float
    stability_impact: float
    coherence_impact: float
    causal_trace_metadata: dict[str, Any]
    rationale: str
    explanation: str
    epoch: int
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "influence_distribution": {k: round(v, 4) for k, v in self.influence_distribution.items()},
            "authority_pressure": round(self.authority_pressure, 4),
            "governance_entropy": round(self.governance_entropy, 4),
            "adaptation_override_attempts": self.adaptation_override_attempts,
            "governance_capture_risk": round(self.governance_capture_risk, 4),
            "constitutional_compliance": round(self.constitutional_compliance, 4),
            "confidence": round(self.confidence, 4),
            "stability_impact": round(self.stability_impact, 4),
            "coherence_impact": round(self.coherence_impact, 4),
            "causal_trace_metadata": dict(self.causal_trace_metadata),
            "rationale": self.rationale,
            "explanation": self.explanation,
            "epoch": self.epoch,
            "timestamp": self.timestamp,
        }


class MetaGovernanceEngine:
    """Govern the governors with constitutional limits and explainability."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._influence: dict[str, float] = {}
        self._reasons: dict[str, int] = {}
        self._adaptation_override_attempts = 0
        self._last_report: MetaGovernanceReport | None = None
        self._load_state()

    def register_influence(self, subsystem: str, delta: float, reason: str = "") -> None:
        with self._lock:
            self._influence[subsystem] = max(0.0, self._influence.get(subsystem, 0.0) + float(delta))
            if reason.strip():
                self._reasons[subsystem] = self._reasons.get(subsystem, 0) + 1

    def compute_influence_balance(self) -> dict[str, float]:
        with self._lock:
            total = sum(self._influence.values()) or 1.0
            return {k: v / total for k, v in self._influence.items()}

    def detect_governance_capture(self) -> float:
        dist = self.compute_influence_balance()
        if not dist:
            return 0.0
        return max(dist.values())

    def validate_constitutional_compliance(self, context: dict[str, Any] | None = None) -> float:
        context = dict(context or {})
        context.setdefault("autonomous", True)
        context.setdefault("confidence", 0.9)
        context.setdefault("stability_score", 0.9)
        context.setdefault("objective_alignment", 0.9)
        try:
            from modules.constitutional_layer import get_constitutional_layer

            verdict = get_constitutional_layer().validate(context)
            return 1.0 if bool(verdict.allowed) else 0.0
        except Exception:
            return 0.5

    def enforce_authority_limits(self, subsystem: str, proposed_delta: float) -> float:
        dist = self.compute_influence_balance()
        if dist.get(subsystem, 0.0) > 0.55:
            return 0.0
        return proposed_delta

    def attempt_constitutional_rewrite(self, rewrite_payload: dict[str, Any]) -> bool:
        allowed = bool(rewrite_payload.get("approved_by_human", False))
        if not allowed:
            with self._lock:
                self._adaptation_override_attempts += 1
        return allowed

    def evaluate(self) -> MetaGovernanceReport:
        dist = self.compute_influence_balance()
        capture = self.detect_governance_capture()
        compliance = self.validate_constitutional_compliance()
        entropy = _entropy(dist)
        authority_pressure = capture
        with self._lock:
            attempts = self._adaptation_override_attempts

        report = MetaGovernanceReport(
            influence_distribution=dist,
            authority_pressure=authority_pressure,
            governance_entropy=entropy,
            adaptation_override_attempts=attempts,
            governance_capture_risk=capture,
            constitutional_compliance=compliance,
            confidence=max(0.0, min(1.0, 1.0 - capture * 0.6)),
            stability_impact=max(0.0, min(1.0, compliance * (1.0 - capture * 0.4))),
            coherence_impact=max(0.0, min(1.0, 0.6 * compliance + 0.4 * (1.0 - capture))),
            causal_trace_metadata={"reason_entries": sum(self._reasons.values())},
            rationale=self._rationale(capture, compliance, attempts),
            explanation="Meta-governance balanced subsystem influence with constitutional enforcement.",
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
                "influence_count": len(self._influence),
                "adaptation_override_attempts": self._adaptation_override_attempts,
                "last_report": self._last_report.to_dict() if self._last_report else None,
            }

    @staticmethod
    def _rationale(capture: float, compliance: float, attempts: int) -> str:
        if capture > 0.55:
            return f"Governance capture risk high={capture:.2f}"
        if compliance < 0.5:
            return "Constitutional compliance degraded"
        if attempts > 0:
            return f"Blocked constitutional rewrite attempts={attempts}"
        return "Governance influence remains balanced and compliant."

    def _emit(self, report: MetaGovernanceReport) -> None:
        try:
            from modules.event_bus import (
                EVENT_GOVERNANCE_CAPTURE_WARNING,
                EVENT_META_GOVERNANCE_EVALUATED,
                EVENT_META_GOVERNANCE_UPDATED,
                NiblitEvent,
                get_event_bus,
            )

            payload = {
                "governance_capture_risk": report.governance_capture_risk,
                "authority_pressure": report.authority_pressure,
                "governance_entropy": report.governance_entropy,
                "adaptation_override_attempts": report.adaptation_override_attempts,
                "confidence": report.confidence,
                "stability_impact": report.stability_impact,
                "coherence_impact": report.coherence_impact,
                "causal_trace_metadata": report.causal_trace_metadata,
                "rationale": report.rationale,
                "epoch": report.epoch,
            }
            bus = get_event_bus()
            if report.governance_capture_risk >= 0.55:
                bus.publish(
                    NiblitEvent(type=EVENT_GOVERNANCE_CAPTURE_WARNING, source="meta_governance_engine", payload=payload)
                )
            bus.publish(
                NiblitEvent(type=EVENT_META_GOVERNANCE_UPDATED, source="meta_governance_engine", payload=payload)
            )
            bus.publish(
                NiblitEvent(type=EVENT_META_GOVERNANCE_EVALUATED, source="meta_governance_engine", payload=payload)
            )
        except Exception:
            pass

    def _save_state(self) -> None:
        try:
            data = {
                "influence": self._influence,
                "reasons": self._reasons,
                "adaptation_override_attempts": self._adaptation_override_attempts,
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
            self._influence = dict(data.get("influence", {}))
            self._reasons = dict(data.get("reasons", {}))
            self._adaptation_override_attempts = int(data.get("adaptation_override_attempts", 0))
        except Exception:
            pass


def _entropy(dist: dict[str, float]) -> float:
    if not dist:
        return 0.0
    h = -sum(v * math.log(max(v, 1e-9), 2) for v in dist.values())
    return min(1.0, h / max(1.0, math.log(max(len(dist), 2), 2)))


def _safe_epoch() -> int:
    try:
        from modules.unified_cognitive_state import get_unified_state

        return int(get_unified_state().status().get("epoch", 0))
    except Exception:
        return 0


_mge: MetaGovernanceEngine | None = None
_mge_lock = threading.Lock()


def get_meta_governance_engine() -> MetaGovernanceEngine:
    global _mge
    with _mge_lock:
        if _mge is None:
            _mge = MetaGovernanceEngine()
    return _mge
