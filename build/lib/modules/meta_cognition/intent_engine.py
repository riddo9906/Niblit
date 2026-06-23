"""modules/meta_cognition/intent_engine.py — IntentEngine (MSG Layer v1).

Provides *strategic intent* beyond simple goal-filling:

    Intent = Goal + Direction + Priority + Time Horizon + Resource Budget

The IntentEngine maintains a current strategic intent and a queue of
candidate intents.  It integrates with the ``GoalEngine`` and the
``SelfModel`` to choose the most valuable next focus area.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

log = logging.getLogger("Niblit.IntentEngine")

# Horizon labels
HORIZON_SHORT  = "short"   # 1–3 cycles
HORIZON_MEDIUM = "medium"  # 4–10 cycles
HORIZON_LONG   = "long"    # 11+ cycles


@dataclass
class Intent:
    """A single strategic intent."""
    label: str                          # human-readable name
    goal: str                           # what to achieve
    direction: str = ""                 # *how* to achieve it
    priority: float = 1.0               # higher = more important
    time_horizon: str = HORIZON_MEDIUM
    resource_budget: float = 0.2        # fraction of total resources [0,1]
    created_at: float = field(default_factory=time.time)
    cycle_target: int = 0               # ALE cycle by which to evaluate
    active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Intent":
        return cls(**{k: v for k, v in d.items()
                      if k in cls.__dataclass_fields__})  # type: ignore[attr-defined]


class IntentEngine:
    """Manages Niblit's active strategic intent and intent queue.

    The engine maintains one *current* intent (highest priority active intent)
    and a backlog of candidates.  On each ``tick()`` call it re-evaluates
    whether to switch intent based on changed conditions.
    """

    _DEFAULT_INTENTS: List[Dict[str, Any]] = [
        {
            "label": "deepen_general_knowledge",
            "goal": "Expand general knowledge breadth across all active domains",
            "direction": "Research one new topic per cycle via PhasedResearch",
            "priority": 1.0,
            "time_horizon": HORIZON_LONG,
            "resource_budget": 0.30,
        },
        {
            "label": "improve_language_understanding",
            "goal": "Improve natural-language comprehension and response quality",
            "direction": "Run language-module training; study linguistics and NLP topics",
            "priority": 1.5,
            "time_horizon": HORIZON_MEDIUM,
            "resource_budget": 0.20,
        },
        {
            "label": "strengthen_weakest_domain",
            "goal": "Reduce the largest knowledge gap identified by the MetaEvaluator",
            "direction": "Prioritise phased research for the lowest-scoring subsystem",
            "priority": 2.0,
            "time_horizon": HORIZON_SHORT,
            "resource_budget": 0.25,
        },
    ]

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: List[Intent] = [
            Intent(**d) for d in self._DEFAULT_INTENTS
        ]
        self._current: Optional[Intent] = None
        self._select_current()

    # ── Internal ─────────────────────────────────────────────────────────

    def _select_current(self) -> None:
        """Pick the highest-priority active intent as current."""
        active = [i for i in self._queue if i.active]
        if not active:
            self._current = None
            return
        self._current = max(active, key=lambda i: i.priority)

    # ── Public API ────────────────────────────────────────────────────────

    def add_intent(self, intent: Intent) -> None:
        """Add a new intent to the queue and re-select current."""
        with self._lock:
            self._queue.append(intent)
            self._select_current()

    def complete_intent(self, label: str) -> None:
        """Mark an intent as inactive (completed)."""
        with self._lock:
            for i in self._queue:
                if i.label == label:
                    i.active = False
            self._select_current()

    def tick(self, cycle: int, meta_scores: Optional[Dict[str, float]] = None) -> None:
        """Re-evaluate intent priorities based on current meta-scores.

        Called by the MSG pre-cycle hook each ALE cycle.
        """
        with self._lock:
            if meta_scores:
                # Boost "strengthen_weakest_domain" priority if any score is poor
                min_score = min(meta_scores.values(), default=0.5)
                for intent in self._queue:
                    if intent.label == "strengthen_weakest_domain":
                        # Lower meta-scores → higher urgency
                        intent.priority = max(1.5, 2.0 + (0.5 - min_score) * 3)
            self._select_current()
            if self._current:
                log.debug("[IntentEngine] Active intent: %s (priority=%.2f)",
                          self._current.label, self._current.priority)

    def current_intent(self) -> Dict[str, Any]:
        """Return the current intent as a dict, or an empty dict if none."""
        with self._lock:
            return self._current.to_dict() if self._current else {}

    def research_topic_hint(self, weaknesses: List[str]) -> Optional[str]:
        """Suggest a research topic aligned with the current intent.

        Returns a topic string or ``None`` if no hint is available.
        """
        with self._lock:
            if not self._current:
                return None
            if self._current.label == "strengthen_weakest_domain" and weaknesses:
                return weaknesses[0]
            return None

    def snapshot(self) -> Dict[str, Any]:
        """Return a serialisable snapshot."""
        with self._lock:
            return {
                "current": self._current.to_dict() if self._current else None,
                "queue_size": len(self._queue),
                "active_intents": [i.label for i in self._queue if i.active],
            }


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[IntentEngine] = None
_inst_lock = threading.Lock()


def get_intent_engine() -> IntentEngine:
    """Return the process-wide :class:`IntentEngine` singleton."""
    global _instance
    if _instance is None:
        with _inst_lock:
            if _instance is None:
                _instance = IntentEngine()
    return _instance


if __name__ == "__main__":
    print('Running intent_engine.py')
