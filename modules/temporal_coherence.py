#!/usr/bin/env python3
"""
modules/temporal_coherence.py — Phase 20: Temporal Coherence Layer

Adaptive systems operating across multiple timescales suffer from
cross-timescale instability: fast subsystems (per-turn learning) can
fire on stale information from slow subsystems (governance, identity),
and vice-versa.  This module provides:

    AdaptationClock       — per-tier cadence gate (should_adapt?)
    EpochManager          — monotonic runtime epoch for decision tagging
    SynchronizationBarrier — staleness guard across tier boundaries
    TemporalCoherenceLayer — unified facade wiring the above together

Tier hierarchy (slowest → fastest):
  IDENTITY     — months: long-horizon objective / identity continuity
  GOVERNANCE   — hundreds of cycles: constitutional floor adaptation
  STRATEGY     — tens of cycles: causal strategy rule derivation
  MEDIUM       — several turns: niblit_learning evolve()
  FAST         — per-turn: quality feedback / adaptive_learning
  REALTIME     — sub-turn: kernel IPC, ring signals

Usage in niblit_core.py:
    tcl = TemporalCoherenceLayer()
    epoch = tcl.tick()
    if tcl.should_adapt("FAST"):
        niblit_learning.evolve()
    if tcl.should_adapt("MEDIUM"):
        adaptive_learning.evolve()
"""

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

log = logging.getLogger(__name__)

# ── Tier configuration ────────────────────────────────────────────────────────
# Min seconds between adaptation calls per tier.
# Override via environment: NIBLIT_TCL_FAST_INTERVAL_S etc.
_TIER_DEFAULTS: Dict[str, float] = {
    "REALTIME":   0.0,     # no gate — kernel-driven
    "FAST":       0.0,     # per-turn (gated by call count, not time)
    "MEDIUM":     60.0,    # ~1 min between heavy evolve() calls
    "STRATEGY":   300.0,   # ~5 min between CSE rule derivation
    "GOVERNANCE": 600.0,   # ~10 min between governance adapt
    "IDENTITY":   3600.0,  # ~1 hr between identity drift checks
}

_ENV_PREFIX = "NIBLIT_TCL_"


def _load_tier_interval(tier: str) -> float:
    env_key = f"{_ENV_PREFIX}{tier}_INTERVAL_S"
    raw = os.environ.get(env_key, "")
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    return _TIER_DEFAULTS.get(tier, 60.0)


# ── Staleness threshold: how old (seconds) a slower tier's epoch may be
# before the faster tier treats its state as stale and skips adaptation.
_DEFAULT_STALENESS_THRESHOLD_S = float(
    os.environ.get("NIBLIT_TCL_STALENESS_THRESHOLD_S", "120")
)


@dataclass
class _TierState:
    last_adapt_time: float = 0.0
    adapt_count: int = 0
    min_interval_s: float = 0.0
    last_epoch: int = 0


# ── AdaptationClock ───────────────────────────────────────────────────────────

class AdaptationClock:
    """
    Per-tier cadence gate.

    should_adapt(tier) returns True at most once per min_interval_s for
    that tier, then resets the clock.  Call mark_adapted(tier) to
    explicitly record that adaptation occurred without consuming the gate.
    """

    def __init__(self) -> None:
        self._tiers: Dict[str, _TierState] = {
            t: _TierState(min_interval_s=_load_tier_interval(t))
            for t in _TIER_DEFAULTS
        }

    def should_adapt(self, tier: str, *, force: bool = False) -> bool:
        """Return True if enough time has passed for this tier to adapt."""
        state = self._tiers.get(tier)
        if state is None:
            return True
        if state.min_interval_s <= 0.0:
            state.adapt_count += 1
            return True
        now = time.monotonic()
        if force or (now - state.last_adapt_time) >= state.min_interval_s:
            state.last_adapt_time = now
            state.adapt_count += 1
            return True
        return False

    def mark_adapted(self, tier: str) -> None:
        """Record that a tier adapted without calling should_adapt."""
        state = self._tiers.get(tier)
        if state:
            state.last_adapt_time = time.monotonic()
            state.adapt_count += 1

    def time_until_next(self, tier: str) -> float:
        """Seconds until next adaptation is allowed for this tier."""
        state = self._tiers.get(tier)
        if not state or state.min_interval_s <= 0.0:
            return 0.0
        elapsed = time.monotonic() - state.last_adapt_time
        return max(0.0, state.min_interval_s - elapsed)

    def status(self) -> Dict[str, object]:
        return {
            tier: {
                "adapt_count": s.adapt_count,
                "min_interval_s": s.min_interval_s,
                "time_until_next_s": round(self.time_until_next(tier), 1),
            }
            for tier, s in self._tiers.items()
        }


