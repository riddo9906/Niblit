"""
test_full_upgrade_pipeline.py — Unit tests for niblit_full_upgrade_pipeline.py.

Run with::

    pytest test_full_upgrade_pipeline.py -v

All tests stub out external services (GitHub, HuggingFace, Docker, etc.) so no
live network calls or API keys are required.
"""

import asyncio
import json
import sqlite3
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import niblit_full_upgrade_pipeline as pipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def _make_db() -> sqlite3.Connection:
    """Return an in-memory SQLite connection pre-initialised for the pipeline."""
    return pipeline._open_db(":memory:")


# ---------------------------------------------------------------------------
# _open_db / _store_knowledge
# ---------------------------------------------------------------------------

class TestSQLiteHelpers(unittest.TestCase):
    def test_open_db_returns_connection(self):
        conn = pipeline._open_db(":memory:")
        self.assertIsInstance(conn, sqlite3.Connection)
        conn.close()

    def test_knowledge_table_created(self):
        conn = pipeline._open_db(":memory:")
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='knowledge'"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        conn.close()

    def test_store_knowledge_persists(self):
        conn = pipeline._open_db(":memory:")
        pipeline._store_knowledge(conn, "test:key", "test value", source="unit_test")
        row = conn.execute("SELECT value, source FROM knowledge WHERE key='test:key'").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], "test value")
        self.assertEqual(row[1], "unit_test")
        conn.close()

    def test_store_knowledge_upserts(self):
        conn = pipeline._open_db(":memory:")
        pipeline._store_knowledge(conn, "dup:key", "first", source="a")
        pipeline._store_knowledge(conn, "dup:key", "second", source="b")
        rows = conn.execute("SELECT value FROM knowledge WHERE key='dup:key'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "second")
        conn.close()


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

class TestMetrics(unittest.TestCase):
    def test_get_metrics_snapshot_returns_dict(self):
        snap = pipeline.get_metrics_snapshot()
        self.assertIsInstance(snap, dict)

    def test_metrics_has_required_keys(self):
        snap = pipeline.get_metrics_snapshot()
        for key in ("cycles", "errors", "durations_sum_s", "prometheus_available"):
            self.assertIn(key, snap)

    def test_record_cycle_increments_counter(self):
        before = pipeline._metrics["cycles"].get("TestAgent", 0)
        pipeline._record_cycle("TestAgent", 0.1)
        after = pipeline._metrics["cycles"].get("TestAgent", 0)
        self.assertEqual(after, before + 1)

    def test_record_error_increments_counter(self):
        before = pipeline._metrics["errors"].get("TestAgent", 0)
        pipeline._record_error("TestAgent")
        after = pipeline._metrics["errors"].get("TestAgent", 0)
        self.assertEqual(after, before + 1)

    def test_prometheus_available_is_bool(self):
        snap = pipeline.get_metrics_snapshot()
        self.assertIsInstance(snap["prometheus_available"], bool)

    def test_start_prometheus_server_returns_bool(self):
        result = pipeline.start_prometheus_server()
        self.assertIsInstance(result, bool)


# ---------------------------------------------------------------------------
# NiblitGraphDB
# ---------------------------------------------------------------------------

class TestNiblitGraphDB(unittest.TestCase):
    def setUp(self):
        self.conn = _make_db()
        self.graph = pipeline.NiblitGraphDB(uri="", sqlite_conn=self.conn)

    def tearDown(self):
        self.conn.close()

    def test_backend_is_sqlite_when_no_neo4j(self):
        self.assertEqual(self.graph.backend, "sqlite")

    def test_merge_node_creates_row(self):
        self.graph.merge_node("Concept", "test_concept")
        rows = self.conn.execute(
            "SELECT name FROM graph_nodes WHERE name='test_concept'"
        ).fetchall()
        self.assertEqual(len(rows), 1)

    def test_merge_node_upserts(self):
        self.graph.merge_node("Concept", "dup_node")
        self.graph.merge_node("Concept", "dup_node")
        rows = self.conn.execute(
            "SELECT name FROM graph_nodes WHERE name='dup_node'"
        ).fetchall()
        self.assertEqual(len(rows), 1)

    def test_merge_relationship_creates_edge(self):
        self.graph.merge_node("A", "src_node")
        self.graph.merge_node("B", "dst_node")
        self.graph.merge_relationship("src_node", "LINKS", "dst_node")
        rows = self.conn.execute(
            "SELECT rel FROM graph_edges WHERE src='src_node' AND dst='dst_node'"
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "LINKS")

    def test_run_query_returns_empty_on_sqlite(self):
        result = self.graph.run_query("MATCH (n) RETURN n")
        self.assertEqual(result, [])

    def test_no_backend_when_no_connection(self):
        g = pipeline.NiblitGraphDB(uri="", sqlite_conn=None)
        self.assertEqual(g.backend, "none")
        # Should not raise
        g.merge_node("X", "y")
        g.merge_relationship("a", "REL", "b")


# ---------------------------------------------------------------------------
# DockerSandbox
# ---------------------------------------------------------------------------

class TestDockerSandbox(unittest.TestCase):
    def test_disabled_sandbox_is_not_available(self):
        sandbox = pipeline.DockerSandbox(enabled=False)
        self.assertFalse(sandbox.is_available())

    def test_subprocess_fallback_runs_code(self):
        sandbox = pipeline.DockerSandbox(enabled=False, timeout=5)
        result = _run(sandbox.run_code("print('hello sandbox')"))
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("hello sandbox", result["stdout"])

    def test_subprocess_captures_stderr(self):
        sandbox = pipeline.DockerSandbox(enabled=False, timeout=5)
        result = _run(sandbox.run_code("import sys; sys.stderr.write('err msg\\n')"))
        self.assertEqual(result["exit_code"], 0)
        self.assertIn("err msg", result["stderr"])

    def test_subprocess_syntax_error_returns_nonzero(self):
        sandbox = pipeline.DockerSandbox(enabled=False, timeout=5)
        result = _run(sandbox.run_code("def broken(: pass"))
        self.assertNotEqual(result["exit_code"], 0)


# ---------------------------------------------------------------------------
# SemanticVectorStore
# ---------------------------------------------------------------------------

class TestSemanticVectorStore(unittest.TestCase):
    def test_backend_property_returns_string(self):
        vs = pipeline.SemanticVectorStore()
        self.assertIsInstance(vs.backend, str)

    def test_add_and_search_when_available(self):
        vs = pipeline.SemanticVectorStore()
        if vs._store is None:
            return  # skip when module unavailable
        vs.add("test-doc-1", "This is a test document about Python async code")
        results = vs.search("Python async", top_k=1)
        self.assertIsInstance(results, list)

    def test_search_returns_list_when_store_none(self):
        vs = pipeline.SemanticVectorStore()
        vs._store = None
        results = vs.search("anything")
        self.assertEqual(results, [])

    def test_add_returns_false_when_store_none(self):
        vs = pipeline.SemanticVectorStore()
        vs._store = None
        result = vs.add("id", "text")
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# GitHubAPI
# ---------------------------------------------------------------------------

class TestGitHubAPI(unittest.TestCase):
    def _make_api(self):
        api = pipeline.GitHubAPI(token="fake", repo="owner/repo", dry_run=True)
        mock_integration = MagicMock()
        mock_integration.is_configured.return_value = True
        mock_integration.get_repo_info.return_value = {"name": "repo", "full_name": "owner/repo"}
        mock_integration.push_file.return_value = {"success": True, "message": "ok"}
        mock_integration.create_pull_request.return_value = {
            "success": True, "message": "PR created", "url": "https://github.com/owner/repo/pull/1"
        }
        api._integration = mock_integration
        return api, mock_integration

    def test_is_available_true_when_configured(self):
        api, _ = self._make_api()
        self.assertTrue(api.is_available())

    def test_is_available_false_when_no_integration(self):
        api = pipeline.GitHubAPI.__new__(pipeline.GitHubAPI)
        api._integration = None
        self.assertFalse(api.is_available())

    def test_fetch_repo_returns_dict(self):
        api, mock = self._make_api()
        result = _run(api.fetch_repo())
        self.assertIsInstance(result, dict)
        mock.get_repo_info.assert_called_once()

    def test_create_branch_and_commit_calls_push_file(self):
        api, mock = self._make_api()
        _run(api.create_branch_and_commit(
            branch_name="test-branch",
            files={"test.md": "# Test"},
        ))
        mock.push_file.assert_called_once()

    def test_create_branch_and_commit_calls_create_pr(self):
        api, mock = self._make_api()
        _run(api.create_branch_and_commit(
            branch_name="test-branch",
            files={"test.md": "# Test"},
        ))
        mock.create_pull_request.assert_called_once()

    def test_unavailable_api_returns_message(self):
        api = pipeline.GitHubAPI.__new__(pipeline.GitHubAPI)
        api._integration = None
        result = _run(api.create_branch_and_commit("branch", {"f.py": ""}))
        self.assertIn("unavailable", result.lower())

    def test_unavailable_fetch_repo_returns_none(self):
        api = pipeline.GitHubAPI.__new__(pipeline.GitHubAPI)
        api._integration = None
        result = _run(api.fetch_repo())
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# HuggingFaceAPI
# ---------------------------------------------------------------------------

class TestHuggingFaceAPI(unittest.TestCase):
    def test_unavailable_query_returns_string(self):
        api = pipeline.HuggingFaceAPI.__new__(pipeline.HuggingFaceAPI)
        api._adapter = None
        result = _run(api.query_model("model", "test prompt"))
        self.assertIsInstance(result, str)
        self.assertIn("unavailable", result.lower())

    def test_unavailable_generate_code_returns_string(self):
        api = pipeline.HuggingFaceAPI.__new__(pipeline.HuggingFaceAPI)
        api._adapter = None
        result = _run(api.generate_code("python", "test purpose"))
        self.assertIsInstance(result, str)
        self.assertIn("unavailable", result.lower())

    def test_is_available_false_when_no_adapter(self):
        api = pipeline.HuggingFaceAPI.__new__(pipeline.HuggingFaceAPI)
        api._adapter = None
        self.assertFalse(api.is_available())

    def test_query_model_calls_adapter(self):
        api = pipeline.HuggingFaceAPI.__new__(pipeline.HuggingFaceAPI)
        mock_adapter = MagicMock()
        mock_adapter.is_online.return_value = True
        mock_adapter.query_llm.return_value = "suggested code"
        api._adapter = mock_adapter
        result = _run(api.query_model("model", "suggest code"))
        self.assertEqual(result, "suggested code")

    def test_generate_code_calls_adapter(self):
        api = pipeline.HuggingFaceAPI.__new__(pipeline.HuggingFaceAPI)
        mock_adapter = MagicMock()
        mock_adapter.generate_code.return_value = "def foo(): pass"
        api._adapter = mock_adapter
        result = _run(api.generate_code("python", "a helper function"))
        self.assertEqual(result, "def foo(): pass")


# ---------------------------------------------------------------------------
# NewsAPIWrapper
# ---------------------------------------------------------------------------

class TestNewsAPIWrapper(unittest.TestCase):
    def test_no_key_returns_empty(self):
        wrapper = pipeline.NewsAPIWrapper(key="")
        result = _run(wrapper.get_top_headlines())
        self.assertEqual(result, [])

    def test_is_available_false_without_key(self):
        wrapper = pipeline.NewsAPIWrapper(key="")
        self.assertFalse(wrapper.is_available())

    def test_is_available_true_with_key(self):
        wrapper = pipeline.NewsAPIWrapper(key="fake-key")
        self.assertTrue(wrapper.is_available())

    def test_network_error_returns_empty(self):
        wrapper = pipeline.NewsAPIWrapper(key="fake-key")
        # Patch urllib.request.urlopen to raise a network error
        with patch("urllib.request.urlopen", side_effect=OSError("Network down")):
            result = _run(wrapper.get_top_headlines())
        self.assertIsInstance(result, list)
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# WikipediaAPIWrapper
# ---------------------------------------------------------------------------

class TestWikipediaAPIWrapper(unittest.TestCase):
    def test_no_manager_returns_empty_string(self):
        wrapper = pipeline.WikipediaAPIWrapper.__new__(pipeline.WikipediaAPIWrapper)
        wrapper._manager = None
        result = _run(wrapper.fetch_page("Python"))
        self.assertEqual(result, "")

    def test_manager_result_returned(self):
        wrapper = pipeline.WikipediaAPIWrapper.__new__(pipeline.WikipediaAPIWrapper)
        mock_manager = MagicMock()
        mock_manager.search_wikipedia.return_value = {"text": "Python is a language"}
        wrapper._manager = mock_manager
        result = _run(wrapper.fetch_page("Python"))
        self.assertIn("Python", result)


# ---------------------------------------------------------------------------
# PipelineAgent base
# ---------------------------------------------------------------------------

class _DummyAgent(pipeline.PipelineAgent):
    def __init__(self, name, succeed=True):
        super().__init__(name)
        self._succeed = succeed

    async def run(self):
        if not self._succeed:
            raise RuntimeError("agent failure")
        return {"done": True}


class TestPipelineAgent(unittest.TestCase):
    def test_successful_run_increments_cycles(self):
        agent = _DummyAgent("test_ok")
        _run(agent._timed_run())
        self.assertEqual(agent._cycles, 1)
        self.assertEqual(agent._errors, 0)

    def test_failed_run_increments_errors(self):
        agent = _DummyAgent("test_err", succeed=False)
        result = _run(agent._timed_run())
        self.assertEqual(agent._cycles, 0)
        self.assertEqual(agent._errors, 1)
        self.assertIn("error", result)

    def test_stats_returns_dict(self):
        agent = _DummyAgent("stats_test")
        self.assertIn("cycles", agent.stats)
        self.assertIn("errors", agent.stats)


# ---------------------------------------------------------------------------
# Individual agents
# ---------------------------------------------------------------------------

class TestBuilderAgent(unittest.TestCase):
    def _make(self):
        github = MagicMock(spec=pipeline.GitHubAPI)
        github.fetch_repo = AsyncMock(return_value={"name": "Niblit"})
        return pipeline.BuilderAgent(github_api=github)

    def test_run_returns_dict(self):
        agent = self._make()
        result = _run(agent.run())
        self.assertIsInstance(result, dict)

    def test_run_has_repo_info_key(self):
        agent = self._make()
        result = _run(agent.run())
        self.assertIn("repo_info", result)

    def test_run_improvements_identified_true(self):
        agent = self._make()
        result = _run(agent.run())
        self.assertTrue(result["improvements_identified"])


class TestResearchAgent(unittest.TestCase):
    def _make(self):
        hf = MagicMock(spec=pipeline.HuggingFaceAPI)
        hf.query_model = AsyncMock(return_value="code suggestion result")
        news = MagicMock(spec=pipeline.NewsAPIWrapper)
        news.get_top_headlines = AsyncMock(return_value=["AI headline 1", "AI headline 2"])
        wiki = MagicMock(spec=pipeline.WikipediaAPIWrapper)
        wiki.fetch_page = AsyncMock(return_value="Wikipedia extract text")
        conn = _make_db()
        vs = pipeline.SemanticVectorStore()
        vs._store = None  # use no-op store to avoid side-effects
        graph = pipeline.NiblitGraphDB(uri="", sqlite_conn=conn)
        agent = pipeline.ResearchAgent(
            hf_api=hf, news_api=news, wiki_api=wiki,
            vector_store=vs, graph_db=graph, db_conn=conn,
        )
        return agent, conn

    def test_run_returns_dict(self):
        agent, conn = self._make()
        result = _run(agent.run())
        conn.close()
        self.assertIsInstance(result, dict)

    def test_run_has_expected_keys(self):
        agent, conn = self._make()
        result = _run(agent.run())
        conn.close()
        for key in ("hf_chars", "wiki_chars", "headlines"):
            self.assertIn(key, result)

    def test_run_headline_count_correct(self):
        agent, conn = self._make()
        result = _run(agent.run())
        conn.close()
        self.assertEqual(result["headlines"], 2)


class TestEvolutionAgent(unittest.TestCase):
    def _make(self):
        hf = MagicMock(spec=pipeline.HuggingFaceAPI)
        hf.generate_code = AsyncMock(return_value="def evolved(): pass")
        sandbox = pipeline.DockerSandbox(enabled=False, timeout=5)
        conn = _make_db()
        vs = pipeline.SemanticVectorStore()
        vs._store = None
        return pipeline.EvolutionAgent(hf_api=hf, sandbox=sandbox, vector_store=vs, db_conn=conn), conn

    def test_run_returns_dict(self):
        agent, conn = self._make()
        result = _run(agent.run())
        conn.close()
        self.assertIsInstance(result, dict)

    def test_run_has_code_length(self):
        agent, conn = self._make()
        result = _run(agent.run())
        conn.close()
        self.assertIn("code_length", result)
        self.assertGreater(result["code_length"], 0)

    def test_run_sandbox_exit_code_present(self):
        agent, conn = self._make()
        result = _run(agent.run())
        conn.close()
        self.assertIn("sandbox_exit_code", result)


class TestSelfTeacherAgent(unittest.TestCase):
    def _make(self):
        conn = _make_db()
        vs = pipeline.SemanticVectorStore()
        vs._store = None
        graph = pipeline.NiblitGraphDB(uri="", sqlite_conn=conn)
        return pipeline.SelfTeacherAgent(graph_db=graph, vector_store=vs, db_conn=conn), conn

    def test_run_returns_dict(self):
        agent, conn = self._make()
        result = _run(agent.run())
        conn.close()
        self.assertIsInstance(result, dict)

    def test_run_has_nodes_added(self):
        agent, conn = self._make()
        result = _run(agent.run())
        conn.close()
        self.assertIn("nodes_added", result)
        self.assertIn("edges_added", result)


class TestSemanticAgent(unittest.TestCase):
    def _make(self):
        conn = _make_db()
        vs = pipeline.SemanticVectorStore()
        vs._store = None
        graph = pipeline.NiblitGraphDB(uri="", sqlite_conn=conn)
        return pipeline.SemanticAgent(vector_store=vs, graph_db=graph, db_conn=conn), conn

    def test_run_returns_dict(self):
        agent, conn = self._make()
        result = _run(agent.run())
        conn.close()
        self.assertIsInstance(result, dict)

    def test_run_indexes_concepts(self):
        agent, conn = self._make()
        result = _run(agent.run())
        conn.close()
        self.assertIn("concepts_indexed", result)
        self.assertGreater(result["concepts_indexed"], 0)

    def test_run_has_graph_backend(self):
        agent, conn = self._make()
        result = _run(agent.run())
        conn.close()
        self.assertIn("graph_backend", result)


# ---------------------------------------------------------------------------
# _retry_async
# ---------------------------------------------------------------------------

class TestRetryAsync(unittest.TestCase):
    def test_succeeds_on_first_attempt(self):
        calls = []
        async def coro():
            calls.append(1)
            return "ok"
        result = _run(pipeline._retry_async(coro, attempts=3, base_delay=0))
        self.assertEqual(result, "ok")
        self.assertEqual(len(calls), 1)

    def test_retries_on_failure(self):
        calls = []
        async def coro():
            calls.append(1)
            if len(calls) < 3:
                raise ValueError("temporary error")
            return "recovered"
        result = _run(pipeline._retry_async(coro, attempts=3, base_delay=0))
        self.assertEqual(result, "recovered")
        self.assertEqual(len(calls), 3)

    def test_raises_after_all_attempts(self):
        async def always_fails():
            raise RuntimeError("permanent error")
        with self.assertRaises(RuntimeError):
            _run(pipeline._retry_async(always_fails, attempts=2, base_delay=0))


# ---------------------------------------------------------------------------
# orchestrate_pipeline (integration-level, fully mocked externals)
# ---------------------------------------------------------------------------

class TestOrchestratePipeline(unittest.TestCase):
    def _run_pipeline(self):
        conn = _make_db()

        # Patch all external I/O at module level
        with patch.object(pipeline.GitHubAPI, "__init__", lambda self, *a, **kw: setattr(self, "_integration", None) or None), \
             patch.object(pipeline.HuggingFaceAPI, "__init__", lambda self, *a, **kw: setattr(self, "_adapter", None) or None), \
             patch.object(pipeline.WikipediaAPIWrapper, "__init__", lambda self, *a, **kw: setattr(self, "_manager", None) or None), \
             patch.object(pipeline.SemanticVectorStore, "__init__", lambda self, *a, **kw: setattr(self, "_store", None) or None):
            result = _run(pipeline.orchestrate_pipeline(dry_run=True, db_conn=conn))

        conn.close()
        return result

    def test_returns_dict(self):
        result = self._run_pipeline()
        self.assertIsInstance(result, dict)

    def test_all_agents_present_in_result(self):
        result = self._run_pipeline()
        for name in ("Builder", "Researcher", "Evolution", "SelfTeacher", "Semantic"):
            self.assertIn(name, result)

    def test_meta_block_present(self):
        result = self._run_pipeline()
        self.assertIn("_meta", result)

    def test_meta_has_duration(self):
        result = self._run_pipeline()
        self.assertIn("duration_s", result["_meta"])
        self.assertGreater(result["_meta"]["duration_s"], 0)

    def test_dry_run_flag_propagated(self):
        result = self._run_pipeline()
        self.assertTrue(result["_meta"]["dry_run"])

    def test_github_pr_url_present(self):
        result = self._run_pipeline()
        self.assertIn("github_pr_url", result)


# ---------------------------------------------------------------------------
# Config additions
# ---------------------------------------------------------------------------

class TestConfigAdditions(unittest.TestCase):
    def test_newsapi_key_in_config(self):
        from config import Config
        self.assertTrue(hasattr(Config, "NEWSAPI_KEY"))

    def test_neo4j_uri_in_config(self):
        from config import Config
        self.assertTrue(hasattr(Config, "NEO4J_URI"))

    def test_neo4j_user_in_config(self):
        from config import Config
        self.assertTrue(hasattr(Config, "NEO4J_USER"))

    def test_neo4j_pass_in_config(self):
        from config import Config
        self.assertTrue(hasattr(Config, "NEO4J_PASS"))

    def test_prometheus_enabled_in_config(self):
        from config import Config
        self.assertTrue(hasattr(Config, "PROMETHEUS_ENABLED"))

    def test_prometheus_port_in_config(self):
        from config import Config
        self.assertTrue(hasattr(Config, "PROMETHEUS_PORT"))

    def test_newsapi_default_is_empty_string(self):
        from config import Config
        self.assertEqual(Config.NEWSAPI_KEY, "")

    def test_neo4j_uri_default_is_empty_string(self):
        from config import Config
        self.assertEqual(Config.NEO4J_URI, "")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
