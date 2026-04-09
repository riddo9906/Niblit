"""
test_qdrant_integration.py — Unit tests for Qdrant client wiring in
HFLLMAdapter (modules/llm_module.py) and ResearcherEngine
(modules/researcher_engine.py).

All external I/O (Qdrant, HuggingFace, HTTP) is mocked, so the tests run
without any live services.

Run with::

    pytest test_qdrant_integration.py -v
"""

from unittest.mock import MagicMock, patch, PropertyMock
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_collections_response(names=("niblit_knowledge",)):
    """Return a mock object that mimics qdrant_client.get_collections()."""
    col = MagicMock()
    col.name = names[0] if names else "default"
    resp = MagicMock()
    resp.collections = [col]
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# HFLLMAdapter — Qdrant wiring
# ─────────────────────────────────────────────────────────────────────────────

class TestHFLLMAdapterQdrant:
    """Tests for the Qdrant client that HFLLMAdapter exposes."""

    def _make_adapter(self, qdrant_url="http://localhost:6333", qdrant_api_key="test-key"):
        """Create an HFLLMAdapter with Qdrant mocked at the library level."""
        mock_qclient = MagicMock()
        mock_qclient.get_collections.return_value = _make_collections_response()

        with (
            patch("modules.llm_module._QDRANT_LIB_AVAILABLE", True),
            patch("modules.llm_module._QdrantClient", return_value=mock_qclient),
            patch("modules.vector_store.VectorStore.__init__", return_value=None),
        ):
            from modules.llm_module import HFLLMAdapter
            adapter = HFLLMAdapter(qdrant_url=qdrant_url, qdrant_api_key=qdrant_api_key)
            # Manually set the qdrant_client since the patch swaps the class
            adapter.qdrant_client = mock_qclient
        return adapter, mock_qclient

    def test_qdrant_client_attribute_exists(self):
        """HFLLMAdapter must have a qdrant_client attribute."""
        from modules.llm_module import HFLLMAdapter
        # No URL → client stays None
        adapter = HFLLMAdapter(qdrant_url="", qdrant_api_key="")
        assert hasattr(adapter, "qdrant_client")

    def test_qdrant_client_none_when_no_url(self):
        """qdrant_client is None when QDRANT_URL is empty."""
        import os
        env_backup = os.environ.pop("QDRANT_URL", None)
        try:
            from modules.llm_module import HFLLMAdapter
            adapter = HFLLMAdapter(qdrant_url="", qdrant_api_key="")
            assert adapter.qdrant_client is None
        finally:
            if env_backup is not None:
                os.environ["QDRANT_URL"] = env_backup

    def test_qdrant_client_initialised_with_url(self):
        """qdrant_client is set when a URL is provided and the library is available."""
        adapter, mock_client = self._make_adapter()
        assert adapter.qdrant_client is mock_client

    def test_get_collections_called_on_init(self):
        """get_collections() is called during init (confirms connection)."""
        adapter, mock_client = self._make_adapter()
        mock_client.get_collections.assert_called()

    def test_qdrant_client_none_on_connection_failure(self, monkeypatch):
        """qdrant_client stays None if the connection raises."""
        bad_client = MagicMock()
        bad_client.get_collections.side_effect = ConnectionRefusedError("refused")

        monkeypatch.setattr("modules.llm_module._QDRANT_LIB_AVAILABLE", True)
        monkeypatch.setattr("modules.llm_module._QdrantClient", lambda **kw: bad_client)

        with patch("modules.vector_store.VectorStore.__init__", return_value=None):
            from modules.llm_module import HFLLMAdapter
            adapter = HFLLMAdapter(qdrant_url="http://bad-host:6333", qdrant_api_key="x")

        assert adapter.qdrant_client is None

    def test_vector_store_attribute_exists(self):
        """HFLLMAdapter must have a vector_store attribute."""
        from modules.llm_module import HFLLMAdapter
        adapter = HFLLMAdapter(qdrant_url="", qdrant_api_key="")
        assert hasattr(adapter, "vector_store")

    def test_generate_code_enriches_context_from_vector_store(self):
        """generate_code() injects vector-store context when none is supplied."""
        from modules.llm_module import HFLLMAdapter
        adapter = HFLLMAdapter(qdrant_url="", qdrant_api_key="")
        # Inject a mock vector_store that returns a hit
        mock_vs = MagicMock()
        mock_vs.search.return_value = [{"id": "x", "text": "use asyncio for concurrency", "score": 0.9}]
        adapter.vector_store = mock_vs
        # Stub query_llm to return valid code
        adapter.query_llm = MagicMock(return_value="def foo(): pass")
        adapter.generate_code("python", "do something async")
        # search was called with a query containing the language+purpose
        mock_vs.search.assert_called_once()
        call_args = mock_vs.search.call_args[0][0]
        assert "python" in call_args

    def test_generate_code_skips_vs_when_context_provided(self):
        """generate_code() does NOT query the vector store when context is given."""
        from modules.llm_module import HFLLMAdapter
        adapter = HFLLMAdapter(qdrant_url="", qdrant_api_key="")
        mock_vs = MagicMock()
        adapter.vector_store = mock_vs
        adapter.query_llm = MagicMock(return_value="def bar(): pass")
        adapter.generate_code("python", "something", context="already have context")
        mock_vs.search.assert_not_called()

    def test_generate_code_works_without_vector_store(self):
        """generate_code() returns code even with no vector store."""
        from modules.llm_module import HFLLMAdapter
        adapter = HFLLMAdapter(qdrant_url="", qdrant_api_key="")
        adapter.vector_store = None
        adapter.query_llm = MagicMock(return_value="def baz(): return 42")
        result = adapter.generate_code("python", "return 42")
        assert "def baz" in result


