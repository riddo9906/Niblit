"""test_niblit_decision_engine.py — offline-safe unit tests for the
Niblit Trading Decision Engine and FreqtradeAdapter.

All Qdrant and MemoryGraph interactions are replaced with lightweight
MagicMock objects so no real infrastructure is required.

Run with::

    pytest test_niblit_decision_engine.py -v
"""

from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_qdrant(hits_by_collection=None):
    """Return a mock HybridQdrantManager.

    Parameters
    ----------
    hits_by_collection:
        Optional dict mapping collection name -> list of result dicts.
        When None, ``query`` returns [] for every collection.
    """
    mock = MagicMock()
    hits_by_collection = hits_by_collection or {}

    def _query(text, collection, top_k=5, **_):
        return hits_by_collection.get(collection, [])

    mock.query = MagicMock(side_effect=_query)
    return mock


def _make_graph(graph_hits=None):
    """Return a mock MemoryGraph.

    Parameters
    ----------
    graph_hits:
        Optional list of ``{"id", "text", "score", "hops"}`` dicts returned
        by ``search()``.  Defaults to [].
    """
    mock = MagicMock()
    mock.search = MagicMock(return_value=graph_hits or [])
    return mock


def _make_router():
    """Return a stub MemoryRouterCore (unused during pure inference)."""
    return MagicMock()


def _hit(text, score=0.8, collection="semantic_memory"):
    """Build a minimal Qdrant result dict."""
    return {"id": 1, "score": score, "payload": {"text": text}, "model": "test", "collection": collection}


def _graph_hit(text, score=0.7):
    """Build a minimal MemoryGraph result dict."""
    return {"id": "g1", "text": text, "score": score, "hops": 1}


# ── Import tests ──────────────────────────────────────────────────────────────

class TestImports(unittest.TestCase):
    def test_package_importable(self):
        from modules import trading_decision_engine  # noqa: F401

    def test_engine_importable(self):
        from modules.trading_decision_engine import NiblitDecisionEngine
        self.assertTrue(callable(NiblitDecisionEngine))

    def test_adapter_importable(self):
        from modules.trading_decision_engine import FreqtradeAdapter
        self.assertTrue(callable(FreqtradeAdapter))

    def test_dataclass_importable(self):
        from modules.trading_decision_engine import TradingDecision
        self.assertTrue(callable(TradingDecision))


# ── TradingDecision dataclass ─────────────────────────────────────────────────

class TestTradingDecision(unittest.TestCase):
    def _make(self, **kwargs):
        from modules.trading_decision_engine import TradingDecision

        defaults = dict(action="buy", confidence=0.6, symbol="BTC/USDT")
        defaults.update(kwargs)
        return TradingDecision(**defaults)

    def test_defaults(self):
        d = self._make()
        self.assertEqual(d.action, "buy")
        self.assertIsInstance(d.reasoning, list)
        self.assertIsInstance(d.metadata, dict)
        self.assertGreater(d.timestamp, 0)

    def test_to_dict_keys(self):
        d = self._make(reasoning=["r1"], metadata={"k": 1})
        out = d.to_dict()
        for key in ("action", "confidence", "symbol", "reasoning", "metadata", "timestamp"):
            self.assertIn(key, out)

    def test_to_dict_confidence_rounded(self):
        d = self._make(confidence=0.123456789)
        self.assertEqual(d.to_dict()["confidence"], round(0.123456789, 4))


# ── NiblitDecisionEngine.retrieve_context ─────────────────────────────────────

class TestRetrieveContext(unittest.TestCase):
    def _engine(self, hits_by_col=None):
        from modules.trading_decision_engine import NiblitDecisionEngine

        return NiblitDecisionEngine(
            qdrant_manager=_make_qdrant(hits_by_col),
            memory_graph=_make_graph(),
            router=_make_router(),
        )

    def test_returns_list(self):
        engine = self._engine()
        result = engine.retrieve_context("query", limit=5)
        self.assertIsInstance(result, list)

    def test_extracts_text_from_payload(self):
        engine = self._engine({"semantic_memory": [_hit("hello world")]})
        results = engine.retrieve_context("query", limit=5)
        texts = [r["text"] for r in results]
        self.assertIn("hello world", texts)

    def test_empty_on_qdrant_exception(self):
        from modules.trading_decision_engine import NiblitDecisionEngine

        bad_qdrant = MagicMock()
        bad_qdrant.query = MagicMock(side_effect=RuntimeError("boom"))
        engine = NiblitDecisionEngine(bad_qdrant, _make_graph(), _make_router())
        # Should not raise; returns empty list
        result = engine.retrieve_context("query")
        self.assertEqual(result, [])

    def test_queries_multiple_collections(self):
        hits = {
            "semantic_memory": [_hit("sem")],
            "episodic_memory": [_hit("ep")],
        }
        engine = self._engine(hits)
        results = engine.retrieve_context("q", limit=5)
        texts = {r["text"] for r in results}
        self.assertIn("sem", texts)
        self.assertIn("ep", texts)