# ── EpochManager ─────────────────────────────────────────────────────────────

class EpochManager:
    """
    Monotonic runtime epoch counter.

    Epoch advances every tick() call (once per interaction in niblit_core).
    All subsystem decisions are stamped with the current epoch so that:
    - delayed outcomes can be attributed to the decision epoch
    - stale decision detection is epoch-based, not just time-based
    """

    def __init__(self) -> None:
        self._epoch: int = 0
        self._epoch_start_time: float = time.monotonic()

    def tick(self) -> int:
        """Advance the epoch by 1 and return the new epoch id."""
        self._epoch += 1
        return self._epoch

    @property
    def current(self) -> int:
        return self._epoch

    def tag(self, data: dict) -> dict:
        """Stamp *data* in-place with current epoch and timestamp."""
        data["_epoch"] = self._epoch
        data["_epoch_ts"] = time.time()
        return data

    def epoch_age(self, epoch: int) -> int:
        """How many epochs ago was *epoch*?"""
        return max(0, self._epoch - epoch)

    def status(self) -> Dict[str, object]:
        return {
            "current_epoch": self._epoch,
            "uptime_s": round(time.monotonic() - self._epoch_start_time, 1),
        }


# ── SynchronizationBarrier ────────────────────────────────────────────────────

class SynchronizationBarrier:
    """
    Cross-tier staleness guard.

    Prevents a fast tier from adapting when the slower tier it depends on
    has not been heard from recently.  This stops stale-state reinforcement
    (e.g. FAST learning updating policy on a governance snapshot that is
    hours old).

    Usage:
        barrier = SynchronizationBarrier(fast="FAST", slow="GOVERNANCE")
        barrier.record_slow_heartbeat()          # call when governance ran
        if barrier.is_coherent():                # check before FAST adapts
            ...adapt...
    """

    def __init__(
        self,
        fast: str,
        slow: str,
        threshold_s: float = _DEFAULT_STALENESS_THRESHOLD_S,
    ) -> None:
        self.fast = fast
        self.slow = slow
        self.threshold_s = threshold_s
        self._last_slow_heartbeat: float = time.monotonic()

    def record_slow_heartbeat(self) -> None:
        self._last_slow_heartbeat = time.monotonic()

    def staleness_s(self) -> float:
        return time.monotonic() - self._last_slow_heartbeat

    def is_coherent(self) -> bool:
        """True if the slow tier heartbeat is fresh enough."""
        return self.staleness_s() < self.threshold_s

    def status(self) -> Dict[str, object]:
        return {
            "fast_tier": self.fast,
            "slow_tier": self.slow,
            "staleness_s": round(self.staleness_s(), 1),
            "threshold_s": self.threshold_s,
            "coherent": self.is_coherent(),
        }


# ── TemporalCoherenceLayer ────────────────────────────────────────────────────

