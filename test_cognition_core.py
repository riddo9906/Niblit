"""test_cognition_core.py — unit tests for GoalEngine, MemoryGraph decay, and CognitionCore.

All tests are offline-safe: no network calls, no LLM tokens required.

Run with::

    pytest test_cognition_core.py -v
"""

import json
import threading
import time
import unittest
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# GoalEngine
# ─────────────────────────────────────────────────────────────────────────────

class TestGoalEngineImport(unittest.TestCase):
    def test_module_importable(self):
        from modules import goal_engine  # noqa: F401

    def test_class_accessible(self):
        from modules.goal_engine import GoalEngine
        self.assertTrue(callable(GoalEngine))

    def test_goal_dataclass(self):
        from modules.goal_engine import Goal
        g = Goal(topic="test", rationale="reason", priority=0.8)
        d = g.to_dict()
        self.assertIn("topic", d)
        self.assertIn("priority", d)
        self.assertEqual(d["topic"], "test")

    def test_singleton(self):
        import modules.goal_engine as ge
        ge._engine = None
        e1 = ge.get_goal_engine()
        e2 = ge.get_goal_engine()
        self.assertIs(e1, e2)
        ge._engine = None


class TestGoalEngineGeneration(unittest.TestCase):
    def _make_engine(self):
        from modules.goal_engine import GoalEngine
        return GoalEngine(max_goals=10, explore_min_facts=1000)  # high threshold → explore goals

    def test_generates_capability_gap_goals(self):
        engine = self._make_engine()
        goals = engine.generate_goals()
        # Should always find at least some capability gap goals
        self.assertGreater(len(goals), 0)
        types = {g.goal_type for g in goals}
        self.assertIn("capability", types)

    def test_metacognition_gaps_become_goals(self):
        from modules.goal_engine import GoalEngine
        engine = GoalEngine(max_goals=10)
        ctx = {"metacognition_gaps": ["advanced algebra", "deep learning theory"]}
        goals = engine.generate_goals(ale_context=ctx)
        topics = {g.topic for g in goals}
        self.assertIn("advanced algebra", topics)
        self.assertIn("deep learning theory", topics)

    def test_metacognition_goals_have_highest_priority(self):
        from modules.goal_engine import GoalEngine
        engine = GoalEngine(max_goals=10)
        ctx = {"metacognition_gaps": ["urgent topic"]}
        goals = engine.generate_goals(ale_context=ctx)
        meta_goal = next((g for g in goals if g.topic == "urgent topic"), None)
        self.assertIsNotNone(meta_goal)
        self.assertGreaterEqual(meta_goal.priority, 0.85)

    def test_goals_sorted_by_priority_descending(self):
        from modules.goal_engine import GoalEngine
        engine = GoalEngine(max_goals=10)
        goals = engine.generate_goals()
        priorities = [g.priority for g in goals]
        self.assertEqual(priorities, sorted(priorities, reverse=True))

    def test_deduplication_by_topic(self):
        """Two sources generating the same topic → only one Goal kept."""
        from modules.goal_engine import GoalEngine
        engine = GoalEngine(max_goals=20)
        ctx = {"metacognition_gaps": ["machine learning"]}
        goals = engine.generate_goals(ale_context=ctx)
        topics = [g.topic.lower() for g in goals]
        unique_topics = list(dict.fromkeys(topics))
        self.assertEqual(len(topics), len(unique_topics))

    def test_max_goals_respected(self):
        from modules.goal_engine import GoalEngine
        engine = GoalEngine(max_goals=3)
        ctx = {"metacognition_gaps": ["a", "b", "c", "d", "e"]}
        goals = engine.generate_goals(ale_context=ctx)
        self.assertLessEqual(len(goals), 3)

    def test_top_topics_returns_strings(self):
        from modules.goal_engine import GoalEngine
        engine = GoalEngine(max_goals=5)
        engine.generate_goals(ale_context={"metacognition_gaps": ["topic_x"]})
        topics = engine.top_topics(3)
        self.assertIsInstance(topics, list)
        for t in topics:
            self.assertIsInstance(t, str)

    def test_status_dict_keys(self):
        from modules.goal_engine import GoalEngine
        engine = GoalEngine()
        engine.generate_goals()
        s = engine.status()
        for key in ("max_goals", "low_score_threshold", "explore_min_facts",
                    "last_run_ts", "total_goals_generated", "last_goals"):
            self.assertIn(key, s)

    def test_none_knowledge_db_does_not_crash(self):
        from modules.goal_engine import GoalEngine
        engine = GoalEngine()
        goals = engine.generate_goals(knowledge_db=None)
        self.assertIsInstance(goals, list)

    def test_knowledge_db_with_low_confidence_facts(self):
        from modules.goal_engine import GoalEngine
        engine = GoalEngine(max_goals=10, low_score_threshold=0.9)
        kb = MagicMock()
        kb.list_facts = MagicMock(return_value=[
            {"key": "topic_knowledge:foobar", "value": "...", "score": 0.2},
        ])
        goals = engine.generate_goals(knowledge_db=kb)
        reinforce_goals = [g for g in goals if g.goal_type == "reinforce"]
        self.assertGreater(len(reinforce_goals), 0)


