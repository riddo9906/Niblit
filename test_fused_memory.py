"""test_fused_memory.py — integration tests for the fused SQLite + Qdrant memory backend.

Validates NiblitMemory, FusedMemoryPrimary, and the pipeline methods added to
NiblitCore, NiblitBrain, and SelfResearcher.

Run with::

    pytest test_fused_memory.py -v

All tests use an in-process SQLite (``:memory:``) database so no files are
created on disk and no external services (Qdrant, network) are required.
"""

import random
import string
import unittest
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_vector(dim: int = 128):
    return [random.random() for _ in range(dim)]


def _random_data(n_fields: int = 3):
    return {
        f"field_{i}": "".join(random.choices(string.ascii_letters, k=6))
        for i in range(n_fields)
    }


# ---------------------------------------------------------------------------
# FusedMemoryPrimary tests
# ---------------------------------------------------------------------------

class TestFusedMemoryPrimary(unittest.TestCase):
    """Unit tests for modules.fused_memory_primary.FusedMemoryPrimary."""

    def setUp(self):
        from niblit_memory import FusedMemoryPrimary
        self.mem = FusedMemoryPrimary(sqlite_path=":memory:")

    # ── structured record CRUD ────────────────────────────────────────────────

    def test_insert_and_get_record(self):
        """insert_record / get_record round-trip."""
        self.mem.insert_record("rec-1", {"name": "Alice", "score": 42})
        rec = self.mem.get_record("rec-1")
        self.assertEqual(rec, {"name": "Alice", "score": 42})

    def test_get_record_missing_returns_none(self):
        self.assertIsNone(self.mem.get_record("nonexistent"))

    def test_insert_record_overwrites(self):
        self.mem.insert_record("rec-1", {"val": "old"})
        self.mem.insert_record("rec-1", {"val": "new"})
        self.assertEqual(self.mem.get_record("rec-1"), {"val": "new"})

    def test_list_records(self):
        for i in range(5):
            self.mem.insert_record(f"rec-{i}", {"index": i})
        rows = self.mem.list_records()
        self.assertGreaterEqual(len(rows), 5)
        self.assertIn("record_id", rows[0])
        self.assertIn("data", rows[0])

    # ── vector API ────────────────────────────────────────────────────────────

    def test_add_embedding_and_search_vectors(self):
        """add_embedding followed by search_vectors returns SQLite results."""
        vec = _random_vector(384)
        self.mem.add_embedding(vec, {"source": "test", "id": "emb-1"})
        results = self.mem.search_vectors(vec, top_k=3)
        self.assertIn("qdrant", results)
        self.assertIn("sqlite", results)
        self.assertIsInstance(results["qdrant"], list)
        self.assertIsInstance(results["sqlite"], list)
        # At least one backend has a result
        total = len(results["qdrant"]) + len(results["sqlite"])
        self.assertGreater(total, 0)

    def test_insert_vector_and_query_vector(self):
        """insert_vector / query_vector (flat-list alias) round-trip."""
        vec = _random_vector(384)
        self.mem.insert_vector("v-1", vec, payload={"tag": "test"})
        hits = self.mem.query_vector(vec, top_k=5)
        self.assertIsInstance(hits, list)
        self.assertGreater(len(hits), 0)

    def test_add_embedding_text_delegates_to_parent(self):
        """add_embedding with a str arg delegates to FusedMemory text path."""
        # Should not raise — just delegate to parent
        self.mem.add_embedding("some text query", {"label": "text-path"})

    # ── similarity search ─────────────────────────────────────────────────────

    def test_overwrite_and_re_query(self):
        """Overwriting a record is reflected in subsequent reads."""
        records = []
        for i in range(5):
            rid = f"task_{i}"
            data = _random_data()
            vec = _random_vector(128)
            self.mem.insert_record(rid, data)
            self.mem.insert_vector(rid, vec, payload=data)
            records.append((rid, data, vec))

        # Overwrite first record
        rid, _, old_vec = records[0]
        new_data = _random_data()
        new_vec = _random_vector(128)
        self.mem.insert_record(rid, new_data)
        reloaded = self.mem.get_record(rid)
        self.assertEqual(reloaded, new_data, "Overwrite not reflected")


# ---------------------------------------------------------------------------
# NiblitCore fused API tests
# ---------------------------------------------------------------------------

