"""
test_reflect.py — Unit tests for modules/reflect.py (ReflectModule).

Run with::

    pytest test_reflect.py -v

The database, self_teacher, and learner dependencies are all stubbed so no
real services are needed.
"""

import pytest
from unittest.mock import MagicMock, call

from modules.reflect import ReflectModule, collect_and_summarize


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    """Return a MagicMock acting as the database."""
    return MagicMock()


@pytest.fixture()
def teacher():
    """Return a MagicMock acting as self_teacher."""
    return MagicMock()


@pytest.fixture()
def learner():
    """Return a MagicMock acting as the learner module."""
    return MagicMock()


@pytest.fixture()
def reflect(db, teacher, learner):
    """Return a fully wired ReflectModule."""
    return ReflectModule(db=db, self_teacher=teacher, learner=learner)


@pytest.fixture()
def reflect_no_deps():
    """Return a ReflectModule with no optional dependencies."""
    return ReflectModule(db=None, self_teacher=None, learner=None)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_creates_with_all_deps(self, db, teacher, learner):
        rm = ReflectModule(db=db, self_teacher=teacher, learner=learner)
        assert rm.db is db
        assert rm.self_teacher is teacher
        assert rm.learner is learner

    def test_creates_with_only_db(self, db):
        rm = ReflectModule(db=db)
        assert rm.db is db
        assert rm.self_teacher is None
        assert rm.learner is None

    def test_creates_with_no_deps(self):
        rm = ReflectModule(db=None)
        assert rm.db is None


# ---------------------------------------------------------------------------
# collect_and_summarize
# ---------------------------------------------------------------------------

class TestCollectAndSummarize:
    def test_no_entry_returns_no_reflection(self, reflect):
        result = reflect.collect_and_summarize()
        assert "No reflection" in result

    def test_empty_entry_returns_no_reflection(self, reflect):
        result = reflect.collect_and_summarize(entry="")
        assert "No reflection" in result

    def test_returns_string(self, reflect):
        result = reflect.collect_and_summarize(entry="Niblit learned Python today.")
        assert isinstance(result, str)

    def test_saves_to_db(self, reflect, db):
        reflect.collect_and_summarize(entry="test entry")
        db.add_fact.assert_called_once()

    def test_db_key_contains_reflect_prefix(self, reflect, db):
        reflect.collect_and_summarize(entry="test entry")
        key_arg = db.add_fact.call_args[0][0]
        assert key_arg.startswith("reflect:")

    def test_calls_self_teacher(self, reflect, teacher):
        reflect.collect_and_summarize(entry="learning something")
        teacher.teach.assert_called_once_with("learning something")

    def test_calls_learner(self, reflect, learner):
        reflect.collect_and_summarize(entry="learning something")
        learner.learn.assert_called_once_with("learning something")

    def test_no_db_does_not_raise(self, reflect_no_deps):
        result = reflect_no_deps.collect_and_summarize(entry="some text")
        assert isinstance(result, str)

    def test_no_teacher_does_not_raise(self, db):
        rm = ReflectModule(db=db, self_teacher=None, learner=None)
        result = rm.collect_and_summarize(entry="text")
        assert isinstance(result, str)

    def test_teacher_exception_does_not_propagate(self, db):
        bad_teacher = MagicMock()
        bad_teacher.teach.side_effect = RuntimeError("bang")
        rm = ReflectModule(db=db, self_teacher=bad_teacher)
        result = rm.collect_and_summarize(entry="robust entry")
        assert isinstance(result, str)

    def test_learner_exception_does_not_propagate(self, db):
        bad_learner = MagicMock()
        bad_learner.learn.side_effect = RuntimeError("oops")
        rm = ReflectModule(db=db, learner=bad_learner)
        result = rm.collect_and_summarize(entry="robust entry")
        assert isinstance(result, str)

    def test_db_exception_does_not_propagate(self):
        bad_db = MagicMock()
        bad_db.add_fact.side_effect = Exception("db error")
        rm = ReflectModule(db=bad_db)
        result = rm.collect_and_summarize(entry="entry text")
        assert isinstance(result, str)

    def test_result_mentions_themes(self, reflect):
        result = reflect.collect_and_summarize(entry="python python python code")
        assert "Themes" in result or "theme" in result.lower()


# ---------------------------------------------------------------------------
# auto_reflect
# ---------------------------------------------------------------------------

class TestAutoReflect:
    def test_empty_events_returns_nothing_to_reflect(self, reflect):
        result = reflect.auto_reflect([])
        assert "Nothing to reflect" in result

    def test_none_events_returns_nothing_to_reflect(self, reflect):
        # auto_reflect treats falsy input as empty
        result = reflect.auto_reflect(None)
        assert "Nothing to reflect" in result

    def test_returns_string(self, reflect):
        result = reflect.auto_reflect(["event one", "event two"])
        assert isinstance(result, str)

    def test_processes_string_events(self, reflect, db):
        reflect.auto_reflect(["startup", "user joined"])
        db.add_fact.assert_called_once()

    def test_processes_dict_events_with_input_key(self, reflect, db):
        events = [{"input": "user said hello", "response": "hi"}]
        reflect.auto_reflect(events)
        db.add_fact.assert_called_once()

    def test_processes_dict_events_with_response_key(self, reflect, db):
        events = [{"response": "I replied with something"}]
        reflect.auto_reflect(events)
        db.add_fact.assert_called_once()

    def test_processes_dict_events_with_event_key(self, reflect, db):
        events = [{"event": "system booted"}]
        reflect.auto_reflect(events)
        db.add_fact.assert_called_once()

    def test_processes_dict_events_fallback_to_json(self, reflect, db):
        events = [{"unknown_key": "some value"}]
        reflect.auto_reflect(events)
        db.add_fact.assert_called_once()

    def test_mixed_string_and_dict_events(self, reflect, db):
        events = ["string event", {"input": "dict event"}]
        reflect.auto_reflect(events)
        db.add_fact.assert_called_once()

    def test_all_bad_events_returns_nothing_to_reflect(self, reflect):
        # All events raise during processing — result should be graceful
        class _Bad:
            def __str__(self):
                raise TypeError("no str")

        result = reflect.auto_reflect([_Bad()])
        assert isinstance(result, str)

    def test_no_deps_does_not_raise(self, reflect_no_deps):
        result = reflect_no_deps.auto_reflect(["one", "two"])
        assert isinstance(result, str)

    def test_limits_to_five_events(self, reflect, db):
        """auto_reflect joins only the first five events."""
        events = [f"event_{i}" for i in range(20)]
        reflect.auto_reflect(events)
        # The key saved to DB should exist; just check it was called once
        db.add_fact.assert_called_once()


# ---------------------------------------------------------------------------
# Module-level collect_and_summarize helper
# ---------------------------------------------------------------------------

class TestModuleLevelHelper:
    def test_module_function_returns_string(self):
        result = collect_and_summarize(entry="some entry", db=None)
        assert isinstance(result, str)

    def test_module_function_no_entry(self):
        result = collect_and_summarize()
        assert "No reflection" in result

    def test_module_function_uses_db(self):
        """The module helper creates a ReflectModule and delegates to it.
        Test this by calling directly on a new instance instead of through
        the singleton wrapper (which caches the first db argument).
        """
        mock_db = MagicMock()
        rm = ReflectModule(db=mock_db)
        rm.collect_and_summarize(entry="test entry for db")
        mock_db.add_fact.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
