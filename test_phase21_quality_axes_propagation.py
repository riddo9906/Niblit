"""test_phase21_quality_axes_propagation.py — Phase 21: Quality-Axes Propagation tests.

Tests cover:
A. niblit_learning.process_interaction stores quality_axes
B. niblit_core._cmd_coherence returns structured output
C. niblit_core._cmd_status exposes Epoch field
D. niblit_core._arbitrate_turn_quality quality_axes passed to learning
E. temporal_coherence.persist_epoch / restore_epoch round-trip
F. TCL heartbeat from autonomous_evolution_agent
"""
from __future__ import annotations

import os
import json
import tempfile


# ── A. NiblitLearning.process_interaction stores quality_axes ─────────────────

def test_learning_stores_quality_axes():
    from niblit_learning import NiblitLearning

    stored = {}

    class _Mem:
        def store_learning(self, data):
            stored.update(data)
        def get_learning_log(self):
            return []

    axes = {"reasoning": 0.9, "engagement": 0.8, "factuality": 0.7,
            "strategic_alignment": 0.85, "stability": 0.75}
    L = NiblitLearning(_Mem())
    L.process_interaction("hello", "hi", quality_axes=axes)
    assert stored.get("quality_axes") == axes


def test_learning_quality_axes_defaults_none():
    from niblit_learning import NiblitLearning

    stored = {}

    class _Mem:
        def store_learning(self, data):
            stored.update(data)
        def get_learning_log(self):
            return []

    L = NiblitLearning(_Mem())
    L.process_interaction("hello", "hi")
    assert "quality_axes" in stored
    assert stored["quality_axes"] is None


def test_learning_invalid_axes_stored_as_none():
    from niblit_learning import NiblitLearning

    stored = {}

    class _Mem:
        def store_learning(self, data):
            stored.update(data)
        def get_learning_log(self):
            return []

    L = NiblitLearning(_Mem())
    L.process_interaction("hello", "hi", quality_axes="not-a-dict")
    assert stored.get("quality_axes") is None


# ── B. _cmd_coherence returns structured text ─────────────────────────────────

def test_cmd_coherence_returns_string_with_epoch():
    from modules.temporal_coherence import TemporalCoherenceLayer

    tcl = TemporalCoherenceLayer()
    tcl.tick()
    tcl.tick()

    # Build minimal NiblitCore stub with just _tcl and _cmd_coherence
    from niblit_core import NiblitCore
    core = NiblitCore.__new__(NiblitCore)
    core._tcl = tcl
    result = core._cmd_coherence("")
    assert "Epoch" in result or "epoch" in result.lower()
    assert "Temporal Coherence" in result


def test_cmd_coherence_shows_tiers():
    from modules.temporal_coherence import TemporalCoherenceLayer
    from niblit_core import NiblitCore

    tcl = TemporalCoherenceLayer()
    core = NiblitCore.__new__(NiblitCore)
    core._tcl = tcl
    result = core._cmd_coherence("")
    # At least one tier name should appear
    assert any(t in result for t in ("FAST", "MEDIUM", "STRATEGY", "GOVERNANCE"))


def test_cmd_coherence_shows_barriers():
    from modules.temporal_coherence import TemporalCoherenceLayer
    from niblit_core import NiblitCore

    tcl = TemporalCoherenceLayer()
    core = NiblitCore.__new__(NiblitCore)
    core._tcl = tcl
    result = core._cmd_coherence("")
    assert "FAST_MEDIUM" in result


def test_cmd_coherence_no_tcl_returns_warning():
    from niblit_core import NiblitCore

    core = NiblitCore.__new__(NiblitCore)
    core._tcl = None
    result = core._cmd_coherence("")
    assert "not initialised" in result or "unavailable" in result.lower()


# ── C. _cmd_status exposes Epoch field ───────────────────────────────────────

def test_cmd_status_includes_epoch():
    from modules.temporal_coherence import TemporalCoherenceLayer
    from niblit_core import NiblitCore
    import types

    core = NiblitCore.__new__(NiblitCore)
    core._tcl = TemporalCoherenceLayer()
    core._tcl.tick()
    # Provide minimal stubs that _cmd_status expects
    core.improvements = None
    core.autonomous_engine = None
    core._deferred_init_phase = "complete"
    core._unified_loop_status = {"recent_loop_quality": 0.75}
    # Stub _get_memory_count and _refresh_unified_feedback_status
    core._get_memory_count = lambda: 42
    core._refresh_unified_feedback_status = lambda: None
    # Provide minimal metrics stub
    core.metrics = types.SimpleNamespace(operation_counts={}, get_stats=lambda _: None)

    result = core._cmd_status("")
    assert "Epoch" in result
    assert "1" in result  # epoch was ticked once


