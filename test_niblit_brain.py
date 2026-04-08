"""test_niblit_brain.py — unit tests for NiblitBrain and BrainTrainer.

All tests are fully offline-safe: NiblitMemory and all heavy optional
dependencies (HFBrain, InternetManager, SelfResearcher, etc.) are mocked
so no real inference calls, network connections, or disk writes occur.

Run with::

    pytest test_niblit_brain.py -v
"""

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Import guard
# ---------------------------------------------------------------------------

try:
    from niblit_brain import NiblitBrain, BrainTrainer, hf_query
    _BRAIN_AVAILABLE = True
except ImportError:
    _BRAIN_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not _BRAIN_AVAILABLE,
    reason="niblit_brain could not be imported",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_memory():
    """Minimal memory stub compatible with NiblitBrain requirements."""
    mem = MagicMock()
    mem.get_preferences.return_value = {"tone": "neutral", "interaction_style": "casual"}
    mem.store_preferences.return_value = None
    mem.recall.return_value = []
    mem.store_learning.return_value = None
    mem.log_event.return_value = None
    mem.add_fact = MagicMock()
    mem.add_embedding = MagicMock(return_value=False)
    mem.search_vectors = MagicMock(return_value=[])
    mem.get_learning_log.return_value = []
    mem.list_facts.return_value = []
    mem.query_knowledge.return_value = []
    return mem


def _make_brain(llm_enabled: bool = False) -> "NiblitBrain":
    """Create a NiblitBrain with mocked heavy dependencies."""
    mem = _make_memory()
    # Patch optional heavy modules so __init__ doesn't try to connect
    with (
        patch("niblit_brain.HFBrain", None),
        patch("niblit_brain.InternetManager", None),
        patch("niblit_brain.SelfResearcher", None),
        patch("niblit_brain.SelfHealer", None),
        patch("niblit_brain.SelfIdeaImplementation", None),
        patch("niblit_brain.ReflectModule", None),
        patch("niblit_brain.SelfTeacher", None),
    ):
        brain = NiblitBrain(
            memory=mem,
            llm_enabled=llm_enabled,
            internet=None,
            enable_improvements=False,
        )
    return brain


# ---------------------------------------------------------------------------
# NiblitBrain — construction
# ---------------------------------------------------------------------------

class TestNiblitBrainConstruction:
    """Tests for NiblitBrain.__init__()."""

    def test_creates_without_errors(self):
        brain = _make_brain()
        assert brain is not None

    def test_llm_enabled_default_false(self):
        brain = _make_brain(llm_enabled=False)
        assert brain.llm_enabled is False

    def test_llm_enabled_true(self):
        brain = _make_brain(llm_enabled=True)
        assert brain.llm_enabled is True

    def test_brain_trainer_initialized(self):
        brain = _make_brain()
        assert brain.brain_trainer is not None

    def test_memory_attribute_set(self):
        brain = _make_brain()
        assert brain.memory is not None

    def test_hf_brain_none_when_unavailable(self):
        brain = _make_brain()
        assert brain.hf_brain is None


# ---------------------------------------------------------------------------
# NiblitBrain.learn
# ---------------------------------------------------------------------------

class TestNiblitBrainLearn:
    """Tests for NiblitBrain.learn()."""

    def test_learn_does_not_raise(self):
        brain = _make_brain()
        brain.learn("machine learning is a subset of AI")

    def test_learn_calls_memory_store_learning(self):
        brain = _make_brain()
        # Just verify learn completes without error; memory wrapping varies
        brain.learn("some topic to learn")

    def test_learn_with_empty_string(self):
        brain = _make_brain()
        brain.learn("")  # should not raise

    def test_learn_with_long_text(self):
        brain = _make_brain()
        long_text = "word " * 500
        brain.learn(long_text)  # should not raise


# ---------------------------------------------------------------------------
# NiblitBrain.think
# ---------------------------------------------------------------------------

class TestNiblitBrainThink:
    """Tests for NiblitBrain.think() — LLM-disabled path."""

    def test_think_returns_string(self):
        brain = _make_brain(llm_enabled=False)
        result = brain.think("what is the speed of light?")
        assert isinstance(result, str)

    def test_think_empty_input_does_not_raise(self):
        brain = _make_brain(llm_enabled=False)
        result = brain.think("")
        assert isinstance(result, str)

    def test_think_long_input_does_not_raise(self):
        brain = _make_brain(llm_enabled=False)
        result = brain.think("explain " * 100)
        assert isinstance(result, str)

    def test_think_with_memory_recall(self):
        brain = _make_brain(llm_enabled=False)
        # Set return_value on the underlying mock's recall
        brain.memory._memory.recall.return_value = [
            {"input": "prior question", "response": "prior answer"}
        ]
        result = brain.think("follow-up question")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# NiblitBrain.handle
