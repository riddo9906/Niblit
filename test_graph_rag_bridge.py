"""
test_graph_rag_bridge.py — Unit tests for modules/graph_rag_bridge.py

Covers:
  - _kb_fact_to_quads: conversion of dict facts, string facts, empty inputs
  - _is_stat_fact: stat-tagging heuristic
  - GraphRAGBridge: ingest_single_fact (dedup, tier routing, doc push)
  - GraphRAGBridge: ingest_from_kb (mocked KnowledgeDB)
  - GraphRAGBridge: start_watch / stop_watch (lifecycle only — no sleep)
  - install_kb_hook: hook installation on mock KnowledgeDB
  - get_graph_rag_bridge: singleton contract

Run with::

    pytest test_graph_rag_bridge.py -v
"""

import pytest
from unittest.mock import MagicMock, patch, call
import threading


# ---------------------------------------------------------------------------
# _kb_fact_to_quads
# ---------------------------------------------------------------------------

class TestKbFactToQuads:
    def _fn(self, key, value, tags=None):
        from modules.graph_rag_bridge import _kb_fact_to_quads
        return _kb_fact_to_quads(key, value, tags)

    def test_dict_fact_with_topic_and_content(self):
        quads = self._fn(
            "ale_research:python:123",
            {"topic": "Python", "content": "Python is a language", "tier": "Foundation"},
        )
        assert len(quads) >= 1
        s, p, o, c = quads[0]
        assert s == "Python"
        assert "Python is a language" in o or "contains" in p

    def test_dict_fact_uses_source_as_predicate(self):
        quads = self._fn(
            "ale_research:ai:456",
            {"topic": "AI", "content": "AI does things", "source": "wikipedia", "tier": "Basic"},
        )
        s, p, o, c = quads[0]
        assert p == "wikipedia"

    def test_dict_fact_uses_step_as_predicate(self):
        quads = self._fn(
            "key",
            {"topic": "ML", "content": "Machine learning is...", "step": "step1_research"},
        )
        s, p, o, c = quads[0]
        assert p == "step1_research"

    def test_dict_fact_context_from_tier(self):
        quads = self._fn(
            "key",
            {"topic": "NLP", "content": "NLP text", "tier": "Advanced"},
        )
        s, p, o, c = quads[0]
        assert c == "Advanced"

    def test_dict_fact_context_from_tags_when_no_tier(self):
        quads = self._fn(
            "key",
            {"topic": "Cloud", "content": "Cloud computing..."},
            tags=["ale_step1", "research"],
        )
        s, p, o, c = quads[0]
        assert c == "ale_step1"

    def test_string_value_converted(self):
        quads = self._fn("mymodule:data", "some plain string value")
        assert len(quads) == 1
        s, p, o, c = quads[0]
        assert s == "mymodule"
        assert o == "some plain string value"

    def test_empty_string_returns_empty(self):
        quads = self._fn("key", "")
        assert quads == []

    def test_empty_dict_returns_empty(self):
        quads = self._fn("key", {})
        assert quads == []

    def test_dict_without_content_returns_empty(self):
        quads = self._fn("key", {"topic": "Thing", "step": "step1"})
        assert quads == []

    def test_content_truncated_to_200_chars(self):
        long_text = "A" * 500
        quads = self._fn("k", {"topic": "T", "content": long_text})
        _, _, o, _ = quads[0]
        assert len(o) <= 200

    def test_extra_fields_produce_extra_quads(self):
        quads = self._fn(
            "k",
            {
                "topic": "T",
                "content": "some content",
                "results_count": 42,
            },
        )
        # Base quad + extra field quad
        assert len(quads) >= 2
        predicates = [q[1] for q in quads]
        assert "results_count" in predicates


class TestIsStatFact:
    def _fn(self, key, tags):
        from modules.graph_rag_bridge import _is_stat_fact
        return _is_stat_fact(key, tags)

    def test_statistics_tag(self):
        assert self._fn("some_key", ["statistics"]) is True

    def test_data_tag(self):
        assert self._fn("some_key", ["data"]) is True

    def test_trading_tag(self):
        assert self._fn("some_key", ["trading"]) is True

    def test_stat_in_key(self):
        assert self._fn("key_stats_data", []) is True

    def test_regular_fact(self):
        assert self._fn("ale_research:python:123", ["ale_step1", "research"]) is False

    def test_empty_tags(self):
        assert self._fn("ale_research:python:123", []) is False


# ---------------------------------------------------------------------------
# GraphRAGBridge
# ---------------------------------------------------------------------------

def _make_mock_pipeline():
    """Return a mock GraphRAGPipeline."""
    p = MagicMock()
    p.add_fact = MagicMock()
    p.add_stat = MagicMock()
    p.add_document = MagicMock()
    p.status = MagicMock(return_value={"tier1_count": 0, "tier2_count": 0, "tier3_available": True})
    return p


