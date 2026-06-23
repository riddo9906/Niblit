#!/usr/bin/env python3
"""
nibblebots/tool_reputation_engine.py — Phase 21 Tool Reputation Engine

Tracks per-tool performance metrics and computes a composite
**trust score** so the execution graph can prefer reliable tools and
demote hallucination-prone or slow ones.

Tracked metrics per tool
------------------------
    success_rate    — fraction of calls that returned without error
    avg_latency_ms  — exponential moving average of call latency
    usefulness_score — EMA of post-call usefulness ratings (0.0–1.0)
    call_count       — total invocations
    error_count      — total errors

Composite trust score
---------------------
::

    tool_score = success_rate × usefulness_score × recency_factor

where ``recency_factor`` decays calls older than ``TRE_DECAY_DAYS`` days.

State persistence
-----------------
State is saved to ``tool_reputation_state.json`` (writable directory).

Configuration (env vars)
------------------------
    NIBLIT_TRE_ENABLED      — "0" to disable (default 1)
    NIBLIT_TRE_DECAY_DAYS   — days before scores decay 50 % (default 7)
    NIBLIT_TRE_EMA_ALPHA    — EMA smoothing factor for latency/usefulness (default 0.2)
    NIBLIT_TRE_STATE_PATH   — override state file path

Usage::

    from nibblebots.tool_reputation_engine import get_tool_reputation_engine

    tre = get_tool_reputation_engine()
    tre.record_call("calculator", success=True, latency_ms=12.3, usefulness=0.9)
    score = tre.get_score("calculator")
    print(f"calculator trust = {score:.3f}")
    print(tre.ranked_tools())
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

_ENABLED: bool = os.getenv("NIBLIT_TRE_ENABLED", "1").strip() not in ("0", "false")
_DECAY_DAYS: float = float(os.getenv("NIBLIT_TRE_DECAY_DAYS", "7"))
_EMA_ALPHA: float = float(os.getenv("NIBLIT_TRE_EMA_ALPHA", "0.2"))
_STATE_PATH: str = os.getenv(
    "NIBLIT_TRE_STATE_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tool_reputation_state.json"),
)


# ── ToolRecord ────────────────────────────────────────────────────────────────

@dataclass
class ToolRecord:
    """Per-tool reputation record."""
    name: str
    call_count: int = 0
    error_count: int = 0
    success_count: int = 0
    avg_latency_ms: float = 0.0
    usefulness_score: float = 0.5   # starts at neutral
    last_call_ts: float = 0.0       # unix timestamp

    @property
    def success_rate(self) -> float:
        if self.call_count == 0:
            return 1.0  # no data → assume trustworthy
        return self.success_count / self.call_count

    def recency_factor(self, now: float, decay_days: float) -> float:
        """Exponential recency decay: 1.0 if called now, ↓ over time."""
        if self.last_call_ts <= 0 or decay_days <= 0:
            return 1.0
        age_days = (now - self.last_call_ts) / 86400.0
        return math.exp(-age_days / decay_days)

    def trust_score(self, now: Optional[float] = None, decay_days: float = _DECAY_DAYS) -> float:
        """Composite trust score in [0.0, 1.0]."""
        now = now or time.time()
        return self.success_rate * self.usefulness_score * self.recency_factor(now, decay_days)

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "call_count": self.call_count,
            "error_count": self.error_count,
            "success_count": self.success_count,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "usefulness_score": round(self.usefulness_score, 4),
            "success_rate": round(self.success_rate, 4),
            "trust_score": round(self.trust_score(), 4),
            "last_call_ts": self.last_call_ts,
        }


# ── ToolReputationEngine ─────────────────────────────────────────────────────

class ToolReputationEngine:
    """Tracks tool performance and computes adaptive trust scores.

    Thread-safe.  State is persisted on every ``record_call`` so rankings
    survive process restarts.
    """

    def __init__(self, state_path: str = _STATE_PATH, decay_days: float = _DECAY_DAYS) -> None:
        self._state_path = state_path
        self._decay_days = decay_days
        self._lock = threading.Lock()
        self._records: Dict[str, ToolRecord] = {}
        self._load_state()
        log.debug("[TRE] initialised with %d tool records", len(self._records))

    # ── Recording ─────────────────────────────────────────────────────────────

    def record_call(
        self,
        tool_name: str,
        success: bool,
        latency_ms: float = 0.0,
        usefulness: Optional[float] = None,
    ) -> None:
        """Record one tool invocation.

        Args:
            tool_name:   Name of the tool that was called.
            success:     Whether the call returned without error.
            latency_ms:  Wall-clock duration of the call in milliseconds.
            usefulness:  Optional 0.0–1.0 rating of how useful the result was.
                         When omitted, the existing EMA is left unchanged.
        """
        if not _ENABLED:
            return
        with self._lock:
            rec = self._records.get(tool_name)
            if rec is None:
                rec = ToolRecord(name=tool_name)
                self._records[tool_name] = rec

            rec.call_count += 1
            rec.last_call_ts = time.time()

            if success:
                rec.success_count += 1
            else:
                rec.error_count += 1

            # EMA update for latency
            if latency_ms > 0:
                if rec.avg_latency_ms <= 0:
                    rec.avg_latency_ms = latency_ms
                else:
                    rec.avg_latency_ms = (
                        _EMA_ALPHA * latency_ms + (1.0 - _EMA_ALPHA) * rec.avg_latency_ms
                    )

            # EMA update for usefulness
            if usefulness is not None:
                usefulness = max(0.0, min(1.0, float(usefulness)))
                rec.usefulness_score = (
                    _EMA_ALPHA * usefulness + (1.0 - _EMA_ALPHA) * rec.usefulness_score
                )

        self._save_state()

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_score(self, tool_name: str) -> float:
        """Return the current trust score for *tool_name* (0.0–1.0)."""
        with self._lock:
            rec = self._records.get(tool_name)
            if rec is None:
                return 0.5  # neutral for unknown tools
            return rec.trust_score()

    def get_record(self, tool_name: str) -> Optional[ToolRecord]:
        """Return the full :class:`ToolRecord` for *tool_name*, or ``None``."""
        with self._lock:
            return self._records.get(tool_name)

    def ranked_tools(self) -> List[Dict]:
        """Return all tools sorted by descending trust score."""
        now = time.time()
        with self._lock:
            recs = list(self._records.values())
        return sorted(
            [r.to_dict() for r in recs],
            key=lambda d: d["trust_score"],
            reverse=True,
        )

    def status(self) -> Dict:
        with self._lock:
            return {
                "enabled": _ENABLED,
                "tool_count": len(self._records),
                "decay_days": self._decay_days,
                "ema_alpha": _EMA_ALPHA,
                "tools": {name: rec.to_dict() for name, rec in self._records.items()},
            }

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_state(self) -> None:
        try:
            with open(self._state_path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            for name, d in raw.items():
                rec = ToolRecord(name=name)
                rec.call_count = d.get("call_count", 0)
                rec.error_count = d.get("error_count", 0)
                rec.success_count = d.get("success_count", rec.call_count - rec.error_count)
                rec.avg_latency_ms = d.get("avg_latency_ms", 0.0)
                rec.usefulness_score = d.get("usefulness_score", 0.5)
                rec.last_call_ts = d.get("last_call_ts", 0.0)
                self._records[name] = rec
        except FileNotFoundError:
            pass
        except Exception as exc:
            log.debug("[TRE] load state failed: %s", exc)

    def _save_state(self) -> None:
        try:
            with self._lock:
                data = {name: rec.to_dict() for name, rec in self._records.items()}
            tmp = self._state_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            os.replace(tmp, self._state_path)
        except Exception as exc:
            log.debug("[TRE] save state failed: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────────────────
_tre: Optional[ToolReputationEngine] = None
_tre_lock = threading.Lock()


def get_tool_reputation_engine() -> ToolReputationEngine:
    """Return the module-level :class:`ToolReputationEngine` singleton."""
    global _tre
    with _tre_lock:
        if _tre is None:
            _tre = ToolReputationEngine()
    return _tre


if __name__ == "__main__":
    print('Running tool_reputation_engine.py')
