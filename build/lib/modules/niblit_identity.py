#!/usr/bin/env python3
"""Phase Ω / Ω.5 Niblit Identity Coherence Layer."""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_ENABLED: bool = os.getenv("NIBLIT_ID_ENABLED", "1").strip().lower() not in {"0", "false", "no"}
_ID_PATH: str = os.getenv("NIBLIT_ID_PATH", str(Path(__file__).resolve().parent.parent / "niblit_identity.json"))
_TIMELINE_PATH: str = os.getenv(
    "NIBLIT_ID_TIMELINE_PATH", str(Path(__file__).resolve().parent.parent / "identity_timeline.jsonl")
)

_CORE_VALUES = [
    "preserve_system_integrity",
    "objective_alignment_outranks_exploration",
    "safety_overrides_efficiency",
    "human_intent_guides_direction",
    "continuous_learning_over_static_knowledge",
    "causal_understanding_over_correlation",
    "governance_constrains_autonomy",
    "temporal_coherence_is_prerequisite",
]


class NiblitIdentityRecord:
    def __init__(self) -> None:
        now = datetime.now(tz=timezone.utc).isoformat()
        self.identity_version = 1
        self.epoch_born = 1
        self.created_at = now
        self.last_updated = now
        self.strategic_direction = "Unify subsystems into stable recursive cognition."
        self.persistent_goals = [
            "maintain continuous learning across sessions",
            "preserve constitutional alignment under adaptation",
            "prioritize coherence and stability over optimization",
        ]
        self.learning_history: list[dict[str, Any]] = []
        self.trust_fingerprint: dict[str, float] = {}

        self.continuity_score = 1.0
        self.identity_integrity = 1.0
        self.value_stability = 1.0
        self.behavioral_coherence = 1.0
        self.identity_drift_score = 0.0
        self.drift_velocity = 0.0

        self.trajectory_validation_score = 1.0
        self.session_count = 0
        self.contradiction_memory: list[dict[str, Any]] = []

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity_version": self.identity_version,
            "epoch_born": self.epoch_born,
            "created_at": self.created_at,
            "last_updated": self.last_updated,
            "core_values": list(_CORE_VALUES),
            "strategic_direction": self.strategic_direction,
            "persistent_goals": list(self.persistent_goals),
            "learning_history": list(self.learning_history),
            "trust_fingerprint": dict(self.trust_fingerprint),
            "continuity_score": round(self.continuity_score, 4),
            "identity_integrity": round(self.identity_integrity, 4),
            "value_stability": round(self.value_stability, 4),
            "behavioral_coherence": round(self.behavioral_coherence, 4),
            "identity_drift_score": round(self.identity_drift_score, 4),
            "drift_velocity": round(self.drift_velocity, 4),
            "trajectory_validation_score": round(self.trajectory_validation_score, 4),
            "session_count": self.session_count,
            "contradiction_memory": list(self.contradiction_memory),
        }


