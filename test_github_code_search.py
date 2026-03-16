"""
test_github_code_search.py — Unit tests for GitHubCodeSearch integration.

Run with::

    pytest test_github_code_search.py -v
"""

import os
from unittest.mock import MagicMock, patch, call
import pytest

from modules.github_code_search import (
    GitHubCodeSearch,
    GITHUB_SEARCH_CODE_URL,
    GITHUB_SEARCH_REPOS_URL,
    _infer_pattern_type,
    _PATTERN_QUERIES,
    _REFACTORING_QUERIES,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_code_item(repo_full_name="owner/repo", path="main.py", fragment="def foo(): pass"):
    return {
        "repository": {"full_name": repo_full_name, "description": "A test repo"},
        "path": path,
        "html_url": f"https://github.com/{repo_full_name}/blob/main/{path}",
        "text_matches": [{"fragment": fragment}],
    }


def _mock_code_response(items):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"total_count": len(items), "items": items}
    return resp


def _mock_repo_response(items):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"total_count": len(items), "items": items}
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def gcs_no_token():
    return GitHubCodeSearch(token="")


@pytest.fixture()
def gcs_with_token():
    return GitHubCodeSearch(token="ghp_testtoken123456")


# ─────────────────────────────────────────────────────────────────────────────
# Token loading
# ─────────────────────────────────────────────────────────────────────────────

class TestTokenLoading:
    def test_explicit_token_stored(self):
        gcs = GitHubCodeSearch(token="explicit-token")
        assert gcs.token == "explicit-token"

    def test_no_token_is_empty_string(self, gcs_no_token):
        assert gcs_no_token.token == ""

    def test_env_var_token_loaded(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "env-token-abc"}):
            gcs = GitHubCodeSearch()
            assert gcs.token == "env-token-abc"

    def test_explicit_takes_precedence_over_env(self):
        with patch.dict(os.environ, {"GITHUB_TOKEN": "env-token"}):
            gcs = GitHubCodeSearch(token="explicit-token")
            assert gcs.token == "explicit-token"

    def test_is_available_true_with_token(self, gcs_with_token):
        assert gcs_with_token.is_available() is True

    def test_is_available_false_without_token(self, gcs_no_token):
        assert gcs_no_token.is_available() is False


# ─────────────────────────────────────────────────────────────────────────────
# _headers()
# ─────────────────────────────────────────────────────────────────────────────

class TestHeaders:
    def test_bearer_auth_sent_when_token_present(self, gcs_with_token):
        h = gcs_with_token._headers()
        assert h["Authorization"] == "Bearer ghp_testtoken123456"

    def test_no_auth_header_when_no_token(self, gcs_no_token):
        h = gcs_no_token._headers()
        assert "Authorization" not in h

    def test_text_match_accept_header(self, gcs_with_token):
        h = gcs_with_token._headers(text_match=True)
        assert "text-match" in h["Accept"]

    def test_standard_accept_header(self, gcs_with_token):
        h = gcs_with_token._headers(text_match=False)
        assert h["Accept"] == "application/vnd.github+json"


# ─────────────────────────────────────────────────────────────────────────────
# search_code()
# ─────────────────────────────────────────────────────────────────────────────

class TestSearchCode:
    def test_returns_empty_on_network_error(self, gcs_with_token):
        with patch("modules.github_code_search.requests.get", side_effect=Exception("network")):
            results = gcs_with_token.search_code("async context manager")
        assert results == []

    def test_returns_normalised_dicts(self, gcs_with_token):
        item = _make_code_item()
        mock_resp = _mock_code_response([item])
        with patch("modules.github_code_search.requests.get", return_value=mock_resp):
            results = gcs_with_token.search_code("decorator pattern", language="python")
        assert len(results) == 1
        r = results[0]
        assert r["source"] == "github_code"
        assert "text" in r
        assert "url" in r
        assert "repo" in r
        assert "path" in r

    def test_language_filter_added_to_query(self, gcs_with_token):
        mock_resp = _mock_code_response([])
        with patch("modules.github_code_search.requests.get", return_value=mock_resp) as mock_get:
            gcs_with_token.search_code("decorator", language="python")
            params = mock_get.call_args.kwargs.get("params", {})
            assert "language:python" in params.get("q", "")

    def test_no_language_filter_when_none(self, gcs_with_token):
        mock_resp = _mock_code_response([])
        with patch("modules.github_code_search.requests.get", return_value=mock_resp) as mock_get:
            gcs_with_token.search_code("decorator")
            params = mock_get.call_args.kwargs.get("params", {})
            assert "language:" not in params.get("q", "")

    def test_respects_max_results(self, gcs_with_token):
        items = [_make_code_item(path=f"f{i}.py") for i in range(10)]
        mock_resp = _mock_code_response(items)
        with patch("modules.github_code_search.requests.get", return_value=mock_resp):
            results = gcs_with_token.search_code("test", max_results=3)
        assert len(results) <= 3

    def test_calls_github_code_search_url(self, gcs_with_token):
        mock_resp = _mock_code_response([])
        with patch("modules.github_code_search.requests.get", return_value=mock_resp) as mock_get:
            gcs_with_token.search_code("test query")
            called_url = mock_get.call_args[0][0]
            assert called_url == GITHUB_SEARCH_CODE_URL

    def test_text_match_header_sent(self, gcs_with_token):
        mock_resp = _mock_code_response([])
        with patch("modules.github_code_search.requests.get", return_value=mock_resp) as mock_get:
            gcs_with_token.search_code("test")
            headers_sent = mock_get.call_args.kwargs.get("headers", {})
            assert "text-match" in headers_sent.get("Accept", "")

    def test_fragment_included_in_text(self, gcs_with_token):
        item = _make_code_item(fragment="def my_decorator(func): return func")
        mock_resp = _mock_code_response([item])
        with patch("modules.github_code_search.requests.get", return_value=mock_resp):
            results = gcs_with_token.search_code("decorator")
        assert "my_decorator" in results[0]["text"]