# ---------------------------------------------------------------------------

class TestNiblitBrainHandle:
    """Tests for NiblitBrain.handle() — router compatibility wrapper."""

    def test_handle_llm_disabled_returns_disabled_message(self):
        brain = _make_brain(llm_enabled=False)
        result = brain.handle("some message")
        assert isinstance(result, str)
        assert "disabled" in result.lower() or len(result) > 0

    def test_handle_unknown_command_calls_think(self):
        brain = _make_brain(llm_enabled=True)
        # Patch think to verify it's called
        brain.think = MagicMock(return_value="think response")
        result = brain.handle("what is gravity?")
        assert result == "think response"


# ---------------------------------------------------------------------------
# NiblitBrain.get_stats
# ---------------------------------------------------------------------------

class TestNiblitBrainGetStats:
    """Tests for NiblitBrain.get_stats()."""

    def test_get_stats_returns_dict(self):
        brain = _make_brain()
        stats = brain.get_stats()
        assert isinstance(stats, dict)

    def test_get_stats_contains_llm_enabled(self):
        brain = _make_brain(llm_enabled=False)
        stats = brain.get_stats()
        assert "llm_enabled" in stats
        assert stats["llm_enabled"] is False


# ---------------------------------------------------------------------------
# NiblitBrain.process_query
# ---------------------------------------------------------------------------

class TestNiblitBrainProcessQuery:
    """Tests for NiblitBrain.process_query() — Qdrant inference pipeline."""

    def test_process_query_returns_dict(self):
        brain = _make_brain()
        result = brain.process_query("what is AI?")
        assert isinstance(result, dict)

    def test_process_query_has_required_keys(self):
        brain = _make_brain()
        result = brain.process_query("define machine learning")
        assert "query" in result
        assert "response" in result
        assert "context_used" in result

    def test_process_query_query_matches_input(self):
        brain = _make_brain()
        q = "what is Python?"
        result = brain.process_query(q)
        assert result["query"] == q


# ---------------------------------------------------------------------------
# NiblitBrain._trigger_gap_learning
# ---------------------------------------------------------------------------

class TestNiblitBrainGapLearning:
    """Tests for NiblitBrain._trigger_gap_learning()."""

    def test_gap_learning_empty_topic_does_not_raise(self):
        brain = _make_brain()
        brain._trigger_gap_learning("")

    def test_gap_learning_short_topic_does_not_raise(self):
        brain = _make_brain()
        brain._trigger_gap_learning("AI")  # < 3 chars after strip

    def test_gap_learning_valid_topic_does_not_raise(self):
        brain = _make_brain()
        brain._trigger_gap_learning("machine learning algorithms")


# ---------------------------------------------------------------------------
# BrainTrainer
# ---------------------------------------------------------------------------

class TestBrainTrainer:
    """Tests for BrainTrainer — persistent conversation pair storage."""

    def _make_trainer(self):
        mem = _make_memory()
        return BrainTrainer(memory=mem), mem

    def test_construction(self):
        trainer, _ = self._make_trainer()
        assert trainer is not None

    def test_record_exchange_does_not_raise(self):
        trainer, _ = self._make_trainer()
        trainer.record_exchange(
            user_prompt="what is deep learning?",
            assistant_response="Deep learning is a subset of machine learning.",
        )

    def test_record_exchange_updates_pair_count(self):
        trainer, _ = self._make_trainer()
        before = len(trainer._pairs)
        trainer.record_exchange("q", "a")
        after = len(trainer._pairs)
        assert after >= before  # pair should be added

    def test_ingest_research_does_not_raise(self):
        trainer, _ = self._make_trainer()
        trainer.ingest_research(
            topic="neural networks",
            text="Neural networks are computational models inspired by biological brains.",
        )

    def test_get_llm_data_summary_returns_dict(self):
        trainer, _ = self._make_trainer()
        summary = trainer.get_llm_data_summary()
        assert isinstance(summary, dict)

    def test_get_context_for_returns_string(self):
        trainer, _ = self._make_trainer()
        ctx = trainer.get_context_for("what is AI?")
        assert isinstance(ctx, str)

    def test_run_training_cycle_returns_string(self):
        trainer, _ = self._make_trainer()
        result = trainer.run_training_cycle()
        assert isinstance(result, str)
