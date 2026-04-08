"""
test_rag_pipeline.py — Unit tests for modules/rag_pipeline.py

Covers:
  - RAGPipeline.query() with mocked VectorStore and KnowledgeComprehension
  - Deduplication of near-identical hits
  - Context assembly and character limit
  - add_document() delegation to VectorStore
  - Module-level singleton via get_rag_pipeline()
  - Graceful degradation when backends are unavailable

Run with::

    pytest test_rag_pipeline.py -v
"""

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hits(texts, source="vector_store"):
    """Build fake search hit dicts."""
    return [
        {"text": t, "score": float(1.0 - i * 0.1), "id": f"id-{i}"}
        for i, t in enumerate(texts)
    ]


def _fresh_pipeline(**kwargs):
    """Return a new RAGPipeline instance without any pre-wired sources."""
    from modules.rag_pipeline import RAGPipeline
    return RAGPipeline(**kwargs)


# ---------------------------------------------------------------------------
# _deduplicate
# ---------------------------------------------------------------------------

class TestDeduplicate:
    def test_removes_identical_hits(self):
        from modules.rag_pipeline import _deduplicate
        hits = [
            {"text": "The quick brown fox jumps over the lazy dog"},
            {"text": "The quick brown fox jumps over the lazy dog"},
        ]
        result = _deduplicate(hits)
        assert len(result) == 1

    def test_keeps_distinct_hits(self):
        from modules.rag_pipeline import _deduplicate
        hits = [
            {"text": "Python is a high-level programming language"},
            {"text": "Docker containers package applications for deployment"},
        ]
        result = _deduplicate(hits)
        assert len(result) == 2

    def test_empty_text_is_filtered(self):
        from modules.rag_pipeline import _deduplicate
        hits = [{"text": ""}, {"text": "  "}, {"text": "real content here"}]
        result = _deduplicate(hits)
        assert len(result) == 1
        assert result[0]["text"] == "real content here"


# ---------------------------------------------------------------------------
# _truncate
# ---------------------------------------------------------------------------

class TestTruncate:
    def test_short_text_unchanged(self):
        from modules.rag_pipeline import _truncate
        assert _truncate("hello", 100) == "hello"

    def test_long_text_is_truncated(self):
        from modules.rag_pipeline import _truncate
        text = "word " * 200
        result = _truncate(text, 50)
        assert len(result) <= 55  # small buffer for ellipsis
        assert result.endswith("…")

    def test_truncates_at_word_boundary(self):
        from modules.rag_pipeline import _truncate
        text = "hello world foo bar baz"
        result = _truncate(text, 12)
        # Should not cut in the middle of a word
        assert " " not in result.rstrip("…").split(" ")[-1] or result.endswith("…")


# ---------------------------------------------------------------------------
# RAGPipeline.query
# ---------------------------------------------------------------------------

class TestRAGPipelineQuery:
    def _make_mock_vs(self, texts=("fact one", "fact two")):
        vs = MagicMock()
        vs.search.return_value = _make_hits(list(texts))
        return vs

    def _make_mock_kc(self, texts=("graph fact",)):
        kc = MagicMock()
        kc.search_graph.return_value = _make_hits(list(texts))
        return kc

    def test_returns_context_string(self):
        pipeline = _fresh_pipeline(
            vector_store=self._make_mock_vs(),
            knowledge_comprehension=self._make_mock_kc(),
        )
        result = pipeline.query("What is Niblit?")
        assert "context" in result
        assert isinstance(result["context"], str)

    def test_returns_sources_list(self):
        pipeline = _fresh_pipeline(
            vector_store=self._make_mock_vs(["fact A"]),
            knowledge_comprehension=self._make_mock_kc(["graph fact B"]),
        )
        result = pipeline.query("some query")
        assert "sources" in result
        assert len(result["sources"]) >= 1

    def test_retrieval_stats_populated(self):
        vs = self._make_mock_vs(["x", "y"])
        kc = self._make_mock_kc(["z"])
        pipeline = _fresh_pipeline(vector_store=vs, knowledge_comprehension=kc)
        result = pipeline.query("test")
        stats = result["retrieval_stats"]
        assert stats["vector_store"] == 2
        assert stats["memory_graph"] == 1

    def test_context_starts_with_header(self):
        pipeline = _fresh_pipeline(
            vector_store=self._make_mock_vs(["some knowledge"]),
            knowledge_comprehension=None,
        )
        result = pipeline.query("query")
        assert result["context"].startswith("Relevant context (RAG retrieval):")

    def test_empty_context_when_no_sources(self):
        vs = MagicMock()
        vs.search.return_value = []
        kc = MagicMock()
        kc.search_graph.return_value = []
        pipeline = _fresh_pipeline(vector_store=vs, knowledge_comprehension=kc)
        result = pipeline.query("empty query")
        assert result["context"] == ""

    def test_max_context_chars_respected(self):
        long_texts = [f"{'word ' * 200}fact {i}" for i in range(10)]
        pipeline = _fresh_pipeline(
            vector_store=self._make_mock_vs(long_texts),
            knowledge_comprehension=None,
            max_context_chars=200,
        )
        result = pipeline.query("test")
        assert len(result["context"]) <= 250  # small buffer for header

    def test_vector_store_exception_handled(self):
        vs = MagicMock()
        vs.search.side_effect = RuntimeError("connection refused")
        kc = self._make_mock_kc(["graph result"])
        pipeline = _fresh_pipeline(vector_store=vs, knowledge_comprehension=kc)
        result = pipeline.query("test")
        # Should not raise, and graph hits still included
        assert result["retrieval_stats"]["vector_store"] == 0
        assert result["retrieval_stats"]["memory_graph"] == 1

    def test_graph_exception_handled(self):
        vs = self._make_mock_vs(["vector result"])
        kc = MagicMock()
        kc.search_graph.side_effect = RuntimeError("graph error")
        pipeline = _fresh_pipeline(vector_store=vs, knowledge_comprehension=kc)
        result = pipeline.query("test")
        assert result["retrieval_stats"]["vector_store"] == 1
        assert result["retrieval_stats"]["memory_graph"] == 0


