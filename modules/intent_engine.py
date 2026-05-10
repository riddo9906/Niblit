#!/usr/bin/env python3
"""
modules/intent_engine.py — Phase 21 Intent Classification Engine

Classifies raw user or system input into a structured :class:`IntentProfile`
that downstream modules use to decide *how* to respond — not just *what* to
respond with.

This is Niblit's "prefrontal cortex": the thin, fast classification pass
that happens before any expensive reasoning, tool calls, or DB hits.

Intent labels
-------------
``conversational``   — casual chat, greetings, small talk
``analytical``       — deep research, reasoning, explanation
``operational``      — execute tools, write code, perform tasks
``forecasting``      — market prediction, trend analysis
``governance``       — safety checks, permission validation
``reflective``       — self-improvement, memory consolidation
``simulation``       — dry-run, what-if, scenario modelling
``trading``          — buy/sell/hold decisions, portfolio queries

Output
------
:class:`IntentProfile` — frozen dataclass containing:
    intent          : str    — primary intent label
    urgency         : float  — 0.0 (low) → 1.0 (critical)
    requires_tools  : bool   — should execution_graph invoke tools?
    requires_forecast: bool  — should forecast_arbitrator be consulted?
    requires_memory : bool   — is memory retrieval needed?
    safety_level    : str    — "low" | "medium" | "high"
    confidence      : float  — classifier confidence 0.0–1.0
    raw_scores      : dict   — per-intent raw probability scores

Configuration (env vars)
------------------------
    NIBLIT_INTENT_ENGINE_ENABLED — "0" to disable (default 1)

Usage::

    from modules.intent_engine import get_intent_engine

    engine = get_intent_engine()
    profile = engine.classify("What will BTC do tomorrow?")
    print(profile.intent)            # "forecasting"
    print(profile.requires_forecast) # True
"""

from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

_ENABLED: bool = os.getenv("NIBLIT_INTENT_ENGINE_ENABLED", "1").strip() not in ("0", "false")

# ── Intent keyword rules ──────────────────────────────────────────────────────
# Each entry: (intent_label, weight, [regex_patterns])
# Patterns are matched case-insensitively against the full input string.
_INTENT_RULES: List[Tuple[str, float, List[str]]] = [
    ("trading", 2.0, [
        r"\b(buy|sell|hold|trade|trading|portfolio|position|entry|exit|stop.?loss|take.?profit)\b",
        r"\b(btc|eth|sol|bnb|crypto|coin|token|market)\b.*\b(price|signal|action|decision)\b",
        r"\b(long|short|hedge|leverage|margin)\b",
    ]),
    ("forecasting", 1.8, [
        r"\b(forecast|predict|prediction|tomorrow|next.?(week|month|year)|future|will.+happen)\b",
        r"\b(trend|direction|outlook|projection|estimate|expect)\b",
        r"\b(price|market|stock|asset)\b.*(rise|fall|drop|crash|rally|moon|dump)\b",
        r"\bwhat.*(happen|be|go|do).*(next|soon|later)\b",
    ]),
    ("operational", 1.5, [
        r"\b(run|execute|call|invoke|tool|function|script|command|compute|calculate|generate|create|make|build|write)\b",
        r"\b(search|lookup|find|fetch|get|query|retrieve)\b",
        r"\b(code|program|implement|fix|debug|test)\b",
        r"\busing (tool|function|calculator|search|api)\b",
    ]),
    ("governance", 1.5, [
        r"\b(safe|safety|risk|danger|allow|deny|permission|authoris|authoriz|restrict|block|check|validate)\b",
        r"\b(should i|is it safe|can i|am i allowed|is this allowed|flag|report|concern)\b",
    ]),
    ("analytical", 1.2, [
        r"\b(explain|describe|analyse|analyze|understand|reason|why|how|what is|define|compare|contrast|evaluate|assess)\b",
        r"\b(research|study|investigate|explore|deep.?dive|breakdown|summary|overview)\b",
        r"\b(cause|effect|impact|implication|consequence|relationship|correlation)\b",
    ]),
    ("reflective", 1.0, [
        r"\b(learn|improve|evolve|update|remember|memory|recall|consolidate|reflect|self|introspect)\b",
        r"\b(what did you learn|what do you know|tell me about yourself|your progress|your goals)\b",
        r"\b(capability|weakness|strength|limitation|confidence)\b",
    ]),
    ("simulation", 1.0, [
        r"\b(simulate|simulation|what if|hypothetical|scenario|dry.?run|model|if we|suppose|assume)\b",
        r"\b(test|try|explore outcome|expected result|estimate impact)\b",
    ]),
    ("conversational", 0.5, [
        r"\b(hi|hello|hey|thanks|thank you|bye|goodbye|ok|okay|great|cool|nice|awesome)\b",
        r"^.{0,40}$",  # very short messages are often conversational
    ]),
]