# ── D. _arbitrate_turn_quality quality_axes propagated ───────────────────────

def test_arbitrate_produces_quality_axes():
    from niblit_core import NiblitCore

    core = NiblitCore.__new__(NiblitCore)
    core._tcl = None
    core._last_feedback_arbitration = None
    result = core._arbitrate_turn_quality(0.9, 0.7)
    axes = result.get("quality_axes")
    assert isinstance(axes, dict)
    assert set(axes.keys()) >= {"reasoning", "engagement", "factuality",
                                "strategic_alignment", "stability"}


def test_arbitrate_quality_axes_factuality_is_min():
    from niblit_core import NiblitCore

    core = NiblitCore.__new__(NiblitCore)
    result = core._arbitrate_turn_quality(0.8, 0.6)
    axes = result["quality_axes"]
    assert abs(axes["factuality"] - min(0.8, 0.6)) < 0.001


def test_arbitrate_no_axes_when_both_none():
    from niblit_core import NiblitCore

    core = NiblitCore.__new__(NiblitCore)
    result = core._arbitrate_turn_quality(None, None)
    assert "quality_axes" not in result


# ── E. persist_epoch / restore_epoch round-trip ───────────────────────────────

def test_persist_restore_epoch_round_trip():
    from modules.temporal_coherence import TemporalCoherenceLayer

    tcl1 = TemporalCoherenceLayer()
    for _ in range(7):
        tcl1.tick()
    assert tcl1.epoch.current == 7

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        path = tmp.name

    try:
        ok = tcl1.persist_epoch(path=path)
        assert ok is True

        # Confirm file contains expected JSON
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        assert data["epoch"] == 7

        # Restore into a fresh instance
        tcl2 = TemporalCoherenceLayer()
        assert tcl2.epoch.current == 0
        restored = tcl2.restore_epoch(path=path)
        assert restored is True
        assert tcl2.epoch.current == 7
    finally:
        os.unlink(path)


def test_restore_epoch_missing_file():
    from modules.temporal_coherence import TemporalCoherenceLayer

    tcl = TemporalCoherenceLayer()
    # Should not raise, should return False
    result = tcl.restore_epoch(path="/tmp/__niblit_nonexistent_epoch__.json")
    assert result is False
    assert tcl.epoch.current == 0


def test_persist_epoch_returns_false_on_bad_path():
    from modules.temporal_coherence import TemporalCoherenceLayer

    tcl = TemporalCoherenceLayer()
    # Writing to a directory that cannot exist as a file
    ok = tcl.persist_epoch(path="/dev/full/no/such/path.json")
    assert ok is False


# ── F. TCL heartbeat gating in autonomous_evolution_agent ────────────────────

def test_tcl_record_heartbeat_strategy():
    """After a heartbeat, the STRATEGY clock is marked and barriers are fresh."""
    from modules.temporal_coherence import TemporalCoherenceLayer

    tcl = TemporalCoherenceLayer()
    # Set STRATEGY to a huge interval so it would not normally fire
    tcl.clock._tiers["STRATEGY"].min_interval_s = 9999.0
    # Before heartbeat the MEDIUM→STRATEGY barrier may start as fresh (just created)
    tcl.record_heartbeat("STRATEGY")
    barrier = tcl._barriers.get("MEDIUM_STRATEGY")
    assert barrier is not None
    # Barrier should now be coherent because heartbeat refreshed it
    assert barrier.is_coherent() is True


def test_tcl_record_heartbeat_governance():
    from modules.temporal_coherence import TemporalCoherenceLayer

    tcl = TemporalCoherenceLayer()
    tcl.record_heartbeat("GOVERNANCE")
    barrier = tcl._barriers.get("STRATEGY_GOVERNANCE")
    assert barrier is not None
    assert barrier.is_coherent() is True


# ── G. TCL status includes all expected sections ─────────────────────────────

def test_tcl_status_has_epoch_clocks_barriers():
    from modules.temporal_coherence import TemporalCoherenceLayer

    tcl = TemporalCoherenceLayer()
    tcl.tick()
    s = tcl.status()
    assert "epoch" in s
    assert "clocks" in s
    assert "barriers" in s
    assert s["epoch"]["current_epoch"] == 1
    assert "FAST_MEDIUM" in s["barriers"]
    assert "MEDIUM_STRATEGY" in s["barriers"]
    assert "STRATEGY_GOVERNANCE" in s["barriers"]


if __name__ == "__main__":
    print('Running test_phase21_quality_axes_propagation.py')
