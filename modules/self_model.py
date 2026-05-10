#!/usr/bin/env python3
"""
modules/self_model.py — Phase 21 Self-Model Layer

Gives Niblit the ability to reason **about itself** — tracking its own
capabilities, confidence bounds, known weaknesses, active goals, and
runtime bottlenecks.  This enables truly adaptive coordination where the
system can adjust its own strategy based on introspective state.

Self-state
----------
:class:`SelfState` — snapshot of introspective metrics::

    reasoning_quality   : float 0.0–1.0  — average quality of recent turns
    memory_pressure     : float 0.0–1.0  — memory subsystem load
    forecast_reliability: float 0.0–1.0  — recent forecast accuracy
    tool_reliability    : float 0.0–1.0  — tool success rate
    dominant_failure_mode: str           — most frequent failure pattern
    active_goals        : list[str]      — top-priority goals
    learning_velocity   : float          — rate of improvement (EMA)
    known_weaknesses    : list[str]      — explicit self-identified gaps
    subsystem_reliability: dict[str,float] — per-subsystem health 0.0–1.0

Key methods
-----------
``update_from_turn(quality)``   — record one interaction quality score
``update_from_tool(name, ok)``  — record a tool call outcome
``update_from_forecast(ok)``    — record a forecast accuracy outcome
``snapshot()``                  — return current :class:`SelfState`
``status()``                    — return raw metrics dict

State persistence
-----------------
Saved to ``self_model_state.json`` in the project root.

Configuration (env vars)
------------------------
    NIBLIT_SELF_MODEL_ENABLED   — "0" to disable (default 1)
    NIBLIT_SELF_MODEL_EMA       — EMA alpha for metric updates (default 0.15)
    NIBLIT_SELF_MODEL_PATH      — override state file path

Usage::

    from modules.self_model import get_self_model

    sm = get_self_model()
    sm.update_from_turn(quality=0.8)
    state = sm.snapshot()
    print(state.reasoning_quality, state.dominant_failure_mode)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_ENABLED: bool = os.getenv("NIBLIT_SELF_MODEL_ENABLED", "1").strip() not in ("0", "false")
_EMA_ALPHA: float = float(os.getenv("NIBLIT_SELF_MODEL_EMA", "0.15"))
_STATE_PATH: str = os.getenv(
    "NIBLIT_SELF_MODEL_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "self_model_state.json"),
)

# Known failure mode labels
FAILURE_NONE          = "none"
FAILURE_TOOL_OVERTRUST = "tool_overtrust"
FAILURE_MEMORY_DRIFT  = "memory_drift"
FAILURE_REASONING_GAP = "reasoning_gap"
FAILURE_CONTEXT_LOSS  = "context_loss"
FAILURE_FORECAST_OVERCONFIDENCE = "forecast_overconfidence"


# ── SelfState ─────────────────────────────────────────────────────────────────

@dataclass
class SelfState:
    """Frozen snapshot of Niblit's introspective self-assessment."""
    reasoning_quality: float
    memory_pressure: float
    forecast_reliability: float
    tool_reliability: float
    dominant_failure_mode: str
    active_goals: List[str]
    learning_velocity: float
    known_weaknesses: List[str]
    subsystem_reliability: Dict[str, float]

    def to_dict(self) -> Dict:
        return {
            "reasoning_quality": round(self.reasoning_quality, 4),
            "memory_pressure": round(self.memory_pressure, 4),
            "forecast_reliability": round(self.forecast_reliability, 4),
            "tool_reliability": round(self.tool_reliability, 4),
            "dominant_failure_mode": self.dominant_failure_mode,
            "active_goals": list(self.active_goals),
            "learning_velocity": round(self.learning_velocity, 4),
            "known_weaknesses": list(self.known_weaknesses),
            "subsystem_reliability": {k: round(v, 4) for k, v in self.subsystem_reliability.items()},
        }


# ── SelfModel ─────────────────────────────────────────────────────────────────

