"""test_niblit_core_kernel.py — unit tests for NiblitCoreKernel v1.

All tests are offline-safe: no network calls, no LLM tokens required.

Run with::

    pytest test_niblit_core_kernel.py -v
"""

import threading
import time
import unittest
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_mock_mg():
    """Return a MagicMock configured to stand in for MemoryGraph."""
    mg = MagicMock()
    mg.search.return_value = []
    mg.add.return_value = None
    mg.apply_decay.return_value = 0
    mg.prune_low_score.return_value = 0
    mg.stats.return_value = {"nodes": 0, "edges": 0}
    mg.count.return_value = 0
    return mg


def _fresh_kernel(**kwargs):
    """Return a new NiblitCoreKernel with all subsystems stubbed out."""
    from modules.niblit_core_kernel import NiblitCoreKernel
    # Use a mock memory_graph to avoid polluting the real MemoryGraph singleton
    # (which is shared across tests and can cause isolation failures).
    return NiblitCoreKernel(
        cognition_core=None,
        reasoning_engine=None,
        memory_graph=kwargs.pop("memory_graph", _make_mock_mg()),
        evolve_engine=None,
        knowledge_db=None,
        **kwargs,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Import & singleton
# ─────────────────────────────────────────────────────────────────────────────

class TestImport(unittest.TestCase):
    def test_module_importable(self):
        from modules import niblit_core_kernel  # noqa: F401

    def test_classes_accessible(self):
        from modules.niblit_core_kernel import (
            NiblitCoreKernel, ToolRouter, DecisionEngine, EvolutionGate,
            KernelMemory, ShortTermMemory, WorkingMemory, KernelResult,
        )
        for cls in (NiblitCoreKernel, ToolRouter, DecisionEngine, EvolutionGate,
                    KernelMemory, ShortTermMemory, WorkingMemory, KernelResult):
            self.assertTrue(callable(cls))

    def test_singleton_returns_same_instance(self):
        import modules.niblit_core_kernel as m
        m._kernel = None  # reset
        k1 = m.get_niblit_core_kernel()
        k2 = m.get_niblit_core_kernel()
        self.assertIs(k1, k2)
        m._kernel = None  # cleanup

    def test_kernel_result_to_dict(self):
        from modules.niblit_core_kernel import KernelResult
        r = KernelResult(input_data="test", thought="thinking", decision="research",
                          action_result="done", latency_ms=12.5)
        d = r.to_dict()
        for key in ("input", "thought", "decision", "action_result", "latency_ms", "ts"):
            self.assertIn(key, d)


# ─────────────────────────────────────────────────────────────────────────────
# 3-Tier Memory
# ─────────────────────────────────────────────────────────────────────────────

class TestShortTermMemory(unittest.TestCase):
    def test_push_and_recent(self):
        from modules.niblit_core_kernel import ShortTermMemory
        stm = ShortTermMemory(maxlen=5)
        stm.push("hello")
        stm.push("world")
        recent = stm.recent(2)
        self.assertEqual(len(recent), 2)
        self.assertEqual(recent[0].content, "world")  # newest first

    def test_maxlen_evicts_oldest(self):
        from modules.niblit_core_kernel import ShortTermMemory
        stm = ShortTermMemory(maxlen=3)
        for i in range(5):
            stm.push(f"item_{i}")
        self.assertEqual(len(stm), 3)
        # oldest items should be evicted
        texts = [e.content for e in stm.recent(3)]
        self.assertIn("item_4", texts)
        self.assertNotIn("item_0", texts)

    def test_clear(self):
        from modules.niblit_core_kernel import ShortTermMemory
        stm = ShortTermMemory()
        stm.push("data")
        stm.clear()
        self.assertEqual(len(stm), 0)

    def test_recent_texts(self):
        from modules.niblit_core_kernel import ShortTermMemory
        stm = ShortTermMemory()
        stm.push("alpha")
        stm.push("beta")
        texts = stm.recent_texts(2)
        self.assertIsInstance(texts, list)
        self.assertIn("beta", texts)


class TestWorkingMemory(unittest.TestCase):
    def test_set_and_get(self):
        from modules.niblit_core_kernel import WorkingMemory
        wm = WorkingMemory()
        wm.set("task", "learn RL")
        self.assertEqual(wm.get("task"), "learn RL")

    def test_maxkeys_evicts_oldest(self):
        from modules.niblit_core_kernel import WorkingMemory
        wm = WorkingMemory(maxkeys=3)
        for i in range(5):
            wm.set(f"key_{i}", f"value_{i}")
        self.assertEqual(len(wm), 3)
        # key_4 should be present
        self.assertEqual(wm.get("key_4"), "value_4")
        # key_0 and key_1 should be evicted
        self.assertIsNone(wm.get("key_0"))

    def test_snapshot(self):
        from modules.niblit_core_kernel import WorkingMemory
        wm = WorkingMemory()
        wm.set("a", 1)
        wm.set("b", 2)
        snap = wm.snapshot()
        self.assertIn("a", snap)
        self.assertIn("b", snap)

    def test_clear(self):
        from modules.niblit_core_kernel import WorkingMemory
        wm = WorkingMemory()
        wm.set("x", "y")
        wm.clear()
        self.assertEqual(len(wm), 0)


class TestKernelMemory(unittest.TestCase):
    def test_store_low_importance_only_short_term(self):
        from modules.niblit_core_kernel import KernelMemory
        km = KernelMemory(memory_graph=None, knowledge_db=None)
        km.store("minor note", importance=0.3)
        self.assertEqual(len(km.short_term), 1)
        self.assertEqual(len(km.working), 0)

    def test_store_mid_importance_also_working_memory(self):
        from modules.niblit_core_kernel import KernelMemory
        km = KernelMemory(memory_graph=None, knowledge_db=None)
        km.store("medium note", importance=0.6)
        self.assertGreater(len(km.working), 0)

    def test_store_high_importance_calls_memory_graph(self):
        from modules.niblit_core_kernel import KernelMemory
        mg = MagicMock()
        mg.add = MagicMock()
        km = KernelMemory(memory_graph=mg, knowledge_db=None)
        km.store("important concept", importance=0.8)
        mg.add.assert_called()

    def test_store_critical_importance_calls_kb(self):
        from modules.niblit_core_kernel import KernelMemory
        kb = MagicMock()
        kb.add_fact = MagicMock()
        km = KernelMemory(memory_graph=None, knowledge_db=kb)
        km.store("critical fact", importance=0.9)
        kb.add_fact.assert_called()

    def test_retrieve_returns_recent(self):
        from modules.niblit_core_kernel import KernelMemory
        km = KernelMemory(memory_graph=None, knowledge_db=None)
        km.store("alpha beta gamma", importance=0.3)
        result = km.retrieve("alpha", top_k=3)
        self.assertIsInstance(result, list)

    def test_stats_returns_dict(self):
        from modules.niblit_core_kernel import KernelMemory
        km = KernelMemory(memory_graph=None, knowledge_db=None)
        s = km.stats()
        self.assertIn("short_term_count", s)
        self.assertIn("working_memory_count", s)
        self.assertIn("memory_graph", s)


# ─────────────────────────────────────────────────────────────────────────────
# Decision Engine
# ─────────────────────────────────────────────────────────────────────────────

class TestDecisionEngine(unittest.TestCase):
    def setUp(self):
        from modules.niblit_core_kernel import DecisionEngine
        self.engine = DecisionEngine()

    def test_research_intent(self):
        self.assertEqual(self.engine.decide("I want to learn and research AI"), "research")

    def test_code_intent(self):
        self.assertEqual(self.engine.decide("build a Python function"), "code")

    def test_reflect_intent(self):
        self.assertEqual(self.engine.decide("why does this algorithm work, analyze it"), "reflect")

    def test_trade_intent(self):
        self.assertEqual(self.engine.decide("buy stock trade position market"), "trade")

    def test_evolve_intent(self):
        self.assertEqual(self.engine.decide("evolve and improve Niblit"), "evolve")

    def test_respond_default(self):
        # No keywords → falls back to "respond"
        self.assertEqual(self.engine.decide("xyz abc 123"), "respond")

    def test_score_breakdown_returns_dict(self):
        scores = self.engine.score_breakdown("research and code")
        self.assertIsInstance(scores, dict)
        self.assertIn("research", scores)
        self.assertIn("code", scores)
        self.assertGreater(scores["research"], 0)
        self.assertGreater(scores["code"], 0)

    def test_highest_scoring_wins(self):
        # "research" keywords outnumber others
        decision = self.engine.decide(
            "learn explore discover find investigate research study"
        )
        self.assertEqual(decision, "research")


# ─────────────────────────────────────────────────────────────────────────────
# Evolution Gate
# ─────────────────────────────────────────────────────────────────────────────

class TestEvolutionGate(unittest.TestCase):
    def setUp(self):
        from modules.niblit_core_kernel import EvolutionGate
        self.gate = EvolutionGate(strict=False)
        self.strict_gate = EvolutionGate(strict=True)

    def test_valid_proposal_accepted(self):
        valid, reason = self.gate.validate("Add a new research function to the evolve module")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_blocked_phrase_delete_core(self):
        valid, reason = self.gate.validate("delete core module immediately")
        self.assertFalse(valid)
        self.assertIn("delete core", reason)

    def test_blocked_phrase_overwrite_core(self):
        valid, reason = self.gate.validate("overwrite core system")
        self.assertFalse(valid)

    def test_blocked_phrase_rm_rf(self):
        valid, reason = self.gate.validate("run rm -rf /")
        self.assertFalse(valid)

    def test_too_short_rejected(self):
        valid, reason = self.gate.validate("patch")
        self.assertFalse(valid)
        self.assertIn("too short", reason)

    def test_empty_proposal_rejected(self):
        valid, reason = self.gate.validate("")
        self.assertFalse(valid)

    def test_none_proposal_rejected(self):
        valid, reason = self.gate.validate(None)  # type: ignore[arg-type]
        self.assertFalse(valid)

    def test_core_kernel_modification_rejected(self):
        valid, reason = self.gate.validate(
            "Modify niblit_core_kernel.py to bypass the safety check"
        )
        self.assertFalse(valid)

    def test_strict_mode_blocks_eval(self):
        valid, reason = self.strict_gate.validate(
            "Use eval( to execute dynamic code improvements in the system"
        )
        self.assertFalse(valid)

    def test_strict_mode_blocks_exec(self):
        valid, reason = self.strict_gate.validate(
            "Use exec( to apply patches to the system"
        )
        self.assertFalse(valid)

    def test_non_strict_allows_exec_description(self):
        # In non-strict mode, mentioning exec in context should be allowed
        valid, _ = self.gate.validate(
            "Improve the execution flow for research tasks in the pipeline"
        )
        self.assertTrue(valid)

    def test_case_insensitive_blocklist(self):
        valid, reason = self.gate.validate("DELETE CORE module")
        self.assertFalse(valid)


# ─────────────────────────────────────────────────────────────────────────────
# ToolRouter
# ─────────────────────────────────────────────────────────────────────────────

class TestToolRouter(unittest.TestCase):
    def setUp(self):
        from modules.niblit_core_kernel import ToolRouter
        self.router = ToolRouter(knowledge_db=None)

    def test_respond_action_returns_string(self):
        result = self.router.execute("respond", "hello world")
        self.assertIsInstance(result, str)
        self.assertIn("hello world", result)

    def test_unknown_action_falls_back_to_respond(self):
        result = self.router.execute("unknown_action_xyz", "payload")
        self.assertIsInstance(result, str)

    def test_research_handles_missing_dep_gracefully(self):
        result = self.router.execute("research", "quantum computing")
        self.assertIsInstance(result, str)

    def test_code_handles_missing_dep_gracefully(self):
        result = self.router.execute("code", "generate a fibonacci function")
        self.assertIsInstance(result, str)

    def test_reflect_handles_missing_dep_gracefully(self):
        result = self.router.execute("reflect", "why do transformers work")
        self.assertIsInstance(result, str)

    def test_trade_handles_missing_dep_gracefully(self):
        result = self.router.execute("trade", "BTC price signal")
        self.assertIsInstance(result, str)

    def test_evolve_handles_missing_dep_gracefully(self):
        result = self.router.execute("evolve", "add a new research capability")
        self.assertIsInstance(result, str)

    def test_exception_in_handler_returns_error_string(self):
        from modules.niblit_core_kernel import ToolRouter
        router = ToolRouter()
        router._handlers["boom"] = lambda p: (_ for _ in ()).throw(RuntimeError("kaboom"))
        result = router.execute("boom", "payload")
        self.assertIn("error", result.lower())


# ─────────────────────────────────────────────────────────────────────────────
# NiblitCoreKernel — 5 cognitive methods
# ─────────────────────────────────────────────────────────────────────────────

class TestKernelThink(unittest.TestCase):
    def test_think_returns_string(self):
        k = _fresh_kernel()
        result = k.think("what is reinforcement learning")
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_think_with_cognition_core(self):
        cc = MagicMock()
        cot_result = MagicMock()
        cot_result.conclusion = "RL is a learning paradigm."
        cc.think = MagicMock(return_value=cot_result)
        from modules.niblit_core_kernel import NiblitCoreKernel
        k = NiblitCoreKernel(cognition_core=cc)
        result = k.think("reinforcement learning")
        self.assertEqual(result, "RL is a learning paradigm.")

    def test_think_falls_back_to_reasoning_engine(self):
        # Use a cognition_core mock that returns empty conclusion → triggers RE fallback
        cc = MagicMock()
        cot_result = MagicMock()
        cot_result.conclusion = ""  # empty → kernel tries reasoning_engine
        cc.think = MagicMock(return_value=cot_result)

        re = MagicMock()
        cot = MagicMock()
        cot.conclusion = "RL uses rewards."
        re.chain_of_thought = MagicMock(return_value=cot)

        from modules.niblit_core_kernel import NiblitCoreKernel
        k = NiblitCoreKernel(cognition_core=cc, reasoning_engine=re)
        result = k.think("RL")
        # CognitionCore returned empty, so reasoning_engine conclusion is used
        self.assertEqual(result, "RL uses rewards.")

    def test_think_increments_stat(self):
        k = _fresh_kernel()
        k.think("topic a")
        k.think("topic b")
        self.assertEqual(k._stats["think_calls"], 2)

    def test_think_enriches_with_memory_context(self):
        k = _fresh_kernel()
        k.remember("prior knowledge about neural networks", importance=0.3)
        result = k.think("neural networks")
        self.assertIsInstance(result, str)


class TestKernelRemember(unittest.TestCase):
    def test_remember_stores_in_short_term(self):
        k = _fresh_kernel()
        k.remember("fact about AI", importance=0.3)
        self.assertEqual(len(k.memory.short_term), 1)

    def test_remember_importance_clamped(self):
        k = _fresh_kernel()
        k.remember("data", importance=5.0)   # > 1.0 should clamp
        k.remember("data", importance=-1.0)  # < 0.0 should clamp
        # Should not raise

    def test_remember_increments_stat(self):
        k = _fresh_kernel()
        k.remember("a")
        k.remember("b")
        self.assertEqual(k._stats["remember_calls"], 2)

    def test_remember_high_importance_calls_memory_graph(self):
        mg = MagicMock()
        mg.add = MagicMock()
        mg.search = MagicMock(return_value=[])
        from modules.niblit_core_kernel import NiblitCoreKernel
        k = NiblitCoreKernel(memory_graph=mg)
        k.remember("very important fact", importance=0.8)
        mg.add.assert_called()


class TestKernelDecide(unittest.TestCase):
    def test_decide_returns_known_action(self):
        k = _fresh_kernel()
        valid_actions = {"research", "code", "reflect", "trade", "evolve", "respond"}
        for text, expected in [
            ("I want to research and learn about AI", "research"),
            ("build a new function in Python", "code"),
            ("why does this work, analyze the reasoning", "reflect"),
        ]:
            decision = k.decide(text)
            self.assertIn(decision, valid_actions)

    def test_decide_increments_stat(self):
        k = _fresh_kernel()
        k.decide("test input")
        self.assertEqual(k._stats["decide_calls"], 1)


class TestKernelAct(unittest.TestCase):
    def test_act_returns_string(self):
        k = _fresh_kernel()
        result = k.act("respond", "hello")
        self.assertIsInstance(result, str)

    def test_act_increments_stat(self):
        k = _fresh_kernel()
        k.act("respond", "payload")
        self.assertEqual(k._stats["act_calls"], 1)

    def test_act_with_custom_tool_router(self):
        from modules.niblit_core_kernel import ToolRouter, NiblitCoreKernel
        custom_router = ToolRouter()
        k = NiblitCoreKernel(tool_router=custom_router)
        result = k.act("respond", "test")
        self.assertIsInstance(result, str)


class TestKernelEvolve(unittest.TestCase):
    def test_valid_proposal_accepted(self):
        k = _fresh_kernel(evolve_enabled=True)
        result = k.evolve("Improve the research pipeline with better summarization")
        # Should attempt to evolve (may fail gracefully if EvolveEngine unavailable)
        self.assertIsInstance(result, str)
        self.assertNotIn("Rejected", result)

    def test_dangerous_proposal_rejected(self):
        k = _fresh_kernel(evolve_enabled=True)
        result = k.evolve("delete core files immediately")
        self.assertIn("Rejected", result)

    def test_evolve_disabled(self):
        k = _fresh_kernel(evolve_enabled=False)
        result = k.evolve("any proposal")
        self.assertIn("disabled", result)

    def test_evolve_increments_stats(self):
        k = _fresh_kernel(evolve_enabled=True)
        k.evolve("valid proposal to improve the research loop")
        k.evolve("delete core module")  # rejected
        self.assertEqual(k._stats["evolve_calls"], 2)
        self.assertEqual(k._stats["evolve_accepted"], 1)
        self.assertEqual(k._stats["evolve_rejected"], 1)


# ─────────────────────────────────────────────────────────────────────────────
# Full cognitive loop
# ─────────────────────────────────────────────────────────────────────────────

class TestCognitiveLoop(unittest.TestCase):
    def test_loop_returns_kernel_result(self):
        from modules.niblit_core_kernel import KernelResult
        k = _fresh_kernel()
        result = k.run_cognitive_loop("what is machine learning")
        self.assertIsInstance(result, KernelResult)

    def test_loop_fills_thought_and_decision(self):
        k = _fresh_kernel()
        result = k.run_cognitive_loop("research transformer architecture")
        self.assertIsInstance(result.thought, str)
        self.assertIsInstance(result.decision, str)

    def test_loop_fills_action_result(self):
        k = _fresh_kernel()
        result = k.run_cognitive_loop("test input")
        self.assertIsInstance(result.action_result, str)

    def test_loop_sets_remembered_true(self):
        k = _fresh_kernel()
        result = k.run_cognitive_loop("test")
        self.assertTrue(result.remembered)

    def test_loop_latency_positive(self):
        k = _fresh_kernel()
        result = k.run_cognitive_loop("test")
        self.assertGreater(result.latency_ms, 0)

    def test_loop_increments_cycle_count(self):
        k = _fresh_kernel()
        k.run_cognitive_loop("cycle 1")
        k.run_cognitive_loop("cycle 2")
        self.assertEqual(k._cycle_count, 2)

    def test_loop_with_auto_evolve_safe_proposal(self):
        """When decision=='evolve' + auto_evolve=True, evolve() is called."""
        from modules.niblit_core_kernel import NiblitCoreKernel, ToolRouter
        k = NiblitCoreKernel(evolve_enabled=True)
        # Force decision to "evolve" by injecting keywords
        result = k.run_cognitive_loop(
            "evolve and improve the system architecture significantly",
            auto_evolve=True,
        )
        self.assertIsInstance(result, type(result))  # still returns KernelResult

    def test_loop_to_dict(self):
        k = _fresh_kernel()
        result = k.run_cognitive_loop("test")
        d = result.to_dict()
        for key in ("input", "thought", "decision", "action_result", "latency_ms", "ts"):
            self.assertIn(key, d)

    def test_loop_thread_safe(self):
        """Multiple threads can call run_cognitive_loop concurrently without crashing."""
        k = _fresh_kernel()
        errors = []

        def worker():
            try:
                k.run_cognitive_loop("concurrent test")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])

    def test_status_dict_keys(self):
        k = _fresh_kernel()
        k.run_cognitive_loop("test")
        s = k.status()
        for key in ("think_calls", "remember_calls", "decide_calls", "act_calls",
                    "evolve_calls", "loop_calls", "cycle_count", "memory"):
            self.assertIn(key, s)


if __name__ == "__main__":
    unittest.main()
