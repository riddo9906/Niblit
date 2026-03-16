"""
test_internet_manager.py — Unit tests for InternetManager SerpEx integration.

Run with::

    pytest test_internet_manager.py -v
"""

import os
from unittest.mock import MagicMock, patch
import pytest

from modules.internet_manager import InternetManager, SERPEX_API_URL


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def manager_no_key():
    """InternetManager with no SerpEx key (key-less fallback mode)."""
    return InternetManager(serpex_api_key="")


@pytest.fixture()
def manager_with_key():
    """InternetManager configured with a dummy SerpEx key."""
    return InternetManager(serpex_api_key="test-serpex-key-12345")


# ─────────────────────────────────────────────────────────────────────────────
# Key loading
# ─────────────────────────────────────────────────────────────────────────────

class TestKeyLoading:
    def test_explicit_key_stored(self):
        im = InternetManager(serpex_api_key="explicit-key")
        assert im.serpex_api_key == "explicit-key"

    def test_no_key_is_empty_string(self, manager_no_key):
        assert manager_no_key.serpex_api_key == ""

    def test_env_var_key_loaded(self):
        with patch.dict(os.environ, {"SERPEX_API_KEY": "env-key-abc"}):
            im = InternetManager()
            assert im.serpex_api_key == "env-key-abc"

    def test_explicit_key_takes_precedence_over_env(self):
        with patch.dict(os.environ, {"SERPEX_API_KEY": "env-key"}):
            im = InternetManager(serpex_api_key="explicit-key")
            assert im.serpex_api_key == "explicit-key"


# ─────────────────────────────────────────────────────────────────────────────
# _serpex_search
# ─────────────────────────────────────────────────────────────────────────────

class TestSerpexSearch:
    def test_returns_empty_without_key(self, manager_no_key):
        results = manager_no_key._serpex_search("python programming")
        assert results == []

    def test_sends_bearer_auth_header(self, manager_with_key):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "organic_results": [
                {"title": "Python Docs", "snippet": "Python is a programming language.", "link": "https://python.org"}
            ]
        }
        with patch("modules.internet_manager.requests.get", return_value=mock_resp) as mock_get:
            manager_with_key._serpex_search("python", max_results=3)
            # Extract headers from keyword arguments (requests.get is always called
            # with keyword args from our implementation)
            headers_sent = mock_get.call_args.kwargs.get("headers", {})
            assert "Authorization" in headers_sent
            assert headers_sent["Authorization"] == "Bearer test-serpex-key-12345"

    def test_uses_serpex_url(self, manager_with_key):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"organic_results": []}
        with patch("modules.internet_manager.requests.get", return_value=mock_resp) as mock_get:
            manager_with_key._serpex_search("test query")
            url_called = mock_get.call_args[0][0]
            assert url_called == SERPEX_API_URL

    def test_web_category_sends_time_range(self, manager_with_key):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"organic_results": []}
        with patch("modules.internet_manager.requests.get", return_value=mock_resp) as mock_get:
            manager_with_key._serpex_search("test", category="web", time_range="day")
            params = mock_get.call_args.kwargs.get("params", {})
            assert params.get("category") == "web"
            assert params.get("time_range") == "day"

    def test_news_category_no_time_range(self, manager_with_key):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {"news_results": []}
        with patch("modules.internet_manager.requests.get", return_value=mock_resp) as mock_get:
            manager_with_key._serpex_search("AI news", category="news")
            params = mock_get.call_args.kwargs.get("params", {})
            assert params.get("category") == "news"
            assert "time_range" not in params

    def test_parses_organic_results(self, manager_with_key):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "organic_results": [
                {"title": "A", "snippet": "First result", "link": "https://example.com/a"},
                {"title": "B", "snippet": "Second result", "link": "https://example.com/b"},
            ]
        }
        with patch("modules.internet_manager.requests.get", return_value=mock_resp):
            results = manager_with_key._serpex_search("test", max_results=5)
        assert len(results) == 2
        assert results[0]["source"] == "serpex"
        assert "First result" in results[0]["text"]
        assert results[0]["url"] == "https://example.com/a"

    def test_parses_answer_box(self, manager_with_key):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "answer_box": {"answer": "42 is the answer to everything."},
            "organic_results": [],
        }
        with patch("modules.internet_manager.requests.get", return_value=mock_resp):
            results = manager_with_key._serpex_search("meaning of life")
        assert any(r["source"] == "serpex_featured" for r in results)
        featured = [r for r in results if r["source"] == "serpex_featured"][0]
        assert "42" in featured["text"]

    def test_returns_empty_on_http_error(self, manager_with_key):
        with patch("modules.internet_manager.requests.get", side_effect=Exception("network error")):
            results = manager_with_key._serpex_search("test")
        assert results == []

    def test_respects_max_results(self, manager_with_key):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "organic_results": [
                {"snippet": f"Result {i}", "link": f"https://example.com/{i}"}
                for i in range(10)
            ]
        }
        with patch("modules.internet_manager.requests.get", return_value=mock_resp):
            results = manager_with_key._serpex_search("test", max_results=3)
        # max_results=3 limits items parsed from organic_results
        assert len(results) <= 3