def _make_mock_db(facts=None):
    """Return a mock KnowledgeDB."""
    db = MagicMock()
    db.list_facts = MagicMock(return_value=facts or [])
    db.add_fact = MagicMock()
    db._graph_rag_bridge_hooked = False
    return db


class TestGraphRAGBridgeIngestSingleFact:
    def _bridge(self):
        from modules.graph_rag_bridge import GraphRAGBridge
        return GraphRAGBridge(graph_rag_pipeline=_make_mock_pipeline())

    def test_dict_fact_inserts_quads(self):
        b = self._bridge()
        n = b.ingest_single_fact(
            "ale_research:ai:1",
            {"topic": "AI", "content": "AI is powerful", "tier": "Foundation"},
        )
        assert n > 0
        b._grp.add_fact.assert_called()

    def test_stat_fact_uses_add_stat(self):
        b = self._bridge()
        b.ingest_single_fact(
            "trading_stat:btc",
            {"topic": "BTC", "content": "BTC price rose", "tier": "trading"},
            tags=["statistics"],
        )
        b._grp.add_stat.assert_called()

    def test_regular_fact_uses_add_fact(self):
        b = self._bridge()
        b.ingest_single_fact(
            "ale_research:python:1",
            {"topic": "Python", "content": "Python is a language", "tier": "Foundation"},
            tags=["research"],
        )
        b._grp.add_fact.assert_called()

    def test_dedup_same_key(self):
        b = self._bridge()
        b.ingest_single_fact("k1", {"topic": "T", "content": "content here"})
        count1 = b._grp.add_fact.call_count
        # Second call with same key should be no-op
        n = b.ingest_single_fact("k1", {"topic": "T", "content": "content here"})
        assert n == 0
        assert b._grp.add_fact.call_count == count1

    def test_long_text_pushed_as_document(self):
        b = self._bridge()
        long_content = "A" * 300
        b.ingest_single_fact(
            "k2",
            {"topic": "T", "content": long_content, "full_text": long_content},
        )
        b._grp.add_document.assert_called()

    def test_no_pipeline_returns_zero(self):
        from modules.graph_rag_bridge import GraphRAGBridge
        b = GraphRAGBridge(graph_rag_pipeline=None)
        with patch.object(b, "_get_pipeline", return_value=None):
            n = b.ingest_single_fact("k", {"topic": "T", "content": "C"})
        assert n == 0

    def test_empty_value_returns_zero(self):
        b = self._bridge()
        n = b.ingest_single_fact("k", {})
        assert n == 0

    def test_empty_subject_skipped(self):
        b = self._bridge()
        # A dict without topic produces no subject → quads are skipped
        n = b.ingest_single_fact("k", {"step": "s1", "content": "x"})
        assert n == 0


class TestGraphRAGBridgeIngestFromKb:
    def test_ingests_all_facts_from_kb(self):
        from modules.graph_rag_bridge import GraphRAGBridge
        facts = [
            {"key": "ale:ai:1", "value": {"topic": "AI", "content": "AI does X", "tier": "F"}, "tags": ["ale_step1"]},
            {"key": "ale:ml:2", "value": {"topic": "ML", "content": "ML learns Y", "tier": "B"}, "tags": ["ale_step1"]},
        ]
        db = _make_mock_db(facts=facts)
        p = _make_mock_pipeline()
        b = GraphRAGBridge(knowledge_db=db, graph_rag_pipeline=p)
        total = b.ingest_from_kb()
        assert total > 0
        db.list_facts.assert_called_once()

    def test_no_db_returns_zero(self):
        from modules.graph_rag_bridge import GraphRAGBridge
        b = GraphRAGBridge(knowledge_db=None, graph_rag_pipeline=_make_mock_pipeline())
        assert b.ingest_from_kb() == 0

    def test_empty_kb_returns_zero(self):
        from modules.graph_rag_bridge import GraphRAGBridge
        b = GraphRAGBridge(knowledge_db=_make_mock_db(facts=[]), graph_rag_pipeline=_make_mock_pipeline())
        assert b.ingest_from_kb() == 0

    def test_background_param_starts_thread(self):
        from modules.graph_rag_bridge import GraphRAGBridge
        facts = [
            {"key": "ale:ai:1", "value": {"topic": "AI", "content": "AI does X", "tier": "F"}, "tags": []},
        ]
        b = GraphRAGBridge(knowledge_db=_make_mock_db(facts=facts), graph_rag_pipeline=_make_mock_pipeline())
        ret = b.ingest_from_kb(background=True)
        assert ret == 0  # background mode returns immediately

    def test_malformed_fact_handled_gracefully(self):
        from modules.graph_rag_bridge import GraphRAGBridge
        facts = [None, "bad_string", {"key": "", "value": {}, "tags": []}]
        b = GraphRAGBridge(knowledge_db=_make_mock_db(facts=facts), graph_rag_pipeline=_make_mock_pipeline())
        # Should not raise
        b.ingest_from_kb()