# ─────────────────────────────────────────────────────────────────────────────
# discover_patterns()
# ─────────────────────────────────────────────────────────────────────────────

class TestDiscoverPatterns:
    def test_returns_github_pattern_source(self, gcs_with_token):
        item = _make_code_item(fragment="@decorator def func(): pass")
        mock_resp = _mock_code_response([item])
        with patch("modules.github_code_search.requests.get", return_value=mock_resp):
            results = gcs_with_token.discover_patterns("python", "decorator", max_results=2)
        assert all(r["source"] == "github_pattern" for r in results)

    def test_pattern_type_annotated_on_results(self, gcs_with_token):
        item = _make_code_item()
        mock_resp = _mock_code_response([item])
        with patch("modules.github_code_search.requests.get", return_value=mock_resp):
            results = gcs_with_token.discover_patterns("python", "async")
        for r in results:
            assert r.get("pattern_type") == "async"

    def test_unknown_pattern_type_uses_fallback_query(self, gcs_with_token):
        mock_resp = _mock_code_response([])
        with patch("modules.github_code_search.requests.get", return_value=mock_resp) as mock_get:
            gcs_with_token.discover_patterns("python", "my_custom_pattern")
            params = mock_get.call_args.kwargs.get("params", {})
            assert "my_custom_pattern" in params.get("q", "")


# ─────────────────────────────────────────────────────────────────────────────
# find_training_data()
# ─────────────────────────────────────────────────────────────────────────────

class TestFindTrainingData:
    def _make_repo_item(self, name="owner/dataset-repo"):
        return {
            "full_name": name,
            "description": "A dataset repo",
            "html_url": f"https://github.com/{name}",
            "stargazers_count": 100,
        }

    def test_returns_dataset_source_for_code_results(self, gcs_with_token):
        code_item = _make_code_item(path="data.csv")
        repo_item = self._make_repo_item()

        def side_effect(url, **kwargs):
            if url == GITHUB_SEARCH_CODE_URL:
                return _mock_code_response([code_item])
            return _mock_repo_response([repo_item])

        with patch("modules.github_code_search.requests.get", side_effect=side_effect):
            results = gcs_with_token.find_training_data("nlp sentiment", max_results=4)

        sources = [r["source"] for r in results]
        assert "github_dataset" in sources or "github_dataset_repo" in sources

    def test_respects_max_results(self, gcs_with_token):
        def side_effect(url, **kwargs):
            items = [_make_code_item(path=f"data{i}.csv") for i in range(5)]
            repo_items = [self._make_repo_item(f"owner/repo{i}") for i in range(5)]
            if url == GITHUB_SEARCH_CODE_URL:
                return _mock_code_response(items)
            return _mock_repo_response(repo_items)

        with patch("modules.github_code_search.requests.get", side_effect=side_effect):
            results = gcs_with_token.find_training_data("sentiment", max_results=3)
        assert len(results) <= 3


# ─────────────────────────────────────────────────────────────────────────────
# find_refactoring_patterns()
# ─────────────────────────────────────────────────────────────────────────────