# ─────────────────────────────────────────────────────────────────────────────
# MemoryGraph decay / prune methods
# ─────────────────────────────────────────────────────────────────────────────

class TestMemoryGraphDecay(unittest.TestCase):
    def _make_graph(self):
        from modules.memory_graph import MemoryGraph
        return MemoryGraph()  # fresh empty graph

    def test_apply_decay_on_empty_graph(self):
        mg = self._make_graph()
        decayed = mg.apply_decay(days_inactive=0.0, decay_factor=0.9)
        self.assertEqual(decayed, 0)

    def test_apply_decay_reduces_inactive_scores(self):
        from modules.memory_graph import MemoryGraph
        mg = MemoryGraph()
        mg.add("n1", "inactive concept")
        # Force the node's last_used to 0 (never used)
        mg._nodes["n1"].last_used = 0
        original_score = mg._nodes["n1"].score

        decayed = mg.apply_decay(days_inactive=0.0, decay_factor=0.5)
        self.assertGreater(decayed, 0)
        self.assertLess(mg._nodes["n1"].score, original_score)

    def test_apply_decay_respects_min_score_floor(self):
        from modules.memory_graph import MemoryGraph
        mg = MemoryGraph()
        mg.add("n1", "concept")
        mg._nodes["n1"].last_used = 0
        mg._nodes["n1"].score = 0.01  # very low already

        mg.apply_decay(days_inactive=0.0, decay_factor=0.1, min_score_floor=0.05)
        self.assertGreaterEqual(mg._nodes["n1"].score, 0.05)

    def test_active_nodes_not_decayed(self):
        from modules.memory_graph import MemoryGraph
        mg = MemoryGraph()
        mg.add("n1", "recently used concept")
        mg._nodes["n1"].last_used = int(time.time())  # very recently used
        original_score = mg._nodes["n1"].score

        mg.apply_decay(days_inactive=7.0, decay_factor=0.5)
        # Score should NOT have changed for a recently used node
        self.assertAlmostEqual(mg._nodes["n1"].score, original_score, places=5)

    def test_prune_low_score_removes_nodes(self):
        from modules.memory_graph import MemoryGraph
        mg = MemoryGraph()
        mg.add("n1", "low value concept")
        mg._nodes["n1"].score = 0.05   # below threshold
        mg._nodes["n1"].usage = 0      # never used — eligible for pruning

        pruned = mg.prune_low_score(min_score=0.10)
        self.assertEqual(pruned, 1)
        self.assertNotIn("n1", mg._nodes)

    def test_prune_low_score_keeps_used_nodes(self):
        """Nodes with usage > 0 should NOT be pruned even if score is low."""
        from modules.memory_graph import MemoryGraph
        mg = MemoryGraph()
        mg.add("n1", "used concept")
        mg._nodes["n1"].score = 0.01
        mg._nodes["n1"].usage = 5  # has been used → keep it

        pruned = mg.prune_low_score(min_score=0.10)
        self.assertEqual(pruned, 0)
        self.assertIn("n1", mg._nodes)

    def test_prune_cleans_edges_to_removed_nodes(self):
        from modules.memory_graph import MemoryGraph
        mg = MemoryGraph()
        mg.add("n1", "keeper")
        mg.add("n2", "to be pruned")
        mg.link("n1", "n2", 0.9)
        mg._nodes["n2"].score = 0.01
        mg._nodes["n2"].usage = 0

        mg.prune_low_score(min_score=0.10)
        # Edge from n1 to n2 should also be gone
        self.assertNotIn("n2", mg._nodes.get("n1", mg._nodes["n1"]).links)

    def test_reinforce_increases_score(self):
        from modules.memory_graph import MemoryGraph
        mg = MemoryGraph()
        mg.add("n1", "concept to reinforce")
        original_score = mg._nodes["n1"].score
        mg.reinforce("n1", delta=0.10)
        self.assertGreater(mg._nodes["n1"].score, original_score)

    def test_reinforce_clamped_at_1(self):
        from modules.memory_graph import MemoryGraph
        mg = MemoryGraph()
        mg.add("n1", "already excellent concept")
        mg._nodes["n1"].score = 0.99
        mg.reinforce("n1", delta=0.5)
        self.assertLessEqual(mg._nodes["n1"].score, 1.0)

    def test_stats_includes_inactive_7d(self):
        from modules.memory_graph import MemoryGraph
        mg = MemoryGraph()
        mg.add("n1", "old never used")
        mg._nodes["n1"].last_used = 0
        s = mg.stats()
        self.assertIn("inactive_7d", s)
        self.assertGreaterEqual(s["inactive_7d"], 1)