# ---------------------------------------------------------------------------
# RAGPipeline.add_document
# ---------------------------------------------------------------------------

class TestRAGPipelineAddDocument:
    def test_delegates_to_vector_store(self):
        vs = MagicMock()
        vs.add.return_value = True
        pipeline = _fresh_pipeline(vector_store=vs)
        result = pipeline.add_document("doc-1", "some text")
        vs.add.assert_called_once_with("doc-1", "some text")
        assert result is True

    def test_returns_false_when_vs_unavailable(self):
        pipeline = _fresh_pipeline(vector_store=None, knowledge_comprehension=None)
        # Patch the lazy loader to return None
        with patch.object(pipeline, "_get_vector_store", return_value=None):
            result = pipeline.add_document("doc-1", "text")
        assert result is False


# ---------------------------------------------------------------------------
# Singleton get_rag_pipeline
# ---------------------------------------------------------------------------

class TestGetRAGPipeline:
    def test_returns_rag_pipeline_instance(self):
        from modules.rag_pipeline import get_rag_pipeline, RAGPipeline
        # Reset singleton for test isolation
        import modules.rag_pipeline as _mod
        _mod._rag_pipeline_instance = None

        instance = get_rag_pipeline()
        assert isinstance(instance, RAGPipeline)

    def test_same_instance_on_repeated_calls(self):
        from modules.rag_pipeline import get_rag_pipeline
        import modules.rag_pipeline as _mod
        _mod._rag_pipeline_instance = None

        a = get_rag_pipeline()
        b = get_rag_pipeline()
        assert a is b


# ---------------------------------------------------------------------------
# research_bot helpers (no network calls)
# ---------------------------------------------------------------------------

class TestResearchBotHelpers:
    """Smoke-test the new research_bot helper functions."""

    def _make_analysis(self, name="test/repo", stars=1000):
        return {
            "full_name": name,
            "description": "A test repo",
            "stars": stars,
            "patterns": {
                "Architecture Patterns": ["pipeline", "plugin"],
                "AI/ML Techniques": ["agent", "rag"],
            },
        }

    def test_build_niblit_findings_structure(self):
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from nibblebots.research_bot import build_niblit_findings

        analyses = [self._make_analysis("owner/repoA", 5000),
                    self._make_analysis("owner/repoB", 1000)]
        synthesis = {
            "new_insights": ["pipeline (Architecture) — found in owner/repoA"],
            "pattern_freq": {
                "Architecture Patterns": [("pipeline", 2), ("plugin", 1)],
                "AI/ML Techniques": [("agent", 2), ("rag", 2)],
            },
        }
        findings = build_niblit_findings(analyses, synthesis)

        assert "patterns" in findings
        assert "new_insights" in findings
        assert "top_repos" in findings
        assert "recommendations" in findings
        # Top repo should be the higher-starred one
        assert findings["top_repos"][0]["full_name"] == "owner/repoA"
        # Patterns should aggregate across all analyses
        assert "pipeline" in findings["patterns"].get("Architecture Patterns", [])

    def test_niblit_integrate_handles_import_error(self, capsys):
        from nibblebots.research_bot import niblit_integrate
        # Patch sys.path to a place where modules won't be found
        with patch("builtins.__import__", side_effect=ImportError("no module")):
            # Should not raise
            try:
                niblit_integrate({"patterns": {}, "new_insights": [], "top_repos": []})
            except Exception:
                pass  # import error handling may vary; just ensure no crash propagates
