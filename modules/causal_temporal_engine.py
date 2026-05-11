#!/usr/bin/env python3
"""Phase Ω.5 Causal Temporal Engine."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TemporalEpisode:
    episode_id: str
    subsystem: str
    cause: str
    expected_effect: str
    expected_at: float
    created_at: float = field(default_factory=time.time)
    observed_effect: str = ""
    observed_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "episode_id": self.episode_id,
            "subsystem": self.subsystem,
            "cause": self.cause,
            "expected_effect": self.expected_effect,
            "expected_at": self.expected_at,
            "created_at": self.created_at,
            "observed_effect": self.observed_effect,
            "observed_at": self.observed_at,
        }


class CausalTemporalEngine:
    """Maintains causally ordered timeline and delayed-outcome reconciliation."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._episodes: Dict[str, TemporalEpisode] = {}
        self._timeline: List[str] = []
        self._contradictions: List[str] = []

    def record_expectation(
        self, subsystem: str, cause: str, expected_effect: str, expected_at: float
    ) -> str:
        eid = str(uuid.uuid4())
        ep = TemporalEpisode(
            episode_id=eid,
            subsystem=subsystem,
            cause=cause,
            expected_effect=expected_effect,
            expected_at=expected_at,
        )
        with self._lock:
            self._episodes[eid] = ep
            self._timeline.append(eid)
        self._emit()
        return eid

    def reconcile_delayed_outcome(
        self,
        episode_id: str,
        observed_effect: str,
        observed_at: Optional[float] = None,
    ) -> bool:
        with self._lock:
            ep = self._episodes.get(episode_id)
            if ep is None:
                return False
            ep.observed_effect = observed_effect
            ep.observed_at = observed_at or time.time()
            if ep.expected_effect and observed_effect and ep.expected_effect != observed_effect:
                self._contradictions.append(f"{episode_id}:expected={ep.expected_effect},observed={observed_effect}")
        self._emit()
        return True

    def temporal_contradictions(self) -> List[str]:
        with self._lock:
            return list(self._contradictions)

    def future_expectation_graph(self) -> Dict[str, List[str]]:
        graph: Dict[str, List[str]] = {}
        with self._lock:
            ordered = sorted(
                (self._episodes[eid] for eid in self._timeline if eid in self._episodes),
                key=lambda e: e.expected_at,
            )
        for ep in ordered:
            graph.setdefault(ep.subsystem, []).append(ep.episode_id)
        return graph

    def replay_timeline(self, since: float = 0.0, until: Optional[float] = None) -> List[Dict[str, Any]]:
        end = until or time.time()
        with self._lock:
            ordered = [
                self._episodes[eid]
                for eid in self._timeline
                if eid in self._episodes and since <= self._episodes[eid].created_at <= end
            ]
        return [ep.to_dict() for ep in ordered]

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "episode_count": len(self._episodes),
                "timeline_length": len(self._timeline),
                "contradiction_count": len(self._contradictions),
            }

    def _emit(self) -> None:
        try:
            from modules.event_bus import EVENT_TEMPORAL_CAUSAL_UPDATED, NiblitEvent, get_event_bus

            get_event_bus().publish(
                NiblitEvent(
                    type=EVENT_TEMPORAL_CAUSAL_UPDATED,
                    source="causal_temporal_engine",
                    payload={"contradictions": len(self._contradictions)},
                )
            )
        except Exception:
            pass


_cte: Optional[CausalTemporalEngine] = None
_cte_lock = threading.Lock()


def get_causal_temporal_engine() -> CausalTemporalEngine:
    global _cte
    with _cte_lock:
        if _cte is None:
            _cte = CausalTemporalEngine()
    return _cte