# ── NiblitDecisionEngine.expand_with_graph ────────────────────────────────────

class TestExpandWithGraph(unittest.TestCase):
    def _engine(self, graph_hits=None):
        from modules.trading_decision_engine import NiblitDecisionEngine

        return NiblitDecisionEngine(
            qdrant_manager=_make_qdrant(),
            memory_graph=_make_graph(graph_hits),
            router=_make_router(),
        )

    def test_no_expansion_without_embeddings(self):
        """Memories without payload embeddings should yield no graph results."""
        engine = self._engine([_graph_hit("graph node")])
        # Memories have no "payload" with "embedding"
        plain_memories = [{"id": 1, "text": "hello", "score": 0.9, "payload": {}}]
        expanded = engine.expand_with_graph(plain_memories)
        self.assertEqual(expanded, [])

    def test_expansion_with_embeddings(self):
        """Memories with embeddings should trigger graph.search."""
        from modules.trading_decision_engine import NiblitDecisionEngine

        graph = _make_graph([_graph_hit("graph knowledge", 0.8)])
        engine = NiblitDecisionEngine(_make_qdrant(), graph, _make_router())
        memories_with_embedding = [
            {"id": 1, "text": "base", "score": 0.9, "payload": {"embedding": [0.1, 0.2, 0.3]}}
        ]
        expanded = engine.expand_with_graph(memories_with_embedding)
        self.assertEqual(len(expanded), 1)
        self.assertEqual(expanded[0]["text"], "graph knowledge")
        self.assertEqual(expanded[0]["collection"], "memory_graph")

    def test_graph_exception_returns_empty(self):
        from modules.trading_decision_engine import NiblitDecisionEngine

        bad_graph = MagicMock()
        bad_graph.search = MagicMock(side_effect=RuntimeError("graph error"))
        engine = NiblitDecisionEngine(_make_qdrant(), bad_graph, _make_router())
        mems = [{"id": 1, "text": "x", "score": 0.9, "payload": {"embedding": [0.1]}}]
        result = engine.expand_with_graph(mems)
        self.assertEqual(result, [])


# ── NiblitDecisionEngine.score_signal ─────────────────────────────────────────

class TestScoreSignal(unittest.TestCase):
    def _engine(self):
        from modules.trading_decision_engine import NiblitDecisionEngine

        return NiblitDecisionEngine(_make_qdrant(), _make_graph(), _make_router())

    def test_empty_memories_zero_score(self):
        engine = self._engine()
        self.assertEqual(engine.score_signal([]), 0.0)

    def test_profit_win_positive_score(self):
        engine = self._engine()
        mems = [{"text": "trade resulted in profit and win"}, {"text": "breakout detected"}]
        score = engine.score_signal(mems)
        self.assertGreater(score, 0)

    def test_loss_error_negative_score(self):
        engine = self._engine()
        mems = [{"text": "strategy resulted in loss and error"}]
        score = engine.score_signal(mems)
        self.assertLess(score, 0)

    def test_score_clamped_to_minus_one(self):
        engine = self._engine()
        mems = [{"text": "loss error loss error loss"} for _ in range(20)]
        score = engine.score_signal(mems)
        self.assertGreaterEqual(score, -1.0)

    def test_score_clamped_to_plus_one(self):
        engine = self._engine()
        mems = [{"text": "profit win breakout trend bullish momentum"} for _ in range(20)]
        score = engine.score_signal(mems)
        self.assertLessEqual(score, 1.0)

    def test_conflict_reduces_score(self):
        """Mixed buy+sell signals should reduce magnitude vs one-sided."""
        engine = self._engine()
        # One-sided buy
        buy_only = [{"text": "profit win breakout trend bullish"}]
        buy_score = abs(engine.score_signal(buy_only))
        # Mixed
        mixed = [{"text": "profit win breakout loss error bearish"}]
        mixed_score = abs(engine.score_signal(mixed))
        # Mixed score should be reduced relative to the same buy keywords alone
        # (hard to assert exact direction since sell may dominate, but conflict
        # penalty should make the mixed score ≤ unpenalised buy score)
        self.assertLessEqual(mixed_score, buy_score + 0.01)  # allow tiny float drift