# ─────────────────────────────────────────────────────────────────────────────
# CognitionCore
# ─────────────────────────────────────────────────────────────────────────────

class TestCognitionCoreImport(unittest.TestCase):
    def test_module_importable(self):
        from modules import cognition_core  # noqa: F401

    def test_class_accessible(self):
        from modules.cognition_core import CognitionCore
        self.assertTrue(callable(CognitionCore))

    def test_cognition_result_dataclass(self):
        from modules.cognition_core import CognitionResult
        r = CognitionResult(topic="test")
        d = r.to_dict()
        self.assertIn("topic", d)
        self.assertIn("conclusion", d)
        self.assertIn("confidence", d)

    def test_singleton(self):
        import modules.cognition_core as cc
        cc._core = None
        c1 = cc.get_cognition_core()
        c2 = cc.get_cognition_core()
        self.assertIs(c1, c2)
        cc._core = None


class TestCognitionCoreThink(unittest.TestCase):
    def _make_core(self, with_memory=False):
        from modules.cognition_core import CognitionCore
        from modules.goal_engine import GoalEngine
        mg = None
        if with_memory:
            from modules.memory_graph import MemoryGraph
            mg = MemoryGraph()
        ge = GoalEngine(max_goals=5)
        return CognitionCore(
            reasoning_engine=None,  # no LLM in tests
            memory_graph=mg,
            goal_engine=ge,
            knowledge_db=None,
        )

    def test_think_returns_cognition_result(self):
        from modules.cognition_core import CognitionResult
        core = self._make_core()
        result = core.think("machine learning")
        self.assertIsInstance(result, CognitionResult)
        self.assertEqual(result.topic, "machine learning")

    def test_think_returns_goals(self):
        core = self._make_core()
        result = core.think("transformer architecture")
        self.assertIsInstance(result.goals, list)
        # GoalEngine always returns at least capability gap goals
        self.assertGreater(len(result.goals), 0)

    def test_think_latency_positive(self):
        core = self._make_core()
        result = core.think("test topic")
        self.assertGreater(result.latency_ms, 0)

    def test_think_increments_stat(self):
        from modules.cognition_core import CognitionCore
        core = CognitionCore(reasoning_engine=None, memory_graph=None, goal_engine=None)
        core.think("topic a")
        core.think("topic b")
        self.assertEqual(core._stats["think_calls"], 2)

    def test_think_with_kb_writes_belief(self):
        """When a KB and reasoning engine are available, beliefs should be written."""
        from modules.cognition_core import CognitionCore
        from modules.goal_engine import GoalEngine

        # Mock KB
        kb = MagicMock()
        kb.search = MagicMock(return_value=[{"value": "test knowledge"}])
        kb.add_fact = MagicMock()

        # Mock reasoning engine that produces a confident conclusion
        re = MagicMock()
        cot = MagicMock()
        cot.conclusion = "Transformers use self-attention for parallelism."
        cot.confidence = 0.75
        cot.steps = []
        cot.source = "graph"
        re.chain_of_thought = MagicMock(return_value=cot)
        re.build_knowledge_graph = MagicMock()

        ge = GoalEngine(max_goals=3)
        core = CognitionCore(reasoning_engine=re, memory_graph=None, goal_engine=ge, knowledge_db=kb)
        result = core.think("transformers")

        # Belief should have been written to KB
        self.assertEqual(result.beliefs_updated, 1)
        kb.add_fact.assert_called()


