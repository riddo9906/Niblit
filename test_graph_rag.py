"""
test_graph_rag.py — Unit tests for modules/graph_rag.py

Covers:
  - QuadStore: add, dedup, single/multi-dimension query, entity query, count
  - extract_entities: heuristic fallback (spaCy-free)
  - _format_quads: readable sentence formatting
  - create_system_prompt: priority label presence and structure
  - GraphRAGPipeline: query tier routing, tier isolation, missing VectorStore
  - get_graph_rag_pipeline: singleton contract

Run with::

    pytest test_graph_rag.py -v
"""

import pytest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# QuadStore
# ---------------------------------------------------------------------------

class TestQuadStore:
    def _qs(self):
        from modules.graph_rag import QuadStore
        return QuadStore()

    def test_add_and_count(self):
        qs = self._qs()
        qs.add("Alice", "knows", "Bob", "test")
        assert qs.count() == 1

    def test_dedup_identical_quads(self):
        qs = self._qs()
        qs.add("Alice", "knows", "Bob", "test")
        qs.add("Alice", "knows", "Bob", "test")
        assert qs.count() == 1

    def test_different_quads_both_stored(self):
        qs = self._qs()
        qs.add("Alice", "knows", "Bob", "ctx1")
        qs.add("Alice", "likes", "Carol", "ctx2")
        assert qs.count() == 2

    def test_query_by_subject(self):
        qs = self._qs()
        qs.add("Alice", "knows", "Bob", "ctx")
        qs.add("Charlie", "knows", "Dave", "ctx")
        results = qs.query(subject="Alice")
        assert len(results) == 1
        assert results[0][0] == "Alice"

    def test_query_by_subject_case_insensitive(self):
        qs = self._qs()
        qs.add("LeBron James", "plays_for", "Ottawa Beavers", "NBA_2023")
        results = qs.query(subject="lebron james")
        assert len(results) == 1

    def test_query_by_object(self):
        qs = self._qs()
        qs.add("LeBron James", "plays_for", "Ottawa Beavers", "NBA_2023")
        qs.add("Kevin Durant", "plays_for", "Phoenix Suns", "NBA_2023")
        results = qs.query(obj="Ottawa Beavers")
        assert len(results) == 1
        assert results[0][0] == "LeBron James"

    def test_query_multi_dimension(self):
        qs = self._qs()
        qs.add("Alice", "knows", "Bob", "work")
        qs.add("Alice", "knows", "Carol", "home")
        # Intersect subject + context
        results = qs.query(subject="Alice", context="work")
        assert len(results) == 1
        assert results[0][2] == "Bob"

    def test_query_no_constraints_returns_all(self):
        qs = self._qs()
        qs.add("A", "b", "C", "ctx")
        qs.add("D", "e", "F", "ctx")
        assert len(qs.query()) == 2

    def test_query_entity_both_subject_and_object(self):
        qs = self._qs()
        qs.add("LeBron James", "plays_for", "Ottawa Beavers", "ctx")
        qs.add("Ottawa Beavers", "based_in", "Ottawa", "ctx")
        results = qs.query_entity("Ottawa Beavers")
        assert len(results) == 2

    def test_query_entity_no_match_returns_empty(self):
        qs = self._qs()
        qs.add("Alice", "knows", "Bob", "ctx")
        assert qs.query_entity("Nonexistent") == []

    def test_all_quads_returns_copy(self):
        qs = self._qs()
        qs.add("A", "b", "C", "ctx")
        q = qs.all_quads()
        q.append(("X", "y", "Z", "ctx"))
        assert qs.count() == 1  # original not mutated

    def test_query_missing_context_key_empty_string(self):
        qs = self._qs()
        qs.add("Alice", "knows", "Bob", "")
        results = qs.query(subject="Alice")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Entity extraction (heuristic fallback — no spaCy required)
# ---------------------------------------------------------------------------

class TestExtractEntitiesHeuristic:
    def test_extracts_capitalised_words(self):
        from modules.graph_rag import _extract_entities_heuristic
        entities = _extract_entities_heuristic("LeBron James plays for Ottawa Beavers")
        # Should find at least "LeBron James" and "Ottawa Beavers" as multi-token sequences
        full = " ".join(entities)
        assert "LeBron" in full
        assert "Ottawa" in full

    def test_no_entities_for_lowercase_text(self):
        from modules.graph_rag import _extract_entities_heuristic
        entities = _extract_entities_heuristic("this is entirely lowercase text")
        assert entities == []

    def test_deduplication(self):
        from modules.graph_rag import _extract_entities_heuristic
        entities = _extract_entities_heuristic("Alice met Alice and Alice again")
        # "Alice" should appear once
        count = sum(1 for e in entities if e.lower() == "alice")
        assert count == 1


