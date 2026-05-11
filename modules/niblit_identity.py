#!/usr/bin/env python3
"""
modules/niblit_identity.py — Phase Ω Niblit Causal Identity Layer

Niblit needs persistent **self-continuity** — the sense of being the same
evolving intelligence across:

    - sessions
    - epochs
    - version upgrades
    - memory compression cycles
    - model swaps
    - AIOS restarts
    - governance shifts

Without this, each restart is effectively a different agent.  With it,
Niblit accumulates wisdom, stable values, and directional intent across
its entire lifetime.

Core concepts
-------------
``NiblitIdentity``
    The persistent identity record.  Contains:

    - ``identity_version``    : monotonic counter
    - ``core_values``         : immutable behavioral principles
    - ``persistent_goals``    : long-term objectives (survivable)
    - ``strategic_direction`` : current high-level direction string
    - ``learning_history``    : summary of lessons learned per phase
    - ``trust_fingerprint``   : per-subsystem trust record
    - ``epoch_born``          : epoch number of first initialisation
    - ``continuity_score``    : 0.0–1.0 how stable identity has been

Identity is preserved through:
    - JSON persistence (niblit_identity.json)
    - Epoch snapshots (tagged with epoch number)
    - Compression-safe summaries

Configuration (env vars)
------------------------
    NIBLIT_ID_ENABLED       — "0" to disable (default 1)
    NIBLIT_ID_PATH          — override state file path

Usage::

    from modules.niblit_identity import get_niblit_identity

    nid = get_niblit_identity()
    nid.record_lesson("Phase 21", "Compositional execution beats linear pipelines.")
    nid.update_direction("Focus on unified orchestration over isolated modules.")
    nid.update_trust("self_model", 0.82)

    snap = nid.snapshot()
    print(snap["strategic_direction"])
    print(snap["core_values"])
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

_ENABLED: bool = os.getenv("NIBLIT_ID_ENABLED", "1").strip() not in ("0", "false")
_ID_PATH: str = os.getenv(
    "NIBLIT_ID_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "niblit_identity.json"),
)

# Immutable core values (never modified by runtime)
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


# ── NiblitIdentityRecord ──────────────────────────────────────────────────────

class NiblitIdentityRecord:
    """Mutable part of Niblit's persistent identity."""

    def __init__(self) -> None:
        self.identity_version: int = 1
        self.epoch_born: int = 1
        self.created_at: str = datetime.now(tz=timezone.utc).isoformat()
        self.last_updated: str = self.created_at
        self.strategic_direction: str = (
            "Unify all subsystems into a temporally coherent cognitive organism."
        )
        self.persistent_goals: List[str] = [
            "maintain continuous learning across sessions",
            "achieve governance-constrained autonomous evolution",
            "build reliable forecasting for adaptive decision-making",
        ]
        self.learning_history: List[Dict] = []  # {phase, lesson, timestamp}
        self.trust_fingerprint: Dict[str, float] = {}  # subsystem → trust 0.0–1.0
        self.continuity_score: float = 1.0
        self.session_count: int = 0

    def to_dict(self) -> Dict:
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
            "session_count": self.session_count,
        }


# ── NiblitIdentity ────────────────────────────────────────────────────────────

class NiblitIdentity:
    """Persistent self-continuity layer for Niblit.

    Provides a stable identity contract that survives restarts, upgrades,
    memory compression, model swaps, and governance shifts.

    Thread-safe singleton.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._record = NiblitIdentityRecord()
        self._loaded = False
        self._load()
        with self._lock:
            self._record.session_count += 1
            self._record.identity_version += 1
            self._record.last_updated = datetime.now(tz=timezone.utc).isoformat()
        self._save()
        log.debug("[NiblitIdentity] session=%d version=%d",
                  self._record.session_count, self._record.identity_version)

    # ── Public API ────────────────────────────────────────────────────────────

    def record_lesson(self, phase: str, lesson: str) -> None:
        """Record a lesson learned in *phase*."""
        with self._lock:
            entry = {
                "phase": phase,
                "lesson": lesson,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            }
            self._record.learning_history.append(entry)
            if len(self._record.learning_history) > 100:
                self._record.learning_history.pop(0)
        self._save()

    def update_direction(self, direction: str) -> None:
        """Update the strategic direction statement."""
        with self._lock:
            self._record.strategic_direction = direction
            self._record.last_updated = datetime.now(tz=timezone.utc).isoformat()
        self._save()

    def add_goal(self, goal: str) -> None:
        """Add a persistent long-term goal."""
        with self._lock:
            if goal not in self._record.persistent_goals:
                self._record.persistent_goals.append(goal)
                if len(self._record.persistent_goals) > 30:
                    self._record.persistent_goals.pop(0)
        self._save()

    def update_trust(self, subsystem: str, trust: float) -> None:
        """Update trust score for a subsystem (EMA)."""
        trust = max(0.0, min(1.0, float(trust)))
        with self._lock:
            old = self._record.trust_fingerprint.get(subsystem, 0.7)
            self._record.trust_fingerprint[subsystem] = 0.15 * trust + 0.85 * old

    def update_continuity(self, delta: float) -> None:
        """Adjust continuity score by *delta* (positive = more coherent)."""
        with self._lock:
            self._record.continuity_score = max(0.0, min(1.0,
                self._record.continuity_score + delta))

    @property
    def core_values(self) -> List[str]:
        """Immutable core values — never modified."""
        return list(_CORE_VALUES)

    def snapshot(self) -> Dict:
        """Return the full identity snapshot as a dict."""
        with self._lock:
            return self._record.to_dict()

    def status(self) -> Dict:
        with self._lock:
            return {
                "enabled": _ENABLED,
                "identity_version": self._record.identity_version,
                "session_count": self._record.session_count,
                "continuity_score": round(self._record.continuity_score, 4),
                "strategic_direction": self._record.strategic_direction,
                "goal_count": len(self._record.persistent_goals),
                "lesson_count": len(self._record.learning_history),
                "trusted_subsystems": sorted(
                    k for k, v in self._record.trust_fingerprint.items() if v >= 0.6
                ),
            }

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            with open(_ID_PATH, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            with self._lock:
                self._record.identity_version = d.get("identity_version", 1)
                self._record.epoch_born = d.get("epoch_born", 1)
                self._record.created_at = d.get("created_at", self._record.created_at)
                self._record.strategic_direction = d.get("strategic_direction", self._record.strategic_direction)
                self._record.persistent_goals = d.get("persistent_goals", self._record.persistent_goals)
                self._record.learning_history = d.get("learning_history", [])
                self._record.trust_fingerprint = d.get("trust_fingerprint", {})
                self._record.continuity_score = d.get("continuity_score", 1.0)
                self._record.session_count = d.get("session_count", 0)
            self._loaded = True
        except FileNotFoundError:
            pass
        except Exception as exc:
            log.debug("[NiblitIdentity] load failed: %s", exc)

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


# ── Singleton ─────────────────────────────────────────────────────────────────
_nid: Optional[NiblitIdentity] = None
_nid_lock = threading.Lock()


def get_niblit_identity() -> NiblitIdentity:
    """Return the module-level :class:`NiblitIdentity` singleton."""
    global _nid
    with _nid_lock:
        if _nid is None:
            _nid = NiblitIdentity()
    return _nid