class TestFindRefactoringPatterns:
    def test_returns_github_refactor_source(self, gcs_with_token):
        item = _make_code_item(fragment="result = [x for x in items if x]")
        mock_resp = _mock_code_response([item])
        with patch("modules.github_code_search.requests.get", return_value=mock_resp):
            results = gcs_with_token.find_refactoring_patterns("python", "list_comprehension")
        assert all(r["source"] == "github_refactor" for r in results)

    def test_technique_annotated_on_results(self, gcs_with_token):
        item = _make_code_item()
        mock_resp = _mock_code_response([item])
        with patch("modules.github_code_search.requests.get", return_value=mock_resp):
            results = gcs_with_token.find_refactoring_patterns("python", "fstring")
        for r in results:
            assert r.get("technique") == "fstring"

    def test_unknown_technique_uses_fallback_query(self, gcs_with_token):
        mock_resp = _mock_code_response([])
        with patch("modules.github_code_search.requests.get", return_value=mock_resp) as mock_get:
            gcs_with_token.find_refactoring_patterns("python", "my_technique")
            params = mock_get.call_args.kwargs.get("params", {})
            assert "my_technique" in params.get("q", "")


# ─────────────────────────────────────────────────────────────────────────────
# research_for_code_generation()
# ─────────────────────────────────────────────────────────────────────────────

class TestResearchForCodeGeneration:
    def test_returns_merged_list(self, gcs_with_token):
        item1 = _make_code_item(path="a.py", fragment="@decorator def a(): pass")
        item2 = _make_code_item(path="b.py", fragment="async def b(): await coro()")
        mock_resp = _mock_code_response([item1, item2])
        with patch("modules.github_code_search.requests.get", return_value=mock_resp):
            results = gcs_with_token.research_for_code_generation("python", "decorator", max_results=5)
        assert isinstance(results, list)
        assert len(results) <= 5

    def test_no_duplicate_urls(self, gcs_with_token):
        item = _make_code_item()  # same url both times
        mock_resp = _mock_code_response([item])
        with patch("modules.github_code_search.requests.get", return_value=mock_resp):
            results = gcs_with_token.research_for_code_generation("python", "decorator", max_results=10)
        urls = [r.get("url") for r in results]
        assert len(urls) == len(set(u for u in urls if u))


# ─────────────────────────────────────────────────────────────────────────────
# _infer_pattern_type()
# ─────────────────────────────────────────────────────────────────────────────

class TestInferPatternType:
    def test_decorator_keyword(self):
        assert _infer_pattern_type("python decorators") == "decorator"

    def test_async_keyword(self):
        assert _infer_pattern_type("async await coroutine") == "async"

    def test_context_keyword(self):
        assert _infer_pattern_type("context manager") == "context_manager"

    def test_generator_keyword(self):
        assert _infer_pattern_type("generator yield") == "generator"

    def test_unknown_returns_default(self):
        result = _infer_pattern_type("some completely random topic")
        assert result in _PATTERN_QUERIES  # must be a valid known key

    def test_case_insensitive(self):
        assert _infer_pattern_type("DECORATOR EXAMPLE") == "decorator"


# ─────────────────────────────────────────────────────────────────────────────
# ALE integration — github_code_search wired into step 8
# ─────────────────────────────────────────────────────────────────────────────

class TestALEIntegration:
    """Verify that the ALE accepts github_code_search and calls it in code research."""

    def test_ale_accepts_github_code_search_param(self):
        from modules.autonomous_learning_engine import AutonomousLearningEngine
        gcs = GitHubCodeSearch(token="test-token")
        ale = AutonomousLearningEngine(core=None, github_code_search=gcs)
        assert ale.github_code_search is gcs

    def test_get_github_code_search_lazy_from_core(self):
        from modules.autonomous_learning_engine import AutonomousLearningEngine
        gcs = GitHubCodeSearch(token="test-token")
        core = MagicMock()
        core.github_code_search = gcs
        ale = AutonomousLearningEngine(core=core)
        assert ale._get_github_code_search() is gcs

    def test_gcs_called_during_code_research(self):
        """_autonomous_code_research() should call research_for_code_generation."""
        from modules.autonomous_learning_engine import AutonomousLearningEngine

        gcs = MagicMock(spec=GitHubCodeSearch)
        gcs.research_for_code_generation.return_value = [
            {"source": "github_pattern", "text": "repo:x | path:y | def test(): pass", "url": "https://github.com/x"}
        ]

        kb = MagicMock()
        kb.add_fact.return_value = None
        kb.queue_learning.return_value = None

        ale = AutonomousLearningEngine(
            core=None,
            github_code_search=gcs,
            knowledge_db=kb,
        )
        # Ensure there are research topics so the step doesn't bail early
        ale.code_research_topics = [("python", "decorator")]

        result = ale._autonomous_code_research()
        # Verify GitHub Code Search was called with the right language+topic pair
        gcs.research_for_code_generation.assert_called_once_with("python", "decorator", max_results=3)
        # Result should mention GitHub as a source and report at least one snippet
        assert "GitHub" in result
        assert "snippet" in result

    def test_initialize_factory_accepts_github_code_search(self):
        from modules.autonomous_learning_engine import initialize_autonomous_engine
        gcs = GitHubCodeSearch(token="tok")
        engine = initialize_autonomous_engine(core=None, github_code_search=gcs)
        assert engine.github_code_search is gcs