class TestNiblitCoreFusedAPI(unittest.TestCase):
    """Test store_task_result / retrieve_task_result / list_all_tasks / search_related_tasks."""

    def setUp(self):
        from niblit_memory import FusedMemoryPrimary
        self.fused = FusedMemoryPrimary(sqlite_path=":memory:")

        # Build a minimal mock memory that has a fused_memory attribute
        self.mock_memory = MagicMock()
        self.mock_memory.fused_memory = self.fused

        # Patch NiblitCore heavily to avoid all the heavyweight __init__ work
        with patch("niblit_core.NiblitCore.__init__", lambda self, *a, **kw: None):
            import niblit_core
            self.core = niblit_core.NiblitCore.__new__(niblit_core.NiblitCore)
            self.core.memory = self.mock_memory

    def test_store_and_retrieve_task_result(self):
        self.core.store_task_result("task-1", {"status": "done", "value": 99})
        result = self.core.retrieve_task_result("task-1")
        self.assertEqual(result.get("status"), "done")
        self.assertEqual(result.get("value"), 99)

    def test_retrieve_missing_task_returns_empty_dict(self):
        result = self.core.retrieve_task_result("nonexistent")
        self.assertEqual(result, {})

    def test_list_all_tasks(self):
        for i in range(3):
            self.core.store_task_result(f"t{i}", {"n": i})
        tasks = self.core.list_all_tasks()
        self.assertGreaterEqual(len(tasks), 3)

    def test_search_related_tasks_returns_list(self):
        vec = _random_vector(384)
        self.core.store_task_result("t-vec", {"label": "vectorized"}, vector=vec)
        hits = self.core.search_related_tasks(vec, top_k=3)
        self.assertIsInstance(hits, list)

    def test_store_with_vector(self):
        vec = _random_vector(384)
        self.core.store_task_result("t-v", {"data": "with_vector"}, vector=vec)
        result = self.core.retrieve_task_result("t-v")
        self.assertEqual(result.get("data"), "with_vector")


# ---------------------------------------------------------------------------
# NiblitBrain fused API tests
# ---------------------------------------------------------------------------

class TestNiblitBrainFusedAPI(unittest.TestCase):
    """Test save_knowledge / load_knowledge / retrieve_similar on NiblitBrain."""

    def setUp(self):
        from niblit_memory import FusedMemoryPrimary
        self.fused = FusedMemoryPrimary(sqlite_path=":memory:")

        self.mock_memory = MagicMock()
        self.mock_memory.fused_memory = self.fused
        self.mock_memory.get_preferences.return_value = {}
        self.mock_memory.store_preferences.return_value = None

        with patch("niblit_brain.NiblitBrain.__init__", lambda self, *a, **kw: None):
            import niblit_brain
            self.brain = niblit_brain.NiblitBrain.__new__(niblit_brain.NiblitBrain)
            self.brain.memory = self.mock_memory

    def test_save_and_load_knowledge(self):
        self.brain.save_knowledge("k1", {"topic": "asyncio", "detail": "event loop"})
        loaded = self.brain.load_knowledge("k1")
        self.assertEqual(loaded.get("topic"), "asyncio")

    def test_load_missing_knowledge_returns_empty_dict(self):
        self.assertEqual(self.brain.load_knowledge("missing"), {})

    def test_save_knowledge_with_embedding(self):
        vec = _random_vector(384)
        self.brain.save_knowledge("k2", {"topic": "vector"}, embedding=vec)
        loaded = self.brain.load_knowledge("k2")
        self.assertEqual(loaded.get("topic"), "vector")

    def test_retrieve_similar_returns_list(self):
        vec = _random_vector(384)
        self.brain.save_knowledge("k3", {"topic": "search"}, embedding=vec)
        hits = self.brain.retrieve_similar(vec, top_k=3)
        self.assertIsInstance(hits, list)

    def test_retrieve_similar_empty_when_no_vectors(self):
        fresh_mem = MagicMock()
        fresh_mem.fused_memory = None
        self.brain.memory = fresh_mem
        hits = self.brain.retrieve_similar(_random_vector(128), top_k=3)
        self.assertEqual(hits, [])


# ---------------------------------------------------------------------------
# SelfResearcher fused API tests
# ---------------------------------------------------------------------------

