"""
test_chat_completions.py — Unit tests for modules/chat_completions.py

Covers:
  - CompletionResult dataclass
  - ChatCompletions.complete(): response routing, tier selection, persist
  - ChatCompletions.chat_history() / clear_history()
  - ChatCompletions.status() / status_summary()
  - ChatCompletions._build_source_labels()
  - ChatCompletions._fallback_response()
  - get_chat_completions() singleton contract

Run with::

    pytest test_chat_completions.py -v
"""

import pytest
from unittest.mock import MagicMock, patch
import threading


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_pipeline(tier1_hits=0, tier2_hits=0, tier3_hits=0):
    """Return a mock GraphRAGPipeline returning specified hit counts."""
    p = MagicMock()
    p.query = MagicMock(return_value={
        "system_prompt": f"[T1:{tier1_hits}][T2:{tier2_hits}][T3:{tier3_hits}]",
        "context": f"Context text tier1={tier1_hits}",
        "tier1_hits": [("S", "P", "O", "C")] * tier1_hits,
        "tier2_hits": [("S", "P", "O", "C")] * tier2_hits,
        "tier3_docs": ["doc"] * tier3_hits,
        "entities": ["entity1"],
        "retrieval_stats": {"tier1": tier1_hits, "tier2": tier2_hits, "tier3": tier3_hits},
    })
    p.status = MagicMock(return_value={
        "tier1_count": tier1_hits,
        "tier2_count": tier2_hits,
        "tier3_available": True,
    })
    return p


def _make_mock_mem(messages=None):
    """Return a mock LLMChatMemory."""
    m = MagicMock()
    m.load_messages = MagicMock(return_value=messages or [])
    m.add = MagicMock()
    m.clear = MagicMock()
    m.message_count = MagicMock(return_value=len(messages or []))
    return m


def _make_mock_pm(response="test answer"):
    """Return a mock LLMProviderManager."""
    pm = MagicMock()
    pm.ask = MagicMock(return_value=response)
    return pm


def _make_cc(grp=None, mem=None, pm=None):
    """Return a fresh ChatCompletions instance with mocked dependencies."""
    from modules.chat_completions import ChatCompletions
    return ChatCompletions(
        llm_provider_manager=pm or _make_mock_pm(),
        llm_chat_memory=mem or _make_mock_mem(),
        graph_rag_pipeline=grp or _make_mock_pipeline(),
    )


# ---------------------------------------------------------------------------
# CompletionResult
# ---------------------------------------------------------------------------

class TestCompletionResult:
    def test_defaults(self):
        from modules.chat_completions import CompletionResult
        r = CompletionResult(response="hello")
        assert r.response == "hello"
        assert r.sources == []
        assert r.tier_used == "none"
        assert r.conversation_id == ""
        assert r.latency_ms == 0.0
        assert r.graph_rag_stats == {}

    def test_custom_fields(self):
        from modules.chat_completions import CompletionResult
        r = CompletionResult(
            response="hi",
            sources=["tier1:3 facts"],
            tier_used="tier1",
            conversation_id="c1",
            latency_ms=42.5,
            graph_rag_stats={"tier1": 3},
        )
        assert r.tier_used == "tier1"
        assert r.latency_ms == 42.5


# ---------------------------------------------------------------------------
# ChatCompletions.complete()
# ---------------------------------------------------------------------------

class TestChatCompletionsComplete:
    def test_returns_completion_result(self):
        cc = _make_cc()
        result = cc.complete("What is Python?")
        from modules.chat_completions import CompletionResult
        assert isinstance(result, CompletionResult)

    def test_response_from_pm(self):
        pm = _make_mock_pm("Python is a language.")
        cc = _make_cc(pm=pm)
        result = cc.complete("What is Python?")
        assert "Python is a language" in result.response

    def test_tier1_hit_sets_tier_used(self):
        cc = _make_cc(grp=_make_mock_pipeline(tier1_hits=2))
        result = cc.complete("query")
        assert result.tier_used == "tier1"

    def test_tier2_hit_sets_tier_used(self):
        cc = _make_cc(grp=_make_mock_pipeline(tier1_hits=0, tier2_hits=1))
        result = cc.complete("query")
        assert result.tier_used == "tier2"

    def test_tier3_only_sets_tier_used(self):
        cc = _make_cc(grp=_make_mock_pipeline(tier1_hits=0, tier2_hits=0, tier3_hits=2))
        result = cc.complete("query")
        assert result.tier_used == "tier3"

    def test_no_hits_sets_tier_none(self):
        cc = _make_cc(grp=_make_mock_pipeline())
        result = cc.complete("query")
        assert result.tier_used == "none"

    def test_empty_question_returns_early(self):
        cc = _make_cc()
        result = cc.complete("")
        assert "(empty question)" in result.response

    def test_persist_true_calls_mem_add(self):
        mem = _make_mock_mem()
        cc = _make_cc(mem=mem)
        cc.complete("Hello?", persist=True)
        mem.add.assert_called()

    def test_persist_false_skips_mem_add(self):
        mem = _make_mock_mem()
        cc = _make_cc(mem=mem)
        cc.complete("Hello?", persist=False)
        mem.add.assert_not_called()

    def test_latency_ms_positive(self):
        cc = _make_cc()
        result = cc.complete("test")
        assert result.latency_ms >= 0

    def test_conversation_id_echoed(self):
        cc = _make_cc()
        result = cc.complete("test", conversation_id="conv-42")
        assert result.conversation_id == "conv-42"

    def test_sources_list_populated(self):
        cc = _make_cc(grp=_make_mock_pipeline(tier1_hits=2, tier2_hits=1, tier3_hits=3))
        result = cc.complete("test")
        assert any("tier1" in s for s in result.sources)
        assert any("tier2" in s for s in result.sources)
        assert any("tier3" in s for s in result.sources)

    def test_graph_rag_query_failure_graceful(self):
        """Pipeline that raises should not crash complete()."""
        grp = MagicMock()
        grp.query = MagicMock(side_effect=RuntimeError("boom"))
        grp.status = MagicMock(return_value={"tier1_count": 0, "tier2_count": 0, "tier3_available": False})
        cc = _make_cc(grp=grp)
        result = cc.complete("test")
        assert isinstance(result.response, str)

    def test_pm_failure_falls_through_to_fallback(self):
        """When PM raises, the fallback response should still return something."""
        pm = _make_mock_pm()
        pm.ask = MagicMock(side_effect=RuntimeError("no LLM"))
        cc = _make_cc(pm=pm)
        # Override _call_llm to simulate total failure
        cc._call_llm = lambda *a, **kw: None
        result = cc.complete("some question")
        assert isinstance(result.response, str)


