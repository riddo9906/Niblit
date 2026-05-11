#!/usr/bin/env python3
"""Phase Ω.5 Meta-Governance Engine."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MetaGovernanceReport:
    influence_distribution: Dict[str, float]
    governance_saturation: float
    explainability_score: float
    constitutional_stability_score: float
    blocked_rewrites: int
    findings: List[str]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "influence_distribution": {
                k: round(v, 4) for k, v in self.influence_distribution.items()
            },
            "governance_saturation": round(self.governance_saturation, 4),
            "explainability_score": round(self.explainability_score, 4),
            "constitutional_stability_score": round(
                self.constitutional_stability_score, 4
            ),
            "blocked_rewrites": self.blocked_rewrites,
            "findings": list(self.findings),
            "timestamp": self.timestamp,
        }


class MetaGovernanceEngine:
    """Governs governance subsystems and prevents silent principle rewrites."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._influence: Dict[str, float] = {}
        self._reasons: Dict[str, int] = {}
        self._blocked_rewrites = 0
        self._last_report: Optional[MetaGovernanceReport] = None

    def register_influence(self, subsystem: str, delta: float, reason: str = "") -> None:
        with self._lock:
            self._influence[subsystem] = max(
                0.0, self._influence.get(subsystem, 0.0) + float(delta)
            )
            if reason.strip():
                self._reasons[subsystem] = self._reasons.get(subsystem, 0) + 1

    def attempt_constitutional_rewrite(self, rewrite_payload: Dict[str, Any]) -> bool:
        allowed = bool(rewrite_payload.get("approved_by_human", False))
        if not allowed:
            with self._lock:
                self._blocked_rewrites += 1
        return allowed

    def evaluate(self) -> MetaGovernanceReport:
        with self._lock:
            infl = dict(self._influence)
            total = sum(infl.values()) or 1.0
            norm = {k: v / total for k, v in infl.items()} if infl else {}
            explainability = (
                sum(self._reasons.values()) / max(1, len(infl)) / 3.0 if infl else 1.0
            )
            saturation = max(norm.values()) if norm else 0.0
            blocked = self._blocked_rewrites
        findings: List[str] = []
        if saturation > 0.45:
            findings.append("influence_concentration_risk")
        if explainability < 0.4:
            findings.append("low_governance_explainability")
        if blocked > 0:
            findings.append("blocked_constitutional_rewrite_attempts")
        constitutional_stability = max(0.0, 1.0 - blocked * 0.1)
        report = MetaGovernanceReport(
            influence_distribution=norm,
            governance_saturation=saturation,
            explainability_score=max(0.0, min(1.0, explainability)),
            constitutional_stability_score=constitutional_stability,
            blocked_rewrites=blocked,
            findings=findings,
        )
        with self._lock:
            self._last_report = report
        self._emit(report)
        return report

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "influence_count": len(self._influence),
                "blocked_rewrites": self._blocked_rewrites,
                "last_report": self._last_report.to_dict() if self._last_report else None,
            }

    def _emit(self, report: MetaGovernanceReport) -> None:
        try:
            from modules.event_bus import (
                EVENT_META_GOVERNANCE_EVALUATED,
                NiblitEvent,
                get_event_bus,
            )

            get_event_bus().publish(
                NiblitEvent(
                    type=EVENT_META_GOVERNANCE_EVALUATED,
                    source="meta_governance_engine",
                    payload={
                        "governance_saturation": report.governance_saturation,
                        "blocked_rewrites": report.blocked_rewrites,
                    },
                )
            )
        except Exception:
            pass


_mge: Optional[MetaGovernanceEngine] = None
_mge_lock = threading.Lock()


def get_meta_governance_engine() -> MetaGovernanceEngine:
    global _mge
    with _mge_lock:
        if _mge is None:
            _mge = MetaGovernanceEngine()
    return _mge

