"""
test_niblit_db.py — Integration tests for NiblitSQLiteDB.

Run with::

    pytest test_niblit_db.py -v

All tests use an in-memory SQLite database so no disk I/O is needed.
"""

import json
import threading
import pytest

from niblit_sqlite_db import NiblitSQLiteDB


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    """Return a fresh in-memory NiblitSQLiteDB instance."""
    instance = NiblitSQLiteDB(":memory:")
    yield instance
    instance.close()


# ---------------------------------------------------------------------------
# Schema / construction
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_creates_without_error(self, db):
        assert db is not None

    def test_list_facts_empty_initially(self, db):
        assert db.list_facts() == []

    def test_list_events_empty_initially(self, db):
        assert db.list_events() == []

    def test_list_interactions_empty_initially(self, db):
        assert db.list_interactions() == []


# ---------------------------------------------------------------------------
# Facts
# ---------------------------------------------------------------------------

class TestFacts:
    def test_add_and_get_fact(self, db):
        db.add_fact("color", "blue")
        assert db.get_fact("color") == "blue"

    def test_get_nonexistent_fact_returns_none(self, db):
        assert db.get_fact("does_not_exist") is None

    def test_update_fact(self, db):
        db.add_fact("color", "blue")
        db.add_fact("color", "red")
        assert db.get_fact("color") == "red"

    def test_list_facts_returns_all(self, db):
        db.add_fact("a", "1")
        db.add_fact("b", "2")
        facts = db.list_facts()
        assert len(facts) == 2

    def test_list_facts_respects_limit(self, db):
        for i in range(10):
            db.add_fact(f"key{i}", f"val{i}")
        facts = db.list_facts(limit=3)
        assert len(facts) == 3

    def test_list_facts_filter_by_category(self, db):
        db.add_fact("fact1", "v1", category="system")
        db.add_fact("fact2", "v2", category="user")
        system_facts = db.list_facts(category="system")
        assert len(system_facts) == 1
        assert system_facts[0]["key"] == "fact1"

    def test_delete_fact(self, db):
        db.add_fact("temp", "value")
        deleted = db.delete_fact("temp")
        assert deleted is True
        assert db.get_fact("temp") is None

    def test_delete_nonexistent_fact(self, db):
        deleted = db.delete_fact("ghost")
        assert deleted is False

    def test_add_fact_serialises_dict(self, db):
        db.add_fact("config", {"key": "value", "num": 42})
        raw = db.get_fact("config")
        # Should be stored as JSON string
        data = json.loads(raw)
        assert data["num"] == 42

    def test_facts_have_required_keys(self, db):
        db.add_fact("x", "y")
        facts = db.list_facts()
        assert "key" in facts[0]
        assert "value" in facts[0]
        assert "created_at" in facts[0]


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

class TestEvents:
    def test_log_and_list_event(self, db):
        db.log_event("startup", {"version": "1.0"})
        events = db.list_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "startup"

    def test_event_payload_stored_as_json(self, db):
        db.log_event("test", {"x": 1})
        events = db.list_events()
        payload = json.loads(events[0]["payload"])
        assert payload["x"] == 1

    def test_filter_events_by_type(self, db):
        db.log_event("type_a", {})
        db.log_event("type_b", {})
        db.log_event("type_a", {})
        a_events = db.list_events(event_type="type_a")
        assert len(a_events) == 2

    def test_events_limit(self, db):
        for i in range(5):
            db.log_event("ev", {"i": i})
        assert len(db.list_events(limit=2)) == 2


# ---------------------------------------------------------------------------
# Interactions
# ---------------------------------------------------------------------------

class TestInteractions:
    def test_add_and_list_interaction(self, db):
        db.add_interaction("user", "hello")
        db.add_interaction("assistant", "hi there")
        interactions = db.list_interactions()
        assert len(interactions) == 2

    def test_interaction_has_role_and_content(self, db):
        db.add_interaction("user", "test message")
        interactions = db.list_interactions()
        assert interactions[0]["role"] in ("user", "assistant")
        assert "content" in interactions[0]

    def test_interactions_limit(self, db):
        for i in range(10):
            db.add_interaction("user", f"msg {i}")
        assert len(db.list_interactions(limit=3)) == 3


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

class TestMeta:
    def test_set_and_get_meta(self, db):
        db.set_meta("version", "1.0")
        assert db.get_meta("version") == "1.0"

    def test_get_meta_default(self, db):
        assert db.get_meta("missing", default="fallback") == "fallback"

    def test_update_meta(self, db):
        db.set_meta("count", 1)
        db.set_meta("count", 2)
        assert db.get_meta("count") == 2

    def test_meta_stores_complex_values(self, db):
        db.set_meta("prefs", {"tone": "neutral"})
        prefs = db.get_meta("prefs")
        assert isinstance(prefs, dict)
        assert prefs["tone"] == "neutral"


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_fact_writes(self, db):
        errors = []

        def _write(i):
            try:
                db.add_fact(f"thread_key_{i}", f"value_{i}")
            except Exception as exc:  # pylint: disable=broad-exception-caught
                errors.append(exc)

        threads = [threading.Thread(target=_write, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"
        assert len(db.list_facts()) == 20


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------

class TestBackup:
    def test_backup_raises_for_memory_db(self, db):
        with pytest.raises(ValueError, match="in-memory"):
            db.backup("/tmp/should_not_exist.sqlite")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