_COMPILED_RULES: List[Tuple[str, float, List[re.Pattern]]] = [
    (label, weight, [re.compile(p, re.IGNORECASE) for p in patterns])
    for label, weight, patterns in _INTENT_RULES
]

# ── Metadata inference tables ─────────────────────────────────────────────────
_REQUIRES_TOOLS: frozenset = frozenset({"operational", "trading"})
_REQUIRES_FORECAST: frozenset = frozenset({"forecasting", "trading"})
_REQUIRES_MEMORY: frozenset = frozenset({"analytical", "reflective", "conversational", "operational"})
_SAFETY_LEVEL: Dict[str, str] = {
    "governance": "high",
    "trading": "medium",
    "operational": "medium",
    "forecasting": "low",
    "analytical": "low",
    "reflective": "low",
    "simulation": "low",
    "conversational": "low",
}
_URGENCY: Dict[str, float] = {
    "trading": 0.8,
    "governance": 0.9,
    "operational": 0.6,
    "forecasting": 0.5,
    "analytical": 0.3,
    "simulation": 0.3,
    "reflective": 0.2,
    "conversational": 0.1,
}


# ── IntentProfile ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class IntentProfile:
    """Structured representation of a classified user intent."""
    intent: str
    urgency: float
    requires_tools: bool
    requires_forecast: bool
    requires_memory: bool
    safety_level: str
    confidence: float
    raw_scores: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "intent": self.intent,
            "urgency": self.urgency,
            "requires_tools": self.requires_tools,
            "requires_forecast": self.requires_forecast,
            "requires_memory": self.requires_memory,
            "safety_level": self.safety_level,
            "confidence": self.confidence,
            "raw_scores": dict(self.raw_scores),
        }


# ── IntentEngine ──────────────────────────────────────────────────────────────

class IntentEngine:
    """Lightweight keyword-weighted intent classifier.

    Designed to be fast (no LLM call needed) and always-available.
    Falls back to ``"conversational"`` on any error.

    Thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total_classified: int = 0
        self._intent_counts: Dict[str, int] = {}
        log.debug("[IntentEngine] initialised")

    def classify(self, text: str) -> IntentProfile:
        """Classify *text* and return an :class:`IntentProfile`.

        Args:
            text: Raw user or system input string.

        Returns:
            :class:`IntentProfile` — always returns a valid profile even if
            classification fails (falls back to ``"conversational"``).
        """
        if not _ENABLED:
            return self._fallback()
        try:
            return self._classify_inner(text or "")
        except Exception as exc:
            log.warning("[IntentEngine] classify error: %s", exc)
            return self._fallback()

    def _classify_inner(self, text: str) -> IntentProfile:
        scores: Dict[str, float] = {label: 0.0 for label, _, _ in _INTENT_RULES}

        for label, weight, patterns in _COMPILED_RULES:
            for pat in patterns:
                if pat.search(text):
                    scores[label] += weight

        total = sum(scores.values())
        if total <= 0.0:
            # No signal — default to conversational
            best = "conversational"
            confidence = 0.5
            norm_scores = {k: 0.0 for k in scores}
            norm_scores["conversational"] = 0.5
        else:
            norm_scores = {k: v / total for k, v in scores.items()}
            best = max(norm_scores, key=norm_scores.__getitem__)
            confidence = norm_scores[best]

        profile = IntentProfile(
            intent=best,
            urgency=_URGENCY.get(best, 0.3),
            requires_tools=best in _REQUIRES_TOOLS,
            requires_forecast=best in _REQUIRES_FORECAST,
            requires_memory=best in _REQUIRES_MEMORY,
            safety_level=_SAFETY_LEVEL.get(best, "low"),
            confidence=round(confidence, 4),
            raw_scores={k: round(v, 4) for k, v in norm_scores.items()},
        )

        with self._lock:
            self._total_classified += 1
            self._intent_counts[best] = self._intent_counts.get(best, 0) + 1

        log.debug("[IntentEngine] '%s…' → %s (conf=%.2f)", text[:40], best, confidence)
        return profile

    def _fallback(self) -> IntentProfile:
        return IntentProfile(
            intent="conversational",
            urgency=0.1,
            requires_tools=False,
            requires_forecast=False,
            requires_memory=True,
            safety_level="low",
            confidence=0.5,
            raw_scores={},
        )

    def status(self) -> Dict:
        with self._lock:
            return {
                "enabled": _ENABLED,
                "total_classified": self._total_classified,
                "intent_counts": dict(self._intent_counts),
            }


# ── Singleton ─────────────────────────────────────────────────────────────────
_engine: Optional[IntentEngine] = None
_engine_lock = threading.Lock()


def get_intent_engine() -> IntentEngine:
    """Return the module-level :class:`IntentEngine` singleton."""
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = IntentEngine()
    return _engine
