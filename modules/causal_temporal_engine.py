#!/usr/bin/env python3
"""Phase Ω.5 Causal Temporal Engine."""

from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_STATE_PATH = Path(__file__).resolve().parent.parent / "causal_temporal_state.json"


@dataclass
class TemporalEvent:
    event_id: str
    subsystem: str
    event_type: str
    cause: str
    expected_effect: str
    epoch: int
    created_at: float = field(default_factory=time.time)
    observed_effect: str = ""
    observed_at: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "subsystem": self.subsystem,
            "event_type": self.event_type,
            "cause": self.cause,
            "expected_effect": self.expected_effect,
            "epoch": self.epoch,
            "created_at": self.created_at,
            "observed_effect": self.observed_effect,
            "observed_at": self.observed_at,
            "metadata": dict(self.metadata),
        }


class CausalTemporalEngine:
    """Create causally ordered temporal cognition."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[str, TemporalEvent] = {}
        self._timeline: list[str] = []
        self._contradictions: list[str] = []
        self._delayed_effects = 0
        self._load_state()

    def register_event(
        self,
        subsystem: str,
        event_type: str,
        cause: str,
        expected_effect: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        event_id = str(uuid.uuid4())
        record = TemporalEvent(
            event_id=event_id,
            subsystem=subsystem,
            event_type=event_type,
            cause=cause,
            expected_effect=expected_effect,
            epoch=_safe_epoch(),
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._events[event_id] = record
            self._timeline.append(event_id)
            self._save_state()
        self._emit_chain_update(record)
        return event_id

    # compatibility API
    def record_expectation(self, subsystem: str, cause: str, expected_effect: str, expected_at: float) -> str:
        return self.register_event(
            subsystem=subsystem,
            event_type="expectation",
            cause=cause,
            expected_effect=expected_effect,
            metadata={"expected_at": expected_at},
        )

    def reconcile_delayed_outcomes(self, event_id: str, observed_effect: str, observed_at: float | None = None) -> bool:
        with self._lock:
            rec = self._events.get(event_id)
            if rec is None:
                return False
            rec.observed_effect = observed_effect
            rec.observed_at = observed_at or time.time()
            if rec.observed_at - rec.created_at > 1.0:
                self._delayed_effects += 1
            if rec.expected_effect and observed_effect and rec.expected_effect != observed_effect:
                self._contradictions.append(f"{event_id}: expected={rec.expected_effect} observed={observed_effect}")
                self._emit_temporal_contradiction(event_id, rec.expected_effect, observed_effect)
            self._save_state()
        return True

    def reconcile_delayed_outcome(self, event_id: str, observed_effect: str, observed_at: float | None = None) -> bool:
        return self.reconcile_delayed_outcomes(event_id, observed_effect, observed_at)

    def detect_temporal_conflicts(self) -> list[str]:
        with self._lock:
            return list(self._contradictions)

    def temporal_contradictions(self) -> list[str]:
        return self.detect_temporal_conflicts()

    def build_causal_chain(self, event_id: str) -> list[dict[str, Any]]:
        with self._lock:
            if event_id not in self._events:
                return []
            target = self._events[event_id]
            chain = [e.to_dict() for e in self._events.values() if e.subsystem == target.subsystem]
        return sorted(chain, key=lambda x: x["created_at"])

    def replay_timeline(self, since: float = 0.0, until: float | None = None) -> list[dict[str, Any]]:
        end = until or time.time()
        with self._lock:
            rows = [
                self._events[eid].to_dict()
                for eid in self._timeline
                if eid in self._events and since <= self._events[eid].created_at <= end
            ]
        return rows

    def future_expectation_graph(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        with self._lock:
            for eid in self._timeline:
                ev = self._events.get(eid)
                if ev is not None and ev.event_type == "expectation":
                    out.setdefault(ev.subsystem, []).append(eid)
        return out

    def status(self) -> dict[str, Any]:
        with self._lock:
            unresolved = len([e for e in self._events.values() if not e.observed_effect])
            return {
                "epoch_causality": _safe_epoch(),
                "delayed_effects": self._delayed_effects,
                "unresolved_outcomes": unresolved,
                "contradiction_timeline": list(self._contradictions),
                "event_count": len(self._events),
                "timeline_length": len(self._timeline),
            }

    def _emit_chain_update(self, rec: TemporalEvent) -> None:
        try:
            from modules.event_bus import EVENT_CAUSAL_CHAIN_UPDATED, NiblitEvent, get_event_bus

            get_event_bus().publish(
                NiblitEvent(
                    type=EVENT_CAUSAL_CHAIN_UPDATED,
                    source="causal_temporal_engine",
                    payload={
                        "event_id": rec.event_id,
                        "subsystem": rec.subsystem,
                        "confidence": 0.75,
                        "stability_impact": 0.7,
                        "coherence_impact": 0.72,
                        "causal_trace_metadata": {"event_type": rec.event_type, "cause": rec.cause},
                        "rationale": "Causal chain updated with temporally tagged event.",
                        "epoch": rec.epoch,
                    },
                )
            )
        except Exception:
            pass

    def _emit_temporal_contradiction(self, event_id: str, expected: str, observed: str) -> None:
        try:
            from modules.event_bus import EVENT_TEMPORAL_CONTRADICTION, NiblitEvent, get_event_bus

            get_event_bus().publish(
                NiblitEvent(
                    type=EVENT_TEMPORAL_CONTRADICTION,
                    source="causal_temporal_engine",
                    payload={
                        "event_id": event_id,
                        "expected": expected,
                        "observed": observed,
                        "confidence": 0.4,
                        "stability_impact": 0.35,
                        "coherence_impact": 0.3,
                        "causal_trace_metadata": {"type": "temporal_mismatch"},
                        "rationale": "Observed effect diverged from expected temporal outcome.",
                        "epoch": _safe_epoch(),
                    },
                )
            )
        except Exception:
            pass

    def _save_state(self) -> None:
        try:
            data = {
                "events": {k: v.to_dict() for k, v in self._events.items()},
                "timeline": self._timeline,
                "contradictions": self._contradictions,
                "delayed_effects": self._delayed_effects,
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
            self._timeline = list(data.get("timeline", []))
            self._contradictions = list(data.get("contradictions", []))
            self._delayed_effects = int(data.get("delayed_effects", 0))
            events = data.get("events", {})
            self._events = {
                k: TemporalEvent(
                    event_id=v["event_id"],
                    subsystem=v["subsystem"],
                    event_type=v.get("event_type", "unknown"),
                    cause=v.get("cause", ""),
                    expected_effect=v.get("expected_effect", ""),
                    epoch=int(v.get("epoch", 0)),
                    created_at=float(v.get("created_at", time.time())),
                    observed_effect=v.get("observed_effect", ""),
                    observed_at=float(v.get("observed_at", 0.0)),
                    metadata=dict(v.get("metadata", {})),
                )
                for k, v in events.items()
            }
        except Exception:
            pass


def _safe_epoch() -> int:
    try:
        from modules.unified_cognitive_state import get_unified_state

        return int(get_unified_state().status().get("epoch", 0))
    except Exception:
        return 0


_cte: CausalTemporalEngine | None = None
_cte_lock = threading.Lock()


def get_causal_temporal_engine() -> CausalTemporalEngine:
    global _cte
    with _cte_lock:
        if _cte is None:
            _cte = CausalTemporalEngine()
    return _cte


if __name__ == "__main__":
    print('Running causal_temporal_engine.py')
