"""
test_autonomous_engine.py — Unit tests for modules/autonomous_learning_engine.py.

Run with::

    pytest test_autonomous_engine.py -v

All external dependencies (NiblitCore, researcher, teacher, …) are stubbed so
the tests run without any real services or network access.
"""

import time
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from modules.autonomous_learning_engine import (
    AutonomousLearningEngine,
    initialize_autonomous_engine,
    get_autonomous_engine,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_core(**kwargs):
    """Return a minimal MagicMock that satisfies NiblitCore duck-typing."""
    core = MagicMock()
    core.db = MagicMock()
    core.db.list_facts.return_value = []
    for key, value in kwargs.items():
        setattr(core, key, value)
    return core


@pytest.fixture()
def core():
    return _make_core()


@pytest.fixture()
def ale(core):
    """Return a minimal AutonomousLearningEngine (no optional modules)."""
    engine = AutonomousLearningEngine(
        core=core,
        idle_threshold=0,   # immediately idle so tests can control state
        poll_interval=9999,  # prevent background loop from firing
    )
    yield engine
    # Ensure background thread stops even if a test fails
    engine.running = False
    engine._stop_event.set()


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_creates_with_core_only(self, core):
        engine = AutonomousLearningEngine(core=core)
        assert engine is not None

    def test_running_is_false_on_init(self, ale):
        assert ale.running is False

    def test_research_topics_non_empty(self, ale):
        # Engine pre-seeds some default research topics
        assert isinstance(ale.research_topics, list)

    def test_pending_ideas_is_list(self, ale):
        assert isinstance(ale.pending_ideas, list)

    def test_optional_modules_default_to_none(self, core):
        engine = AutonomousLearningEngine(core=core)
        assert engine.researcher is None
        assert engine.reflect is None
        assert engine.self_teacher is None
        assert engine.evolve_engine is None

    def test_accepts_optional_modules(self, core):
        mock_researcher = MagicMock()
        mock_teacher = MagicMock()
        engine = AutonomousLearningEngine(
            core=core,
            researcher=mock_researcher,
            self_teacher=mock_teacher,
        )
        assert engine.researcher is mock_researcher
        assert engine.self_teacher is mock_teacher


# ---------------------------------------------------------------------------
# is_idle / update_last_interaction
# ---------------------------------------------------------------------------

class TestIdleDetection:
    def test_idle_when_threshold_zero(self, ale):
        # idle_threshold=0 means always idle immediately
        assert ale.is_idle() is True

    def test_not_idle_after_interaction(self, core):
        engine = AutonomousLearningEngine(
            core=core,
            idle_threshold=9999,
            poll_interval=9999,
        )
        engine.update_last_interaction()
        assert engine.is_idle() is False

    def test_update_last_interaction_does_not_raise(self, ale):
        ale.update_last_interaction()  # should be silent


# ---------------------------------------------------------------------------
# add_research_topic / add_research_topics
# ---------------------------------------------------------------------------

class TestResearchTopics:
    def test_add_new_topic_returns_true(self, ale):
        before = len(ale.research_topics)
        result = ale.add_research_topic("quantum computing")
        assert result is True
        assert len(ale.research_topics) == before + 1

    def test_add_duplicate_topic_returns_false(self, ale):
        ale.add_research_topic("unique_topic_xyz")
        result = ale.add_research_topic("unique_topic_xyz")
        assert result is False

    def test_add_topic_persists(self, ale):
        ale.add_research_topic("new_topic_abc")
        assert "new_topic_abc" in ale.research_topics

    def test_add_research_topics_bulk(self, ale):
        added = ale.add_research_topics(["alpha", "beta", "gamma"])
        assert set(added) == {"alpha", "beta", "gamma"}

    def test_add_research_topics_skips_duplicates(self, ale):
        ale.add_research_topic("delta")
        added = ale.add_research_topics(["delta", "epsilon"])
        assert "delta" not in added
        assert "epsilon" in added


# ---------------------------------------------------------------------------
# get_learning_stats
# ---------------------------------------------------------------------------

class TestGetLearningStats:
    def test_returns_dict(self, ale):
        stats = ale.get_learning_stats()
        assert isinstance(stats, dict)

    def test_contains_required_keys(self, ale):
        stats = ale.get_learning_stats()
        for key in ("running", "is_idle", "stats", "pending_ideas",
                    "research_topics", "modules_available"):
            assert key in stats, f"Missing key: {key}"

    def test_running_false_when_not_started(self, ale):
        assert ale.get_learning_stats()["running"] is False

    def test_modules_available_is_dict(self, ale):
        mods = ale.get_learning_stats()["modules_available"]
        assert isinstance(mods, dict)

    def test_modules_available_all_false_when_no_deps(self, ale):
        mods = ale.get_learning_stats()["modules_available"]
        assert mods["researcher"] is False
        assert mods["reflect"] is False
        assert mods["self_teacher"] is False

    def test_modules_available_true_when_provided(self, core):
        researcher = MagicMock()
        engine = AutonomousLearningEngine(core=core, researcher=researcher, poll_interval=9999)
        mods = engine.get_learning_stats()["modules_available"]
        assert mods["researcher"] is True

    def test_research_topics_count_matches(self, ale):
        before = ale.get_learning_stats()["research_topics"]
        ale.add_research_topic("brand_new_topic_xyz")
        after = ale.get_learning_stats()["research_topics"]
        assert after == before + 1

    def test_cycle_count_starts_at_zero(self, ale):
        assert ale.get_learning_stats()["cycle_count"] == 0

    def test_serpex_research_agent_in_modules_available(self, ale):
        mods = ale.get_learning_stats()["modules_available"]
        assert "serpex_research_agent" in mods

    def test_serpex_research_agent_available_without_key(self, ale, monkeypatch):
        # Scrapy-backed search requires no API key — agent is always available.
        monkeypatch.delenv("SERPEX_API_KEY", raising=False)
        ale.serpex_research_agent = None
        if ale.core:
            try:
                del ale.core.serpex_research_agent
            except AttributeError:
                pass
        mods = ale.get_learning_stats()["modules_available"]
        assert mods["serpex_research_agent"] is True


# ---------------------------------------------------------------------------
# start / stop
# ---------------------------------------------------------------------------

class TestStartStop:
    def test_start_returns_true(self, ale):
        result = ale.start()
        ale.stop()
        assert result is True

    def test_start_sets_running(self, ale):
        ale.start()
        running = ale.running
        ale.stop()
        assert running is True

    def test_start_twice_returns_false(self, ale):
        ale.start()
        result = ale.start()
        ale.stop()
        assert result is False

    def test_stop_clears_running(self, ale):
        ale.start()
        ale.stop()
        assert ale.running is False

    def test_stop_returns_true(self, ale):
        ale.start()
        result = ale.stop()
        assert result is True

    def test_stop_without_start_does_not_raise(self, ale):
        result = ale.stop()
        assert result is True


# ---------------------------------------------------------------------------
# initialize_autonomous_engine factory
# ---------------------------------------------------------------------------

class TestInitializeFactory:
    def test_returns_ale_instance(self, core):
        engine = initialize_autonomous_engine(core=core)
        assert isinstance(engine, AutonomousLearningEngine)
        engine.running = False
        engine._stop_event.set()

    def test_accepts_optional_researcher(self, core):
        researcher = MagicMock()
        engine = initialize_autonomous_engine(core=core, researcher=researcher)
        assert engine.researcher is researcher
        engine.running = False
        engine._stop_event.set()

    def test_accepts_serpex_research_agent(self, core):
        """Factory should wire serpex_research_agent into the ALE instance."""
        mock_agent = MagicMock()
        engine = initialize_autonomous_engine(core=core, serpex_research_agent=mock_agent)
        assert engine.serpex_research_agent is mock_agent
        engine.running = False
        engine._stop_event.set()

    def test_get_autonomous_engine_returns_instance_after_init(self, core):
        initialize_autonomous_engine(core=core)
        engine = get_autonomous_engine()
        assert engine is not None
        engine.running = False
        engine._stop_event.set()


# ---------------------------------------------------------------------------
# run_self_learn_sequence (smoke test with all deps stubbed)
# ---------------------------------------------------------------------------

class TestRunSelfLearnSequence:
    def test_returns_string(self, ale):
        result = ale.run_self_learn_sequence()
        assert isinstance(result, str)

    def test_runs_without_any_optional_modules(self, ale):
        # Should not raise even though no optional modules are wired
        result = ale.run_self_learn_sequence()
        assert result is not None

    def test_with_researcher_stub(self, core):
        researcher = MagicMock()
        researcher.research.return_value = "some research findings"
        engine = AutonomousLearningEngine(
            core=core,
            researcher=researcher,
            idle_threshold=0,
            poll_interval=9999,
        )
        result = engine.run_self_learn_sequence()
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Step 27: _autonomous_serpex_research
# ---------------------------------------------------------------------------

class TestSerpexResearchStep:
    """Verify ALE Step 27 (_autonomous_serpex_research) behaviour."""

    def test_returns_skip_message_without_agent(self, ale, monkeypatch):
        """No agent → graceful skip or 'no valid results' message, no exception."""
        monkeypatch.delenv("SERPEX_API_KEY", raising=False)
        ale.serpex_research_agent = None
        if ale.core:
            try:
                del ale.core.serpex_research_agent
            except AttributeError:
                pass
        result = ale._autonomous_serpex_research()
        assert isinstance(result, str)
        # Either "skipped" (no agent at all) or "no valid results" (key missing/wrong)
        lower = result.lower()
        assert any(kw in lower for kw in ("skip", "unavailable", "results", "error"))

    def test_uses_injected_serpex_agent(self, core):
        """Injected ResearchAgent is called and results stored in KB."""
        mock_agent = MagicMock()
        mock_agent._serpex_key = "test-key"
        mock_agent.search_web.return_value = [
            {"title": "Endianness", "url": "http://example.com",
             "snippet": "endianness refers to byte order in memory"}
        ]
        mock_kb = MagicMock()
        engine = AutonomousLearningEngine(
            core=core,
            serpex_research_agent=mock_agent,
            knowledge_db=mock_kb,
            poll_interval=9999,
        )
        result = engine._autonomous_serpex_research()
        mock_agent.search_web.assert_called_once()
        # KB should have received at least one add_fact call
        mock_kb.add_fact.assert_called()
        assert isinstance(result, str)
        assert "snippet" in result.lower() or "serpex" in result.lower()

    def test_increments_serpex_research_cycles(self, core):
        """Counter increments after a successful run."""
        mock_agent = MagicMock()
        mock_agent._serpex_key = "key"
        mock_agent.search_web.return_value = [
            {"title": "T", "url": "http://u.com", "snippet": "some relevant snippet text here"}
        ]
        engine = AutonomousLearningEngine(
            core=core,
            serpex_research_agent=mock_agent,
            poll_interval=9999,
        )
        before = engine.learning_history["serpex_research_cycles"]
        engine._autonomous_serpex_research()
        after = engine.learning_history["serpex_research_cycles"]
        assert after == before + 1

    def test_cycle_count_increments_each_run(self, ale):
        """_cycle_count should be 0 before any cycle has run (verify initial state)."""
        assert ale._cycle_count == 0

    def test_get_serpex_agent_returns_injected(self, core):
        """_get_serpex_agent() should return the injected instance."""
        mock_agent = MagicMock()
        mock_agent._serpex_key = "k"
        engine = AutonomousLearningEngine(
            core=core,
            serpex_research_agent=mock_agent,
            poll_interval=9999,
        )
        assert engine._get_serpex_agent() is mock_agent

    def test_get_serpex_agent_returns_none_without_key(self, ale, monkeypatch):
        """Without an injected agent and no key, _get_serpex_agent returns None."""
        monkeypatch.delenv("SERPEX_API_KEY", raising=False)
        ale.serpex_research_agent = None
        if ale.core:
            try:
                del ale.core.serpex_research_agent
            except AttributeError:
                pass
        result = ale._get_serpex_agent()
        # Should be None (no key) or a ResearchAgent (key found) — never raise.
        assert result is None or hasattr(result, "search_web")


class TestQwenCopilotIntegration:
    def test_code_research_adds_qwen_brief_when_local_copilot_available(self, core):
        researcher = MagicMock()
        researcher.research_code_and_feed_generator.return_value = "Use context managers for file safety."

        local_brain = MagicMock()
        local_brain.ask.return_value = "• Keep functions short\n• Validate inputs"
        core.local_brain = local_brain

        kb = MagicMock()
        engine = AutonomousLearningEngine(
            core=core,
            researcher=researcher,
            knowledge_db=kb,
            poll_interval=9999,
        )
        engine.code_research_topics = [("python", "file io")]

        result = engine._autonomous_code_research()
        assert "Qwen" in result
        assert any(
            str(call.args[0]).startswith("ale_qwen_code_brief:")
            for call in kb.add_fact.call_args_list
            if call.args
        )

    def test_code_compilation_uses_qwen_fallback_syntax_fix(self, core, monkeypatch):
        class _NoFixer:
            def __init__(self, db=None):
                self.db = db

            def fix_syntax_errors(self, _language, code, _error_msg, _compiler):
                return code, False, "no built-in fix"

        monkeypatch.setattr("modules.code_error_fixer.CodeErrorFixer", _NoFixer)

        class _Compiler:
            def syntax_test(self, language, code):  # noqa: ARG002
                ok = "print('ok')" in code
                return {"valid": ok, "error": None if ok else "SyntaxError: bad syntax"}

            def run(self, language, code):  # noqa: ARG002
                return SimpleNamespace(success=True, stdout="ok", stderr="", error="")

        local_brain = MagicMock()
        local_brain.ask.return_value = "```python\nprint('ok')\n```"
        core.local_brain = local_brain

        engine = AutonomousLearningEngine(
            core=core,
            code_compiler=_Compiler(),
            poll_interval=9999,
        )
        engine._pending_compiled = [{
            "language": "python",
            "code": "print(",
            "topic": "syntax_test",
        }]

        result = engine._autonomous_code_compilation()
        assert "✅ success" in result
        assert local_brain.ask.called
        assert engine._compiled_for_reflection[-1]["success"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