# ─────────────────────────────────────────────────────────────────────────────
# search() — SerpEx used as primary when key is present
# ─────────────────────────────────────────────────────────────────────────────

class TestSearchWithSerpex:
    def test_serpex_used_when_key_present(self, manager_with_key):
        """When SerpEx key is set, search() should call _serpex_search and return results."""
        fake_results = [{"source": "serpex", "text": "SerpEx result text.", "url": "https://serpex.dev"}]
        with patch.object(manager_with_key, "_serpex_search", return_value=fake_results) as mock_sx:
            results = manager_with_key.search("machine learning", use_llm=False)
        assert mock_sx.called
        assert any(r.get("source") == "serpex" for r in results)

    def test_fallback_to_ddg_when_no_key(self, manager_no_key):
        """When no SerpEx key, search() must NOT call _serpex_search."""
        with patch.object(manager_no_key, "_serpex_search") as mock_sx:
            with patch("modules.internet_manager.requests.get", side_effect=Exception("offline")):
                manager_no_key.search("test", use_llm=False)
        mock_sx.assert_not_called()

    def test_results_have_required_keys(self, manager_with_key):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "organic_results": [
                {"title": "Test", "snippet": "A short snippet.", "link": "https://t.co"}
            ]
        }
        with patch("modules.internet_manager.requests.get", return_value=mock_resp):
            results = manager_with_key.search("test query", use_llm=False)
        for r in results:
            assert "source" in r
            assert "text" in r
            assert "url" in r


# ─────────────────────────────────────────────────────────────────────────────
# ResearcherEngine SerpEx support
# ─────────────────────────────────────────────────────────────────────────────

class TestResearcherEngineSerpex:
    def test_serpex_search_called_when_key_in_env(self):
        from modules.researcher_engine import ResearcherEngine
        engine = ResearcherEngine()
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "organic_results": [{"snippet": "SerpEx research data.", "link": "https://serpex.dev"}]
        }
        with patch.dict(os.environ, {"SERPEX_API_KEY": "test-key"}):
            with patch("modules.researcher_engine.requests.get", return_value=mock_resp):
                result = engine.run("neural networks")
        assert result.get("topic") == "neural networks"
        assert "summary" in result
        assert result["summary"]

    def test_ddg_fallback_when_no_key(self):
        from modules.researcher_engine import ResearcherEngine
        engine = ResearcherEngine()
        with patch.dict(os.environ, {}, clear=False):
            # Ensure key is absent
            os.environ.pop("SERPEX_API_KEY", None)
            with patch("modules.researcher_engine.requests.get", side_effect=Exception("offline")):
                result = engine.run("test topic")
        # Should handle gracefully (error or empty)
        assert isinstance(result, dict)
