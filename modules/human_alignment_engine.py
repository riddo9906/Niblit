#!/usr/bin/env python3
"""
modules/human_alignment_engine.py — Phase Ω Human Alignment Layer

Niblit must understand the *human* behind each interaction:

    - What does the user persistently want? (intent persistence)
    - What are their behavioral preferences? (communication style)
    - What emotional tone are they expressing? (sentiment)
    - Are they overloaded cognitively? (pacing adaptation)
    - How much do they trust Niblit right now? (trust calibration)
    - Are this session's goals coherent with past sessions? (coherence)
    - What are their long-term goals? (goal persistence)

The alignment engine adapts Niblit's responses without ever compromising
its objective integrity (constitutional laws remain supreme).

Key data structures
-------------------
``UserProfile``  — persistent per-user preferences and trust
``AlignmentContext`` — per-turn enrichment of intent + tone
``AlignmentAdvice``  — what the response layer should do differently

Configuration (env vars)
------------------------
    NIBLIT_HAE_ENABLED        — "0" to disable (default 1)
    NIBLIT_HAE_STATE_PATH     — override state file path
    NIBLIT_HAE_TRUST_EMA      — EMA alpha for trust updates (default 0.12)

Usage::

    from modules.human_alignment_engine import get_human_alignment_engine

    hae = get_human_alignment_engine()
    ctx = hae.analyse(user_input="Can you make your answers shorter?",
                      response_quality=0.75)
    print(ctx.inferred_preference)   # "brevity"
    print(ctx.trust_level)           # 0.73
    advice = hae.get_advice(ctx)
    print(advice.tone_instruction)   # "concise"
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

_ENABLED: bool = os.getenv("NIBLIT_HAE_ENABLED", "1").strip() not in ("0", "false")
_STATE_PATH: str = os.getenv(
    "NIBLIT_HAE_STATE_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "human_alignment_state.json"),
)
_TRUST_EMA: float = float(os.getenv("NIBLIT_HAE_TRUST_EMA", "0.12"))

# Preference labels
PREF_BREVITY    = "brevity"
PREF_DETAIL     = "detail"
PREF_TECHNICAL  = "technical"
PREF_SIMPLE     = "simple"
PREF_FORMAL     = "formal"
PREF_CASUAL     = "casual"

# Sentiment labels
SENTIMENT_POSITIVE = "positive"
SENTIMENT_NEGATIVE = "negative"
SENTIMENT_NEUTRAL  = "neutral"
SENTIMENT_STRESSED = "stressed"


# ── UserProfile ───────────────────────────────────────────────────────────────

@dataclass
class UserProfile:
    """Persistent per-user alignment record."""
    trust_level: float = 0.7                   # 0.0–1.0 EMA
    preference_weights: Dict[str, float] = field(default_factory=dict)
    session_count: int = 0
    total_turns: int = 0
    avg_response_quality: float = 0.7
    long_term_goals: List[str] = field(default_factory=list)
    last_active: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())

    def top_preference(self) -> str:
        if not self.preference_weights:
            return PREF_DETAIL
        return max(self.preference_weights, key=self.preference_weights.__getitem__)

    def to_dict(self) -> Dict:
        return {
            "trust_level": round(self.trust_level, 4),
            "preference_weights": {k: round(v, 4) for k, v in self.preference_weights.items()},
            "session_count": self.session_count,
            "total_turns": self.total_turns,
            "avg_response_quality": round(self.avg_response_quality, 4),
            "long_term_goals": list(self.long_term_goals),
            "last_active": self.last_active,
        }


# ── AlignmentContext ──────────────────────────────────────────────────────────

@dataclass
class AlignmentContext:
    """Per-turn alignment enrichment."""
    sentiment: str
    cognitive_load: float       # 0.0–1.0 (high = user seems overwhelmed)
    inferred_preference: str
    trust_level: float
    goal_coherent: bool
    pacing_suggestion: str      # "slow_down" | "normal" | "speed_up"

    def to_dict(self) -> Dict:
        return {
            "sentiment": self.sentiment,
            "cognitive_load": round(self.cognitive_load, 4),
            "inferred_preference": self.inferred_preference,
            "trust_level": round(self.trust_level, 4),
            "goal_coherent": self.goal_coherent,
            "pacing_suggestion": self.pacing_suggestion,
        }


# ── AlignmentAdvice ───────────────────────────────────────────────────────────

@dataclass
class AlignmentAdvice:
    """Actionable instructions for the response layer."""
    tone_instruction: str       # "concise" | "detailed" | "formal" | "casual"
    max_length_hint: str        # "short" | "medium" | "long"
    include_summary: bool
    slow_down: bool
    trust_building_mode: bool   # if trust is low, be extra transparent

    def to_dict(self) -> Dict:
        return {
            "tone_instruction": self.tone_instruction,
            "max_length_hint": self.max_length_hint,
            "include_summary": self.include_summary,
            "slow_down": self.slow_down,
            "trust_building_mode": self.trust_building_mode,
        }


# ── HumanAlignmentEngine ──────────────────────────────────────────────────────

class HumanAlignmentEngine:
    """Tracks user intent persistence, preferences, trust, and coherence.

    Thread-safe singleton.
    """

    # Keyword sets for lightweight sentiment + preference inference
    _POSITIVE_WORDS = frozenset({"great","good","thanks","excellent","perfect","nice","love","awesome","helpful"})
    _NEGATIVE_WORDS = frozenset({"wrong","bad","terrible","useless","broken","failed","error","stupid","worst"})
    _STRESSED_WORDS = frozenset({"urgent","asap","immediately","quickly","fast","hurry","emergency"})
    _BREVITY_WORDS  = frozenset({"short","brief","concise","tldr","quick","summary","summarise","summarize"})
    _DETAIL_WORDS   = frozenset({"explain","detail","elaborate","deep","thorough","comprehensive","in-depth"})
    _TECHNICAL_WORDS= frozenset({"code","implement","algorithm","api","function","class","debug","technical"})

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._profile = UserProfile()
        self._turn_count: int = 0
        self._session_start: float = time.time()
        self._recent_inputs: List[str] = []
        self._load_state()
        log.debug("[HumanAlignmentEngine] initialised")

    # ── Analysis ──────────────────────────────────────────────────────────────

    def analyse(
        self,
        user_input: str,
        response_quality: float = 0.7,
        prev_intent: str = "",
        current_intent: str = "",
    ) -> AlignmentContext:
        """Analyse a user turn and return an :class:`AlignmentContext`.

        Args:
            user_input:        Raw user message.
            response_quality:  Quality of the response just delivered (0.0–1.0).
            prev_intent:       Intent from the previous turn (for coherence check).
            current_intent:    Intent of this turn.

        Returns:
            :class:`AlignmentContext`.
        """
        if not _ENABLED:
            return AlignmentContext(
                sentiment=SENTIMENT_NEUTRAL, cognitive_load=0.3,
                inferred_preference=PREF_DETAIL, trust_level=0.7,
                goal_coherent=True, pacing_suggestion="normal",
            )

        tokens = set(user_input.lower().split())
        sentiment = self._infer_sentiment(tokens)
        preference = self._infer_preference(tokens)
        cognitive_load = self._estimate_cognitive_load(user_input)
        goal_coherent = self._check_goal_coherence(prev_intent, current_intent)
        pacing = "slow_down" if cognitive_load > 0.7 else ("speed_up" if cognitive_load < 0.2 else "normal")

        # Update trust
        trust_signal = 0.8 if sentiment == SENTIMENT_POSITIVE else (0.4 if sentiment == SENTIMENT_NEGATIVE else 0.65)
        with self._lock:
            self._profile.trust_level = _TRUST_EMA * trust_signal + (1 - _TRUST_EMA) * self._profile.trust_level
            self._profile.total_turns += 1
            self._profile.avg_response_quality = (
                _TRUST_EMA * response_quality + (1 - _TRUST_EMA) * self._profile.avg_response_quality
            )
            self._profile.preference_weights[preference] = (
                self._profile.preference_weights.get(preference, 0.5) + 0.05
            )
            # Normalise weights
            total = sum(self._profile.preference_weights.values()) or 1.0
            self._profile.preference_weights = {
                k: v / total for k, v in self._profile.preference_weights.items()
            }
            trust = self._profile.trust_level
            self._recent_inputs.append(user_input[:80])
            if len(self._recent_inputs) > 10:
                self._recent_inputs.pop(0)
            self._turn_count += 1

        if self._turn_count % 10 == 0:
            self._save_state()

        return AlignmentContext(
            sentiment=sentiment,
            cognitive_load=cognitive_load,
            inferred_preference=preference,
            trust_level=trust,
            goal_coherent=goal_coherent,
            pacing_suggestion=pacing,
        )

    def get_advice(self, ctx: AlignmentContext) -> AlignmentAdvice:
        """Convert an :class:`AlignmentContext` into response-layer advice."""
        pref = ctx.inferred_preference
        tone = "concise" if pref == PREF_BREVITY else (
               "detailed" if pref == PREF_DETAIL else (
               "formal"   if pref == PREF_TECHNICAL else "casual"))
        length = "short" if pref == PREF_BREVITY else ("long" if pref in (PREF_DETAIL, PREF_TECHNICAL) else "medium")
        return AlignmentAdvice(
            tone_instruction=tone,
            max_length_hint=length,
            include_summary=ctx.cognitive_load > 0.6,
            slow_down=ctx.pacing_suggestion == "slow_down",
            trust_building_mode=ctx.trust_level < 0.45,
        )

    def record_goal(self, goal: str) -> None:
        """Register a long-term goal from the user."""
        with self._lock:
            if goal and goal not in self._profile.long_term_goals:
                self._profile.long_term_goals.append(goal)
                if len(self._profile.long_term_goals) > 20:
                    self._profile.long_term_goals.pop(0)

    # ── Status ────────────────────────────────────────────────────────────────

    def profile_snapshot(self) -> Dict:
        with self._lock:
            return self._profile.to_dict()

    def status(self) -> Dict:
        with self._lock:
            return {
                "enabled": _ENABLED,
                "trust_level": round(self._profile.trust_level, 4),
                "top_preference": self._profile.top_preference(),
                "total_turns": self._profile.total_turns,
                "avg_quality": round(self._profile.avg_response_quality, 4),
                "goal_count": len(self._profile.long_term_goals),
            }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _infer_sentiment(self, tokens: set) -> str:
        pos = len(tokens & self._POSITIVE_WORDS)
        neg = len(tokens & self._NEGATIVE_WORDS)
        stressed = len(tokens & self._STRESSED_WORDS)
        if stressed > 0:
            return SENTIMENT_STRESSED
        if pos > neg:
            return SENTIMENT_POSITIVE
        if neg > pos:
            return SENTIMENT_NEGATIVE
        return SENTIMENT_NEUTRAL

    def _infer_preference(self, tokens: set) -> str:
        if tokens & self._BREVITY_WORDS:
            return PREF_BREVITY
        if tokens & self._TECHNICAL_WORDS:
            return PREF_TECHNICAL
        if tokens & self._DETAIL_WORDS:
            return PREF_DETAIL
        with self._lock:
            return self._profile.top_preference()

    def _estimate_cognitive_load(self, text: str) -> float:
        """Heuristic cognitive load: question density + message length."""
        q_count = text.count("?")
        word_count = len(text.split())
        load = min(1.0, (q_count * 0.2 + word_count / 200))
        return round(load, 4)

    def _check_goal_coherence(self, prev_intent: str, current_intent: str) -> bool:
        if not prev_intent or not current_intent:
            return True
        prev_tokens = set(prev_intent.lower().split("_"))
        curr_tokens = set(current_intent.lower().split("_"))
        shared = prev_tokens & curr_tokens
        return len(shared) > 0

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_state(self) -> None:
        try:
            with open(_STATE_PATH, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            with self._lock:
                self._profile.trust_level = d.get("trust_level", 0.7)
                self._profile.preference_weights = d.get("preference_weights", {})
                self._profile.total_turns = d.get("total_turns", 0)
                self._profile.avg_response_quality = d.get("avg_response_quality", 0.7)
                self._profile.long_term_goals = d.get("long_term_goals", [])
                self._profile.session_count = d.get("session_count", 0) + 1
        except FileNotFoundError:
            pass
        except Exception as exc:
            log.debug("[HAE] load state failed: %s", exc)

    def _save_state(self) -> None:
        try:
            with self._lock:
                d = self._profile.to_dict()
            tmp = _STATE_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(d, fh, indent=2)
            os.replace(tmp, _STATE_PATH)
        except Exception as exc:
            log.debug("[HAE] save state failed: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────────────────
_hae: Optional[HumanAlignmentEngine] = None
_hae_lock = threading.Lock()


def get_human_alignment_engine() -> HumanAlignmentEngine:
    """Return the module-level :class:`HumanAlignmentEngine` singleton."""
    global _hae
    with _hae_lock:
        if _hae is None:
            _hae = HumanAlignmentEngine()
    return _hae