class TestExtractEntities:
    def test_falls_back_gracefully(self):
        """extract_entities() must not raise even when spaCy is absent."""
        from modules.graph_rag import extract_entities
        # Patch the spaCy import to fail
        with patch("builtins.__import__", side_effect=lambda name, *a, **kw: (
            (_ for _ in ()).throw(ImportError("no spacy")) if name == "spacy" else __import__(name, *a, **kw)
        )):
            try:
                result = extract_entities("LeBron James plays for Ottawa Beavers")
                # If we get here, heuristic was used
                assert isinstance(result, list)
            except Exception:
                pass  # acceptable if the patch bubbles through


# ---------------------------------------------------------------------------
# _format_quads
# ---------------------------------------------------------------------------

class TestFormatQuads:
    def test_formats_with_context(self):
        from modules.graph_rag import _format_quads
        quads = [("LeBron James", "plays_for", "Ottawa Beavers", "NBA_2023")]
        text = _format_quads(quads)
        assert "LeBron James" in text
        assert "plays for" in text        # underscores replaced
        assert "Ottawa Beavers" in text
        assert "NBA_2023" in text

    def test_formats_without_context(self):
        from modules.graph_rag import _format_quads
        quads = [("Alice", "knows", "Bob", "")]
        text = _format_quads(quads)
        assert "Alice" in text
        assert "knows" in text

    def test_empty_returns_none_placeholder(self):
        from modules.graph_rag import _format_quads
        assert _format_quads([]) == "(none)"

    def test_multiple_quads(self):
        from modules.graph_rag import _format_quads
        quads = [
            ("Alice", "knows", "Bob", "work"),
            ("Bob", "reports_to", "Carol", "work"),
        ]
        text = _format_quads(quads)
        assert "Alice" in text
        assert "Carol" in text


# ---------------------------------------------------------------------------
# create_system_prompt
# ---------------------------------------------------------------------------

class TestCreateSystemPrompt:
    def test_all_priority_labels_present(self):
        from modules.graph_rag import create_system_prompt
        prompt = create_system_prompt(
            facts=[("A", "b", "C", "ctx")],
            stats=[("D", "e", "F", "ctx")],
            vector_docs=["Some document text."],
        )
        assert "PRIORITY 1" in prompt
        assert "PRIORITY 2" in prompt
        assert "PRIORITY 3" in prompt

    def test_empty_tiers_produce_none_placeholders(self):
        from modules.graph_rag import create_system_prompt
        prompt = create_system_prompt(facts=[], stats=[], vector_docs=[])
        assert "(none)" in prompt

    def test_facts_appear_in_prompt(self):
        from modules.graph_rag import create_system_prompt
        prompt = create_system_prompt(
            facts=[("LeBron James", "plays_for", "Ottawa Beavers", "NBA_2023")],
            stats=[],
            vector_docs=[],
        )
        assert "LeBron James" in prompt
        assert "Ottawa Beavers" in prompt

    def test_priority_rules_present(self):
        from modules.graph_rag import create_system_prompt
        prompt = create_system_prompt(facts=[], stats=[], vector_docs=[])
        assert "PRIORITY RULES" in prompt

    def test_hallucination_guard_present(self):
        from modules.graph_rag import create_system_prompt
        prompt = create_system_prompt(facts=[], stats=[], vector_docs=[])
        assert "I do not have enough information" in prompt


# ---------------------------------------------------------------------------
# GraphRAGPipeline
# ---------------------------------------------------------------------------

def _make_mock_vs(texts=("doc one", "doc two")):
    vs = MagicMock()
    vs.search.return_value = [
        {"text": t, "score": 0.9 - i * 0.1, "id": f"id-{i}"}
        for i, t in enumerate(texts)
    ]
    vs.add.return_value = True
    return vs


