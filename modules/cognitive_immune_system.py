#!/usr/bin/env python3
"""Phase Ω.5 Cognitive Immune System."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set


@dataclass
class ImmuneReport:
    anomalies: List[str]
    quarantined_subsystems: List[str]
    trust_suppressions: Dict[str, float]
    rollback_recommended: bool
    coherence_restoration_actions: List[str]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "anomalies": list(self.anomalies),
            "quarantined_subsystems": list(self.quarantined_subsystems),
            "trust_suppressions": {k: round(v, 4) for k, v in self.trust_suppressions.items()},
            "rollback_recommended": self.rollback_recommended,
            "coherence_restoration_actions": list(self.coherence_restoration_actions),
            "timestamp": self.timestamp,
        }


class CognitiveImmuneSystem:
    """Detects harmful internal patterns and applies containment."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._quarantine: Set[str] = set()
        self._suppression: Dict[str, float] = {}
        self._last_report: Optional[ImmuneReport] = None

    def scan(self, signals: Dict[str, float]) -> ImmuneReport:
        anomalies = self._detect_anomalies(signals)
        actions: List[str] = []
        for anomaly in anomalies:
            if "identity_collapse" in anomaly:
                self._quarantine_subsystem("adaptive_learning")
                actions.append("quarantine_adaptive_learning")
            if "governance_saturation" in anomaly:
                self._quarantine_subsystem("governance_evolution_engine")
                actions.append("quarantine_governance_path")
            if "prediction_addiction" in anomaly:
                self.suppress_trust("tft", 0.3)
                actions.append("suppress_predictive_trust")
        rollback = any(a in anomalies for a in ["memory_corruption_propagation", "identity_collapse_risk"])
        report = ImmuneReport(
            anomalies=anomalies,
            quarantined_subsystems=sorted(self._quarantine),
            trust_suppressions=dict(self._suppression),
            rollback_recommended=rollback,
            coherence_restoration_actions=actions,
        )
        with self._lock:
            self._last_report = report
        self._emit(report)
        return report

    def is_quarantined(self, subsystem: str) -> bool:
        with self._lock:
            return subsystem in self._quarantine

    def suppress_trust(self, subsystem: str, amount: float) -> None:
        with self._lock:
            self._suppression[subsystem] = min(1.0, self._suppression.get(subsystem, 0.0) + amount)

    def recommend_rollback(self) -> bool:
        with self._lock:
            return bool(self._last_report and self._last_report.rollback_recommended)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "quarantined_subsystems": sorted(self._quarantine),
                "trust_suppressions": dict(self._suppression),
                "last_report": self._last_report.to_dict() if self._last_report else None,
            }

    def _detect_anomalies(self, signals: Dict[str, float]) -> List[str]:
        out: List[str] = []
        if signals.get("coherence_score", 1.0) < 0.35:
            out.append("cognitive_fragmentation")
        if signals.get("recursion_depth", 0.0) >= 4:
            out.append("recursive_overfitting")
        if signals.get("governance_saturation", 0.0) > 0.6:
            out.append("governance_saturation")
        if signals.get("prediction_dependency", 0.0) > 0.75:
            out.append("prediction_addiction")
        if signals.get("memory_corruption_risk", 0.0) > 0.7:
            out.append("memory_corruption_propagation")
        if signals.get("identity_integrity", 1.0) < 0.4:
            out.append("identity_collapse_risk")
        return out

    def _quarantine_subsystem(self, subsystem: str) -> None:
        with self._lock:
            self._quarantine.add(subsystem)

    def _emit(self, report: ImmuneReport) -> None:
        try:
            from modules.event_bus import EVENT_COGNITIVE_THREAT_DETECTED, NiblitEvent, get_event_bus

            get_event_bus().publish(
                NiblitEvent(
                    type=EVENT_COGNITIVE_THREAT_DETECTED,
                    source="cognitive_immune_system",
                    payload={
                        "anomaly_count": len(report.anomalies),
                        "rollback_recommended": report.rollback_recommended,
                    },
                )
            )
        except Exception:
            pass


_cis: Optional[CognitiveImmuneSystem] = None
_cis_lock = threading.Lock()


def get_cognitive_immune_system() -> CognitiveImmuneSystem:
    global _cis
    with _cis_lock:
        if _cis is None:
            _cis = CognitiveImmuneSystem()
    return _cis