class TemporalCoherenceLayer:
    """
    Phase 20: Unified Temporal Coherence Layer.

    Wires AdaptationClock + EpochManager + SynchronizationBarriers together
    into a single facade used by niblit_core, niblit_learning, and
    nibblebots feedback_learner.

    Typical integration in niblit_core._trigger_learning():

        epoch = self._tcl.tick()
        if self._tcl.should_adapt("FAST"):
            self.learning.process_interaction(..., epoch_tag=epoch)
        if self._tcl.should_adapt("MEDIUM"):
            self.learning.evolve()
        if self._tcl.should_adapt("GOVERNANCE"):
            self._tcl.record_heartbeat("GOVERNANCE")

    Barriers registered:
        FAST   → depends on MEDIUM  (must not be too stale)
        MEDIUM → depends on STRATEGY
        STRATEGY → depends on GOVERNANCE
    """

    def __init__(self) -> None:
        self.clock = AdaptationClock()
        self.epoch = EpochManager()
        # Cross-tier staleness guards
        self._barriers: Dict[str, SynchronizationBarrier] = {
            "FAST_MEDIUM": SynchronizationBarrier("FAST", "MEDIUM", threshold_s=300.0),
            "MEDIUM_STRATEGY": SynchronizationBarrier("MEDIUM", "STRATEGY", threshold_s=900.0),
            "STRATEGY_GOVERNANCE": SynchronizationBarrier(
                "STRATEGY", "GOVERNANCE", threshold_s=1800.0
            ),
        }
        log.debug("[TCL] Temporal Coherence Layer initialised (Phase 20).")

    # ── Primary interface ─────────────────────────────────────────────────────

    def tick(self) -> int:
        """Advance epoch (call once per interaction)."""
        return self.epoch.tick()

    def should_adapt(self, tier: str, *, force: bool = False) -> bool:
        """Cadence gate: returns True when this tier is allowed to adapt."""
        return self.clock.should_adapt(tier, force=force)

    def tag_decision(self, data: dict) -> dict:
        """Stamp a decision dict with current epoch."""
        return self.epoch.tag(data)

    def record_heartbeat(self, tier: str) -> None:
        """
        Signal that a slow tier ran successfully.
        Refreshes barriers that depend on this tier.
        """
        self.clock.mark_adapted(tier)
        for barrier in self._barriers.values():
            if barrier.slow == tier:
                barrier.record_slow_heartbeat()

    def barrier_coherent(self, barrier_key: str) -> bool:
        """Check if a specific cross-tier barrier is coherent."""
        barrier = self._barriers.get(barrier_key)
        return barrier.is_coherent() if barrier else True

    # ── Epoch persistence (Phase 21) ──────────────────────────────────────────

    def persist_epoch(self, path: Optional[str] = None) -> bool:
        """Save the current epoch counter to disk so it survives restarts.

        The epoch file is a tiny JSON: ``{"epoch": <int>}``.
        Default path: NIBLIT_TCL_EPOCH_PATH env var or ``niblit_tcl_epoch.json``
        in the current working directory.

        Returns True on success, False on error.
        """
        _path = path or os.environ.get("NIBLIT_TCL_EPOCH_PATH", "niblit_tcl_epoch.json")
        try:
            import json  # noqa: PLC0415
            with open(_path, "w", encoding="utf-8") as fh:
                json.dump({"epoch": self.epoch.current}, fh)
            log.debug("[TCL] Epoch %d persisted to %s", self.epoch.current, _path)
            return True
        except Exception as exc:
            log.warning("[TCL] persist_epoch failed: %s", exc)
            return False

    def restore_epoch(self, path: Optional[str] = None) -> bool:
        """Restore the epoch counter from disk (call during initialisation).

        If the file is missing or unreadable the epoch stays at 0 (safe default).
        Returns True if a saved epoch was loaded, False otherwise.
        """
        _path = path or os.environ.get("NIBLIT_TCL_EPOCH_PATH", "niblit_tcl_epoch.json")
        try:
            import json  # noqa: PLC0415
            with open(_path, encoding="utf-8") as fh:
                data = json.load(fh)
            saved = int(data.get("epoch", 0))
            if saved > 0:
                self.epoch._epoch = saved
                log.info("[TCL] Epoch restored to %d from %s", saved, _path)
                return True
        except FileNotFoundError:
            log.debug("[TCL] No epoch file at %s — starting from 0", _path)
        except Exception as exc:
            log.warning("[TCL] restore_epoch failed: %s", exc)
        return False

    # ── Status / observability ────────────────────────────────────────────────

    def status(self) -> Dict[str, object]:
        return {
            "epoch": self.epoch.status(),
            "clocks": self.clock.status(),
            "barriers": {k: v.status() for k, v in self._barriers.items()},
        }


# ── Module-level singleton ────────────────────────────────────────────────────

_tcl_instance: Optional[TemporalCoherenceLayer] = None


def get_temporal_coherence_layer() -> TemporalCoherenceLayer:
    """Return the process-level TemporalCoherenceLayer singleton."""
    global _tcl_instance
    if _tcl_instance is None:
        _tcl_instance = TemporalCoherenceLayer()
    return _tcl_instance


if __name__ == "__main__":
    print('Running temporal_coherence.py')