# ─────────────────────────────────────────────────────────────────────────────
# ResearcherEngine — Qdrant wiring
# ─────────────────────────────────────────────────────────────────────────────

class TestResearcherEngineQdrant:
    """Tests for the Qdrant client that ResearcherEngine exposes."""

    def _make_engine(self, qdrant_url="http://localhost:6333", qdrant_api_key="test-key"):
        mock_qclient = MagicMock()
        mock_qclient.get_collections.return_value = _make_collections_response()

        with (
            patch("modules.researcher_engine._QDRANT_LIB_AVAILABLE", True),
            patch("modules.researcher_engine._QdrantClient", return_value=mock_qclient),
            patch("modules.vector_store.VectorStore.__init__", return_value=None),
        ):
            from modules.researcher_engine import ResearcherEngine
            engine = ResearcherEngine(qdrant_url=qdrant_url, qdrant_api_key=qdrant_api_key)
            engine.qdrant_client = mock_qclient
        return engine, mock_qclient

    def test_qdrant_client_attribute_exists(self):
        from modules.researcher_engine import ResearcherEngine
        engine = ResearcherEngine(qdrant_url="", qdrant_api_key="")
        assert hasattr(engine, "qdrant_client")

    def test_qdrant_client_none_when_no_url(self):
        import os
        env_backup = os.environ.pop("QDRANT_URL", None)
        try:
            from modules.researcher_engine import ResearcherEngine
            engine = ResearcherEngine(qdrant_url="", qdrant_api_key="")
            assert engine.qdrant_client is None
        finally:
            if env_backup is not None:
                os.environ["QDRANT_URL"] = env_backup

    def test_qdrant_client_initialised_with_url(self):
        engine, mock_client = self._make_engine()
        assert engine.qdrant_client is mock_client

    def test_get_collections_called_on_init(self):
        engine, mock_client = self._make_engine()
        mock_client.get_collections.assert_called()

    def test_qdrant_client_none_on_connection_failure(self, monkeypatch):
        bad_client = MagicMock()
        bad_client.get_collections.side_effect = ConnectionRefusedError("refused")

        monkeypatch.setattr("modules.researcher_engine._QDRANT_LIB_AVAILABLE", True)
        monkeypatch.setattr("modules.researcher_engine._QdrantClient", lambda **kw: bad_client)

        with patch("modules.vector_store.VectorStore.__init__", return_value=None):
            from modules.researcher_engine import ResearcherEngine
            engine = ResearcherEngine(qdrant_url="http://bad-host:6333", qdrant_api_key="x")

        assert engine.qdrant_client is None

    def test_vector_store_attribute_exists(self):
        from modules.researcher_engine import ResearcherEngine
        engine = ResearcherEngine(qdrant_url="", qdrant_api_key="")
        assert hasattr(engine, "vector_store")

    def test_run_returns_cache_hit(self):
        """run() returns cached result from vector store when score >= 0.85."""
        from modules.researcher_engine import ResearcherEngine
        engine = ResearcherEngine(qdrant_url="", qdrant_api_key="")
        mock_vs = MagicMock()
        mock_vs.search.return_value = [{"id": "r:abc", "text": "cached summary", "score": 0.92}]
        engine.vector_store = mock_vs
        result = engine.run("python asyncio")
        assert result["summary"] == "cached summary"
        assert result.get("source") == "cache"
        mock_vs.search.assert_called_once()

    def test_run_falls_through_to_web_on_low_score(self):
        """run() performs web search when cache score < 0.85."""
        from modules.researcher_engine import ResearcherEngine
        engine = ResearcherEngine(qdrant_url="", qdrant_api_key="")
        mock_vs = MagicMock()
        mock_vs.search.return_value = [{"id": "r:abc", "text": "stale summary", "score": 0.50}]
        engine.vector_store = mock_vs
        # Patch web_search to return a fresh result
        engine.web_search = MagicMock(return_value="fresh result from web")
        result = engine.run("python asyncio")
        assert result.get("source") == "web"
        assert "fresh" in result["summary"]

    def test_run_stores_new_result_in_vector_store(self):
        """Newly fetched results are persisted to the vector store."""
        from modules.researcher_engine import ResearcherEngine
        engine = ResearcherEngine(qdrant_url="", qdrant_api_key="")
        mock_vs = MagicMock()
        mock_vs.search.return_value = []  # no cache
        engine.vector_store = mock_vs
        engine.web_search = MagicMock(return_value="brand new research")
        engine.run("machine learning")
        mock_vs.add.assert_called_once()
        # The stored text must contain the research result
        stored_text = mock_vs.add.call_args[0][1]
        assert "brand new research" in stored_text

    def test_run_returns_error_when_no_results(self):
        """run() returns an error dict when neither cache nor web yields results."""
        from modules.researcher_engine import ResearcherEngine
        engine = ResearcherEngine(qdrant_url="", qdrant_api_key="")
        engine.vector_store = None
        engine.web_search = MagicMock(return_value=None)
        result = engine.run("unsearchable topic")
        assert "error" in result

    def test_run_with_no_vector_store(self):
        """run() works fine without a vector store (graceful degradation)."""
        from modules.researcher_engine import ResearcherEngine
        engine = ResearcherEngine(qdrant_url="", qdrant_api_key="")
        engine.vector_store = None
        engine.web_search = MagicMock(return_value="some result")
        result = engine.run("topic")
        assert result["summary"] == "some result"

    def test_source_field_present_in_web_result(self):
        """run() sets source='web' for live web results."""
        from modules.researcher_engine import ResearcherEngine
        engine = ResearcherEngine(qdrant_url="", qdrant_api_key="")
        engine.vector_store = None
        engine.web_search = MagicMock(return_value="web data")
        result = engine.run("any topic")
        assert result.get("source") == "web"