class TestCognitionCoreMaintenance(unittest.TestCase):
    def _make_graph_with_old_nodes(self):
        from modules.memory_graph import MemoryGraph
        mg = MemoryGraph()
        mg.add("old1", "forgotten concept 1")
        mg.add("old2", "forgotten concept 2")
        mg._nodes["old1"].last_used = 0
        mg._nodes["old1"].score = 0.08
        mg._nodes["old2"].last_used = 0
        mg._nodes["old2"].score = 0.50
        return mg

    def test_maintenance_returns_summary_dict(self):
        from modules.cognition_core import CognitionCore
        mg = self._make_graph_with_old_nodes()
        core = CognitionCore(memory_graph=mg)
        summary = core.run_maintenance()
        for key in ("decayed", "pruned", "nodes_before", "nodes_after"):
            self.assertIn(key, summary)

    def test_maintenance_decrements_node_count(self):
        from modules.cognition_core import CognitionCore
        mg = self._make_graph_with_old_nodes()
        before = mg.count()
        core = CognitionCore(memory_graph=mg, prune_threshold=0.06)
        summary = core.run_maintenance()
        # old1 has score 0.08 → may be pruned (usage=0)
        self.assertLessEqual(summary["nodes_after"], before)

    def test_maintenance_without_memory_graph(self):
        from modules.cognition_core import CognitionCore
        core = CognitionCore(memory_graph=None)
        summary = core.run_maintenance()
        self.assertEqual(summary["decayed"], 0)
        self.assertEqual(summary["pruned"], 0)

    def test_maintenance_increments_stat(self):
        from modules.cognition_core import CognitionCore
        from modules.memory_graph import MemoryGraph
        mg = MemoryGraph()
        core = CognitionCore(memory_graph=mg)
        core.run_maintenance()
        self.assertEqual(core._stats["maintenance_runs"], 1)


class TestCognitionCoreCycle(unittest.TestCase):
    def test_cycle_injects_goal_objectives_into_context(self):
        from modules.cognition_core import CognitionCore
        from modules.goal_engine import GoalEngine
        ge = GoalEngine(max_goals=5)
        core = CognitionCore(goal_engine=ge)
        ctx: dict = {}
        core.cycle(ale_context=ctx)
        self.assertIn("goal_objectives", ctx)
        self.assertIsInstance(ctx["goal_objectives"], list)

    def test_cycle_increments_cycle_count(self):
        from modules.cognition_core import CognitionCore
        core = CognitionCore()
        core.cycle()
        core.cycle()
        self.assertEqual(core._cycle_count, 2)

    def test_cycle_triggers_maintenance_at_interval(self):
        from modules.cognition_core import CognitionCore
        from modules.memory_graph import MemoryGraph
        mg = MemoryGraph()
        core = CognitionCore(memory_graph=mg, maintenance_every=2)
        # Cycle 1: no maintenance
        r1 = core.cycle()
        self.assertFalse(r1["maintenance_ran"])
        # Cycle 2: maintenance should run
        r2 = core.cycle()
        self.assertTrue(r2["maintenance_ran"])

    def test_cycle_returns_summary_dict(self):
        from modules.cognition_core import CognitionCore
        core = CognitionCore()
        summary = core.cycle(topic="transformers")
        for key in ("topic", "conclusion", "confidence", "goals_count",
                    "maintenance_ran", "cycle_count"):
            self.assertIn(key, summary)

    def test_status_dict_keys(self):
        from modules.cognition_core import CognitionCore
        core = CognitionCore()
        core.cycle()
        s = core.status()
        for key in ("think_calls", "cycle_calls", "maintenance_runs",
                    "reasoning_available", "memory_graph_available",
                    "goal_engine_available"):
            self.assertIn(key, s)


if __name__ == "__main__":
    unittest.main()