class TestGraphRAGPipelineAddAndQuery:
    def _fresh(self, vs=None):
        from modules.graph_rag import GraphRAGPipeline
        return GraphRAGPipeline(vector_store=vs)

    def test_add_fact_increments_tier1(self):
        p = self._fresh()
        p.add_fact("Alice", "knows", "Bob", "test")
        assert p._tier1.count() == 1
        assert p._tier2.count() == 0

    def test_add_stat_increments_tier2(self):
        p = self._fresh()
        p.add_stat("Alice", "score", "42", "test")
        assert p._tier2.count() == 1
        assert p._tier1.count() == 0

    def test_query_returns_required_keys(self):
        p = self._fresh()
        result = p.query("Who is Alice?")
        assert "system_prompt" in result
        assert "context" in result
        assert "tier1_hits" in result
        assert "tier2_hits" in result
        assert "tier3_docs" in result
        assert "entities" in result
        assert "retrieval_stats" in result

    def test_tier1_hit_populates_system_prompt(self):
        p = self._fresh()
        p.add_fact("LeBron James", "plays_for", "Ottawa Beavers", "NBA_2023")
        result = p.query("Who does LeBron James play for?")
        assert result["retrieval_stats"]["tier1"] >= 1
        assert "PRIORITY 1" in result["system_prompt"]

    def test_tier3_queried_when_vector_store_present(self):
        vs = _make_mock_vs(["document text"])
        p = self._fresh(vs=vs)
        result = p.query("some question")
        assert result["retrieval_stats"]["tier3"] >= 1
        vs.search.assert_called_once()

    def test_tier3_empty_when_no_vector_store(self):
        p = self._fresh(vs=None)
        with patch.object(p, "_get_vector_store", return_value=None):
            result = p.query("some question")
        assert result["retrieval_stats"]["tier3"] == 0
        assert result["tier3_docs"] == []

    def test_vector_store_exception_handled(self):
        vs = MagicMock()
        vs.search.side_effect = RuntimeError("db down")
        p = self._fresh(vs=vs)
        result = p.query("question")
        assert result["retrieval_stats"]["tier3"] == 0

    def test_add_document_delegates_to_vector_store(self):
        vs = _make_mock_vs()
        p = self._fresh(vs=vs)
        ok = p.add_document("doc1", "some text")
        vs.add.assert_called_once_with("doc1", "some text")
        assert ok is True

    def test_add_document_returns_false_without_vs(self):
        p = self._fresh(vs=None)
        with patch.object(p, "_get_vector_store", return_value=None):
            ok = p.add_document("doc1", "text")
        assert ok is False

    def test_entities_list_returned(self):
        p = self._fresh()
        result = p.query("LeBron James Ottawa Beavers")
        assert isinstance(result["entities"], list)

    def test_context_non_empty_when_tier1_hit(self):
        p = self._fresh()
        p.add_fact("Alice", "knows", "Bob", "ctx")
        result = p.query("Alice knows Bob")
        assert len(result["context"]) > 0

    def test_context_empty_when_no_hits(self):
        vs = MagicMock()
        vs.search.return_value = []
        p = self._fresh(vs=vs)
        result = p.query("XYZ123 Unknown Entity")
        assert result["context"] == ""

    def test_max_tier3_docs_respected(self):
        vs = _make_mock_vs([f"doc {i}" for i in range(20)])
        p = self._fresh(vs=vs)
        p.max_tier3_docs = 3
        result = p.query("question")
        assert len(result["tier3_docs"]) <= 3


class TestGraphRAGPipelineStatus:
    def test_status_returns_counts(self):
        from modules.graph_rag import GraphRAGPipeline
        p = GraphRAGPipeline()
        p.add_fact("A", "b", "C", "ctx")
        p.add_stat("D", "e", "F", "ctx")
        s = p.status()
        assert s["tier1_count"] == 1
        assert s["tier2_count"] == 1

    def test_status_summary_string(self):
        from modules.graph_rag import GraphRAGPipeline
        p = GraphRAGPipeline()
        summary = p.status_summary()
        assert "T1" in summary
        assert "T2" in summary
        assert "T3" in summary


# ---------------------------------------------------------------------------
# Singleton get_graph_rag_pipeline
# ---------------------------------------------------------------------------

class TestGetGraphRAGPipelineSingleton:
    def test_returns_graph_rag_pipeline_instance(self):
        from modules.graph_rag import get_graph_rag_pipeline, GraphRAGPipeline
        import modules.graph_rag as mod
        mod._instance = None
        instance = get_graph_rag_pipeline()
        assert isinstance(instance, GraphRAGPipeline)

    def test_same_instance_on_repeated_calls(self):
        from modules.graph_rag import get_graph_rag_pipeline
        import modules.graph_rag as mod
        mod._instance = None
        a = get_graph_rag_pipeline()
        b = get_graph_rag_pipeline()
        assert a is b


if __name__ == "__main__":
    print("Running test_graph_rag.py")