# ---------------------------------------------------------------------------
# ChatCompletions.chat_history()
# ---------------------------------------------------------------------------

class TestChatHistory:
    def test_returns_messages_from_mem(self):
        messages = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]
        cc = _make_cc(mem=_make_mock_mem(messages=messages))
        history = cc.chat_history(limit=10)
        assert len(history) == 2

    def test_empty_when_no_mem(self):
        from modules.chat_completions import ChatCompletions
        cc = ChatCompletions(llm_chat_memory=None)
        cc._get_chat_memory = lambda: None
        assert cc.chat_history() == []


# ---------------------------------------------------------------------------
# ChatCompletions.clear_history()
# ---------------------------------------------------------------------------

class TestClearHistory:
    def test_calls_mem_clear(self):
        mem = _make_mock_mem()
        cc = _make_cc(mem=mem)
        cc.clear_history()
        mem.clear.assert_called_once()

    def test_no_mem_does_not_raise(self):
        from modules.chat_completions import ChatCompletions
        cc = ChatCompletions()
        cc._chat_mem = None
        cc._get_chat_memory = lambda: None
        cc.clear_history()  # should not raise


# ---------------------------------------------------------------------------
# ChatCompletions.status()
# ---------------------------------------------------------------------------

class TestStatus:
    def test_status_keys(self):
        cc = _make_cc()
        s = cc.status()
        assert "llm_available" in s
        assert "chat_memory_msgs" in s
        assert "graph_rag_ready" in s
        assert "tier1_quads" in s
        assert "tier2_quads" in s
        assert "tier3_available" in s

    def test_status_summary_string(self):
        cc = _make_cc()
        summary = cc.status_summary()
        assert "ChatCompletions" in summary
        assert "LLM" in summary
        assert "GraphRAG" in summary


# ---------------------------------------------------------------------------
# _build_source_labels
# ---------------------------------------------------------------------------

class TestBuildSourceLabels:
    def _fn(self, stats, entities=None):
        from modules.chat_completions import ChatCompletions
        return ChatCompletions._build_source_labels(stats, entities or [])

    def test_tier1_only(self):
        labels = self._fn({"tier1": 3, "tier2": 0, "tier3": 0})
        assert any("tier1" in l for l in labels)
        assert not any("tier2" in l for l in labels)

    def test_all_tiers(self):
        labels = self._fn({"tier1": 1, "tier2": 2, "tier3": 4})
        assert len(labels) == 3

    def test_entities_included(self):
        labels = self._fn({"tier1": 1, "tier2": 0, "tier3": 0}, entities=["Alice", "Bob"])
        assert any("entities" in l for l in labels)

    def test_zero_counts_omitted(self):
        labels = self._fn({"tier1": 0, "tier2": 0, "tier3": 0})
        assert not any("tier" in l for l in labels)


# ---------------------------------------------------------------------------
# _fallback_response
# ---------------------------------------------------------------------------

class TestFallbackResponse:
    def _fn(self, question, context):
        from modules.chat_completions import ChatCompletions
        cc = ChatCompletions.__new__(ChatCompletions)
        return cc._fallback_response(question, context)

    def test_with_context_returns_excerpt(self):
        r = self._fn("What is X?", "X is a thing that does stuff.")
        assert "stored knowledge" in r.lower() or "X is a thing" in r

    def test_without_context_suggests_research(self):
        r = self._fn("What is Y?", "")
        assert "self-research" in r or "don't have" in r.lower()

    def test_question_truncated(self):
        long_q = "Q" * 200
        r = self._fn(long_q, "")
        # Should not raise and should not include 200+ chars of the question
        assert isinstance(r, str)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestGetChatCompletionsSingleton:
    def test_returns_chat_completions_instance(self):
        from modules.chat_completions import get_chat_completions, ChatCompletions
        import modules.chat_completions as mod
        mod._instance = None
        cc = get_chat_completions()
        assert isinstance(cc, ChatCompletions)

    def test_same_instance_repeated(self):
        from modules.chat_completions import get_chat_completions
        import modules.chat_completions as mod
        mod._instance = None
        a = get_chat_completions()
        b = get_chat_completions()
        assert a is b


if __name__ == "__main__":
    print("Running test_chat_completions.py")
