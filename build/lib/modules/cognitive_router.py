#!/usr/bin/env python3
"""
modules/cognitive_router.py — Phase 21 Cognitive Router Layer

Determines the *execution mode* Niblit should adopt before taking any action.
It sits between raw user input and the execution graph, deciding *which
cognitive hat to wear* for a given request.

Execution modes
---------------
Mode            | Purpose
----------------|--------------------------------------------------------
conversational  | Normal chat / small talk
analytical      | Deep reasoning, research, explanations
operational     | Execute tools, run code, fetch data
forecasting     | Predict future states, trend analysis
governance      | Safety checks, permission validation, risk assessment
reflective      | Self-improvement, memory consolidation, learning
simulation      | Dry-run future outcomes, what-if scenarios

The router accepts either a raw text string or a pre-computed
:class:`~modules.intent_engine.IntentProfile` and returns a
:class:`CognitiveMode` decision.

Architecture
------------
::

    User Input
        │
        ▼
    IntentEngine.classify()
        │
        ▼
    CognitiveRouter.route()        ← this module
        │
        ├── MODE_CONVERSATIONAL → fast LLM response
        ├── MODE_ANALYTICAL     → extended reasoning + memory retrieval
        ├── MODE_OPERATIONAL    → execution_graph with tools
        ├── MODE_FORECASTING    → forecast_arbitrator consultation
        ├── MODE_GOVERNANCE     → safety / risk validation first
        ├── MODE_REFLECTIVE     → self_model update + memory consolidation
        └── MODE_SIMULATION     → deliberative_planner dry-run

Configuration (env vars)
------------------------
    NIBLIT_COGNITIVE_ROUTER_ENABLED — "0" to disable (default 1)

Usage::

    from modules.cognitive_router import get_cognitive_router

    router = get_cognitive_router()
    mode = router.route("What will BTC do next week?")
    print(mode.mode_name)     # "forecasting"
    print(mode.use_tools)     # False
    print(mode.use_forecast)  # True
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

log = logging.getLogger(__name__)

_ENABLED: bool = os.getenv("NIBLIT_COGNITIVE_ROUTER_ENABLED", "1").strip() not in ("0", "false")

# ── Mode constants ─────────────────────────────────────────────────────────────
MODE_CONVERSATIONAL = "conversational"
MODE_ANALYTICAL     = "analytical"
MODE_OPERATIONAL    = "operational"
MODE_FORECASTING    = "forecasting"
MODE_GOVERNANCE     = "governance"
MODE_REFLECTIVE     = "reflective"
MODE_SIMULATION     = "simulation"

_ALL_MODES = frozenset({
    MODE_CONVERSATIONAL, MODE_ANALYTICAL, MODE_OPERATIONAL,
    MODE_FORECASTING, MODE_GOVERNANCE, MODE_REFLECTIVE, MODE_SIMULATION,
})

# ── Intent → mode mapping ─────────────────────────────────────────────────────
# Maps intent_engine labels to cognitive modes.
# "trading" intent maps to OPERATIONAL (with forecast flag set too).
_INTENT_TO_MODE: Dict[str, str] = {
    "conversational": MODE_CONVERSATIONAL,
    "analytical":     MODE_ANALYTICAL,
    "operational":    MODE_OPERATIONAL,
    "forecasting":    MODE_FORECASTING,
    "governance":     MODE_GOVERNANCE,
    "reflective":     MODE_REFLECTIVE,
    "simulation":     MODE_SIMULATION,
    "trading":        MODE_OPERATIONAL,
}

# Per-mode capability flags
_MODE_FLAGS: Dict[str, Dict[str, bool]] = {
    MODE_CONVERSATIONAL: {"use_tools": False, "use_forecast": False, "use_memory": True,  "run_governance": False},
    MODE_ANALYTICAL:     {"use_tools": False, "use_forecast": False, "use_memory": True,  "run_governance": False},
    MODE_OPERATIONAL:    {"use_tools": True,  "use_forecast": False, "use_memory": True,  "run_governance": True},
    MODE_FORECASTING:    {"use_tools": False, "use_forecast": True,  "use_memory": True,  "run_governance": False},
    MODE_GOVERNANCE:     {"use_tools": False, "use_forecast": False, "use_memory": True,  "run_governance": True},
    MODE_REFLECTIVE:     {"use_tools": False, "use_forecast": False, "use_memory": True,  "run_governance": False},
    MODE_SIMULATION:     {"use_tools": True,  "use_forecast": True,  "use_memory": True,  "run_governance": True},
}


# ── CognitiveMode ─────────────────────────────────────────────────────────────

@dataclass
class CognitiveMode:
    """The routing decision for a single request."""
    mode_name: str
    use_tools: bool
    use_forecast: bool
    use_memory: bool
    run_governance: bool
    intent: str = ""
    confidence: float = 1.0
    context: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "mode_name": self.mode_name,
            "use_tools": self.use_tools,
            "use_forecast": self.use_forecast,
            "use_memory": self.use_memory,
            "run_governance": self.run_governance,
            "intent": self.intent,
            "confidence": self.confidence,
        }


# ── CognitiveRouter ───────────────────────────────────────────────────────────

class CognitiveRouter:
    """Maps intent profiles to execution modes.

    Thread-safe singleton.  Falls back to ``conversational`` mode on any
    error so the system always produces some response.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._route_counts: Dict[str, int] = {}
        self._total_routes: int = 0
        log.debug("[CognitiveRouter] initialised")

    # ── Public API ─────────────────────────────────────────────────────────────

    def route(self, text_or_profile: "str | Any") -> CognitiveMode:
        """Determine the :class:`CognitiveMode` for a given input.

        Args:
            text_or_profile: Either a raw string (will be classified via
                             :class:`~modules.intent_engine.IntentEngine`) or
                             a pre-computed
                             :class:`~modules.intent_engine.IntentProfile`.

        Returns:
            :class:`CognitiveMode` — always valid, falls back to
            ``conversational`` on errors.
        """
        if not _ENABLED:
            return self._default_mode()
        try:
            return self._route_inner(text_or_profile)
        except Exception as exc:
            log.warning("[CognitiveRouter] route error: %s", exc)
            return self._default_mode()

    def _route_inner(self, text_or_profile: Any) -> CognitiveMode:
        # Accept a pre-classified IntentProfile or a raw string
        if hasattr(text_or_profile, "intent") and hasattr(text_or_profile, "confidence"):
            profile = text_or_profile
        else:
            from modules.intent_engine import get_intent_engine
            profile = get_intent_engine().classify(str(text_or_profile))

        intent = profile.intent
        mode_name = _INTENT_TO_MODE.get(intent, MODE_CONVERSATIONAL)
        flags = _MODE_FLAGS.get(mode_name, _MODE_FLAGS[MODE_CONVERSATIONAL])

        # For trading intent, also enable forecast
        extra_forecast = (intent == "trading") or profile.requires_forecast

        mode = CognitiveMode(
            mode_name=mode_name,
            use_tools=flags["use_tools"] or profile.requires_tools,
            use_forecast=flags["use_forecast"] or extra_forecast,
            use_memory=flags["use_memory"] or profile.requires_memory,
            run_governance=flags["run_governance"] or profile.safety_level == "high",
            intent=intent,
            confidence=profile.confidence,
        )

        with self._lock:
            self._total_routes += 1
            self._route_counts[mode_name] = self._route_counts.get(mode_name, 0) + 1

        log.debug("[CognitiveRouter] intent=%s → mode=%s (conf=%.2f)", intent, mode_name, profile.confidence)
        return mode

    def _default_mode(self) -> CognitiveMode:
        flags = _MODE_FLAGS[MODE_CONVERSATIONAL]
        return CognitiveMode(mode_name=MODE_CONVERSATIONAL, **flags)

    def status(self) -> Dict:
        with self._lock:
            return {
                "enabled": _ENABLED,
                "total_routes": self._total_routes,
                "route_counts": dict(self._route_counts),
            }


# ── Singleton ─────────────────────────────────────────────────────────────────
_router: Optional[CognitiveRouter] = None
_router_lock = threading.Lock()


def get_cognitive_router() -> CognitiveRouter:
    """Return the module-level :class:`CognitiveRouter` singleton."""
    global _router
    with _router_lock:
        if _router is None:
            _router = CognitiveRouter()
    return _router


if __name__ == "__main__":
    print('Running cognitive_router.py')
