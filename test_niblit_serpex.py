"""
test_niblit_serpex.py — Unit tests for the Niblit-integrated Serpex system.

Covers:
  - niblit_tools/serpex_api.py  (SerpexAPI, niblit_serpex_search, NIBLIT_SERPEX_TOOL)
  - niblit_agents/research_agent.py  (ResearchAgent)
  - niblit_memory/knowledge_store.py  (KnowledgeStore)
  - niblit_brain.py  (NiblitBrain tool wiring)

All HTTP / Qdrant / SQLite calls are mocked — no live services required.

Run with::

    pytest test_niblit_serpex.py -v
"""

import os
import sqlite3
import tempfile
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _serpex_response(items=None):
    """Build a minimal Serpex API response."""
    return {
        "results": items or [
            {"title": "Python Asyncio", "url": "https://example.com/1", "snippet": "asyncio intro"},
            {"title": "Async patterns",  "url": "https://example.com/2", "snippet": "async patterns"},
        ]
    }


# ─────────────────────────────────────────────────────────────────────────────
# SerpexAPI
# ─────────────────────────────────────────────────────────────────────────────

class TestSerpexAPI:
    def test_raises_without_key(self, monkeypatch):
        monkeypatch.delenv("SERPEX_API_KEY", raising=False)
        from niblit_tools.serpex_api import SerpexAPI
        with pytest.raises(ValueError, match="SERPEX_API_KEY"):
            SerpexAPI(api_key=None)

    def test_accepts_explicit_key(self):
        from niblit_tools.serpex_api import SerpexAPI
        api = SerpexAPI(api_key="test-key")
        assert api.api_key == "test-key"

    def test_reads_key_from_env(self, monkeypatch):
        monkeypatch.setenv("SERPEX_API_KEY", "env-key")
        from niblit_tools.serpex_api import SerpexAPI
        api = SerpexAPI()
        assert api.api_key == "env-key"

    def test_search_web_returns_dict(self, monkeypatch):
        monkeypatch.setenv("SERPEX_API_KEY", "key")
        from niblit_tools.serpex_api import SerpexAPI
        api = SerpexAPI()
        mock_resp = MagicMock()
        mock_resp.json.return_value = _serpex_response()
        mock_resp.raise_for_status = MagicMock()
        with patch("niblit_tools.serpex_api.requests.get", return_value=mock_resp) as mock_get:
            result = api.search("python asyncio")
        mock_get.assert_called_once()
        assert "results" in result

    def test_search_includes_bearer_auth(self, monkeypatch):
        monkeypatch.setenv("SERPEX_API_KEY", "my-secret")
        from niblit_tools.serpex_api import SerpexAPI
        api = SerpexAPI()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        with patch("niblit_tools.serpex_api.requests.get", return_value=mock_resp) as mock_get:
            api.search("test")
        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer my-secret"

    def test_search_web_passes_time_range(self, monkeypatch):
        monkeypatch.setenv("SERPEX_API_KEY", "key")
        from niblit_tools.serpex_api import SerpexAPI
        api = SerpexAPI()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        with patch("niblit_tools.serpex_api.requests.get", return_value=mock_resp) as mock_get:
            api.search("test", category="web", time_range="week")
        params = mock_get.call_args[1]["params"]
        assert params.get("time_range") == "week"

    def test_search_news_omits_time_range(self, monkeypatch):
        monkeypatch.setenv("SERPEX_API_KEY", "key")
        from niblit_tools.serpex_api import SerpexAPI
        api = SerpexAPI()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        with patch("niblit_tools.serpex_api.requests.get", return_value=mock_resp) as mock_get:
            api.search("test", category="news")
        params = mock_get.call_args[1]["params"]
        assert "time_range" not in params

    def test_search_returns_error_on_exception(self, monkeypatch):
        monkeypatch.setenv("SERPEX_API_KEY", "key")
        from niblit_tools.serpex_api import SerpexAPI
        api = SerpexAPI()
        with patch("niblit_tools.serpex_api.requests.get", side_effect=ConnectionError("refused")):
            result = api.search("test")
        assert "error" in result

    def test_niblit_serpex_search_web(self, monkeypatch):
        monkeypatch.setenv("SERPEX_API_KEY", "key")
        from niblit_tools.serpex_api import niblit_serpex_search
        mock_agent = MagicMock()
        mock_agent.search_web.return_value = [{"title": "t", "url": "u", "snippet": "s"}]
        with patch("niblit_tools.serpex_api._ResearchAgent", return_value=mock_agent):
            result = niblit_serpex_search("python", "web")
        mock_agent.search_web.assert_called_once_with("python")
        assert result[0]["title"] == "t"

    def test_niblit_serpex_search_news(self, monkeypatch):
        monkeypatch.setenv("SERPEX_API_KEY", "key")
        from niblit_tools.serpex_api import niblit_serpex_search
        mock_agent = MagicMock()
        mock_agent.search_news.return_value = [{"title": "news"}]
        with patch("niblit_tools.serpex_api._ResearchAgent", return_value=mock_agent):
            result = niblit_serpex_search("AI", "news")
        mock_agent.search_news.assert_called_once_with("AI")

    def test_niblit_serpex_tool_definition(self):
        from niblit_tools.serpex_api import NIBLIT_SERPEX_TOOL
        assert NIBLIT_SERPEX_TOOL["name"] == "niblit_serpex_search"
        assert "query" in NIBLIT_SERPEX_TOOL["parameters"]["properties"]
        assert "query" in NIBLIT_SERPEX_TOOL["parameters"]["required"]

    def test_niblit_serpex_search_error_handling(self, monkeypatch):
        """niblit_serpex_search returns error dict on exception."""
        monkeypatch.setenv("SERPEX_API_KEY", "key")
        from niblit_tools.serpex_api import niblit_serpex_search
        with patch("niblit_tools.serpex_api._ResearchAgent", side_effect=RuntimeError("boom")):
            result = niblit_serpex_search("test")
        assert result[0].get("error")


