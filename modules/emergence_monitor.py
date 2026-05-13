#!/usr/bin/env python3
"""Phase Ω.5 Emergence Monitor."""

from __future__ import annotations

import collections
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_STATE_PATH = Path(__file__).resolve().parent.parent / "emergence_monitor_state.json"


@dataclass
class EmergenceReport:
    emergence_index: float
    emergence_velocity: float
    motif_frequency: dict[str, int]
    coalition_strength: dict[str, int]
    attractor_stability: float
    patterns: list[str]
    coalitions: list[str]
    classified_behavior: str
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
            "emergence_index": round(self.emergence_index, 4),
            "emergence_velocity": round(self.emergence_velocity, 4),
            "motif_frequency": dict(self.motif_frequency),
            "coalition_strength": dict(self.coalition_strength),
            "attractor_stability": round(self.attractor_stability, 4),
            "patterns": list(self.patterns),
            "coalitions": list(self.coalitions),
            "classified_behavior": self.classified_behavior,
            "confidence": round(self.confidence, 4),
            "stability_impact": round(self.stability_impact, 4),
            "coherence_impact": round(self.coherence_impact, 4),
            "causal_trace_metadata": dict(self.causal_trace_metadata),
            "rationale": self.rationale,
            "explanation": self.explanation,
            "epoch": self.epoch,
            "timestamp": self.timestamp,
        }


class EmergenceMonitor:
    """Detect emergent unprogrammed behavior patterns."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._motifs: collections.Counter[str] = collections.Counter()
        self._pairs: collections.Counter[str] = collections.Counter()
        self._history: list[tuple[float, str]] = []
        self._last_report: EmergenceReport | None = None
        self._load_state()

    def observe_pattern(self, motif: str, subsystems: list[str] | None = None) -> None:
        now = time.time()
        with self._lock:
            self._motifs[motif] += 1
            self._history.append((now, motif))
            subs = sorted(set(subsystems or []))
            if len(subs) >= 2:
                coalition = "+".join(subs)
                self._pairs[coalition] += 1
            if len(self._history) > 2000:
                self._history = self._history[-2000:]

    def detect_emergent_patterns(self) -> list[str]:
        with self._lock:
            return [m for m, c in self._motifs.items() if c >= 3]

    def identify_coalitions(self) -> list[str]:
        with self._lock:
            return [c for c, v in self._pairs.items() if v >= 2]

    def compute_emergence_index(self) -> float:
        patterns = self.detect_emergent_patterns()
        coalitions = self.identify_coalitions()
        attractors = [m for m in patterns if "loop" in m or "attractor" in m or "self_opt" in m]
        return min(1.0, 0.12 * len(patterns) + 0.1 * len(coalitions) + 0.22 * len(attractors))

    def classify_emergent_behavior(self, idx: float) -> str:
        if idx >= 0.75:
            return "high_unstable_emergence"
        if idx >= 0.45:
            return "moderate_emergence"
        return "low_emergence"

    def analyze(self) -> EmergenceReport:
        patterns = self.detect_emergent_patterns()
        coalitions = self.identify_coalitions()
        idx = self.compute_emergence_index()
        now = time.time()
        with self._lock:
            recent = [m for ts, m in self._history if now - ts <= 60]
            velocity = min(1.0, len(recent) / 25.0)
            motif_frequency = dict(self._motifs)
            coalition_strength = dict(self._pairs)
        attractor_stability = max(0.0, 1.0 - min(1.0, len([m for m in patterns if "loop" in m]) / 5.0))
        behavior = self.classify_emergent_behavior(idx)
        report = EmergenceReport(
            emergence_index=idx,
            emergence_velocity=velocity,
            motif_frequency=motif_frequency,
            coalition_strength=coalition_strength,
            attractor_stability=attractor_stability,
            patterns=patterns,
            coalitions=coalitions,
            classified_behavior=behavior,
            confidence=max(0.0, 1.0 - idx * 0.5),
            stability_impact=max(0.0, 1.0 - idx),
            coherence_impact=max(0.0, 1.0 - idx * 0.8),
            causal_trace_metadata={"recent_pattern_count": len(recent)},
            rationale=f"Emergence index={idx:.2f} based on motifs, coalitions, and attractors.",
            explanation="Emergent pattern monitor classified behavior intensity and coalition dynamics.",
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
                "pattern_count": len(self._motifs),
                "coalition_edges": len(self._pairs),
                "last_report": self._last_report.to_dict() if self._last_report else None,
            }

    def _emit(self, report: EmergenceReport) -> None:
        try:
            from modules.event_bus import EVENT_EMERGENCE_DETECTED, NiblitEvent, get_event_bus

            get_event_bus().publish(
                NiblitEvent(
                    type=EVENT_EMERGENCE_DETECTED,
                    source="emergence_monitor",
                    payload={
                        "emergence_index": report.emergence_index,
                        "classified_behavior": report.classified_behavior,
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
                "motifs": dict(self._motifs),
                "pairs": dict(self._pairs),
                "history": self._history[-200:],
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
            self._motifs = collections.Counter(data.get("motifs", {}))
            self._pairs = collections.Counter(data.get("pairs", {}))
            self._history = [(float(ts), str(m)) for ts, m in data.get("history", [])]
        except Exception:
            pass


def _safe_epoch() -> int:
    try:
        from modules.unified_cognitive_state import get_unified_state

        return int(get_unified_state().status().get("epoch", 0))
    except Exception:
        return 0


_em: EmergenceMonitor | None = None
_em_lock = threading.Lock()


def get_emergence_monitor() -> EmergenceMonitor:
    global _em
    with _em_lock:
        if _em is None:
            _em = EmergenceMonitor()
    return _em


if __name__ == "__main__":
    print('Running emergence_monitor.py')
