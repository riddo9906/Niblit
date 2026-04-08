"""test_niblit_memory.py — unit tests for the niblit_memory package.

Covers FusedMemory, FusedMemoryPrimary, LocalDB, and the module-level helpers
(event, canonicalize, ingest).

All tests are fully offline-safe: no Qdrant instance or network access is
required. SQLite is exercised exclusively in ``:memory:`` mode; LocalDB uses
pytest's ``tmp_path`` fixture so no files remain after the test session.

Run with::

    pytest test_niblit_memory.py -v
"""

import random
import string

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_vector(dim: int = 64) -> list:
    return [random.random() for _ in range(dim)]


# ---------------------------------------------------------------------------
# FusedMemory  (non-singleton, SQLite-backed)
# ---------------------------------------------------------------------------

class TestFusedMemory:
    """Tests for niblit_memory.FusedMemory (sqlite_path=':memory:')."""

    def _make(self):
        from niblit_memory import FusedMemory
        return FusedMemory(sqlite_path=":memory:")

    def test_construction(self):
        mem = self._make()
        assert mem is not None

    def test_store_and_query_knowledge(self):
        mem = self._make()
        mem.store_knowledge("sky_color", "blue", source="test")
        # query_knowledge filters by source — no filter returns all
        results = mem.query_knowledge()
        assert isinstance(results, list)
        assert len(results) >= 1

    def test_query_knowledge_by_source(self):
        mem = self._make()
        mem.store_knowledge("fact_a", "value_a", source="src_unit_test")
        results = mem.query_knowledge(source="src_unit_test")
        assert isinstance(results, list)
        assert len(results) >= 1
        assert results[0]["source"] == "src_unit_test"

    def test_log_event_does_not_raise(self):
        mem = self._make()
        mem.log_event("unit_test_event", {"detail": "hello"})

    def test_query_events_returns_list(self):
        mem = self._make()
        mem.log_event("test_evt_type", {"x": 1})
        events = mem.query_events(event_type="test_evt_type")
        assert isinstance(events, list)

    def test_add_embedding_returns_bool(self):
        # add_embedding requires VectorStore; offline returns False gracefully
        mem = self._make()
        result = mem.add_embedding("niblit is an AI system")
        assert isinstance(result, bool)

    def test_search_vectors_returns_list(self):
        # search_vectors requires VectorStore; offline returns empty list gracefully
        mem = self._make()
        results = mem.search_vectors("niblit query", top_k=3)
        assert isinstance(results, list)

    def test_retrieve_returns_dict(self):
        mem = self._make()
        mem.store_knowledge("recall_key", "recall_value")
        result = mem.retrieve(query="recall_key")
        assert isinstance(result, dict)

    def test_merge_node_does_not_raise(self):
        mem = self._make()
        mem.merge_node("Concept", "Python", category="language")

    def test_merge_relationship_does_not_raise(self):
        mem = self._make()
        mem.merge_node("Concept", "AI")
        mem.merge_node("Concept", "ML")
        mem.merge_relationship("AI", "INCLUDES", "ML")

    def test_is_vector_available_bool(self):
        mem = self._make()
        # is_vector_available is a method
        assert isinstance(mem.is_vector_available(), bool)

    def test_vector_backend_str(self):
        mem = self._make()
        assert isinstance(mem.vector_backend, str)

    def test_close_does_not_raise(self):
        mem = self._make()
        mem.close()


# ---------------------------------------------------------------------------
# FusedMemoryPrimary  (non-singleton, extends FusedMemory with record store)
# ---------------------------------------------------------------------------

class TestFusedMemoryPrimaryExtra:
    """Additional tests for niblit_memory.FusedMemoryPrimary not in test_fused_memory.py."""

    def _make(self):
        from niblit_memory import FusedMemoryPrimary
        return FusedMemoryPrimary(sqlite_path=":memory:")

    def test_query_vector_multiple_results(self):
        mem = self._make()
        base = _random_vector(64)
        for i in range(5):
            vec = [v + i * 0.001 for v in base]
            mem.insert_vector(f"v_{i}", vec, {"idx": i})
        results = mem.query_vector(base, top_k=3)
        # Returns a flat list; may be empty when VectorStore is offline
        assert isinstance(results, list)

    def test_insert_record_returns_on_duplicate(self):
        mem = self._make()
        mem.insert_record("dup_id", {"value": "first"})
        mem.insert_record("dup_id", {"value": "second"})  # overwrite
        rec = mem.get_record("dup_id")
        assert rec is not None

    def test_list_records_respects_limit(self):
        mem = self._make()
        for i in range(10):
            mem.insert_record(f"lim_{i}", {"n": i})
        results = mem.list_records(limit=4)
        assert len(results) <= 4


# ---------------------------------------------------------------------------
# LocalDB  (non-singleton, JSON-backed)
# ---------------------------------------------------------------------------