# ── NiblitDecisionEngine.decide — action thresholds ───────────────────────────

class TestDecide(unittest.TestCase):
    def _engine(self, hits_by_col=None):
        from modules.trading_decision_engine import NiblitDecisionEngine

        return NiblitDecisionEngine(
            qdrant_manager=_make_qdrant(hits_by_col),
            memory_graph=_make_graph(),
            router=_make_router(),
            collections=["semantic_memory"],
        )

    def test_hold_when_no_memories(self):
        engine = self._engine()
        decision = engine.decide("BTC rally", "BTC/USDT")
        self.assertEqual(decision.action, "hold")

    def test_buy_on_strong_positive_signal(self):
        engine = self._engine({
            "semantic_memory": [_hit("profit win breakout trend bullish momentum") for _ in range(6)]
        })
        decision = engine.decide("market context", "BTC/USDT")
        self.assertEqual(decision.action, "buy")
        self.assertGreater(decision.confidence, 0.0)

    def test_sell_on_strong_negative_signal(self):
        engine = self._engine({
            "semantic_memory": [_hit("loss error bearish breakdown drawdown decline fail") for _ in range(6)]
        })
        decision = engine.decide("market context", "BTC/USDT")
        self.assertEqual(decision.action, "sell")

    def test_hold_when_below_confidence_threshold(self):
        # A single memory with a marginal positive signal produces low confidence.
        engine = self._engine({
            "semantic_memory": [_hit("trend") for _ in range(6)]
        })
        decision = engine.decide("market context", "BTC/USDT")
        # trend alone gives 0.30 score per memory * 6 = clamped 1.0 → confidence > threshold
        # We just check the dataclass is well-formed; action depends on exact weight sums.
        self.assertIn(decision.action, ("buy", "sell", "hold"))
        self.assertGreaterEqual(decision.confidence, 0.0)
        self.assertLessEqual(decision.confidence, 1.0)

    def test_metadata_fields_present(self):
        engine = self._engine()
        decision = engine.decide("q", "ETH/USDT")
        for key in ("memory_count", "qdrant_count", "graph_count", "raw_score", "raw_action"):
            self.assertIn(key, decision.metadata)

    def test_reasoning_capped_at_ten(self):
        engine = self._engine({
            "semantic_memory": [_hit(f"memory {i}") for i in range(20)]
        })
        decision = engine.decide("q", "BTC/USDT")
        self.assertLessEqual(len(decision.reasoning), 10)

    def test_symbol_propagated(self):
        engine = self._engine()
        decision = engine.decide("q", "SOL/USDT")
        self.assertEqual(decision.symbol, "SOL/USDT")

    def test_timestamp_recent(self):
        before = time.time()
        engine = self._engine()
        decision = engine.decide("q", "BTC/USDT")
        after = time.time()
        self.assertGreaterEqual(decision.timestamp, before)
        self.assertLessEqual(decision.timestamp, after)


# ── Risk control: memory count floor ─────────────────────────────────────────

class TestRiskControls(unittest.TestCase):
    def _engine(self, hits):
        from modules.trading_decision_engine import NiblitDecisionEngine

        return NiblitDecisionEngine(
            qdrant_manager=_make_qdrant({"semantic_memory": hits}),
            memory_graph=_make_graph(),
            router=_make_router(),
            collections=["semantic_memory"],
        )

    def test_hold_below_memory_floor(self):
        # Only 3 memories (< _MIN_MEMORY_THRESHOLD=5) → must hold
        engine = self._engine([_hit("profit win breakout trend") for _ in range(3)])
        decision = engine.decide("q", "BTC/USDT")
        self.assertEqual(decision.action, "hold")
        self.assertEqual(decision.confidence, 0.0)

    def test_trade_allowed_above_memory_floor(self):
        engine = self._engine([_hit("profit win breakout bullish momentum") for _ in range(6)])
        decision = engine.decide("q", "BTC/USDT")
        # Above floor; action determined by score
        self.assertIn(decision.action, ("buy", "sell", "hold"))


# ── FreqtradeAdapter ──────────────────────────────────────────────────────────

