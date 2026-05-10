#!/usr/bin/env python3
"""
nibblebots/context_guard.py — Phase 8 Context Integrity & Intent Alignment Layer

Detects *context misbinding*: the failure mode where the system attaches a
new input / fix batch to the wrong prior context, causing it to act on stale
intent.

Failure classes handled
-----------------------
MISMATCH  — current fix-type/subsystem profile diverges sharply from the
             recent context window (likely a topic / phase boundary not
             properly reset).

SPIKE     — sudden single-step shift in fix_type that looks like noise rather
             than a natural transition (spike detector complement to EWMA).

REPEATED  — the exact same fix_type+subsystem combination appears for the
             second consecutive call, which is a strong human-in-the-loop
             retry signal.

ALIGNED   — everything checks out; proceed normally.

How it integrates
-----------------
semantic_engine.classify()   → calls context_guard.observe() after each issue
                               so the guard always has the current context.

evolution_planner.build_plan() → calls context_guard.check() before scoring;
                                  adjusts max_fixes / confidence gate based on
                                  the returned ContextVerdict.

modules/meta_engine.py       → subscribes to EVENT_CONTEXT_MISMATCH; lowers
                                context-persistence confidence and records the
                                pattern.

State persistence             → context_guard_log.jsonl  (audit trail)
                                context_guard_state.json (current window)
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, NamedTuple, Optional, Sequence

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Token-overlap similarity threshold below which we declare a context mismatch
_MISMATCH_THRESHOLD = float(os.environ.get("CTX_MISMATCH_THRESHOLD", "0.30"))

# Size of the rolling context window (recent fix_type+subsystem observations)
_CONTEXT_WINDOW = int(os.environ.get("CTX_WINDOW", "5"))

# Spike: if the current profile differs from the *immediate* prior by more
# than this, flag as a spike (even if the longer window still looks OK)
_SPIKE_THRESHOLD = float(os.environ.get("CTX_SPIKE_THRESHOLD", "0.20"))

# How much to penalise per-issue confidence on a mismatch verdict
_CONFIDENCE_PENALTY = float(os.environ.get("CTX_CONFIDENCE_PENALTY", "0.15"))

_STATE_FILE = Path(os.environ.get("CTX_STATE_FILE", str(Path(__file__).parent / "context_guard_state.json")))
_LOG_FILE = Path(os.environ.get("CTX_LOG_FILE", str(Path(__file__).parent / "context_guard_log.jsonl")))

# Stop words for token-overlap similarity (not meaningful for topic comparison)
_STOP_WORDS = frozenset(
    {"the", "a", "an", "in", "of", "to", "and", "or", "is", "are", "at",
     "for", "on", "with", "it", "this", "that", "be"}
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class ContextVerdict(NamedTuple):
    """Result of context_guard.check()."""
    status: str            # "aligned" | "mismatch" | "spike" | "repeated"
    similarity: float      # 0.0–1.0 overlap with recent context window
    confidence_adj: float  # subtract from per-issue confidence (0.0 on aligned)
    max_fixes_scale: float # multiply max_fixes by this (1.0 = no change)
    details: str           # human-readable explanation


@dataclass
class _ContextObservation:
    """One observed classify() call."""
    fix_type: str
    subsystem: str
    semantic_type: str
    ts: float = field(default_factory=lambda: datetime.now(timezone.utc).timestamp())

    def tokens(self) -> frozenset:
        """Token bag for overlap similarity."""
        raw = f"{self.fix_type} {self.subsystem} {self.semantic_type}"
        return frozenset(
            t for t in re.split(r"[\W_]+", raw.lower()) if t and t not in _STOP_WORDS
        )


# ---------------------------------------------------------------------------
# Core guard implementation
# ---------------------------------------------------------------------------

class _ContextGuard:
    """Stateful context guard instance (singleton in practice)."""

    def __init__(self) -> None:
        self._window: Deque[_ContextObservation] = deque(maxlen=_CONTEXT_WINDOW)
        self._last_obs: Optional[_ContextObservation] = None
        self._mismatch_count: int = 0
        self._total_checks: int = 0
        self._load_state()

    # ── Public API ────────────────────────────────────────────────────────────

    def observe(
        self,
        fix_type: str,
        subsystem: str,
        semantic_type: str = "unknown",
    ) -> None:
        """Record a classify() observation into the context window.

        Called by ``semantic_engine.classify()`` after each issue.
        """
        obs = _ContextObservation(fix_type=fix_type, subsystem=subsystem,
                                  semantic_type=semantic_type)
        self._window.append(obs)
        self._last_obs = obs
        self._save_state()

    def check(
        self,
        fix_type: str,
        subsystem: str,
        semantic_type: str = "unknown",
    ) -> ContextVerdict:
        """Validate that the *incoming* fix_type+subsystem aligns with recent context.

        Called by ``evolution_planner.build_plan()`` before scoring.

        Returns a :class:`ContextVerdict` that the planner uses to:
        • reduce ``max_fixes`` on mismatch
        • reduce per-issue confidence on mismatch / spike
        • boost priority (keep at 1.0 scale) on repeated input
        • pass through unchanged on aligned

        Also emits ``EVENT_CONTEXT_MISMATCH`` on the EventBus when status is
        not ``"aligned"``.
        """
        self._total_checks += 1
        incoming = _ContextObservation(fix_type=fix_type, subsystem=subsystem,
                                       semantic_type=semantic_type)
        incoming_tokens = incoming.tokens()

        # ── Repeated input detection ─────────────────────────────────────────
        if (self._last_obs is not None
                and self._last_obs.fix_type == fix_type
                and self._last_obs.subsystem == subsystem):
            verdict = ContextVerdict(
                status="repeated",
                similarity=1.0,
                confidence_adj=0.0,
                max_fixes_scale=1.0,
                details=(
                    f"Repeated input detected: fix_type='{fix_type}' "
                    f"subsystem='{subsystem}' — boosting priority"
                ),
            )
            self._log_event(verdict, fix_type, subsystem)
            return verdict

        # ── Spike detection (compare against immediate prior only) ────────────
        if self._last_obs is not None:
            spike_sim = _jaccard(incoming_tokens, self._last_obs.tokens())
            if spike_sim < _SPIKE_THRESHOLD:
                verdict = ContextVerdict(
                    status="spike",
                    similarity=spike_sim,
                    confidence_adj=_CONFIDENCE_PENALTY * 0.5,
                    max_fixes_scale=0.8,
                    details=(
                        f"Sudden context spike: similarity {spike_sim:.2f} < "
                        f"{_SPIKE_THRESHOLD} vs immediate prior "
                        f"'{self._last_obs.fix_type}/{self._last_obs.subsystem}'"
                    ),
                )
                self._mismatch_count += 1
                self._log_event(verdict, fix_type, subsystem)
                self._emit_event(verdict)
                return verdict

        # ── Window-level mismatch detection ───────────────────────────────────
        if len(self._window) >= 2:
            window_sim = self._window_similarity(incoming_tokens)
            if window_sim < _MISMATCH_THRESHOLD:
                verdict = ContextVerdict(
                    status="mismatch",
                    similarity=window_sim,
                    confidence_adj=_CONFIDENCE_PENALTY,
                    max_fixes_scale=0.6,
                    details=(
                        f"Context mismatch: similarity {window_sim:.2f} < "
                        f"{_MISMATCH_THRESHOLD} against {len(self._window)}-entry window. "
                        f"Possible phase boundary or topic shift."
                    ),
                )
                self._mismatch_count += 1
                self._log_event(verdict, fix_type, subsystem)
                self._emit_event(verdict)
                return verdict
            window_sim_val = window_sim
        else:
            window_sim_val = 1.0  # not enough history yet

        # ── Aligned ───────────────────────────────────────────────────────────
        verdict = ContextVerdict(
            status="aligned",
            similarity=window_sim_val,
            confidence_adj=0.0,
            max_fixes_scale=1.0,
            details=f"Context aligned (similarity={window_sim_val:.2f})",
        )
        self._log_event(verdict, fix_type, subsystem)
        return verdict

    def reset(self) -> None:
        """Partial context reset — clear the window but keep audit counters."""
        log.info("[ContextGuard] Partial context reset triggered.")
        self._window.clear()
        self._last_obs = None
        self._save_state()

    def status(self) -> Dict[str, Any]:
        """Return current guard diagnostics."""
        return {
            "window_size": len(self._window),
            "total_checks": self._total_checks,
            "mismatch_count": self._mismatch_count,
            "mismatch_rate": (
                round(self._mismatch_count / self._total_checks, 3)
                if self._total_checks else 0.0
            ),
            "last_fix_type": self._last_obs.fix_type if self._last_obs else None,
            "last_subsystem": self._last_obs.subsystem if self._last_obs else None,
        }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _window_similarity(self, incoming_tokens: frozenset) -> float:
        """Mean Jaccard similarity of incoming tokens against all window entries."""
        if not self._window:
            return 1.0
        sims = [_jaccard(incoming_tokens, obs.tokens()) for obs in self._window]
        return sum(sims) / len(sims)

    def _log_event(
        self,
        verdict: ContextVerdict,
        fix_type: str,
        subsystem: str,
    ) -> None:
        """Append a JSONL audit record."""
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "status": verdict.status,
            "fix_type": fix_type,
            "subsystem": subsystem,
            "similarity": round(verdict.similarity, 4),
            "confidence_adj": round(verdict.confidence_adj, 4),
            "max_fixes_scale": round(verdict.max_fixes_scale, 4),
            "details": verdict.details,
        }
        try:
            with _LOG_FILE.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError as exc:
            log.debug("[ContextGuard] Could not write audit log: %s", exc)

    def _emit_event(self, verdict: ContextVerdict) -> None:
        """Publish EVENT_CONTEXT_MISMATCH on the EventBus (best-effort)."""
        try:
            from modules.event_bus import get_event_bus, NiblitEvent, EVENT_CONTEXT_MISMATCH  # noqa: PLC0415
            get_event_bus().publish(NiblitEvent(
                type=EVENT_CONTEXT_MISMATCH,
                source="context_guard",
                payload={
                    "status": verdict.status,
                    "similarity": verdict.similarity,
                    "details": verdict.details,
                },
            ))
        except Exception as exc:  # noqa: BLE001
            log.debug("[ContextGuard] EventBus emit failed: %s", exc)

    def _save_state(self) -> None:
        state = {
            "window": [asdict(o) for o in self._window],
            "mismatch_count": self._mismatch_count,
            "total_checks": self._total_checks,
        }
        try:
            with _STATE_FILE.open("w", encoding="utf-8") as fh:
                json.dump(state, fh, indent=2)
        except OSError as exc:
            log.debug("[ContextGuard] Could not save state: %s", exc)

    def _load_state(self) -> None:
        if not _STATE_FILE.exists():
            return
        try:
            with _STATE_FILE.open("r", encoding="utf-8") as fh:
                state = json.load(fh)
            for entry in state.get("window", []):
                self._window.append(_ContextObservation(
                    fix_type=entry["fix_type"],
                    subsystem=entry["subsystem"],
                    semantic_type=entry.get("semantic_type", "unknown"),
                    ts=entry.get("ts", 0.0),
                ))
            self._mismatch_count = int(state.get("mismatch_count", 0))
            self._total_checks = int(state.get("total_checks", 0))
            if self._window:
                self._last_obs = self._window[-1]
        except Exception as exc:  # noqa: BLE001
            log.debug("[ContextGuard] Could not load state: %s", exc)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_guard: Optional[_ContextGuard] = None


def _get_guard() -> _ContextGuard:
    global _guard  # noqa: PLW0603
    if _guard is None:
        _guard = _ContextGuard()
    return _guard


# ---------------------------------------------------------------------------
# Public module-level API (used by semantic_engine and evolution_planner)
# ---------------------------------------------------------------------------

def observe(fix_type: str, subsystem: str, semantic_type: str = "unknown") -> None:
    """Record a classify() observation.

    Called automatically by ``semantic_engine.classify()`` so the guard
    always tracks the live context window.
    """
    _get_guard().observe(fix_type, subsystem, semantic_type)


def check(
    fix_type: str,
    subsystem: str,
    semantic_type: str = "unknown",
) -> ContextVerdict:
    """Check incoming fix_type+subsystem alignment with recent context.

    Returns a :class:`ContextVerdict` for the planner to act on.
    """
    return _get_guard().check(fix_type, subsystem, semantic_type)


def reset() -> None:
    """Trigger a partial context reset (clears window, keeps counters)."""
    _get_guard().reset()


def status() -> Dict[str, Any]:
    """Return current guard diagnostics dict."""
    return _get_guard().status()


if __name__ == "__main__":
    print('Running context_guard.py')