# ─────────────────────────────────────────────────────────────────────────────
# ResearchAgent
# ─────────────────────────────────────────────────────────────────────────────

class TestResearchAgent:
    def _make_agent(self, serpex_key="test-key"):
        from niblit_agents.research_agent import ResearchAgent
        return ResearchAgent(serpex_api_key=serpex_key)

    def test_search_web_returns_list(self):
        agent = self._make_agent()
        mock_api = MagicMock()
        mock_api.search.return_value = _serpex_response()
        agent._serpex = mock_api
        agent._knowledge_store = MagicMock()
        results = agent.search_web("asyncio")
        assert isinstance(results, list)
        assert results[0]["title"] == "Python Asyncio"

    def test_search_news_uses_google_engine(self):
        agent = self._make_agent()
        mock_api = MagicMock()
        mock_api.search.return_value = _serpex_response()
        agent._serpex = mock_api
        agent._knowledge_store = MagicMock()
        agent.search_news("AI trends")
        call_kwargs = mock_api.search.call_args[1]
        assert call_kwargs["category"] == "news"
        assert call_kwargs["engine"] == "google"

    def test_process_results_normalises_items(self):
        agent = self._make_agent()
        agent._knowledge_store = MagicMock()
        data = {
            "results": [
                {"title": "T1", "url": "http://a.com", "snippet": "snip1"},
                {"title": "T2", "link": "http://b.com", "description": "snip2"},
            ]
        }
        extracted = agent._process_results(data, query="test")
        assert len(extracted) == 2
        assert extracted[0]["url"] == "http://a.com"
        assert extracted[1]["url"] == "http://b.com"

    def test_process_results_stores_in_knowledge_store(self):
        agent = self._make_agent()
        mock_ks = MagicMock()
        agent._knowledge_store = mock_ks
        agent._process_results(_serpex_response(), query="asyncio")
        mock_ks.store_search_results.assert_called_once()

    def test_process_results_error_response(self):
        agent = self._make_agent()
        agent._knowledge_store = MagicMock()
        result = agent._process_results({"error": "API failed"})
        assert result[0].get("error") == "API failed"

    def test_process_results_embeds_to_qdrant(self):
        """When a vector_store is present, snippets are embedded."""
        agent = self._make_agent()
        mock_vs = MagicMock()
        agent._vector_store = mock_vs
        agent._knowledge_store = MagicMock()
        agent._process_results(_serpex_response(), query="test")
        # add() should be called for each item with a snippet
        assert mock_vs.add.call_count >= 1

    def test_process_results_skips_empty_snippets(self):
        """Items with no extractable text are not embedded."""
        agent = self._make_agent()
        mock_vs = MagicMock()
        agent._vector_store = mock_vs
        agent._knowledge_store = MagicMock()
        data = {"results": [{"title": "No text"}]}
        agent._process_results(data, query="test")
        mock_vs.add.assert_not_called()

    def test_knowledge_store_not_required(self):
        """ResearchAgent works fine with no KnowledgeStore."""
        agent = self._make_agent()
        mock_api = MagicMock()
        mock_api.search.return_value = _serpex_response()
        agent._serpex = mock_api
        agent._knowledge_store = None
        # Should not raise even if no KnowledgeStore and no VectorStore
        with patch.object(agent, "_knowledge_store_client", return_value=None):
            results = agent.search_web("test")
        assert isinstance(results, list)


# ─────────────────────────────────────────────────────────────────────────────
# KnowledgeStore
# ─────────────────────────────────────────────────────────────────────────────