class SelfModel:
    """Tracks and updates Niblit's introspective self-assessment.

    Thread-safe.  All metrics are maintained as exponential moving averages
    so they reflect recent history without being volatile.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # Core metrics (EMA)
        self._reasoning_quality: float = 0.5
        self._forecast_reliability: float = 0.5
        self._tool_reliability: float = 0.5
        self._learning_velocity: float = 0.0

        # Counters for failure-mode detection
        self._failure_counts: Dict[str, int] = {k: 0 for k in [
            FAILURE_NONE, FAILURE_TOOL_OVERTRUST, FAILURE_MEMORY_DRIFT,
            FAILURE_REASONING_GAP, FAILURE_CONTEXT_LOSS,
            FAILURE_FORECAST_OVERCONFIDENCE,
        ]}

        # Known weaknesses (static + runtime-updated)
        self._weaknesses: List[str] = [
            "context window limits on small models",
            "hallucination risk without grounding",
            "no long-horizon planning yet",
        ]

        # Active goals (pulled from GoalEngine if available)
        self._active_goals: List[str] = []

        # Per-subsystem reliability
        self._subsystem_reliability: Dict[str, float] = {
            "brain":         0.8,
            "memory":        0.8,
            "tools":         0.8,
            "forecast":      0.5,
            "governance":    0.8,
            "learning":      0.7,
        }

        self._update_count: int = 0
        self._load_state()
        log.debug("[SelfModel] initialised")

    # ── Update methods ─────────────────────────────────────────────────────────

    def update_from_turn(self, quality: float) -> None:
        """Record the quality of a completed interaction turn.

        Args:
            quality: Interaction quality score 0.0–1.0.
        """
        if not _ENABLED:
            return
        quality = max(0.0, min(1.0, float(quality)))
        with self._lock:
            prev = self._reasoning_quality
            self._reasoning_quality = _ema(self._reasoning_quality, quality)
            # Learning velocity = how much reasoning quality is improving
            delta = self._reasoning_quality - prev
            self._learning_velocity = _ema(self._learning_velocity, delta + 0.5)  # centre on 0.5
            self._update_count += 1

            # Detect reasoning gap failure mode
            if quality < 0.4:
                self._failure_counts[FAILURE_REASONING_GAP] += 1

        self._save_state()

    def update_from_tool(self, tool_name: str, success: bool) -> None:
        """Record a tool call outcome and update tool reliability.

        Args:
            tool_name: Name of the tool that was called.
            success:   Whether the call succeeded.
        """
        if not _ENABLED:
            return
        score = 1.0 if success else 0.0
        with self._lock:
            self._tool_reliability = _ema(self._tool_reliability, score)
            self._subsystem_reliability["tools"] = self._tool_reliability

            if not success:
                self._failure_counts[FAILURE_TOOL_OVERTRUST] += 1

        self._save_state()

    def update_from_forecast(self, accurate: bool) -> None:
        """Record whether the most recent forecast was accurate.

        Args:
            accurate: True if the forecast matched the actual outcome.
        """
        if not _ENABLED:
            return
        score = 1.0 if accurate else 0.0
        with self._lock:
            self._forecast_reliability = _ema(self._forecast_reliability, score)
            self._subsystem_reliability["forecast"] = self._forecast_reliability

            if not accurate:
                self._failure_counts[FAILURE_FORECAST_OVERCONFIDENCE] += 1

        self._save_state()

    def update_subsystem(self, subsystem: str, health: float) -> None:
        """Directly update a subsystem reliability score.

        Args:
            subsystem: Name of the subsystem (e.g. ``"memory"``, ``"brain"``).
            health:    Health score 0.0–1.0.
        """
        if not _ENABLED:
            return
        health = max(0.0, min(1.0, float(health)))
        with self._lock:
            if subsystem in self._subsystem_reliability:
                self._subsystem_reliability[subsystem] = _ema(
                    self._subsystem_reliability[subsystem], health
                )
            else:
                self._subsystem_reliability[subsystem] = health

    def add_weakness(self, weakness: str) -> None:
        """Add a new known weakness if not already present."""
        with self._lock:
            if weakness not in self._weaknesses:
                self._weaknesses.append(weakness)
        self._save_state()

    # ── Query methods ──────────────────────────────────────────────────────────

    def snapshot(self) -> SelfState:
        """Return a :class:`SelfState` snapshot of current self-assessment."""
        with self._lock:
            dominant_failure = max(
                (k for k in self._failure_counts if k != FAILURE_NONE),
                key=lambda k: self._failure_counts[k],
                default=FAILURE_NONE,
            )
            # Pull fresh goals from GoalEngine if available
            goals = self._get_active_goals()

            # Memory pressure from NiblitMemory if available
            mem_pressure = self._get_memory_pressure()

            return SelfState(
                reasoning_quality=self._reasoning_quality,
                memory_pressure=mem_pressure,
                forecast_reliability=self._forecast_reliability,
                tool_reliability=self._tool_reliability,
                dominant_failure_mode=dominant_failure,
                active_goals=goals[:5],
                learning_velocity=max(0.0, min(1.0, self._learning_velocity)),
                known_weaknesses=list(self._weaknesses),
                subsystem_reliability=dict(self._subsystem_reliability),
            )

    def status(self) -> Dict:
        """Return raw metrics dict (for monitoring / status commands)."""
        state = self.snapshot()
        with self._lock:
            return {
                "enabled": _ENABLED,
                "update_count": self._update_count,
                "failure_counts": dict(self._failure_counts),
                **state.to_dict(),
            }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _get_active_goals(self) -> List[str]:
        """Pull top goals from GoalEngine (best-effort, returns [] on failure)."""
        try:
            from modules.goal_engine import get_goal_engine
            goals = get_goal_engine().generate_goals()
            return [g.topic for g in goals[:5]]
        except Exception:
            return list(self._active_goals)

    def _get_memory_pressure(self) -> float:
        """Estimate memory pressure 0.0–1.0 (best-effort)."""
        try:
            from niblit_memory import NiblitMemory
            mem = NiblitMemory()
            if hasattr(mem, "stats"):
                stats = mem.stats()
                # Rough heuristic: fact count / 10000
                count = stats.get("fact_count", 0) or stats.get("total_facts", 0)
                return min(1.0, count / 10000.0)
        except Exception:
            pass
        return 0.0

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_state(self) -> None:
        try:
            with open(_STATE_PATH, "r", encoding="utf-8") as fh:
                d = json.load(fh)
            self._reasoning_quality = d.get("reasoning_quality", 0.5)
            self._forecast_reliability = d.get("forecast_reliability", 0.5)
            self._tool_reliability = d.get("tool_reliability", 0.5)
            self._learning_velocity = d.get("learning_velocity", 0.0)
            self._failure_counts.update(d.get("failure_counts", {}))
            self._weaknesses = d.get("known_weaknesses", self._weaknesses)
            self._subsystem_reliability.update(d.get("subsystem_reliability", {}))
        except FileNotFoundError:
            pass
        except Exception as exc:
            log.debug("[SelfModel] load state failed: %s", exc)

    def _save_state(self) -> None:
        try:
            with self._lock:
                data = {
                    "reasoning_quality": self._reasoning_quality,
                    "forecast_reliability": self._forecast_reliability,
                    "tool_reliability": self._tool_reliability,
                    "learning_velocity": self._learning_velocity,
                    "failure_counts": dict(self._failure_counts),
                    "known_weaknesses": list(self._weaknesses),
                    "subsystem_reliability": dict(self._subsystem_reliability),
                }
            tmp = _STATE_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, _STATE_PATH)
        except Exception as exc:
            log.debug("[SelfModel] save state failed: %s", exc)


# ── EMA helper ────────────────────────────────────────────────────────────────

def _ema(current: float, new_value: float, alpha: float = _EMA_ALPHA) -> float:
    return alpha * new_value + (1.0 - alpha) * current


# ── Singleton ─────────────────────────────────────────────────────────────────
_model: Optional[SelfModel] = None
_model_lock = threading.Lock()


def get_self_model() -> SelfModel:
    """Return the module-level :class:`SelfModel` singleton."""
    global _model
    with _model_lock:
        if _model is None:
            _model = SelfModel()
    return _model
