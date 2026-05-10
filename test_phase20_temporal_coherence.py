"""test_phase20_temporal_coherence.py — Phase 20 Temporal Coherence Layer tests."""
from __future__ import annotations

import time


# ── AdaptationClock ───────────────────────────────────────────────────────────

def test_adaptation_clock_zero_interval_always_fires():
    from modules.temporal_coherence import AdaptationClock
    clock = AdaptationClock()
    # FAST tier has 0 s interval — should always fire
    assert clock.should_adapt("FAST") is True
    assert clock.should_adapt("FAST") is True


def test_adaptation_clock_nonzero_interval_gates():
    from modules.temporal_coherence import AdaptationClock, _TierState
    clock = AdaptationClock()
    # Manually set MEDIUM to a large interval
    clock._tiers["MEDIUM"].min_interval_s = 3600.0
    clock._tiers["MEDIUM"].last_adapt_time = time.monotonic()
    # Should not fire immediately after a recent adapt
    assert clock.should_adapt("MEDIUM") is False


def test_adaptation_clock_force_overrides_gate():
    from modules.temporal_coherence import AdaptationClock
    clock = AdaptationClock()
    clock._tiers["MEDIUM"].min_interval_s = 3600.0
    clock._tiers["MEDIUM"].last_adapt_time = time.monotonic()
    assert clock.should_adapt("MEDIUM", force=True) is True


def test_adaptation_clock_unknown_tier_returns_true():
    from modules.temporal_coherence import AdaptationClock
    clock = AdaptationClock()
    assert clock.should_adapt("NONEXISTENT_TIER") is True


def test_adaptation_clock_adapt_count_increments():
    from modules.temporal_coherence import AdaptationClock
    clock = AdaptationClock()
    clock.should_adapt("FAST")
    clock.should_adapt("FAST")
    assert clock._tiers["FAST"].adapt_count == 2


def test_adaptation_clock_status_structure():
    from modules.temporal_coherence import AdaptationClock
    clock = AdaptationClock()
    status = clock.status()
    assert "FAST" in status
    assert "MEDIUM" in status
    assert "adapt_count" in status["FAST"]
    assert "min_interval_s" in status["FAST"]
    assert "time_until_next_s" in status["FAST"]


# ── EpochManager ──────────────────────────────────────────────────────────────

def test_epoch_manager_starts_at_zero():
    from modules.temporal_coherence import EpochManager
    em = EpochManager()
    assert em.current == 0


def test_epoch_manager_tick_increments():
    from modules.temporal_coherence import EpochManager
    em = EpochManager()
    e1 = em.tick()
    e2 = em.tick()
    assert e1 == 1
    assert e2 == 2
    assert em.current == 2


def test_epoch_manager_tag_stamps_dict():
    from modules.temporal_coherence import EpochManager
    em = EpochManager()
    em.tick()
    data = {"foo": "bar"}
    em.tag(data)
    assert data["_epoch"] == 1
    assert "_epoch_ts" in data
    assert data["foo"] == "bar"


def test_epoch_manager_epoch_age():
    from modules.temporal_coherence import EpochManager
    em = EpochManager()
    em.tick()
    em.tick()
    em.tick()
    assert em.epoch_age(1) == 2
    assert em.epoch_age(3) == 0


def test_epoch_manager_status():
    from modules.temporal_coherence import EpochManager
    em = EpochManager()
    em.tick()
    status = em.status()
    assert status["current_epoch"] == 1
    assert "uptime_s" in status


# ── SynchronizationBarrier ────────────────────────────────────────────────────

def test_barrier_coherent_when_fresh():
    from modules.temporal_coherence import SynchronizationBarrier
    barrier = SynchronizationBarrier("FAST", "MEDIUM", threshold_s=60.0)
    barrier.record_slow_heartbeat()
    assert barrier.is_coherent() is True


def test_barrier_incoherent_when_stale():
    from modules.temporal_coherence import SynchronizationBarrier
    barrier = SynchronizationBarrier("FAST", "MEDIUM", threshold_s=0.001)
    time.sleep(0.01)
    assert barrier.is_coherent() is False


def test_barrier_status_structure():
    from modules.temporal_coherence import SynchronizationBarrier
    barrier = SynchronizationBarrier("FAST", "MEDIUM", threshold_s=60.0)
    status = barrier.status()
    assert status["fast_tier"] == "FAST"
    assert status["slow_tier"] == "MEDIUM"
    assert "staleness_s" in status
    assert "coherent" in status


# ── TemporalCoherenceLayer ────────────────────────────────────────────────────