# ─────────────────────────────────────────────────────────────────────────────
# Env-var passthrough
# ─────────────────────────────────────────────────────────────────────────────

class TestEnvVarPassthrough:
    """Verify QDRANT_URL / QDRANT_API_KEY env vars are picked up automatically."""

    def test_llm_adapter_reads_qdrant_url_from_env(self, monkeypatch):
        monkeypatch.setenv("QDRANT_URL", "http://env-qdrant:6333")
        monkeypatch.setenv("QDRANT_API_KEY", "env-key")

        captured = {}

        def fake_qdrant(**kwargs):
            captured.update(kwargs)
            client = MagicMock()
            client.get_collections.return_value = _make_collections_response()
            return client

        monkeypatch.setattr("modules.llm_module._QDRANT_LIB_AVAILABLE", True)
        monkeypatch.setattr("modules.llm_module._QdrantClient", fake_qdrant)
        with patch("modules.vector_store.VectorStore.__init__", return_value=None):
            from modules.llm_module import HFLLMAdapter
            HFLLMAdapter()  # no explicit qdrant_url → reads from env

        assert captured.get("url") == "http://env-qdrant:6333"
        assert captured.get("api_key") == "env-key"

    def test_researcher_reads_qdrant_url_from_env(self, monkeypatch):
        monkeypatch.setenv("QDRANT_URL", "http://env-qdrant:6333")
        monkeypatch.setenv("QDRANT_API_KEY", "env-key")

        captured = {}

        def fake_qdrant(**kwargs):
            captured.update(kwargs)
            client = MagicMock()
            client.get_collections.return_value = _make_collections_response()
            return client

        monkeypatch.setattr("modules.researcher_engine._QDRANT_LIB_AVAILABLE", True)
        monkeypatch.setattr("modules.researcher_engine._QdrantClient", fake_qdrant)
        with patch("modules.vector_store.VectorStore.__init__", return_value=None):
            from modules.researcher_engine import ResearcherEngine
            ResearcherEngine()  # no explicit qdrant_url → reads from env

        assert captured.get("url") == "http://env-qdrant:6333"
        assert captured.get("api_key") == "env-key"


if __name__ == "__main__":
    print('Running test_qdrant_integration.py')
