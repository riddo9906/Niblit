"""
test_searchcode_search.py — Unit tests for modules/searchcode_search.py

All HTTP I/O is mocked so tests run without any network access.

Run with::

    pytest test_searchcode_search.py -v
"""

import json
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sc(**kwargs):
    """Return a SearchcodeSearch instance with defaults (prefer_mcp=False)."""
    from modules.searchcode_search import SearchcodeSearch
    return SearchcodeSearch(prefer_mcp=kwargs.pop("prefer_mcp", False), **kwargs)


def _rest_response(items):
    """Build a mock requests.Response for the REST codesearch endpoint."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"results": items}
    mock_resp.raise_for_status = lambda: None
    return mock_resp


def _mcp_response(content_blocks):
    """Build a mock requests.Response for MCP tools/call."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": content_blocks},
    }
    mock_resp.raise_for_status = lambda: None
    return mock_resp


# ---------------------------------------------------------------------------
# availability
# ---------------------------------------------------------------------------

class TestAvailability:
    def test_is_always_available(self):
        sc = _make_sc()
        assert sc.is_available() is True

    def test_mcp_available_when_ping_succeeds(self):
        sc = _make_sc()
        with patch("modules.searchcode_search.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_post.return_value = mock_resp
            assert sc.mcp_is_available() is True

    def test_mcp_unavailable_when_ping_fails(self):
        sc = _make_sc()
        with patch("modules.searchcode_search.requests.post", side_effect=Exception("timeout")):
            assert sc.mcp_is_available() is False

    def test_mcp_probe_is_cached(self):
        sc = _make_sc()
        with patch("modules.searchcode_search.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            sc.mcp_is_available()
            sc.mcp_is_available()
        assert mock_post.call_count == 1  # cached after first probe


# ---------------------------------------------------------------------------
# REST search
# ---------------------------------------------------------------------------

class TestRestSearch:
    def _rest_item(self, filename="foo.py", lang="Python", code="import os", url="http://example.com/foo.py"):
        return {
            "filename": filename,
            "language": lang,
            "lines": {"1": code},
            "url": url,
            "repo": "test/repo",
        }

    def test_returns_results(self):
        sc = _make_sc()
        items = [self._rest_item(), self._rest_item(filename="bar.py")]
        with patch("modules.searchcode_search.requests.get", return_value=_rest_response(items)):
            results = sc._rest_search("asyncio example", language="python", max_results=5)
        assert len(results) == 2
        assert results[0]["source"] == "searchcode_rest"

    def test_result_has_required_keys(self):
        sc = _make_sc()
        items = [self._rest_item()]
        with patch("modules.searchcode_search.requests.get", return_value=_rest_response(items)):
            results = sc._rest_search("test", max_results=5)
        r = results[0]
        assert "text" in r
        assert "url" in r
        assert "filename" in r
        assert "source" in r

    def test_respects_max_results(self):
        sc = _make_sc()
        items = [self._rest_item(filename=f"f{i}.py") for i in range(10)]
        with patch("modules.searchcode_search.requests.get", return_value=_rest_response(items)):
            results = sc._rest_search("test", max_results=3)
        assert len(results) <= 3

    def test_graceful_on_request_failure(self):
        sc = _make_sc()
        with patch("modules.searchcode_search.requests.get", side_effect=Exception("network error")):
            results = sc._rest_search("test")
        assert results == []

    def test_handles_empty_results(self):
        sc = _make_sc()
        with patch("modules.searchcode_search.requests.get", return_value=_rest_response([])):
            results = sc._rest_search("no results")
        assert results == []

    def test_text_truncated_to_max_fragment_length(self):
        from modules.searchcode_search import _MAX_FRAGMENT_LENGTH
        sc = _make_sc()
        long_code = "x = 1\n" * 200
        items = [self._rest_item(code=long_code)]
        with patch("modules.searchcode_search.requests.get", return_value=_rest_response(items)):
            results = sc._rest_search("test")
        if results:
            assert len(results[0]["text"]) <= _MAX_FRAGMENT_LENGTH


# ---------------------------------------------------------------------------
# MCP search
# ---------------------------------------------------------------------------

class TestMcpSearch:
    def test_returns_results_from_mcp(self):
        sc = _make_sc(prefer_mcp=True)
        sc._mcp_available = True  # skip probe
        content = [{"text": "def my_func(): pass", "url": "http://x.com/a.py", "filename": "a.py", "language": "Python"}]
        with patch("modules.searchcode_search.requests.post", return_value=_mcp_response(content)):
            results = sc._mcp_search("async python example", language="python", max_results=5)
        assert len(results) == 1
        assert results[0]["source"] == "searchcode_mcp"
        assert "my_func" in results[0]["text"]

    def test_mcp_marks_unavailable_on_failure(self):
        sc = _make_sc(prefer_mcp=True)
        sc._mcp_available = True
        with patch("modules.searchcode_search.requests.post", side_effect=Exception("err")):
            results = sc._mcp_search("test")
        assert results == []
        assert sc._mcp_available is False

    def test_mcp_skips_empty_content_blocks(self):
        sc = _make_sc(prefer_mcp=True)
        sc._mcp_available = True
        content = [{"text": ""}, {"text": "  "}, {"text": "real snippet here"}]
        with patch("modules.searchcode_search.requests.post", return_value=_mcp_response(content)):
            results = sc._mcp_search("test")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# search_code — transport selection
# ---------------------------------------------------------------------------

class TestSearchCode:
    def test_uses_rest_when_mcp_not_preferred(self):
        sc = _make_sc(prefer_mcp=False)
        with patch.object(sc, "_rest_search", return_value=[{"source": "rest"}]) as mock_rest:
            results = sc.search_code("test")
        mock_rest.assert_called_once()
        assert results[0]["source"] == "rest"

    def test_falls_back_to_rest_when_mcp_unavailable(self):
        sc = _make_sc(prefer_mcp=True)
        with patch.object(sc, "mcp_is_available", return_value=False):
            with patch.object(sc, "_rest_search", return_value=[{"source": "rest"}]) as mock_rest:
                results = sc.search_code("test")
        mock_rest.assert_called_once()

    def test_uses_mcp_when_available_and_preferred(self):
        sc = _make_sc(prefer_mcp=True)
        with patch.object(sc, "mcp_is_available", return_value=True):
            with patch.object(sc, "_mcp_search", return_value=[{"source": "mcp"}]) as mock_mcp:
                results = sc.search_code("test")
        mock_mcp.assert_called_once()

    def test_falls_back_to_rest_when_mcp_returns_empty(self):
        sc = _make_sc(prefer_mcp=True)
        with patch.object(sc, "mcp_is_available", return_value=True):
            with patch.object(sc, "_mcp_search", return_value=[]):
                with patch.object(sc, "_rest_search", return_value=[{"source": "rest"}]) as mock_rest:
                    results = sc.search_code("test")
        mock_rest.assert_called_once()

    def test_empty_query_returns_empty(self):
        sc = _make_sc()
        results = sc.search_code("")
        assert results == []


# ---------------------------------------------------------------------------
# discover_patterns
# ---------------------------------------------------------------------------

class TestDiscoverPatterns:
    def test_returns_tagged_results(self):
        sc = _make_sc()
        mock_result = [{"source": "searchcode_rest", "text": "decorator code here", "url": "http://x.com"}]
        with patch.object(sc, "search_code", return_value=mock_result):
            results = sc.discover_patterns("python", "decorator", max_results=5)
        assert all(r.get("source") == "searchcode_pattern" for r in results)
        assert all(r.get("pattern_type") == "decorator" for r in results)

    def test_deduplicates_by_url(self):
        sc = _make_sc()
        dup = {"source": "rest", "text": "same snippet", "url": "http://same.com"}
        with patch.object(sc, "search_code", return_value=[dup, dup]):
            results = sc.discover_patterns("python", "decorator", max_results=10)
        urls = [r.get("url") for r in results]
        assert len(set(urls)) == len(urls)

    def test_uses_free_text_for_unknown_pattern_type(self):
        sc = _make_sc()
        with patch.object(sc, "search_code", return_value=[]) as mock_sc:
            sc.discover_patterns("python", "unknown_pattern_xyz")
        mock_sc.assert_called()


# ---------------------------------------------------------------------------
# research_for_code_generation
# ---------------------------------------------------------------------------

class TestResearchForCodeGeneration:
    def test_returns_merged_results(self):
        sc = _make_sc()
        pattern_result = [{"source": "searchcode_pattern", "text": "pattern snippet", "url": "http://a.com"}]
        code_result = [{"source": "searchcode_rest", "text": "code snippet", "url": "http://b.com"}]
        with patch.object(sc, "discover_patterns", return_value=pattern_result):
            with patch.object(sc, "search_code", return_value=code_result):
                results = sc.research_for_code_generation("python", "asyncio", max_results=5)
        urls = {r["url"] for r in results}
        # Verify each expected origin is represented in the merged set
        assert any(u == "http://a.com" for u in urls)
        assert any(u == "http://b.com" for u in urls)

    def test_respects_max_results(self):
        sc = _make_sc()
        many = [{"source": "rest", "text": f"t{i}", "url": f"http://u{i}.com"} for i in range(10)]
        with patch.object(sc, "discover_patterns", return_value=many):
            with patch.object(sc, "search_code", return_value=many):
                results = sc.research_for_code_generation("python", "asyncio", max_results=4)
        assert len(results) <= 4


# ---------------------------------------------------------------------------
# MCP tool — niblit_searchcode
# ---------------------------------------------------------------------------

class TestMcpToolSearchcode:
    def _handler(self):
        from modules.mcp_server import NiblitMCPHandler
        h = NiblitMCPHandler()
        return h

    def _rpc(self, method, params=None):
        return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}

    def test_searchcode_tool_in_tools_list(self):
        h = self._handler()
        resp = h.handle(self._rpc("tools/list"))
        names = {t["name"] for t in resp["result"]["tools"]}
        assert "niblit_searchcode" in names

    def test_searchcode_tool_schema_has_query(self):
        h = self._handler()
        tools = h.handle(self._rpc("tools/list"))["result"]["tools"]
        sc_tool = next(t for t in tools if t["name"] == "niblit_searchcode")
        assert "query" in sc_tool["inputSchema"]["properties"]
        assert "query" in sc_tool["inputSchema"]["required"]

    def test_searchcode_tool_graceful_without_core(self):
        h = self._handler()
        resp = h.handle(self._rpc("tools/call", {
            "name": "niblit_searchcode",
            "arguments": {"query": "async python"},
        }))
        text = resp["result"]["content"][0]["text"]
        assert isinstance(text, str)

    def test_searchcode_tool_empty_query_returns_error(self):
        h = self._handler()
        resp = h.handle(self._rpc("tools/call", {
            "name": "niblit_searchcode",
            "arguments": {"query": ""},
        }))
        text = resp["result"]["content"][0]["text"]
        assert "error" in text.lower()

    def test_searchcode_tool_with_mocked_sc(self):
        h = self._handler()
        core = MagicMock()
        mock_sc = MagicMock()
        mock_sc.search_code.return_value = [
            {"filename": "foo.py", "language": "Python", "text": "import asyncio", "url": "http://x.com"}
        ]
        core.searchcode_search = mock_sc
        h.set_core(core)
        resp = h.handle(self._rpc("tools/call", {
            "name": "niblit_searchcode",
            "arguments": {"query": "asyncio python"},
        }))
        text = resp["result"]["content"][0]["text"]
        assert "foo.py" in text
        assert "asyncio" in text


# ---------------------------------------------------------------------------
# ALE wiring
# ---------------------------------------------------------------------------

class TestALESearchcodeWiring:
    def _make_ale(self, sc=None):
        from modules.autonomous_learning_engine import AutonomousLearningEngine
        core = MagicMock()
        core.searchcode_search = sc
        return AutonomousLearningEngine(core=core, searchcode_search=sc)

    def test_searchcode_search_stored_as_attribute(self):
        mock_sc = MagicMock()
        ale = self._make_ale(sc=mock_sc)
        assert ale.searchcode_search is mock_sc

    def test_get_searchcode_search_resolves_from_core(self):
        ale = self._make_ale()
        mock_sc = MagicMock()
        ale.core.searchcode_search = mock_sc
        assert ale._get_searchcode_search() is mock_sc

    def test_autonomous_searchcode_discovery_skipped_when_no_sc(self):
        ale = self._make_ale()
        ale.core.searchcode_search = None
        result = ale._autonomous_searchcode_discovery()
        assert "skipped" in result.lower()

    def test_autonomous_searchcode_discovery_runs_and_returns_summary(self):
        ale = self._make_ale()
        mock_sc = MagicMock()
        mock_sc.discover_patterns.return_value = [
            {"text": "def decorator(fn): return fn", "url": "http://sc.com/a.py"}
        ]
        ale.searchcode_search = mock_sc
        ale.knowledge_db = None  # no KB — just check it doesn't raise
        result = ale._autonomous_searchcode_discovery()
        assert isinstance(result, str)

    def test_searchcode_discovery_increments_counter(self):
        ale = self._make_ale()
        mock_sc = MagicMock()
        mock_sc.discover_patterns.return_value = []
        ale.searchcode_search = mock_sc
        ale.knowledge_db = None
        before = ale.learning_history.get("searchcode_discovery_cycles", 0)
        ale._autonomous_searchcode_discovery()
        after = ale.learning_history.get("searchcode_discovery_cycles", 0)
        assert after == before + 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