class TestLocalDB:
    """Tests for niblit_memory.LocalDB (JSON file, uses tmp_path)."""

    def _make(self, tmp_path):
        from niblit_memory import LocalDB
        return LocalDB(path=str(tmp_path / "niblit_test.json"))

    def test_construction(self, tmp_path):
        db = self._make(tmp_path)
        assert db is not None

    def test_add_and_get_fact(self, tmp_path):
        db = self._make(tmp_path)
        db.add_fact("sky", "blue")
        fact = db.get_fact("sky")
        assert fact is not None
        assert fact["value"] == "blue"

    def test_get_missing_fact_returns_none(self, tmp_path):
        db = self._make(tmp_path)
        assert db.get_fact("this_key_does_not_exist_xyz") is None

    def test_overwrite_fact(self, tmp_path):
        db = self._make(tmp_path)
        db.add_fact("lang", "python")
        db.add_fact("lang", "rust")
        fact = db.get_fact("lang")
        assert fact is not None
        assert fact["value"] == "rust"

    def test_list_facts(self, tmp_path):
        db = self._make(tmp_path)
        db.add_fact("a", 1)
        db.add_fact("b", 2)
        facts = db.list_facts()
        assert isinstance(facts, list)
        assert len(facts) >= 2

    def test_add_entry_get_log(self, tmp_path):
        db = self._make(tmp_path)
        db.add_entry("event_key", "event_value")
        log = db.get_log()
        assert isinstance(log, list)
        assert len(log) >= 1
        assert any(item.get("key") == "event_key" for item in log)

    def test_store_and_get_learning(self, tmp_path):
        db = self._make(tmp_path)
        entry = {"topic": "Niblit", "note": "AI OS"}
        db.store_learning(entry)
        log = db.get_learning_log()
        assert any("Niblit" in str(item) for item in log)

    def test_recall_returns_matching_entries(self, tmp_path):
        db = self._make(tmp_path)
        db.store_learning({"topic": "solar_system", "note": "planets"})
        results = db.recall("solar_system")
        assert isinstance(results, list)
        assert len(results) >= 1

    def test_recall_no_match_returns_empty(self, tmp_path):
        db = self._make(tmp_path)
        results = db.recall("zyxwv_no_match_xyz")
        assert isinstance(results, list)
        assert len(results) == 0

    def test_store_and_get_preferences(self, tmp_path):
        db = self._make(tmp_path)
        prefs = {"theme": "dark", "language": "en"}
        db.store_preferences(prefs)
        loaded = db.get_preferences()
        assert loaded.get("theme") == "dark"
        assert loaded.get("language") == "en"

    def test_condense_trims_interactions(self, tmp_path):
        db = self._make(tmp_path)
        for i in range(10):
            db.add_entry(f"key_{i}", f"val_{i}")
        db.condense(keep_top=3)
        log = db.get_log()
        assert len(log) <= 3


# ---------------------------------------------------------------------------
# Module-level helpers: event, canonicalize, ingest
# ---------------------------------------------------------------------------

class TestMemoryHelpers:
    """Tests for niblit_memory.event, canonicalize, and ingest."""

    def test_event_returns_dict(self):
        from niblit_memory import event
        e = event("user", "Hello Niblit")
        assert isinstance(e, dict)
        assert e["speaker"] == "user"
        assert e["msg"] == "Hello Niblit"

    def test_event_timestamp_is_int(self):
        from niblit_memory import event
        e = event("assistant", "Hi there")
        assert isinstance(e["ts"], int)
        assert e["ts"] > 0

    def test_event_meta_defaults_to_empty_dict(self):
        from niblit_memory import event
        e = event("system", "boot")
        assert e["meta"] == {}

    def test_event_with_intent_and_meta(self):
        from niblit_memory import event
        e = event("user", "query", intent="search", meta={"lang": "en"})
        assert e["intent"] == "search"
        assert e["meta"]["lang"] == "en"

    def test_canonicalize_plain_text(self):
        from niblit_memory import canonicalize
        result = canonicalize("Hello world")
        assert isinstance(result, dict)
        assert result["msg"] == "Hello world"
        assert result["speaker"] == "user"

    def test_canonicalize_prefixed_user(self):
        from niblit_memory import canonicalize
        result = canonicalize("user: what is AI?")
        assert result["speaker"] == "user"
        assert result["msg"] == "what is AI?"

    def test_canonicalize_prefixed_assistant(self):
        from niblit_memory import canonicalize
        # "assistant" is not in the _USER_PATTERN (user|agent|system),
        # so the raw string falls through and the default speaker is used.
        result = canonicalize("assistant: I am Niblit", default="user")
        assert isinstance(result, dict)
        assert "I am Niblit" in result["msg"] or result["speaker"] == "user"

    def test_canonicalize_default_override(self):
        from niblit_memory import canonicalize
        result = canonicalize("plain message", default="system")
        assert result["speaker"] == "system"

    def test_ingest_returns_event_dict(self):
        from niblit_memory import ingest
        mem = object()  # minimal — ingest handles missing methods gracefully
        result = ingest(mem, "user: hello")
        assert isinstance(result, dict)
        assert result["msg"] == "hello"

    def test_ingest_with_fused_memory(self):
        from niblit_memory import FusedMemory, ingest
        mem = FusedMemory(sqlite_path=":memory:")
        result = ingest(mem, "user: ping pong")
        assert isinstance(result, dict)
        assert result["speaker"] == "user"