class TestGraphRAGBridgeStatus:
    def test_status_keys_present(self):
        from modules.graph_rag_bridge import GraphRAGBridge
        b = GraphRAGBridge(knowledge_db=_make_mock_db(), graph_rag_pipeline=_make_mock_pipeline())
        s = b.status()
        assert "kb_available" in s
        assert "keys_ingested" in s
        assert "tier1_quads" in s
        assert "tier2_quads" in s
        assert "watch_running" in s

    def test_status_summary_string(self):
        from modules.graph_rag_bridge import GraphRAGBridge
        b = GraphRAGBridge(knowledge_db=_make_mock_db(), graph_rag_pipeline=_make_mock_pipeline())
        summary = b.status_summary()
        assert "T1" in summary
        assert "T2" in summary


class TestGraphRAGBridgeWatchLifecycle:
    def test_start_stop_watch(self):
        from modules.graph_rag_bridge import GraphRAGBridge
        b = GraphRAGBridge(knowledge_db=_make_mock_db(), graph_rag_pipeline=_make_mock_pipeline(), watch_interval=1)
        b.start_watch()
        assert b._watch_thread is not None
        b.stop_watch()

    def test_watch_disabled_at_zero_interval(self):
        from modules.graph_rag_bridge import GraphRAGBridge
        b = GraphRAGBridge(knowledge_db=_make_mock_db(), graph_rag_pipeline=_make_mock_pipeline(), watch_interval=0)
        b.start_watch()
        assert b._watch_thread is None

    def test_double_start_watch_no_second_thread(self):
        from modules.graph_rag_bridge import GraphRAGBridge
        b = GraphRAGBridge(knowledge_db=_make_mock_db(), graph_rag_pipeline=_make_mock_pipeline(), watch_interval=60)
        b.start_watch()
        t1 = b._watch_thread
        b.start_watch()
        assert b._watch_thread is t1  # same thread object
        b.stop_watch()


# ---------------------------------------------------------------------------
# install_kb_hook
# ---------------------------------------------------------------------------

class TestInstallKbHook:
    def test_hook_installed(self):
        from modules.graph_rag_bridge import install_kb_hook, GraphRAGBridge
        db = _make_mock_db()
        b = GraphRAGBridge(graph_rag_pipeline=_make_mock_pipeline())
        result = install_kb_hook(db, b)
        assert result is True
        assert getattr(db, "_graph_rag_bridge_hooked", False) is True

    def test_hook_calls_ingest_on_add_fact(self):
        from modules.graph_rag_bridge import install_kb_hook, GraphRAGBridge
        db = _make_mock_db()
        b = GraphRAGBridge(graph_rag_pipeline=_make_mock_pipeline())
        install_kb_hook(db, b)
        # Calling the hooked add_fact should trigger ingest
        called = []
        original_ingest = b.ingest_single_fact
        b.ingest_single_fact = lambda *a, **kw: called.append(a) or 1
        db.add_fact("test_key", {"topic": "T", "content": "C"}, ["tag"])
        assert len(called) == 1
        assert called[0][0] == "test_key"

    def test_double_hook_is_no_op(self):
        from modules.graph_rag_bridge import install_kb_hook, GraphRAGBridge
        db = _make_mock_db()
        b = GraphRAGBridge(graph_rag_pipeline=_make_mock_pipeline())
        r1 = install_kb_hook(db, b)
        r2 = install_kb_hook(db, b)
        assert r1 is True
        assert r2 is True  # idempotent

    def test_none_db_returns_false(self):
        from modules.graph_rag_bridge import install_kb_hook, GraphRAGBridge
        b = GraphRAGBridge(graph_rag_pipeline=_make_mock_pipeline())
        assert install_kb_hook(None, b) is False

    def test_none_bridge_returns_false(self):
        from modules.graph_rag_bridge import install_kb_hook
        db = _make_mock_db()
        assert install_kb_hook(db, None) is False


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestGetGraphRAGBridgeSingleton:
    def test_returns_bridge_instance(self):
        from modules.graph_rag_bridge import get_graph_rag_bridge, GraphRAGBridge
        import modules.graph_rag_bridge as mod
        mod._instance = None
        b = get_graph_rag_bridge()
        assert isinstance(b, GraphRAGBridge)

    def test_same_instance_repeated(self):
        from modules.graph_rag_bridge import get_graph_rag_bridge
        import modules.graph_rag_bridge as mod
        mod._instance = None
        a = get_graph_rag_bridge()
        b = get_graph_rag_bridge()
        assert a is b

    def test_late_bind_kb(self):
        from modules.graph_rag_bridge import get_graph_rag_bridge
        import modules.graph_rag_bridge as mod
        mod._instance = None
        b1 = get_graph_rag_bridge(knowledge_db=None)
        assert b1.knowledge_db is None
        db = _make_mock_db()
        b2 = get_graph_rag_bridge(knowledge_db=db)
        assert b1 is b2
        assert b1.knowledge_db is db


if __name__ == "__main__":
    print("Running test_graph_rag_bridge.py")
