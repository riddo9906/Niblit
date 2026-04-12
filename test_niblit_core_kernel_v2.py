"""test_niblit_core_kernel_v2.py — unit tests for Cognitive Kernel v2.

All tests are offline-safe: no network calls, no LLM tokens required.

Run with::

    pytest test_niblit_core_kernel_v2.py -v
"""

import math
import threading
import time
import unittest
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Import sanity
# ─────────────────────────────────────────────────────────────────────────────

class TestImports(unittest.TestCase):
    def test_module_importable(self):
        from modules import niblit_core_kernel_v2  # noqa: F401

    def test_public_symbols(self):
        from modules.niblit_core_kernel_v2 import (
            Embedder, ConceptGraph, PatternSynthesizer,
            NiblitCoreKernelV2, KernelV2Result,
            get_niblit_core_kernel_v2,
        )
        for sym in (Embedder, ConceptGraph, PatternSynthesizer,
                    NiblitCoreKernelV2, KernelV2Result,
                    get_niblit_core_kernel_v2):
            self.assertTrue(callable(sym) or isinstance(sym, type))

    def test_singleton_is_same_instance(self):
        import modules.niblit_core_kernel_v2 as m
        m._kernel_v2 = None  # reset
        k1 = m.get_niblit_core_kernel_v2()
        k2 = m.get_niblit_core_kernel_v2()
        self.assertIs(k1, k2)
        m._kernel_v2 = None  # cleanup


# ─────────────────────────────────────────────────────────────────────────────
# cosine helper
# ─────────────────────────────────────────────────────────────────────────────