class TestKnowledgeStore:
    def _make_store(self, tmp_path):
        from niblit_memory.knowledge_store import KnowledgeStore
        return KnowledgeStore(db_path=str(tmp_path / "test.sqlite"))

    def test_store_and_retrieve(self, tmp_path):
        ks = self._make_store(tmp_path)
        results = [
            {"title": "T1", "url": "http://x.com", "snippet": "hello world"},
            {"title": "T2", "url": "http://y.com", "snippet": "foo bar"},
        ]
        ks.store_search_results("test query", results)
        rows = ks.get_by_source("serpex")
        assert len(rows) == 2
        keys = {r["key"] for r in rows}
        assert keys == {"http://x.com", "http://y.com"}

    def test_url_used_as_key(self, tmp_path):
        ks = self._make_store(tmp_path)
        ks.store_search_results("q", [{"title": "A", "url": "http://a.com", "snippet": "text"}])
        rows = ks.get_by_source("serpex")
        assert rows[0]["key"] == "http://a.com"

    def test_upsert_on_duplicate_url(self, tmp_path):
        ks = self._make_store(tmp_path)
        item = {"title": "X", "url": "http://dup.com", "snippet": "first"}
        ks.store_search_results("q", [item])
        item["snippet"] = "updated"
        ks.store_search_results("q", [item])
        rows = ks.get_by_source("serpex")
        assert len(rows) == 1  # upsert, not duplicate

    def test_empty_results_no_error(self, tmp_path):
        ks = self._make_store(tmp_path)
        ks.store_search_results("q", [])  # must not raise

    def test_error_items_skipped(self, tmp_path):
        ks = self._make_store(tmp_path)
        ks.store_search_results("q", [{"error": "API failed"}])
        rows = ks.get_by_source("serpex")
        assert len(rows) == 0

    def test_hash_key_when_no_url(self, tmp_path):
        ks = self._make_store(tmp_path)
        ks.store_search_results("q", [{"title": "No URL", "snippet": "some text"}])
        rows = ks.get_by_source("serpex")
        assert len(rows) == 1
        assert rows[0]["key"].startswith("sha:")

    def test_qdrant_embed_called_on_store(self, tmp_path):
        """store_search_results triggers _embed_to_qdrant with stored rows."""
        from niblit_memory.knowledge_store import KnowledgeStore
        ks = KnowledgeStore(db_path=str(tmp_path / "ks.sqlite"))
        mock_vs = MagicMock()
        ks._vector_store = mock_vs
        ks.store_search_results("q", [{"url": "u", "snippet": "text"}])
        mock_vs.add.assert_called_once()

    def test_qdrant_embed_not_called_when_no_vs(self, tmp_path):
        ks = self._make_store(tmp_path)
        ks._vector_store = None
        # Should not raise
        ks.store_search_results("q", [{"url": "u", "snippet": "text"}])

    def test_get_by_source_limit(self, tmp_path):
        ks = self._make_store(tmp_path)
        items = [{"url": f"http://x{i}.com", "snippet": f"text{i}"} for i in range(10)]
        ks.store_search_results("q", items)
        rows = ks.get_by_source("serpex", limit=3)
        assert len(rows) == 3


# ─────────────────────────────────────────────────────────────────────────────
# NiblitBrain tool wiring
# ─────────────────────────────────────────────────────────────────────────────

class TestNiblitBrainToolWiring:
    def _make_brain(self):
        from niblit_brain import NiblitBrain
        memory = MagicMock()
        memory.get_preferences.return_value = {}
        memory.store_preferences = MagicMock()
        memory.add_fact = MagicMock()
        memory.recall = MagicMock(return_value=[])
        return NiblitBrain(memory, llm_enabled=False, enable_improvements=False)

    def test_serpex_tool_fn_attribute_exists(self):
        brain = self._make_brain()
        assert hasattr(brain, "serpex_tool_fn")

    def test_serpex_tool_def_attribute_exists(self):
        brain = self._make_brain()
        assert hasattr(brain, "serpex_tool_def")

    def test_get_tools_returns_list(self):
        brain = self._make_brain()
        tools = brain.get_tools()
        assert isinstance(tools, list)

    def test_get_tools_contains_serpex_tool(self):
        brain = self._make_brain()
        tools = brain.get_tools()
        names = [t["name"] for t in tools if isinstance(t, dict)]
        assert "niblit_serpex_search" in names

    def test_serpex_tool_fn_is_callable(self):
        brain = self._make_brain()
        # When the tool is available it should be callable
        if brain.serpex_tool_fn is not None:
            assert callable(brain.serpex_tool_fn)

    def test_serpex_tool_def_has_required_keys(self):
        brain = self._make_brain()
        if brain.serpex_tool_def is not None:
            assert "name" in brain.serpex_tool_def
            assert "parameters" in brain.serpex_tool_def