class TestSelfResearcherFusedAPI(unittest.TestCase):
    """Test log_finding / get_finding / query_past_findings on SelfResearcher."""

    def setUp(self):
        from niblit_memory import FusedMemoryPrimary
        self.fused = FusedMemoryPrimary(sqlite_path=":memory:")

        self.mock_db = MagicMock()
        self.mock_db.fused_memory = self.fused

        with patch("modules.self_researcher.SelfResearcher.__init__", lambda self, *a, **kw: None):
            from modules.self_researcher import SelfResearcher
            self.researcher = SelfResearcher.__new__(SelfResearcher)
            self.researcher.db = self.mock_db
            self.researcher.history = []
            self.researcher.responses = []
            self.researcher.learning_patterns = {}

    def test_log_and_get_finding(self):
        self.researcher.log_finding("r1", {"query": "asyncio", "source": "web"})
        finding = self.researcher.get_finding("r1")
        self.assertEqual(finding.get("query"), "asyncio")

    def test_get_missing_finding_returns_empty_dict(self):
        self.assertEqual(self.researcher.get_finding("nope"), {})

    def test_log_finding_with_embedding(self):
        vec = _random_vector(384)
        self.researcher.log_finding("r2", {"topic": "vectors"}, embedding=vec)
        finding = self.researcher.get_finding("r2")
        self.assertEqual(finding.get("topic"), "vectors")

    def test_query_past_findings_returns_list(self):
        vec = _random_vector(384)
        self.researcher.log_finding("r3", {"topic": "search"}, embedding=vec)
        hits = self.researcher.query_past_findings(vec, top_k=3)
        self.assertIsInstance(hits, list)

    def test_query_past_findings_empty_without_fused(self):
        db = MagicMock()
        db.fused_memory = None
        self.researcher.db = db
        hits = self.researcher.query_past_findings(_random_vector(128), top_k=3)
        self.assertEqual(hits, [])

    def test_log_finding_fallback_without_fused(self):
        """When fused_memory is None, falls back to store_learning."""
        db = MagicMock()
        db.fused_memory = None
        db.store_learning = MagicMock()
        self.researcher.db = db
        self.researcher.log_finding("r4", {"data": "fallback"})
        db.store_learning.assert_called_once()


# ---------------------------------------------------------------------------
# Full pipeline smoke test
# ---------------------------------------------------------------------------

class TestFusedPipelineIntegration(unittest.TestCase):
    """Smoke test: save → load → search round-trip across all three components."""

    def setUp(self):
        from niblit_memory import FusedMemoryPrimary
        self.fused = FusedMemoryPrimary(sqlite_path=":memory:")
        self.mock_memory = MagicMock()
        self.mock_memory.fused_memory = self.fused

    def _make_core(self):
        with patch("niblit_core.NiblitCore.__init__", lambda self, *a, **kw: None):
            import niblit_core
            core = niblit_core.NiblitCore.__new__(niblit_core.NiblitCore)
            core.memory = self.mock_memory
            return core

    def _make_brain(self):
        with patch("niblit_brain.NiblitBrain.__init__", lambda self, *a, **kw: None):
            import niblit_brain
            brain = niblit_brain.NiblitBrain.__new__(niblit_brain.NiblitBrain)
            brain.memory = self.mock_memory
            return brain

    def _make_researcher(self):
        with patch("modules.self_researcher.SelfResearcher.__init__", lambda self, *a, **kw: None):
            from modules.self_researcher import SelfResearcher
            r = SelfResearcher.__new__(SelfResearcher)
            r.db = self.mock_memory
            r.history = []
            r.responses = []
            r.learning_patterns = {}
            return r

    def test_core_brain_researcher_share_fused_backend(self):
        """All three components reading from the same fused backend."""
        core = self._make_core()
        brain = self._make_brain()
        researcher = self._make_researcher()

        # Write from core
        core.store_task_result("shared-1", {"origin": "core"})
        # Read from brain
        loaded = brain.load_knowledge("shared-1")
        self.assertEqual(loaded.get("origin"), "core")

        # Write from researcher
        researcher.log_finding("shared-2", {"origin": "researcher"})
        # Read from core
        loaded2 = core.retrieve_task_result("shared-2")
        self.assertEqual(loaded2.get("origin"), "researcher")

    def test_vector_search_across_components(self):
        """A vector saved by brain can be found by core's search."""
        core = self._make_core()
        brain = self._make_brain()

        vec = _random_vector(384)
        brain.save_knowledge("kv-1", {"tag": "vector-test"}, embedding=vec)
        hits = core.search_related_tasks(vec, top_k=5)
        self.assertIsInstance(hits, list)

    def test_list_all_tasks_after_multi_component_writes(self):
        core = self._make_core()
        brain = self._make_brain()
        researcher = self._make_researcher()

        core.store_task_result("t1", {"x": 1})
        brain.save_knowledge("t2", {"x": 2})
        researcher.log_finding("t3", {"x": 3})

        tasks = core.list_all_tasks()
        ids = {t["record_id"] for t in tasks}
        self.assertIn("t1", ids)
        self.assertIn("t2", ids)
        self.assertIn("t3", ids)


if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO)
    unittest.main()