def test_tcl_tick_advances_epoch():
    from modules.temporal_coherence import TemporalCoherenceLayer
    tcl = TemporalCoherenceLayer()
    e1 = tcl.tick()
    e2 = tcl.tick()
    assert e1 == 1
    assert e2 == 2


def test_tcl_tag_decision_stamps_epoch():
    from modules.temporal_coherence import TemporalCoherenceLayer
    tcl = TemporalCoherenceLayer()
    tcl.tick()
    data = {"resolved_quality": 0.8}
    tcl.tag_decision(data)
    assert data["_epoch"] == 1


def test_tcl_should_adapt_fast_always_fires():
    from modules.temporal_coherence import TemporalCoherenceLayer
    tcl = TemporalCoherenceLayer()
    assert tcl.should_adapt("FAST") is True


def test_tcl_record_heartbeat_refreshes_clock():
    from modules.temporal_coherence import TemporalCoherenceLayer
    tcl = TemporalCoherenceLayer()
    # Force MEDIUM to a huge interval so it won't fire normally
    tcl.clock._tiers["MEDIUM"].min_interval_s = 3600.0
    tcl.clock._tiers["MEDIUM"].last_adapt_time = time.monotonic()
    # But after recording heartbeat, next call resets last_adapt_time and
    # MEDIUM barrier becomes fresh
    tcl.record_heartbeat("MEDIUM")
    # Barriers that depend on MEDIUM should now be coherent
    barrier = tcl._barriers.get("FAST_MEDIUM")
    assert barrier is not None
    assert barrier.is_coherent() is True


def test_tcl_status_contains_all_sections():
    from modules.temporal_coherence import TemporalCoherenceLayer
    tcl = TemporalCoherenceLayer()
    status = tcl.status()
    assert "epoch" in status
    assert "clocks" in status
    assert "barriers" in status
    assert "FAST_MEDIUM" in status["barriers"]


def test_tcl_singleton_returns_same_instance():
    from modules.temporal_coherence import get_temporal_coherence_layer, _tcl_instance
    import modules.temporal_coherence as tc_mod
    # Reset singleton for isolation
    tc_mod._tcl_instance = None
    tcl1 = get_temporal_coherence_layer()
    tcl2 = get_temporal_coherence_layer()
    assert tcl1 is tcl2


# ── Integration: niblit_learning epoch_tag ───────────────────────────────────

def test_niblit_learning_accepts_epoch_tag():
    from niblit_learning import NiblitLearning

    stored = {}

    class DummyMemory:
        def store_learning(self, data):
            stored.update(data)
        def get_learning_log(self):
            return []

    L = NiblitLearning(DummyMemory())
    L.process_interaction("hello", "hi", epoch_tag=7)
    assert stored.get("epoch_tag") == 7


def test_niblit_learning_epoch_tag_defaults_none():
    from niblit_learning import NiblitLearning

    stored = {}

    class DummyMemory:
        def store_learning(self, data):
            stored.update(data)
        def get_learning_log(self):
            return []

    L = NiblitLearning(DummyMemory())
    L.process_interaction("hello", "hi")
    assert "epoch_tag" in stored
    assert stored["epoch_tag"] is None


# ── Multi-axis arbitration ────────────────────────────────────────────────────

def test_arbitration_has_quality_axes_when_resolved():
    """_arbitrate_turn_quality() produces quality_axes alongside scalar."""
    import sys, types

    # Minimal stub of NiblitCore to test _arbitrate_turn_quality in isolation
    class _DummyCore:
        _tcl = None
        _last_feedback_arbitration = None

        # paste just the method under test
        from niblit_core import NiblitCore
        _arbitrate_turn_quality = NiblitCore._arbitrate_turn_quality

    import os as _os
    core = _DummyCore.__new__(_DummyCore)
    result = core._arbitrate_turn_quality(0.8, 0.6)
    assert result["resolved_quality"] is not None
    axes = result.get("quality_axes")
    assert axes is not None, "quality_axes missing from arbitration result"
    assert "reasoning" in axes
    assert "engagement" in axes
    assert "factuality" in axes
    assert "strategic_alignment" in axes
    assert "stability" in axes
    # factuality is min(eval, qf)
    assert abs(axes["factuality"] - min(0.8, 0.6)) < 0.001


def test_arbitration_no_axes_when_no_input():
    """No quality_axes when both sources are None."""
    class _DummyCore:
        from niblit_core import NiblitCore
        _arbitrate_turn_quality = NiblitCore._arbitrate_turn_quality

    core = _DummyCore.__new__(_DummyCore)
    result = core._arbitrate_turn_quality(None, None)
    assert result["resolved_quality"] is None
    assert "quality_axes" not in result
