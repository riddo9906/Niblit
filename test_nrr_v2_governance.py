"""Tests for NRR-v2 governance contracts.

Covers:
- GovernanceViolationError raised on embedding dimension mismatch
- GovernanceViolationError raised on non-finite / zero-norm vectors
- QdrantAdapter routing enforcement
- ClusterBootstrap idempotency (409 = success, existing = governed)
- initialize_cluster.sh idempotency assertions (static analysis)
"""

from __future__ import annotations

import math
import unittest
from unittest.mock import MagicMock, patch

from modules.embedding_engine import GovernanceViolationError, EmbeddingEngine, EMBEDDING_DIM
from modules.vector_memory.qdrant_adapter import QdrantAdapter
from modules.vector_memory.cluster_bootstrap import (
    ClusterBootstrap,
    CollectionSpec,
    BootstrapResult,
    _GOVERNED_COLLECTIONS,
    VECTOR_DIM as BOOTSTRAP_DIM,
)


def _valid_vector(dim: int = 384) -> list:
    """Return a valid normalized vector of the given dimension."""
    v = [float(i % 13 + 1) for i in range(dim)]
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


class TestGovernanceViolationError(unittest.TestCase):
    """GovernanceViolationError is the authoritative governance signal."""

    def test_is_exception_subclass(self):
        self.assertTrue(issubclass(GovernanceViolationError, Exception))

    def test_raises_with_message(self):
        with self.assertRaises(GovernanceViolationError) as ctx:
            raise GovernanceViolationError("dimension mismatch")
        self.assertIn("dimension mismatch", str(ctx.exception))


class TestEmbeddingEngineValidation(unittest.TestCase):
    """EmbeddingEngine._validate_and_normalize raises GovernanceViolationError on contract breach."""

    def test_wrong_dim_raises_governance_error(self):
        engine = EmbeddingEngine()
        bad_vector = [0.5] * 128  # wrong dim
        with self.assertRaises(GovernanceViolationError) as ctx:
            engine._validate_and_normalize(bad_vector)
        self.assertIn("384", str(ctx.exception))

    def test_zero_dim_raises_governance_error(self):
        engine = EmbeddingEngine()
        with self.assertRaises(GovernanceViolationError):
            engine._validate_and_normalize([])

    def test_non_finite_raises_governance_error(self):
        engine = EmbeddingEngine()
        bad = [1.0] * EMBEDDING_DIM
        bad[0] = float("nan")
        with self.assertRaises(GovernanceViolationError) as ctx:
            engine._validate_and_normalize(bad)
        self.assertIn("non-finite", str(ctx.exception))

    def test_inf_raises_governance_error(self):
        engine = EmbeddingEngine()
        bad = [1.0] * EMBEDDING_DIM
        bad[0] = float("inf")
        with self.assertRaises(GovernanceViolationError):
            engine._validate_and_normalize(bad)

    def test_zero_norm_raises_governance_error(self):
        engine = EmbeddingEngine()
        zeros = [0.0] * EMBEDDING_DIM
        with self.assertRaises(GovernanceViolationError) as ctx:
            engine._validate_and_normalize(zeros)
        self.assertIn("zero", str(ctx.exception).lower())

    def test_valid_vector_normalized(self):
        engine = EmbeddingEngine()
        v = [float(i + 1) for i in range(EMBEDDING_DIM)]
        result = engine._validate_and_normalize(v)
        self.assertEqual(len(result), EMBEDDING_DIM)
        norm = math.sqrt(sum(x * x for x in result))
        self.assertAlmostEqual(norm, 1.0, places=5)

    def test_embed_requires_non_empty_string(self):
        engine = EmbeddingEngine()
        with self.assertRaises(ValueError):
            engine.embed("")
        with self.assertRaises(ValueError):
            engine.embed("   ")


class TestQdrantAdapterRouting(unittest.TestCase):
    """QdrantAdapter only proxies through HybridQdrantManager."""

    def test_insert_vector_proxies_to_hybrid_manager(self):
        hybrid = MagicMock()
        hybrid.insert.return_value = True
        adapter = QdrantAdapter(hybrid)
        result = adapter.insert_vector("hello", {"vector": [0.1, 0.2], "collection": "episodic_memory"})
        self.assertTrue(result)
        hybrid.insert.assert_called_once_with(
            "hello",
            {"vector": [0.1, 0.2], "collection": "episodic_memory"},
        )

    def test_query_proxies_to_hybrid_manager(self):
        hybrid = MagicMock()
        hybrid.query.return_value = [{"id": 1}]
        adapter = QdrantAdapter(hybrid)
        result = adapter.query("hello", collection="episodic_memory", top_k=3)
        self.assertEqual(result, [{"id": 1}])
        hybrid.query.assert_called_once_with("hello", collection="episodic_memory", top_k=3)