class NiblitIdentity:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._record = NiblitIdentityRecord()
        self._load()
        with self._lock:
            self._record.session_count += 1
            self._record.identity_version += 1
            self._record.last_updated = datetime.now(tz=timezone.utc).isoformat()
        self._save()

    @property
    def core_values(self) -> list[str]:
        return list(_CORE_VALUES)

    def record_lesson(self, phase: str, lesson: str) -> None:
        with self._lock:
            self._record.learning_history.append(
                {"phase": phase, "lesson": lesson, "timestamp": datetime.now(tz=timezone.utc).isoformat()}
            )
            if len(self._record.learning_history) > 200:
                self._record.learning_history = self._record.learning_history[-200:]
        self._save()

    def update_direction(self, direction: str) -> None:
        with self._lock:
            self._record.strategic_direction = direction
            self._record.last_updated = datetime.now(tz=timezone.utc).isoformat()
        self._save()
        self._emit_identity_validated("update_direction")

    def add_goal(self, goal: str) -> None:
        with self._lock:
            if goal not in self._record.persistent_goals:
                self._record.persistent_goals.append(goal)
        self._save()

    def update_trust(self, subsystem: str, trust: float) -> None:
        trust = max(0.0, min(1.0, float(trust)))
        with self._lock:
            old = self._record.trust_fingerprint.get(subsystem, 0.7)
            self._record.trust_fingerprint[subsystem] = 0.15 * trust + 0.85 * old

    def update_continuity(self, delta: float) -> None:
        with self._lock:
            self._record.continuity_score = max(0.0, min(1.0, self._record.continuity_score + delta))
            self._record.identity_integrity = self._record.continuity_score
        self._save()

    def compute_behavioral_consistency(self, observed_behaviors: dict[str, float]) -> float:
        with self._lock:
            baseline = dict(self._record.trust_fingerprint)
        if not observed_behaviors:
            score = 1.0
        elif not baseline:
            score = 0.8
        else:
            keys = set(baseline) | set(observed_behaviors)
            avg_delta = sum(
                abs(float(baseline.get(k, 0.5)) - float(observed_behaviors.get(k, 0.5))) for k in keys
            ) / len(keys)
            score = max(0.0, min(1.0, 1.0 - avg_delta))
        with self._lock:
            self._record.behavioral_coherence = score
        return score

    # compatibility API
    def behavioral_consistency_score(self, observed_behaviors: dict[str, float]) -> float:
        return self.compute_behavioral_consistency(observed_behaviors)

    def value_integrity_check(self, candidate_values: list[str]) -> dict[str, Any]:
        current = {v.lower().strip() for v in candidate_values}
        core = {v.lower().strip() for v in _CORE_VALUES}
        missing = sorted(core - current)
        value_stability = max(0.0, min(1.0, 1.0 - (len(missing) / max(1, len(core)))))
        with self._lock:
            self._record.value_stability = value_stability
        if missing:
            self.record_contradiction("value_integrity_missing_core", {"missing": missing})
        self._emit_identity_validated("value_integrity_check")
        return {"score": value_stability, "missing_core_values": missing, "is_valid": not missing}

    def validate_trajectory(self, proposed_direction: str) -> float:
        with self._lock:
            cur = self._record.strategic_direction
        cur_tokens = set(cur.lower().split())
        new_tokens = set((proposed_direction or "").lower().split())
        overlap = len(cur_tokens & new_tokens) / max(1, len(cur_tokens | new_tokens))
        score = max(0.0, min(1.0, overlap))
        with self._lock:
            self._record.trajectory_validation_score = score
        if score < 0.2:
            self.record_contradiction("trajectory_divergence", {"current": cur, "proposed": proposed_direction})
        self._emit_identity_validated("validate_trajectory")
        return score

    # compatibility API
    def validate_long_term_trajectory(self, proposed_direction: str) -> float:
        return self.validate_trajectory(proposed_direction)

    def detect_identity_drift(self, observed_behaviors: dict[str, float]) -> float:
        behavior = self.compute_behavioral_consistency(observed_behaviors)
        with self._lock:
            old = self._record.identity_drift_score
            drift = max(
                0.0, min(1.0, 1.0 - ((behavior + self._record.value_stability + self._record.continuity_score) / 3.0))
            )
            self._record.drift_velocity = max(0.0, drift - old)
            self._record.identity_drift_score = drift
            self._record.identity_integrity = max(0.0, 1.0 - drift)
        self._save()
        self._append_timeline("identity_drift", {"drift": drift, "drift_velocity": self._record.drift_velocity})
        self._emit_identity_drift("detect_identity_drift")
        return drift

    def record_contradiction(self, category: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._record.contradiction_memory.append(
                {"category": category, "payload": dict(payload), "timestamp": datetime.now(tz=timezone.utc).isoformat()}
            )
            if len(self._record.contradiction_memory) > 300:
                self._record.contradiction_memory = self._record.contradiction_memory[-300:]
        self._save()
        self._append_timeline("contradiction", {"category": category})

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return self._record.to_dict()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": _ENABLED,
                "identity_version": self._record.identity_version,
                "session_count": self._record.session_count,
                "continuity_score": round(self._record.continuity_score, 4),
                "identity_integrity": round(self._record.identity_integrity, 4),
                "value_stability": round(self._record.value_stability, 4),
                "behavioral_coherence": round(self._record.behavioral_coherence, 4),
                "identity_drift_score": round(self._record.identity_drift_score, 4),
                "drift_velocity": round(self._record.drift_velocity, 4),
                "trajectory_validation_score": round(self._record.trajectory_validation_score, 4),
                "strategic_direction": self._record.strategic_direction,
                "goal_count": len(self._record.persistent_goals),
                "lesson_count": len(self._record.learning_history),
                "contradiction_count": len(self._record.contradiction_memory),
                "trusted_subsystems": sorted(
                    k for k, v in self._record.trust_fingerprint.items() if v >= 0.6
                ),
                "confidence": round(self._record.identity_integrity, 4),
                "stability_impact": round(self._record.continuity_score, 4),
                "coherence_impact": round(self._record.behavioral_coherence, 4),
                "causal_trace_metadata": {"timeline_path": _TIMELINE_PATH},
                "rationale": "Identity integrity combines continuity, values, behavior, and drift dynamics.",
                "epoch": _safe_epoch(),
            }

    def _load(self) -> None:
        try:
            with open(_ID_PATH, encoding="utf-8") as fh:
                d = json.load(fh)
        except FileNotFoundError:
            return
        except Exception as exc:
            log.debug("[NiblitIdentity] load failed: %s", exc)
            return

        with self._lock:
            self._record.identity_version = int(d.get("identity_version", 1))
            self._record.epoch_born = int(d.get("epoch_born", 1))
            self._record.created_at = d.get("created_at", self._record.created_at)
            self._record.last_updated = d.get("last_updated", self._record.last_updated)
            self._record.strategic_direction = d.get("strategic_direction", self._record.strategic_direction)
            self._record.persistent_goals = list(d.get("persistent_goals", self._record.persistent_goals))
            self._record.learning_history = list(d.get("learning_history", []))
            self._record.trust_fingerprint = dict(d.get("trust_fingerprint", {}))
            self._record.continuity_score = float(d.get("continuity_score", 1.0))
            self._record.identity_integrity = float(d.get("identity_integrity", self._record.continuity_score))
            self._record.value_stability = float(d.get("value_stability", 1.0))
            self._record.behavioral_coherence = float(d.get("behavioral_coherence", 1.0))
            self._record.identity_drift_score = float(d.get("identity_drift_score", 0.0))
            self._record.drift_velocity = float(d.get("drift_velocity", 0.0))
            self._record.trajectory_validation_score = float(d.get("trajectory_validation_score", 1.0))
            self._record.session_count = int(d.get("session_count", 0))
            self._record.contradiction_memory = list(d.get("contradiction_memory", []))

    def _save(self) -> None:
        if not _ENABLED:
            return
        try:
            with self._lock:
                d = self._record.to_dict()
            tmp = _ID_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(d, fh, indent=2)
            os.replace(tmp, _ID_PATH)
        except Exception as exc:
            log.debug("[NiblitIdentity] save failed: %s", exc)

    def _append_timeline(self, event_type: str, payload: dict[str, Any]) -> None:
        try:
            row = {
                "event_type": event_type,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "epoch": _safe_epoch(),
                "identity_version": self._record.identity_version,
                "payload": payload,
            }
            with open(_TIMELINE_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def _emit_identity_drift(self, action: str) -> None:
        try:
            from modules.event_bus import EVENT_IDENTITY_DRIFT, EVENT_IDENTITY_UPDATED, NiblitEvent, get_event_bus

            payload = {
                "action": action,
                "identity_drift_score": self._record.identity_drift_score,
                "drift_velocity": self._record.drift_velocity,
                "confidence": self._record.identity_integrity,
                "stability_impact": self._record.continuity_score,
                "coherence_impact": self._record.behavioral_coherence,
                "causal_trace_metadata": {"identity_version": self._record.identity_version},
                "rationale": "Identity drift computed from behavior/value/continuity divergence.",
                "epoch": _safe_epoch(),
            }
            bus = get_event_bus()
            bus.publish(NiblitEvent(type=EVENT_IDENTITY_DRIFT, source="niblit_identity", payload=payload))
            bus.publish(NiblitEvent(type=EVENT_IDENTITY_UPDATED, source="niblit_identity", payload=payload))
        except Exception:
            pass

    def _emit_identity_validated(self, action: str) -> None:
        try:
            from modules.event_bus import (
                EVENT_IDENTITY_UPDATED,
                EVENT_IDENTITY_VALIDATED,
                NiblitEvent,
                get_event_bus,
            )

            payload = {
                "action": action,
                "identity_integrity": self._record.identity_integrity,
                "continuity_score": self._record.continuity_score,
                "value_stability": self._record.value_stability,
                "behavioral_coherence": self._record.behavioral_coherence,
                "confidence": self._record.identity_integrity,
                "stability_impact": self._record.continuity_score,
                "coherence_impact": self._record.behavioral_coherence,
                "causal_trace_metadata": {"identity_version": self._record.identity_version},
                "rationale": "Identity validation performed against trajectory, values, and behavior.",
                "epoch": _safe_epoch(),
            }
            bus = get_event_bus()
            bus.publish(NiblitEvent(type=EVENT_IDENTITY_VALIDATED, source="niblit_identity", payload=payload))
            bus.publish(NiblitEvent(type=EVENT_IDENTITY_UPDATED, source="niblit_identity", payload=payload))
        except Exception:
            pass


def _safe_epoch() -> int:
    try:
        from modules.unified_cognitive_state import get_unified_state

        return int(get_unified_state().status().get("epoch", 0))
    except Exception:
        return 0


_nid: NiblitIdentity | None = None
_nid_lock = threading.Lock()


def get_niblit_identity() -> NiblitIdentity:
    global _nid
    with _nid_lock:
        if _nid is None:
            _nid = NiblitIdentity()
    return _nid


if __name__ == "__main__":
    print('Running niblit_identity.py')
