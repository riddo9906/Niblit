"""modules/meta_cognition/meta_evaluator.py — MetaEvaluator (MSG Layer v1).

Evaluates and scores *entire subsystems* (not individual facts/code) so
Niblit can introspect at the system level:

    SystemScore = {ALE: 0.81, Kernel: 0.76, Trading: 0.42, Security: 0.91}

Scores are updated incrementally from signals gathered during each ALE cycle
(step durations, error rates, success indicators) and from explicit calls by
individual modules.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("Niblit.MetaEvaluator")

# ── Default subsystem registry ────────────────────────────────────────────────

_DEFAULT_SUBSYSTEMS = [
    "ALE",           # Autonomous Learning Engine
    "Kernel",        # Core Kernel / KernelV3
    "Trading",       # TradingBrain
    "Security",      # CyberMembrane + DEL
    "Memory",        # MWDS / MemoryStore
    "Language",      # LanguageModule
    "Research",      # PhasedResearch / SelfResearcher
    "Reasoning",     # ReasoningEngine / CognitionCore
    "Evolution",     # EvolveEngine / EvolutionPlanner
    "Civilization",  # STACA civilization agents
]

# Scoring bounds
_SCORE_MIN = 0.0
_SCORE_MAX = 1.0
_INITIAL_SCORE = 0.5  # neutral starting point
_ALPHA = 0.2          # EMA weight for new observations


class SubsystemRecord:
    """Tracks score and error/success events for one subsystem."""

    __slots__ = ("name", "score", "errors", "successes", "last_updated")

    def __init__(self, name: str) -> None:
        self.name = name
        self.score: float = _INITIAL_SCORE
        self.errors: int = 0
        self.successes: int = 0
        self.last_updated: float = time.time()

    def update(self, observation: float) -> None:
        """EMA update with a new observation ∈ [0, 1]."""
        observation = max(_SCORE_MIN, min(_SCORE_MAX, observation))
        self.score = round(self.score * (1 - _ALPHA) + observation * _ALPHA, 4)
        self.last_updated = time.time()

    def record_error(self, weight: float = 0.2) -> None:
        self.errors += 1
        self.update(max(0.0, self.score - weight))

    def record_success(self, weight: float = 0.1) -> None:
        self.successes += 1
        self.update(min(1.0, self.score + weight))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "score": self.score,
            "errors": self.errors,
            "successes": self.successes,
            "last_updated": self.last_updated,
        }


class MetaEvaluator:
    """Scores Niblit's subsystems and identifies the weakest links.

    Thread-safe.  All write methods acquire the internal lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subsystems: Dict[str, SubsystemRecord] = {
            name: SubsystemRecord(name) for name in _DEFAULT_SUBSYSTEMS
        }

    # ── Public update API ─────────────────────────────────────────────────

    def observe(self, subsystem: str, score: float) -> None:
        """Feed a new quality observation ∈ [0, 1] for *subsystem*."""
        with self._lock:
            if subsystem not in self._subsystems:
                self._subsystems[subsystem] = SubsystemRecord(subsystem)
            self._subsystems[subsystem].update(score)

    def record_error(self, subsystem: str, weight: float = 0.2) -> None:
        """Mark an error event for *subsystem*, penalising its score."""
        with self._lock:
            rec = self._subsystems.setdefault(subsystem, SubsystemRecord(subsystem))
            rec.record_error(weight)
            log.debug("[MetaEvaluator] %s error recorded → score=%.3f", subsystem, rec.score)

    def record_success(self, subsystem: str, weight: float = 0.1) -> None:
        """Mark a success event for *subsystem*, boosting its score."""
        with self._lock:
            rec = self._subsystems.setdefault(subsystem, SubsystemRecord(subsystem))
            rec.record_success(weight)

    # ── Query API ─────────────────────────────────────────────────────────

    def scores(self) -> Dict[str, float]:
        """Return a {subsystem: score} mapping."""
        with self._lock:
            return {name: rec.score for name, rec in self._subsystems.items()}

    def weakest(self, n: int = 3) -> List[str]:
        """Return the *n* subsystem names with the lowest scores."""
        with self._lock:
            return sorted(
                self._subsystems,
                key=lambda k: self._subsystems[k].score,
            )[:n]

    def strongest(self, n: int = 3) -> List[str]:
        """Return the *n* subsystem names with the highest scores."""
        with self._lock:
            return sorted(
                self._subsystems,
                key=lambda k: self._subsystems[k].score,
                reverse=True,
            )[:n]

    def score_for(self, subsystem: str) -> float:
        """Return the current score for *subsystem* (default 0.5 if unknown)."""
        with self._lock:
            rec = self._subsystems.get(subsystem)
            return rec.score if rec else _INITIAL_SCORE

    def snapshot(self) -> Dict[str, Any]:
        """Return a full serialisable snapshot."""
        with self._lock:
            return {
                "subsystems": {name: rec.to_dict()
                               for name, rec in self._subsystems.items()},
                "weakest": self.weakest(3),
                "strongest": self.strongest(3),
            }


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[MetaEvaluator] = None
_inst_lock = threading.Lock()


def get_meta_evaluator() -> MetaEvaluator:
    """Return the process-wide :class:`MetaEvaluator` singleton."""
    global _instance
    if _instance is None:
        with _inst_lock:
            if _instance is None:
                _instance = MetaEvaluator()
    return _instance
