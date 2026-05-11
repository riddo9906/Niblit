#!/usr/bin/env python3
"""Phase Ω.5 Emergence Monitor."""

from __future__ import annotations

import collections
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class EmergenceReport:
    emergence_index: float
    strategy_motifs: List[str]
    subsystem_coalitions: List[str]
    feedback_attractors: List[str]
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "emergence_index": round(self.emergence_index, 4),
            "strategy_motifs": list(self.strategy_motifs),
            "subsystem_coalitions": list(self.subsystem_coalitions),
            "feedback_attractors": list(self.feedback_attractors),
            "timestamp": self.timestamp,
        }


class EmergenceMonitor:
    """Detects unprogrammed recurring behavior and implicit coalitions."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._patterns: collections.Counter[str] = collections.Counter()
        self._pairs: collections.Counter[Tuple[str, str]] = collections.Counter()
        self._last_report: Optional[EmergenceReport] = None

    def observe_pattern(self, motif: str, subsystems: Optional[List[str]] = None) -> None:
        with self._lock:
            self._patterns[motif] += 1
            subs = sorted(set(subsystems or []))
            for i in range(len(subs)):
                for j in range(i + 1, len(subs)):
                    self._pairs[(subs[i], subs[j])] += 1

    def analyze(self) -> EmergenceReport:
        with self._lock:
            motifs = [m for m, c in self._patterns.items() if c >= 3]
            coalitions = [f"{a}+{b}" for (a, b), c in self._pairs.items() if c >= 2]
        attractors = [m for m in motifs if "loop" in m or "self_opt" in m]
        emergence_index = min(
            1.0, (len(motifs) * 0.15) + (len(coalitions) * 0.1) + (len(attractors) * 0.2)
        )
        report = EmergenceReport(
            emergence_index=emergence_index,
            strategy_motifs=motifs,
            subsystem_coalitions=coalitions,
            feedback_attractors=attractors,
        )
        with self._lock:
            self._last_report = report
        self._emit(report)
        return report

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "pattern_count": len(self._patterns),
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
                    payload={"emergence_index": report.emergence_index},
                )
            )
        except Exception:
            pass


_em: Optional[EmergenceMonitor] = None
_em_lock = threading.Lock()


def get_emergence_monitor() -> EmergenceMonitor:
    global _em
    with _em_lock:
        if _em is None:
            _em = EmergenceMonitor()
    return _em
