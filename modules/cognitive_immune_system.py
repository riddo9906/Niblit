#!/usr/bin/env python3
"""Phase Ω.5 Cognitive Immune System."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_STATE_PATH = Path(__file__).resolve().parent.parent / "cognitive_immune_state.json"


@dataclass
class ImmuneReport:
    immune_pressure: float
    quarantined_subsystems: list[str]
    active_threats: list[str]
    recovery_cycles: int
    rollback_recommended: bool
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
            "immune_pressure": round(self.immune_pressure, 4),
            "quarantined_subsystems": list(self.quarantined_subsystems),
            "active_threats": list(self.active_threats),
            "recovery_cycles": self.recovery_cycles,
            "rollback_recommended": self.rollback_recommended,
            "confidence": round(self.confidence, 4),
            "stability_impact": round(self.stability_impact, 4),
            "coherence_impact": round(self.coherence_impact, 4),
            "causal_trace_metadata": dict(self.causal_trace_metadata),
            "rationale": self.rationale,
            "explanation": self.explanation,
            "epoch": self.epoch,
            "timestamp": self.timestamp,
        }


class CognitiveImmuneSystem:
    """Detect and isolate harmful internal cognitive patterns."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._quarantine: set[str] = set()
        self._suppression: dict[str, float] = {}
        self._recovery_cycles = 0
        self._last_report: ImmuneReport | None = None
        self._load_state()

    def detect_cognitive_anomalies(self, signals: dict[str, float]) -> list[str]:
        out: list[str] = []
        if signals.get("recursive_instability", 0.0) > 0.6:
            out.append("recursive_instability")
        if signals.get("resonance_contamination", 0.0) > 0.6:
            out.append("resonance_poisoning")
        if signals.get("causal_corruption", 0.0) > 0.6:
            out.append("causal_corruption")
        if signals.get("memory_contamination", 0.0) > 0.6:
            out.append("memory_contamination")
        if signals.get("overconfidence", 0.0) > 0.7:
            out.append("overconfidence_spiral")
        if signals.get("governance_saturation", 0.0) > 0.6:
            out.append("governance_saturation")
        if signals.get("identity_integrity", 1.0) < 0.4:
            out.append("identity_collapse_risk")
        if signals.get("unstable_emergence", 0.0) > 0.6:
            out.append("unstable_emergence")
        return out

    def quarantine_subsystem(self, subsystem: str) -> None:
        with self._lock:
            self._quarantine.add(subsystem)
        self._emit_simple("EVENT_SUBSYSTEM_QUARANTINED", {"subsystem": subsystem})

    def suppress_trust(self, subsystem: str, amount: float) -> None:
        with self._lock:
            self._suppression[subsystem] = min(1.0, self._suppression.get(subsystem, 0.0) + max(0.0, amount))

    def recommend_rollback(self, threats: list[str]) -> bool:
        return any(t in threats for t in ("memory_contamination", "identity_collapse_risk", "causal_corruption"))

    def restore_coherence(self) -> list[str]:
        actions = []
        with self._lock:
            if self._quarantine:
                actions.append("review_quarantine")
            if self._suppression:
                actions.append("decay_trust_suppression")
            self._recovery_cycles += 1
        self._emit_simple("EVENT_COHERENCE_RESTORED", {"actions": actions})
        return actions

    def scan(self, signals: dict[str, float]) -> ImmuneReport:
        threats = self.detect_cognitive_anomalies(signals)
        for threat in threats:
            if threat in {"recursive_instability", "unstable_emergence"}:
                self.quarantine_subsystem("reflection_engine")
            if threat == "governance_saturation":
                self.quarantine_subsystem("governance")
            if threat == "overconfidence_spiral":
                self.suppress_trust("predictive_world_model", 0.25)
        rollback = self.recommend_rollback(threats)
        pressure = min(1.0, len(threats) * 0.18)
        report = ImmuneReport(
            immune_pressure=pressure,
            quarantined_subsystems=sorted(self._quarantine),
            active_threats=threats,
            recovery_cycles=self._recovery_cycles,
            rollback_recommended=rollback,
            confidence=max(0.0, 1.0 - pressure),
            stability_impact=max(0.0, 1.0 - pressure),
            coherence_impact=max(0.0, 1.0 - pressure),
            causal_trace_metadata={"suppressed_trust": dict(self._suppression)},
            rationale="Threat isolation with trust suppression and optional rollback.",
            explanation="Immune scan classified anomaly signals and triggered containment actions.",
            epoch=_safe_epoch(),
        )
        with self._lock:
            self._last_report = report
            self._save_state()
        self._emit(report)
        return report

    def is_quarantined(self, subsystem: str) -> bool:
        with self._lock:
            return subsystem in self._quarantine

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "quarantined_subsystems": sorted(self._quarantine),
                "trust_suppressions": dict(self._suppression),
                "recovery_cycles": self._recovery_cycles,
                "last_report": self._last_report.to_dict() if self._last_report else None,
            }

    def _emit(self, report: ImmuneReport) -> None:
        try:
            from modules.event_bus import EVENT_COGNITIVE_THREAT_DETECTED, NiblitEvent, get_event_bus

            get_event_bus().publish(
                NiblitEvent(
                    type=EVENT_COGNITIVE_THREAT_DETECTED,
                    source="cognitive_immune_system",
                    payload={
                        "active_threats": list(report.active_threats),
                        "immune_pressure": report.immune_pressure,
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

    def _emit_simple(self, event_name: str, payload: dict[str, Any]) -> None:
        try:
            from modules import event_bus as eb
            from modules.event_bus import NiblitEvent, get_event_bus

            evt = getattr(eb, event_name)
            get_event_bus().publish(NiblitEvent(type=evt, source="cognitive_immune_system", payload=payload))
        except Exception:
            pass

    def _save_state(self) -> None:
        try:
            data = {
                "quarantine": sorted(self._quarantine),
                "suppression": self._suppression,
                "recovery_cycles": self._recovery_cycles,
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
            self._quarantine = set(data.get("quarantine", []))
            self._suppression = dict(data.get("suppression", {}))
            self._recovery_cycles = int(data.get("recovery_cycles", 0))
        except Exception:
            pass


def _safe_epoch() -> int:
    try:
        from modules.unified_cognitive_state import get_unified_state

        return int(get_unified_state().status().get("epoch", 0))
    except Exception:
        return 0


_cis: CognitiveImmuneSystem | None = None
_cis_lock = threading.Lock()


def get_cognitive_immune_system() -> CognitiveImmuneSystem:
    global _cis
    with _cis_lock:
        if _cis is None:
            _cis = CognitiveImmuneSystem()
    return _cis