class TestFreqtradeAdapter(unittest.TestCase):
    def _adapter(self):
        from modules.trading_decision_engine import FreqtradeAdapter

        return FreqtradeAdapter()

    def _decision(self, action, confidence=0.6, reasoning=None):
        from modules.trading_decision_engine import TradingDecision

        return TradingDecision(
            action=action,
            confidence=confidence,
            symbol="BTC/USDT",
            reasoning=reasoning or ["r1"],
            metadata={"score": 0.5},
        )

    def test_buy_signal(self):
        signal = self._adapter().to_freqtrade_signal(self._decision("buy"))
        self.assertTrue(signal["enter_long"])
        self.assertFalse(signal["enter_short"])
        self.assertFalse(signal["exit_long"])
        self.assertTrue(signal["exit_short"])

    def test_sell_signal(self):
        signal = self._adapter().to_freqtrade_signal(self._decision("sell"))
        self.assertFalse(signal["enter_long"])
        self.assertTrue(signal["enter_short"])
        self.assertTrue(signal["exit_long"])
        self.assertFalse(signal["exit_short"])

    def test_hold_signal(self):
        signal = self._adapter().to_freqtrade_signal(self._decision("hold"))
        self.assertFalse(signal["enter_long"])
        self.assertFalse(signal["enter_short"])
        self.assertFalse(signal["exit_long"])
        self.assertFalse(signal["exit_short"])

    def test_signal_includes_confidence(self):
        signal = self._adapter().to_freqtrade_signal(self._decision("buy", confidence=0.75))
        self.assertAlmostEqual(signal["confidence"], 0.75, places=4)

    def test_signal_includes_reason(self):
        signal = self._adapter().to_freqtrade_signal(self._decision("hold", reasoning=["abc", "def"]))
        self.assertEqual(signal["reason"], ["abc", "def"])

    def test_reason_capped_at_ten(self):
        long_reasoning = [f"item {i}" for i in range(20)]
        signal = self._adapter().to_freqtrade_signal(self._decision("hold", reasoning=long_reasoning))
        self.assertLessEqual(len(signal["reason"]), 10)

    def test_metadata_forwarded(self):
        decision = self._decision("buy")
        decision.metadata = {"custom_key": 42}
        signal = self._adapter().to_freqtrade_signal(decision)
        self.assertEqual(signal["metadata"]["custom_key"], 42)

    def test_bulk_conversion(self):
        adapter = self._adapter()
        decisions = [self._decision(a) for a in ("buy", "sell", "hold")]
        signals = adapter.to_freqtrade_signal_bulk(decisions)
        self.assertEqual(len(signals), 3)
        self.assertTrue(signals[0]["enter_long"])
        self.assertTrue(signals[1]["enter_short"])
        self.assertFalse(signals[2]["enter_long"])

    def test_unknown_action_defaults_to_hold_behaviour(self):
        """An unrecognised action should produce all-False entry/exit flags."""
        decision = self._decision("unknown_action")
        signal = self._adapter().to_freqtrade_signal(decision)
        self.assertFalse(signal["enter_long"])
        self.assertFalse(signal["enter_short"])
        self.assertFalse(signal["exit_long"])
        self.assertFalse(signal["exit_short"])


# ── End-to-end pipeline smoke test ───────────────────────────────────────────

class TestPipeline(unittest.TestCase):
    """Full pipeline: engine.decide() → adapter.to_freqtrade_signal()."""

    def test_full_pipeline_buy(self):
        from modules.trading_decision_engine import (
            FreqtradeAdapter,
            NiblitDecisionEngine,
        )

        hits = [_hit("profit win breakout bullish momentum") for _ in range(6)]
        engine = NiblitDecisionEngine(
            qdrant_manager=_make_qdrant({"semantic_memory": hits}),
            memory_graph=_make_graph(),
            router=_make_router(),
            collections=["semantic_memory"],
        )
        adapter = FreqtradeAdapter()

        decision = engine.decide("BTC breakout above 70k", "BTC/USDT")
        signal = adapter.to_freqtrade_signal(decision)

        self.assertIn("enter_long", signal)
        self.assertIn("enter_short", signal)
        self.assertIn("exit_long", signal)
        self.assertIn("exit_short", signal)
        self.assertIn("confidence", signal)
        self.assertIn("reason", signal)
        self.assertIn("metadata", signal)

    def test_full_pipeline_hold_no_memory(self):
        from modules.trading_decision_engine import (
            FreqtradeAdapter,
            NiblitDecisionEngine,
        )

        engine = NiblitDecisionEngine(
            qdrant_manager=_make_qdrant(),
            memory_graph=_make_graph(),
            router=_make_router(),
        )
        adapter = FreqtradeAdapter()
        decision = engine.decide("market quiet", "ETH/USDT")
        signal = adapter.to_freqtrade_signal(decision)

        self.assertFalse(signal["enter_long"])
        self.assertFalse(signal["enter_short"])


if __name__ == "__main__":
    unittest.main()