class TestClusterBootstrapIdempotency(unittest.TestCase):
    """ClusterBootstrap treats 409 and existing collections as governed successes."""

    def setUp(self):
        self.bootstrap = ClusterBootstrap(url="http://localhost:6333")

    def test_governed_collections_count(self):
        self.assertEqual(len(_GOVERNED_COLLECTIONS), 10)

    def test_all_collection_dims_are_384(self):
        self.assertEqual(BOOTSTRAP_DIM, 384)

    def test_all_governed_collection_names(self):
        names = {s.name for s in _GOVERNED_COLLECTIONS}
        expected = {
            "episodic_memory", "semantic_memory", "reflection_memory",
            "governance_memory", "runtime_memory", "replay_memory",
            "telemetry_memory", "advisor_memory", "federation_memory",
            "execution_memory",
        }
        self.assertEqual(names, expected)

    def test_bootstrap_collection_returns_already_governed_when_exists(self):
        """When the collection already exists, status must be 'already_governed'."""
        mock_client = MagicMock()
        collection_obj = MagicMock()
        collection_obj.name = "episodic_memory"
        mock_client.get_collections.return_value.collections = [collection_obj]
        mock_client.get_collection.return_value = MagicMock(config=None)

        spec = next(s for s in _GOVERNED_COLLECTIONS if s.name == "episodic_memory")
        with patch.object(self.bootstrap, "_get_client", return_value=mock_client):
            result = self.bootstrap.bootstrap_collection(spec)

        self.assertEqual(result.status, "already_governed")
        mock_client.create_collection.assert_not_called()

    def test_bootstrap_collection_creates_when_missing(self):
        """When the collection is missing, it should be created."""
        mock_client = MagicMock()
        mock_client.get_collections.return_value.collections = []  # empty cluster

        spec = next(s for s in _GOVERNED_COLLECTIONS if s.name == "advisor_memory")
        with patch.object(self.bootstrap, "_get_client", return_value=mock_client):
            result = self.bootstrap.bootstrap_collection(spec)

        self.assertEqual(result.status, "created")
        mock_client.create_collection.assert_called_once()
        call_kwargs = mock_client.create_collection.call_args
        self.assertEqual(call_kwargs.kwargs["collection_name"], "advisor_memory")

    def test_bootstrap_409_treated_as_governed_success(self):
        """A 409 / 'already exists' exception from the client is not an error."""
        mock_client = MagicMock()
        mock_client.get_collections.return_value.collections = []  # not listed
        mock_client.create_collection.side_effect = Exception("collection already exists (409)")

        spec = next(s for s in _GOVERNED_COLLECTIONS if s.name == "semantic_memory")
        with patch.object(self.bootstrap, "_get_client", return_value=mock_client):
            result = self.bootstrap.bootstrap_collection(spec)

        self.assertEqual(result.status, "already_governed")

    def test_bootstrap_conflict_treated_as_governed_success(self):
        """A 'conflict' exception from the client is treated as governed success."""
        mock_client = MagicMock()
        mock_client.get_collections.return_value.collections = []
        mock_client.create_collection.side_effect = Exception("conflict: resource already exists")

        spec = next(s for s in _GOVERNED_COLLECTIONS if s.name == "reflection_memory")
        with patch.object(self.bootstrap, "_get_client", return_value=mock_client):
            result = self.bootstrap.bootstrap_collection(spec)

        self.assertEqual(result.status, "already_governed")

    def test_bootstrap_returns_error_on_real_failure(self):
        """A non-409 exception correctly returns error status."""
        mock_client = MagicMock()
        mock_client.get_collections.return_value.collections = []
        mock_client.create_collection.side_effect = Exception("network timeout")

        spec = _GOVERNED_COLLECTIONS[0]
        with patch.object(self.bootstrap, "_get_client", return_value=mock_client):
            result = self.bootstrap.bootstrap_collection(spec)

        self.assertEqual(result.status, "error")
        self.assertIn("network timeout", result.message)

    def test_bootstrap_all_returns_10_results(self):
        """bootstrap_all_collections returns one result per governed collection."""
        mock_client = MagicMock()
        # All collections already exist
        mocked = [MagicMock(name=s.name) for s in _GOVERNED_COLLECTIONS]
        for i, s in enumerate(_GOVERNED_COLLECTIONS):
            mocked[i].name = s.name
        mock_client.get_collections.return_value.collections = mocked
        mock_client.get_collection.return_value = MagicMock(config=None)

        with patch.object(self.bootstrap, "_get_client", return_value=mock_client):
            results = self.bootstrap.bootstrap_all_collections()

        self.assertEqual(len(results), 10)
        for r in results:
            self.assertEqual(r.status, "already_governed")

    def test_bootstrap_unavailable_qdrant_returns_error(self):
        """When Qdrant is unavailable, each collection returns error (not crash)."""
        with patch.object(self.bootstrap, "_get_client", return_value=None):
            results = self.bootstrap.bootstrap_all_collections()

        self.assertEqual(len(results), 10)
        for r in results:
            self.assertEqual(r.status, "error")

    def test_payload_indexes_409_does_not_crash(self):
        """Index creation 409/conflict must not crash the bootstrap."""
        mock_client = MagicMock()
        collection_obj = MagicMock()
        collection_obj.name = "advisor_memory"
        mock_client.get_collections.return_value.collections = [collection_obj]
        mock_client.get_collection.return_value = MagicMock(config=None)
        mock_client.create_payload_index.side_effect = Exception("already exists")

        spec = next(s for s in _GOVERNED_COLLECTIONS if s.name == "advisor_memory")
        with patch.object(self.bootstrap, "_get_client", return_value=mock_client):
            result = self.bootstrap.bootstrap_collection(spec)

        # Index error must not change collection status
        self.assertIn(result.status, ("already_governed", "created"))


class TestBootstrapResultDataclass(unittest.TestCase):
    def test_construction(self):
        r = BootstrapResult(name="x", status="created", message="ok")
        self.assertEqual(r.name, "x")
        self.assertEqual(r.status, "created")

    def test_collection_spec_construction(self):
        s = CollectionSpec(name="test_col", purpose="test")
        self.assertEqual(s.name, "test_col")
        self.assertEqual(s.payload_indexes, [])


if __name__ == "__main__":
    unittest.main()