class TestCosineSim(unittest.TestCase):
    def _sim(self, a, b):
        from modules.niblit_core_kernel_v2 import _cosine_sim
        return _cosine_sim(a, b)

    def test_identical_vectors(self):
        v = [1.0, 0.0, 0.0]
        self.assertAlmostEqual(self._sim(v, v), 1.0, places=4)

    def test_orthogonal_vectors(self):
        self.assertAlmostEqual(self._sim([1, 0, 0], [0, 1, 0]), 0.0, places=4)

    def test_opposite_vectors(self):
        result = self._sim([1, 0, 0], [-1, 0, 0])
        self.assertAlmostEqual(result, -1.0, places=4)

    def test_zero_vector_returns_zero(self):
        self.assertEqual(self._sim([0, 0, 0], [1, 2, 3]), 0.0)

    def test_empty_vectors_returns_zero(self):
        self.assertEqual(self._sim([], []), 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Embedder
# ─────────────────────────────────────────────────────────────────────────────

def _embedder_with_fallback():
    """Return an Embedder that always uses the TF fallback."""
    from modules.niblit_core_kernel_v2 import Embedder
    emb = Embedder()
    emb._using_fallback = True
    emb._model = None
    return emb


class TestEmbedderFallback(unittest.TestCase):
    def test_fallback_encode_returns_list(self):
        emb = _embedder_with_fallback()
        vec = emb._fallback_encode("hello world")
        self.assertIsInstance(vec, list)

    def test_fallback_encode_correct_dim(self):
        from modules.niblit_core_kernel_v2 import Embedder
        emb = _embedder_with_fallback()
        vec = emb._fallback_encode("hello world")
        self.assertEqual(len(vec), Embedder._FALLBACK_DIM)

    def test_fallback_encode_normalised(self):
        emb = _embedder_with_fallback()
        vec = emb._fallback_encode("normalise me")
        mag = math.sqrt(sum(v * v for v in vec))
        self.assertAlmostEqual(mag, 1.0, places=4)

    def test_fallback_encode_empty_string(self):
        emb = _embedder_with_fallback()
        vec = emb._fallback_encode("")
        self.assertIsInstance(vec, list)

    def test_encode_uses_fallback_when_model_none(self):
        emb = _embedder_with_fallback()
        vec = emb.encode("test text")
        self.assertIsInstance(vec, list)
        self.assertGreater(len(vec), 0)

    def test_using_fallback_property_true(self):
        emb = _embedder_with_fallback()
        self.assertTrue(emb.using_fallback)

    def test_embedding_dim_returns_fallback_dim(self):
        from modules.niblit_core_kernel_v2 import Embedder
        emb = _embedder_with_fallback()
        self.assertEqual(emb.embedding_dim, Embedder._FALLBACK_DIM)

    def test_different_texts_produce_different_vectors(self):
        emb = _embedder_with_fallback()
        v1 = emb.encode("neural networks are powerful")
        v2 = emb.encode("the quick brown fox")
        # Should not be identical (unless collision — extremely unlikely)
        self.assertNotEqual(v1, v2)

    def test_same_text_produces_same_vector(self):
        emb = _embedder_with_fallback()
        v1 = emb.encode("consistent encoding test")
        v2 = emb.encode("consistent encoding test")
        self.assertEqual(v1, v2)

    def test_long_text_truncated(self):
        emb = _embedder_with_fallback()
        long_text = "a" * 2000
        vec = emb.encode(long_text)
        self.assertIsInstance(vec, list)


# ─────────────────────────────────────────────────────────────────────────────
# ConceptGraph
# ─────────────────────────────────────────────────────────────────────────────

class TestConceptGraphIdToConcept(unittest.TestCase):
    def _clean(self, node_id):
        from modules.niblit_core_kernel_v2 import ConceptGraph
        return ConceptGraph._id_to_concept(node_id)

    def test_strips_hex_suffix(self):
        result = self._clean("ck_a1b2c3d4e5f6")
        self.assertNotIn("a1b2c3d4e5f6", result)

    def test_removes_ck_prefix(self):
        # "ck_a1b2c3d4e5f6" is purely prefix+hash — no concept label
        result = self._clean("ck_a1b2c3d4e5f6")
        self.assertEqual(result, "")

    def test_removes_km_prefix(self):
        # "km_deadbeef1234" is purely prefix+hash — no concept label
        result = self._clean("km_deadbeef1234")
        self.assertEqual(result, "")

    def test_plain_word_returned(self):
        result = self._clean("python")
        self.assertEqual(result, "python")

    def test_very_short_returns_empty(self):
        result = self._clean("x")
        self.assertEqual(result, "")


class TestConceptGraphTextTokens(unittest.TestCase):
    def test_extracts_words(self):
        from modules.niblit_core_kernel_v2 import ConceptGraph
        tokens = ConceptGraph._text_tokens("neural networks are powerful tools")
        self.assertIn("neural", tokens)
        self.assertIn("networks", tokens)
        self.assertIn("powerful", tokens)
        self.assertIn("tools", tokens)

    def test_filters_short_words(self):
        from modules.niblit_core_kernel_v2 import ConceptGraph
        tokens = ConceptGraph._text_tokens("a to the is and for")
        self.assertEqual(tokens, [])

    def test_filters_stopwords(self):
        from modules.niblit_core_kernel_v2 import ConceptGraph
        tokens = ConceptGraph._text_tokens("this that with from have been will")
        self.assertEqual(tokens, [])

    def test_empty_text(self):
        from modules.niblit_core_kernel_v2 import ConceptGraph
        tokens = ConceptGraph._text_tokens("")
        self.assertEqual(tokens, [])


class TestConceptGraphExpand(unittest.TestCase):
    def _make_hits(self, n=3):
        return [
            {"id": f"ck_abc{i:06x}", "text": f"machine learning concept {i}",
             "score": 0.8 - i * 0.1, "hops": 0}
            for i in range(n)
        ]

    def test_expand_returns_list(self):
        from modules.niblit_core_kernel_v2 import ConceptGraph
        cg = ConceptGraph(memory_graph=None)
        result = cg.expand(self._make_hits())
        self.assertIsInstance(result, list)

    def test_expand_empty_hits_returns_empty(self):
        from modules.niblit_core_kernel_v2 import ConceptGraph
        cg = ConceptGraph(memory_graph=None)
        result = cg.expand([])
        self.assertEqual(result, [])

    def test_expand_respects_max_concepts(self):
        from modules.niblit_core_kernel_v2 import ConceptGraph
        cg = ConceptGraph(memory_graph=None)
        result = cg.expand(self._make_hits(20), max_concepts=5)
        self.assertLessEqual(len(result), 5)

    def test_expand_contains_text_tokens(self):
        from modules.niblit_core_kernel_v2 import ConceptGraph
        cg = ConceptGraph(memory_graph=None)
        hits = [{"id": "ck_test", "text": "reinforcement learning reward system",
                 "score": 0.9, "hops": 0}]
        result = cg.expand(hits)
        # Should contain words from the text
        self.assertTrue(
            any(w in result for w in ("learning", "reinforcement", "reward", "system"))
        )

    def test_neighbors_returns_empty_without_graph(self):
        from modules.niblit_core_kernel_v2 import ConceptGraph
        result = ConceptGraph._neighbors("some_id", None)
        self.assertEqual(result, [])


# ─────────────────────────────────────────────────────────────────────────────
# PatternSynthesizer
# ─────────────────────────────────────────────────────────────────────────────

def _make_hits(n=3, score_start=0.9):
    return [
        {"id": f"node{i}", "text": f"fact {i} about topic", "score": score_start - i * 0.1, "hops": 0}
        for i in range(n)
    ]


class TestPatternSynthesizerGenerate(unittest.TestCase):
    def setUp(self):
        from modules.niblit_core_kernel_v2 import PatternSynthesizer
        self.s = PatternSynthesizer()

    def test_generate_returns_string(self):
        result = self.s.generate("hello", _make_hits(), ["concept1"])
        self.assertIsInstance(result, str)

    def test_generate_contains_input(self):
        result = self.s.generate("my test query", [], [])
        self.assertIn("my test query", result)

    def test_generate_contains_insight(self):
        result = self.s.generate("test", _make_hits(), ["ai"])
        self.assertIn("Insight:", result)

    def test_generate_contains_relevant_hits(self):
        hits = _make_hits(2)
        result = self.s.generate("test", hits, [])
        self.assertIn("Relevant", result)

    def test_generate_contains_concepts(self):
        result = self.s.generate("test", [], ["machine", "learning"])
        self.assertIn("Concepts:", result)
        self.assertIn("machine", result)

    def test_generate_empty_hits_and_concepts(self):
        result = self.s.generate("test", [], [])
        self.assertIn("Input:", result)
        self.assertIn("Insight:", result)


class TestPatternSynthesizerInfer(unittest.TestCase):
    def setUp(self):
        from modules.niblit_core_kernel_v2 import PatternSynthesizer
        self.s = PatternSynthesizer()

    def test_error_pattern(self):
        result = self.s._infer("I got an error in my code", [], [])
        self.assertIn("debug", result.lower())

    def test_exception_pattern(self):
        result = self.s._infer("traceback: AttributeError", [], [])
        self.assertIn("debug", result.lower())

    def test_learn_pattern_with_concepts(self):
        result = self.s._infer("I want to learn", [], ["python", "ml"])
        self.assertIn("python", result.lower())

    def test_learn_pattern_no_concepts(self):
        result = self.s._infer("I want to learn something", [], [])
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_memory_hit_high_score(self):
        hits = [{"id": "n1", "text": "key insight here", "score": 0.8, "hops": 0}]
        result = self.s._infer("what is X", hits, [])
        self.assertIn("key insight here", result)

    def test_memory_hit_low_score(self):
        hits = [{"id": "n1", "text": "weak match text", "score": 0.25, "hops": 0}]
        result = self.s._infer("query", hits, [])
        self.assertIsInstance(result, str)

    def test_concepts_only(self):
        result = self.s._infer("something", [], ["topic1", "topic2"])
        self.assertIn("topic1", result.lower())

    def test_default_fallback(self):
        result = self.s._infer("xyzzy", [], [])
        self.assertIn("research", result.lower())


class TestPatternSynthesizerIntentClassify(unittest.TestCase):
    def setUp(self):
        from modules.niblit_core_kernel_v2 import PatternSynthesizer
        self.s = PatternSynthesizer()

    def test_debug_intent(self):
        self.assertEqual(self.s.intent_classify("there was an error in the log"), "debug")

    def test_research_intent(self):
        self.assertEqual(self.s.intent_classify("I want to learn about AI"), "research")

    def test_generate_code_intent(self):
        self.assertEqual(self.s.intent_classify("build a Python class"), "generate_code")

    def test_reflect_intent(self):
        self.assertEqual(self.s.intent_classify("analyse this situation"), "reflect")

    def test_trade_intent(self):
        self.assertEqual(self.s.intent_classify("evaluate market portfolio"), "trade")

    def test_evolve_intent(self):
        self.assertEqual(self.s.intent_classify("evolve your capabilities"), "evolve")

    def test_respond_fallback(self):
        self.assertEqual(self.s.intent_classify("zxqwerty"), "respond")

    def test_case_insensitive(self):
        self.assertEqual(self.s.intent_classify("LEARN about neural networks"), "research")


class TestPatternSynthesizerToResponse(unittest.TestCase):
    def setUp(self):
        from modules.niblit_core_kernel_v2 import PatternSynthesizer
        self.s = PatternSynthesizer()

    def test_extracts_insight_line(self):
        thought = "Input: hello\nRelevant: foo\nInsight: key insight here"
        self.assertEqual(self.s.to_response(thought), "key insight here")

    def test_case_insensitive_insight(self):
        thought = "Input: hello\nINSIGHT: another insight"
        self.assertEqual(self.s.to_response(thought), "another insight")

    def test_fallback_to_full_thought(self):
        thought = "No insight line present"
        self.assertEqual(self.s.to_response(thought), "No insight line present")

    def test_empty_thought(self):
        self.assertEqual(self.s.to_response(""), "")

    def test_strips_whitespace(self):
        thought = "Input: x\nInsight:   trim me  "
        self.assertEqual(self.s.to_response(thought), "trim me")


# ─────────────────────────────────────────────────────────────────────────────
# _TemporalFocusTracker
# ─────────────────────────────────────────────────────────────────────────────

class TestTemporalFocusTracker(unittest.TestCase):
    def _tracker(self, window=10.0, threshold=3, boost=0.15):
        from modules.niblit_core_kernel_v2 import _TemporalFocusTracker
        return _TemporalFocusTracker(window=window, threshold=threshold, boost=boost)

    def test_no_boost_below_threshold(self):
        t = self._tracker()
        result = t.check("topic")
        self.assertEqual(result, 0.0)

    def test_boost_at_threshold(self):
        t = self._tracker(threshold=3, boost=0.15)
        for _ in range(3):
            result = t.check("same topic")
        self.assertEqual(result, 0.15)

    def test_boost_above_threshold(self):
        t = self._tracker(threshold=2, boost=0.2)
        t.check("x")
        t.check("x")
        self.assertEqual(t.check("x"), 0.2)

    def test_different_topics_independent(self):
        t = self._tracker(threshold=3, boost=0.1)
        for _ in range(3):
            t.check("topic_a")
        result_b = t.check("topic_b")
        self.assertEqual(result_b, 0.0)

    def test_clear_resets_history(self):
        t = self._tracker(threshold=2, boost=0.1)
        t.check("topic")
        t.check("topic")
        t.clear("topic")
        result = t.check("topic")
        self.assertEqual(result, 0.0)

    def test_clear_all(self):
        t = self._tracker(threshold=2, boost=0.1)
        t.check("a")
        t.check("a")
        t.clear()
        # After clear all, should need threshold again
        result = t.check("a")
        self.assertEqual(result, 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# KernelV2Result
# ─────────────────────────────────────────────────────────────────────────────

class TestKernelV2Result(unittest.TestCase):
    def test_defaults(self):
        from modules.niblit_core_kernel_v2 import KernelV2Result
        r = KernelV2Result(input_data="hello")
        self.assertEqual(r.decision, "respond")
        self.assertEqual(r.memory_hits, [])
        self.assertEqual(r.concepts, [])
        self.assertFalse(r.remembered)

    def test_to_dict_has_required_keys(self):
        from modules.niblit_core_kernel_v2 import KernelV2Result
        r = KernelV2Result(input_data="hello")
        d = r.to_dict()
        for key in ("input", "thought", "response", "decision",
                    "action_result", "remembered", "latency_ms", "ts"):
            self.assertIn(key, d)


# ─────────────────────────────────────────────────────────────────────────────
# NiblitCoreKernelV2 — isolated (no real memory, no real tool router)
# ─────────────────────────────────────────────────────────────────────────────

def _make_kernel(with_memory=True):
    """Return a KernelV2 with mocked dependencies."""
    from modules.niblit_core_kernel_v2 import (
        NiblitCoreKernelV2, Embedder, ConceptGraph, PatternSynthesizer
    )
    from modules.niblit_core_kernel import KernelMemory

    emb = Embedder()
    emb._using_fallback = True
    emb._model = None

    cg = ConceptGraph(memory_graph=None)
    synth = PatternSynthesizer()

    mem_mock = MagicMock(spec=KernelMemory)
    mem_mock.semantic_search.return_value = []
    mem_mock.store.return_value = None
    mem_mock.reinforce_content.return_value = 0
    mem_mock.stats.return_value = {"short_term_count": 0, "working_memory_count": 0}

    tr_mock = MagicMock()
    tr_mock.execute.return_value = "tool result"

    km = mem_mock if with_memory else None

    kernel = NiblitCoreKernelV2(
        embedder=emb,
        concept_graph=cg,
        synthesizer=synth,
        kernel_memory=km,
        tool_router=tr_mock,
    )
    return kernel, mem_mock, tr_mock


class TestNiblitCoreKernelV2Think(unittest.TestCase):
    def test_think_returns_three_tuple(self):
        kernel, _, _ = _make_kernel()
        result = kernel.think("what is machine learning?")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)

    def test_thought_is_string(self):
        kernel, _, _ = _make_kernel()
        thought, _, _ = kernel.think("hello")
        self.assertIsInstance(thought, str)

    def test_thought_contains_input(self):
        kernel, _, _ = _make_kernel()
        thought, _, _ = kernel.think("specific_query_xyz")
        self.assertIn("specific_query_xyz", thought)

    def test_hits_is_list(self):
        kernel, _, _ = _make_kernel()
        _, hits, _ = kernel.think("test")
        self.assertIsInstance(hits, list)

    def test_concepts_is_list(self):
        kernel, _, _ = _make_kernel()
        _, _, concepts = kernel.think("test")
        self.assertIsInstance(concepts, list)

    def test_semantic_search_called(self):
        kernel, mem_mock, _ = _make_kernel()
        kernel.think("test")
        mem_mock.semantic_search.assert_called_once()

    def test_think_without_memory_still_works(self):
        kernel, _, _ = _make_kernel(with_memory=False)
        kernel._kernel_memory = None
        thought, hits, concepts = kernel.think("test")
        self.assertIsInstance(thought, str)
        self.assertEqual(hits, [])


class TestNiblitCoreKernelV2Decide(unittest.TestCase):
    def test_returns_string(self):
        kernel, _, _ = _make_kernel()
        self.assertIsInstance(kernel.decide("learn about AI"), str)

    def test_research_intent(self):
        kernel, _, _ = _make_kernel()
        self.assertEqual(kernel.decide("Input: hello\nInsight: I want to learn"), "research")

    def test_code_intent(self):
        kernel, _, _ = _make_kernel()
        self.assertEqual(kernel.decide("Input: build\nInsight: write a function"), "generate_code")

    def test_respond_fallback(self):
        kernel, _, _ = _make_kernel()
        self.assertEqual(kernel.decide("xyzqwerty gibberish"), "respond")


class TestNiblitCoreKernelV2Act(unittest.TestCase):
    def test_returns_string(self):
        kernel, _, tr = _make_kernel()
        result = kernel.act("research", "topic")
        self.assertIsInstance(result, str)

    def test_tool_router_called_for_research(self):
        kernel, _, tr = _make_kernel()
        kernel.act("research", "topic")
        tr.execute.assert_called_once_with("research", "topic")

    def test_tool_router_called_for_code(self):
        kernel, _, tr = _make_kernel()
        kernel.act("generate_code", "build something")
        tr.execute.assert_called_once_with("code", "build something")

    def test_tool_router_called_for_debug(self):
        kernel, _, tr = _make_kernel()
        kernel.act("debug", "traceback")
        tr.execute.assert_called_once_with("reflect", "traceback")

    def test_respond_goes_to_local_fallback_when_no_router(self):
        from modules.niblit_core_kernel_v2 import NiblitCoreKernelV2, Embedder, ConceptGraph, PatternSynthesizer
        kernel = NiblitCoreKernelV2(
            embedder=Embedder(),
            concept_graph=ConceptGraph(memory_graph=None),
            synthesizer=PatternSynthesizer(),
            tool_router=None,
        )
        kernel._tool_router = None
        result = kernel.act("respond", "hello")
        self.assertIsInstance(result, str)

    def test_unknown_intent_maps_to_respond(self):
        kernel, _, tr = _make_kernel()
        kernel.act("totally_unknown_intent", "payload")
        tr.execute.assert_called_once_with("respond", "payload")


class TestNiblitCoreKernelV2Remember(unittest.TestCase):
    def test_calls_memory_store(self):
        kernel, mem, _ = _make_kernel()
        kernel.remember("important data", importance=0.8)
        mem.store.assert_called_once()

    def test_importance_clamped(self):
        kernel, mem, _ = _make_kernel()
        kernel.remember("data", importance=5.0)
        call_kwargs = mem.store.call_args
        # importance arg should be ≤ 1.0
        args, kwargs = call_kwargs
        importance = kwargs.get("importance", args[1] if len(args) > 1 else None)
        self.assertLessEqual(importance, 1.0)

    def test_remember_without_memory_does_not_raise(self):
        kernel, _, _ = _make_kernel(with_memory=False)
        kernel._kernel_memory = None
        # Should not raise
        kernel.remember("data")


class TestNiblitCoreKernelV2Reinforce(unittest.TestCase):
    def test_calls_reinforce_content(self):
        kernel, mem, _ = _make_kernel()
        kernel.reinforce("some memory text", success=True)
        mem.reinforce_content.assert_called_once_with("some memory text", success=True)

    def test_reinforce_failure(self):
        kernel, mem, _ = _make_kernel()
        kernel.reinforce("bad memory", success=False)
        mem.reinforce_content.assert_called_once_with("bad memory", success=False)

    def test_reinforce_without_memory_does_not_raise(self):
        kernel, _, _ = _make_kernel(with_memory=False)
        kernel._kernel_memory = None
        kernel.reinforce("data")  # should not raise


class TestNiblitCoreKernelV2CognitiveLoop(unittest.TestCase):
    def test_returns_kernel_v2_result(self):
        from modules.niblit_core_kernel_v2 import KernelV2Result
        kernel, _, _ = _make_kernel()
        result = kernel.run_cognitive_loop("hello world")
        self.assertIsInstance(result, KernelV2Result)

    def test_result_input_data_set(self):
        kernel, _, _ = _make_kernel()
        result = kernel.run_cognitive_loop("test input")
        self.assertEqual(result.input_data, "test input")

    def test_result_thought_is_string(self):
        kernel, _, _ = _make_kernel()
        result = kernel.run_cognitive_loop("test")
        self.assertIsInstance(result.thought, str)
        self.assertGreater(len(result.thought), 0)

    def test_result_response_is_string(self):
        kernel, _, _ = _make_kernel()
        result = kernel.run_cognitive_loop("test")
        self.assertIsInstance(result.response, str)

    def test_result_decision_is_string(self):
        kernel, _, _ = _make_kernel()
        result = kernel.run_cognitive_loop("test")
        self.assertIn(result.decision, (
            "debug", "research", "generate_code", "reflect",
            "trade", "evolve", "respond",
        ))

    def test_result_remembered_true(self):
        kernel, _, _ = _make_kernel()
        result = kernel.run_cognitive_loop("test")
        self.assertTrue(result.remembered)

    def test_result_latency_ms_positive(self):
        kernel, _, _ = _make_kernel()
        result = kernel.run_cognitive_loop("test")
        self.assertGreater(result.latency_ms, 0)

    def test_result_ts_set(self):
        kernel, _, _ = _make_kernel()
        result = kernel.run_cognitive_loop("test")
        self.assertGreater(result.ts, 0)

    def test_cycle_count_increments(self):
        kernel, _, _ = _make_kernel()
        kernel.run_cognitive_loop("a")
        kernel.run_cognitive_loop("b")
        self.assertEqual(kernel._cycle_count, 2)

    def test_to_dict_from_result(self):
        kernel, _, _ = _make_kernel()
        result = kernel.run_cognitive_loop("test")
        d = result.to_dict()
        for key in ("input", "thought", "response", "decision", "remembered"):
            self.assertIn(key, d)

    def test_memory_hits_used_for_reinforcement(self):
        kernel, mem, _ = _make_kernel()
        # Seed a hit in the mock
        mem.semantic_search.return_value = [
            {"id": "n1", "text": "relevant memory text", "score": 0.9, "hops": 0}
        ]
        kernel.run_cognitive_loop("recall something")
        mem.reinforce_content.assert_called()

    def test_auto_act_false_uses_response(self):
        kernel, _, tr = _make_kernel()
        result = kernel.run_cognitive_loop("do some research", auto_act=False)
        # ToolRouter should NOT be called when auto_act=False
        tr.execute.assert_not_called()

    def test_stats_incremented(self):
        kernel, _, _ = _make_kernel()
        kernel.run_cognitive_loop("test")
        self.assertEqual(kernel._stats["loop_calls"], 1)


class TestNiblitCoreKernelV2Status(unittest.TestCase):
    def test_status_returns_dict(self):
        kernel, _, _ = _make_kernel()
        s = kernel.status()
        self.assertIsInstance(s, dict)

    def test_status_has_cycle_count(self):
        kernel, _, _ = _make_kernel()
        kernel.run_cognitive_loop("test")
        s = kernel.status()
        self.assertIn("cycle_count", s)
        self.assertEqual(s["cycle_count"], 1)

    def test_status_has_embedder_info(self):
        kernel, _, _ = _make_kernel()
        s = kernel.status()
        self.assertIn("embedder_fallback", s)
        self.assertIn("embedding_dim", s)


class TestNiblitCoreKernelV2ThreadSafety(unittest.TestCase):
    def test_concurrent_loops(self):
        kernel, _, _ = _make_kernel()
        errors = []

        def run_loop(i):
            try:
                kernel.run_cognitive_loop(f"query {i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=run_loop, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(kernel._cycle_count, 10)


# ─────────────────────────────────────────────────────────────────────────────
# KernelMemory.semantic_search (added in this PR)
# ─────────────────────────────────────────────────────────────────────────────

class TestKernelMemorySemanticSearch(unittest.TestCase):
    def test_semantic_search_returns_list(self):
        from modules.niblit_core_kernel import KernelMemory
        mg = MagicMock()
        mg.search.return_value = [{"id": "n1", "text": "hello", "score": 0.9, "hops": 0}]
        km = KernelMemory(memory_graph=mg, memory_store=None)
        result = km.semantic_search([0.1] * 64)
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)

    def test_semantic_search_without_graph_returns_empty(self):
        from modules.niblit_core_kernel import KernelMemory
        km = KernelMemory(memory_graph=None, memory_store=None)
        result = km.semantic_search([0.1] * 64)
        self.assertEqual(result, [])

    def test_semantic_search_passes_embedding(self):
        from modules.niblit_core_kernel import KernelMemory
        mg = MagicMock()
        mg.search.return_value = []
        km = KernelMemory(memory_graph=mg, memory_store=None)
        emb = [0.1] * 32
        km.semantic_search(emb, top_k=3)
        mg.search.assert_called_once_with(emb, top_k=3)

    def test_semantic_search_handles_exception(self):
        from modules.niblit_core_kernel import KernelMemory
        mg = MagicMock()
        mg.search.side_effect = RuntimeError("graph error")
        km = KernelMemory(memory_graph=mg, memory_store=None)
        result = km.semantic_search([0.1])
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
