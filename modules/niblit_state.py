#!/usr/bin/env python3
"""modules/niblit_state.py — Shared SDAL State Object for Niblit.

Provides a thread-safe NiblitState singleton that serves as the single
shared state representation for all layers of the SDAL pipeline:

  - Perception (CyberMembrane, ChatDetector)
  - Advisor Pool (Memory, Reasoning, Goal, Quality, LLM)
  - Decision Engine (single gate)
  - Execution Layer (tools, APIs)

All modules update/read this central state rather than maintaining
independent local state, achieving true architectural unification.

Public API
----------
``NiblitState``
    Thread-safe dataclass with context, memory, signals, constraints, and
    active_goal fields.  All mutating methods are lock-protected.

``get_niblit_state() → NiblitState``
    Process-level singleton accessor (matching the pattern used by
    ``get_cognition_core()``, ``get_goal_engine()``, etc.).

Configuration (environment variables)::

    NIBLIT_STATE_MAX_MEMORY  — Maximum recalled facts kept in state.memory
                               (default 20)
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import os

log = logging.getLogger("NiblitState")

_MAX_MEMORY = int(os.environ.get("NIBLIT_STATE_MAX_MEMORY", "20"))


@dataclass
class NiblitState:
    """Shared state object for all SDAL pipeline layers.

    Attributes
    ----------
    context:     Current session/conversation state dict.
                 Keys: session_id, user_input, turn_count, last_topic, etc.
    memory:      Recent recalled facts from KnowledgeDB / MemoryGraph
                 (up to NIBLIT_STATE_MAX_MEMORY entries).
    signals:     Advisor signal outputs.  Keys: ``"memory"``, ``"reasoning"``,
                 ``"goal"``, ``"quality"``, ``"llm"``, ``"decision"``.
                 Values: ``{"suggestion": str, "confidence": float, "ts": int}``.
    constraints: CyberMembrane flags, rate limits, and security-layer outputs.
    active_goal: The current GoalEngine objective (Goal instance or None).
    """

    context: Dict[str, Any] = field(default_factory=dict)
    memory: List[Dict[str, Any]] = field(default_factory=list)
    signals: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    constraints: Dict[str, Any] = field(default_factory=dict)
    active_goal: Optional[Any] = None
    identity: Dict[str, Any] = field(default_factory=lambda: {
        "decision_style": "balanced",
        "risk_tolerance": 0.50,
        "response_bias": {},
        "total_decisions": 0,
    })

    # Internal lock — not part of the public data model.
    _lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )

    # ── Mutating helpers (all lock-protected) ─────────────────────────────────

    def update_context(self, **kwargs: Any) -> None:
        """Thread-safely merge *kwargs* into the context dict."""
        with self._lock:
            self.context.update(kwargs)

    def set_signal(self, advisor: str, suggestion: str, confidence: float) -> None:
        """Record a single advisor output."""
        with self._lock:
            self.signals[advisor] = {
                "suggestion": suggestion,
                "confidence": float(confidence),
                "ts": int(time.time()),
            }

    def set_memory(self, facts: List[Dict[str, Any]]) -> None:
        """Replace the current memory snapshot (capped at NIBLIT_STATE_MAX_MEMORY)."""
        with self._lock:
            self.memory = list(facts[:_MAX_MEMORY])

    def set_constraints(self, **kwargs: Any) -> None:
        """Thread-safely merge *kwargs* into the constraints dict."""
        with self._lock:
            self.constraints.update(kwargs)

    def set_active_goal(self, goal: Optional[Any]) -> None:
        """Set the current active learning goal."""
        with self._lock:
            self.active_goal = goal

    def update_identity(self, **kwargs: Any) -> None:
        """Thread-safely merge *kwargs* into the identity dict.

        Called by CognitiveIdentity to keep the shared state in sync with
        the persisted profile (decision_style, risk_tolerance, response_bias,
        total_decisions).
        """
        with self._lock:
            self.identity.update(kwargs)

    def clear_signals(self) -> None:
        """Clear all advisor signals at the start of a new request cycle."""
        with self._lock:
            self.signals.clear()

    # ── Read helpers ──────────────────────────────────────────────────────────

    def get_signal(self, advisor: str) -> Dict[str, Any]:
        """Return the most recent signal for *advisor*, or an empty dict."""
        with self._lock:
            return dict(self.signals.get(advisor, {}))

    def snapshot(self) -> Dict[str, Any]:
        """Return a point-in-time copy of all state fields for logging/debug."""
        with self._lock:
            goal_repr = (
                self.active_goal.to_dict()
                if self.active_goal is not None and hasattr(self.active_goal, "to_dict")
                else str(self.active_goal)
            )
            return {
                "context": dict(self.context),
                "memory_facts": len(self.memory),
                "signals": {k: dict(v) for k, v in self.signals.items()},
                "constraints": dict(self.constraints),
                "active_goal": goal_repr,
                "identity": dict(self.identity),
            }


# ── Singleton ─────────────────────────────────────────────────────────────────

_state: Optional[NiblitState] = None
_state_lock = threading.Lock()


def get_niblit_state() -> NiblitState:
    """Return the process-level :class:`NiblitState` singleton."""
    global _state  # pylint: disable=global-statement
    with _state_lock:
        if _state is None:
            _state = NiblitState()
            log.info("[NiblitState] Singleton created")
        return _state


if __name__ == "__main__":
    s = get_niblit_state()
    s.update_context(user_input="hello", turn_count=1)
    s.set_signal("memory", "Relevant context found", 0.7)
    print(s.snapshot())
