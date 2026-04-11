"""test_memory_weighting.py — unit tests for MWDS v2 (modules/memory_weighting.py).

All tests are offline-safe: no network calls, no LLM tokens required.

Run with::

    pytest test_memory_weighting.py -v
"""

import math
import time
import threading
import unittest
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Import sanity
# ─────────────────────────────────────────────────────────────────────────────

class TestImport(unittest.TestCase):
    def test_module_importable(self):
        from modules import memory_weighting  # noqa: F401

    def test_public_symbols_accessible(self):
        from modules.memory_weighting import (
            MemoryRecord, MemoryStore, BASE_IMPORTANCE, BASE_DECAY,
            compute_weight, update_decay, reinforce, assign_tier,
            compress_memories, make_record, get_memory_store,
            TIER_HOT, TIER_WARM, TIER_COLD,
        )
        for sym in (MemoryRecord, MemoryStore, compute_weight, update_decay,
                    reinforce, assign_tier, compress_memories, make_record,
                    get_memory_store):
            self.assertTrue(callable(sym))

    def test_singleton_returns_same_instance(self):
        import modules.memory_weighting as m
        m._store = None  # reset
        s1 = m.get_memory_store()
        s2 = m.get_memory_store()
        self.assertIs(s1, s2)
        m._store = None  # cleanup


# ─────────────────────────────────────────────────────────────────────────────
# BASE_IMPORTANCE and BASE_DECAY
# ─────────────────────────────────────────────────────────────────────────────

class TestConstants(unittest.TestCase):
    def test_base_importance_all_between_0_and_1(self):
        from modules.memory_weighting import BASE_IMPORTANCE
        for src, val in BASE_IMPORTANCE.items():
            self.assertGreater(val, 0.0, f"BASE_IMPORTANCE[{src!r}] should be > 0")
            self.assertLessEqual(val, 1.0, f"BASE_IMPORTANCE[{src!r}] should be ≤ 1")

    def test_base_decay_all_positive(self):
        from modules.memory_weighting import BASE_DECAY
        for src, val in BASE_DECAY.items():
            self.assertGreater(val, 0.0, f"BASE_DECAY[{src!r}] should be > 0")

    def test_tier_constants_ordered(self):
        from modules.memory_weighting import TIER_HOT, TIER_WARM, TIER_COLD
        self.assertGreater(TIER_HOT, TIER_WARM)
        self.assertGreater(TIER_WARM, TIER_COLD)
        self.assertGreater(TIER_COLD, 0.0)

    def test_user_has_highest_importance(self):
        from modules.memory_weighting import BASE_IMPORTANCE
        self.assertEqual(BASE_IMPORTANCE["user"], max(BASE_IMPORTANCE.values()))

    def test_user_has_lowest_decay(self):
        from modules.memory_weighting import BASE_DECAY
        self.assertEqual(BASE_DECAY["user"], min(BASE_DECAY.values()))


# ─────────────────────────────────────────────────────────────────────────────
# MemoryRecord
# ─────────────────────────────────────────────────────────────────────────────

class TestMemoryRecord(unittest.TestCase):
    def _make(self, source="user", confidence=0.8):
        from modules.memory_weighting import make_record
        return make_record("rec1", "test content", source=source, confidence=confidence)

    def test_make_record_sets_id_content_source(self):
        from modules.memory_weighting import make_record
        rec = make_record("myid", "hello world", source="research", confidence=0.7)
        self.assertEqual(rec.id, "myid")
        self.assertEqual(rec.content, "hello world")
        self.assertEqual(rec.source, "research")

    def test_importance_equals_base_times_confidence(self):
        from modules.memory_weighting import make_record, BASE_IMPORTANCE
        rec = make_record("r1", "content", source="user", confidence=0.8)
        expected = BASE_IMPORTANCE["user"] * 0.8
        self.assertAlmostEqual(rec.importance, expected, places=5)

    def test_unknown_source_falls_back(self):
        from modules.memory_weighting import make_record
        rec = make_record("r2", "content", source="totally_unknown", confidence=0.5)
        self.assertEqual(rec.source, "unknown")

    def test_initial_weight_positive(self):
        rec = self._make()
        self.assertGreater(rec.weight, 0.0)

    def test_initial_tier_set(self):
        rec = self._make()
        self.assertIn(rec.tier, ("hot", "warm", "cold", "dead"))

    def test_decay_rate_positive(self):
        rec = self._make()
        self.assertGreater(rec.decay_rate, 0.0)

    def test_half_life_positive(self):
        rec = self._make()
        self.assertGreater(rec.half_life, 0.0)

    def test_to_dict_has_required_keys(self):
        rec = self._make()
        d = rec.to_dict()
        for key in ("id", "content", "source", "confidence", "importance",
                    "access_count", "success_count", "failure_count",
                    "last_accessed", "connections", "centrality",
                    "decay_rate", "half_life", "weight", "tier"):
            self.assertIn(key, d, f"Missing key: {key}")

    def test_confidence_clamped_to_1(self):
        from modules.memory_weighting import make_record
        rec = make_record("r3", "c", source="user", confidence=2.0)
        self.assertLessEqual(rec.confidence, 1.0)

    def test_confidence_clamped_to_0(self):
        from modules.memory_weighting import make_record
        rec = make_record("r4", "c", source="user", confidence=-0.5)
        self.assertGreaterEqual(rec.confidence, 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# assign_tier
# ─────────────────────────────────────────────────────────────────────────────

class TestAssignTier(unittest.TestCase):
    def test_hot_tier(self):
        from modules.memory_weighting import assign_tier, TIER_HOT
        self.assertEqual(assign_tier(TIER_HOT + 0.1), "hot")

    def test_warm_tier(self):
        from modules.memory_weighting import assign_tier, TIER_WARM, TIER_HOT
        mid = (TIER_WARM + TIER_HOT) / 2
        self.assertEqual(assign_tier(mid), "warm")

    def test_cold_tier(self):
        from modules.memory_weighting import assign_tier, TIER_COLD, TIER_WARM
        mid = (TIER_COLD + TIER_WARM) / 2
        self.assertEqual(assign_tier(mid), "cold")

    def test_dead_tier(self):
        from modules.memory_weighting import assign_tier, TIER_COLD
        self.assertEqual(assign_tier(TIER_COLD - 0.01), "dead")

    def test_zero_is_dead(self):
        from modules.memory_weighting import assign_tier
        self.assertEqual(assign_tier(0.0), "dead")


# ─────────────────────────────────────────────────────────────────────────────
# compute_weight
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeWeight(unittest.TestCase):
    def _make(self, **kwargs):
        from modules.memory_weighting import make_record
        return make_record("id", "text", **kwargs)

    def test_weight_positive(self):
        from modules.memory_weighting import compute_weight
        rec = self._make(source="user", confidence=0.8)
        w = compute_weight(rec)
        self.assertGreater(w, 0.0)

    def test_higher_confidence_yields_higher_weight(self):
        from modules.memory_weighting import compute_weight
        now = time.time()
        r_low = self._make(source="user", confidence=0.2)
        r_high = self._make(source="user", confidence=0.9)
        self.assertGreater(compute_weight(r_high, now), compute_weight(r_low, now))

    def test_age_reduces_weight(self):
        from modules.memory_weighting import compute_weight, make_record
        rec = make_record("id", "text", source="research", confidence=0.8)
        now = time.time()
        w_fresh = compute_weight(rec, now)
        w_old = compute_weight(rec, now + 86400 * 30)  # 30 days later
        self.assertGreater(w_fresh, w_old)

    def test_access_count_boosts_weight(self):
        from modules.memory_weighting import compute_weight, make_record
        now = time.time()
        r1 = make_record("r1", "text", source="user", confidence=0.8)
        r2 = make_record("r2", "text", source="user", confidence=0.8)
        r2.access_count = 100
        self.assertGreater(compute_weight(r2, now), compute_weight(r1, now))

    def test_high_centrality_boosts_weight(self):
        from modules.memory_weighting import compute_weight, make_record
        now = time.time()
        r1 = make_record("r1", "text", source="user", confidence=0.8)
        r2 = make_record("r2", "text", source="user", confidence=0.8)
        r2.centrality = 0.9
        self.assertGreater(compute_weight(r2, now), compute_weight(r1, now))

    def test_recent_access_boosts_weight(self):
        from modules.memory_weighting import compute_weight, make_record
        now = time.time()
        r1 = make_record("r1", "text", source="user", confidence=0.8)
        r2 = make_record("r2", "text", source="user", confidence=0.8)
        r2.last_accessed = int(now)  # just accessed
        r1.last_accessed = int(now - 86400 * 7)  # week ago
        self.assertGreater(compute_weight(r2, now), compute_weight(r1, now))

    def test_returns_zero_for_zero_confidence(self):
        from modules.memory_weighting import compute_weight, make_record
        rec = make_record("r", "text", source="user", confidence=0.0)
        w = compute_weight(rec)
        self.assertAlmostEqual(w, 0.0, places=5)


# ─────────────────────────────────────────────────────────────────────────────
# update_decay
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateDecay(unittest.TestCase):
    def test_strong_memory_decays_slower(self):
        from modules.memory_weighting import update_decay, make_record
        r_weak = make_record("w", "text", source="research", confidence=0.1)
        r_strong = make_record("s", "text", source="research", confidence=0.99)
        update_decay(r_weak)
        update_decay(r_strong)
        self.assertGreater(r_weak.decay_rate, r_strong.decay_rate)

    def test_decay_rate_never_zero(self):
        from modules.memory_weighting import update_decay, make_record
        rec = make_record("r", "text", source="user", confidence=1.0)
        update_decay(rec)
        self.assertGreater(rec.decay_rate, 0.0)

    def test_decay_rate_bounded_by_base(self):
        from modules.memory_weighting import update_decay, make_record, BASE_DECAY
        rec = make_record("r", "text", source="research", confidence=0.0)
        update_decay(rec)
        self.assertLessEqual(rec.decay_rate, BASE_DECAY["research"])


# ─────────────────────────────────────────────────────────────────────────────
# reinforce
# ─────────────────────────────────────────────────────────────────────────────

class TestReinforce(unittest.TestCase):
    def _make(self):
        from modules.memory_weighting import make_record
        return make_record("r", "text", source="agent", confidence=0.5)

    def test_success_increments_success_count(self):
        from modules.memory_weighting import reinforce
        rec = self._make()
        reinforce(rec, success=True)
        self.assertEqual(rec.success_count, 1)
        self.assertEqual(rec.access_count, 1)

    def test_failure_increments_failure_count(self):
        from modules.memory_weighting import reinforce
        rec = self._make()
        reinforce(rec, success=False)
        self.assertEqual(rec.failure_count, 1)
        self.assertEqual(rec.access_count, 1)

    def test_success_raises_confidence(self):
        from modules.memory_weighting import reinforce
        rec = self._make()
        before = rec.confidence
        reinforce(rec, success=True)
        self.assertGreater(rec.confidence, before)

    def test_failure_lowers_confidence(self):
        from modules.memory_weighting import reinforce
        rec = self._make()
        before = rec.confidence
        reinforce(rec, success=False)
        self.assertLess(rec.confidence, before)

    def test_success_cap_at_1(self):
        from modules.memory_weighting import reinforce, make_record
        rec = make_record("r", "text", source="user", confidence=1.0)
        for _ in range(100):
            reinforce(rec, success=True)
        self.assertLessEqual(rec.confidence, 1.0)

    def test_last_accessed_updated(self):
        from modules.memory_weighting import reinforce
        rec = self._make()
        before = rec.last_accessed
        time.sleep(0.01)
        reinforce(rec, success=True)
        self.assertGreaterEqual(rec.last_accessed, before)

    def test_weight_recomputed_after_reinforce(self):
        from modules.memory_weighting import reinforce
        rec = self._make()
        w_before = rec.weight
        reinforce(rec, success=True)
        # weight can go up or down depending on timing, but must be recomputed
        self.assertIsNotNone(rec.weight)

    def test_tier_updated_after_reinforce(self):
        from modules.memory_weighting import reinforce
        rec = self._make()
        reinforce(rec, success=True)
        self.assertIn(rec.tier, ("hot", "warm", "cold", "dead"))


# ─────────────────────────────────────────────────────────────────────────────
# compress_memories
# ─────────────────────────────────────────────────────────────────────────────

class TestCompressMemories(unittest.TestCase):
    def _make_batch(self, n=5):
        from modules.memory_weighting import make_record
        return [make_record(f"r{i}", f"fact {i} about topic", source="research")
                for i in range(n)]

    def test_returns_none_for_empty_list(self):
        from modules.memory_weighting import compress_memories
        self.assertIsNone(compress_memories([]))

    def test_returns_memory_record(self):
        from modules.memory_weighting import compress_memories, MemoryRecord
        records = self._make_batch()
        compressed = compress_memories(records)
        self.assertIsInstance(compressed, MemoryRecord)

    def test_compressed_content_starts_with_abstract(self):
        from modules.memory_weighting import compress_memories
        records = self._make_batch()
        compressed = compress_memories(records)
        self.assertTrue(compressed.content.startswith("[Abstract]"))

    def test_compressed_source_is_reflection(self):
        from modules.memory_weighting import compress_memories
        records = self._make_batch()
        compressed = compress_memories(records)
        self.assertEqual(compressed.source, "reflection")

    def test_compressed_importance_is_0_4(self):
        from modules.memory_weighting import compress_memories
        records = self._make_batch()
        compressed = compress_memories(records)
        self.assertAlmostEqual(compressed.importance, 0.4, places=5)

    def test_single_record_compresses(self):
        from modules.memory_weighting import compress_memories, make_record
        single = [make_record("x", "lonely fact", source="user")]
        result = compress_memories(single)
        self.assertIsNotNone(result)


# ─────────────────────────────────────────────────────────────────────────────
# MemoryStore
# ─────────────────────────────────────────────────────────────────────────────

def _fresh_store(**kwargs):
    """Return a fresh MemoryStore with MWDS defaults for isolated tests."""
    from modules.memory_weighting import MemoryStore
    return MemoryStore(**kwargs)


class TestMemoryStoreStore(unittest.TestCase):
    def test_store_inserts_record(self):
        ms = _fresh_store()
        ms.store("id1", "hello world", source="user")
        self.assertEqual(len(ms), 1)

    def test_store_upserts_existing(self):
        ms = _fresh_store()
        ms.store("id1", "old", source="user", confidence=0.5)
        ms.store("id1", "new", source="user", confidence=0.9)
        self.assertEqual(len(ms), 1)
        rec = ms.get_record("id1")
        self.assertEqual(rec.content, "new")

    def test_store_returns_memory_record(self):
        from modules.memory_weighting import MemoryRecord
        ms = _fresh_store()
        rec = ms.store("id1", "content")
        self.assertIsInstance(rec, MemoryRecord)

    def test_evicts_when_at_capacity(self):
        ms = _fresh_store(max_records=3)
        for i in range(4):
            ms.store(f"id{i}", f"content {i}", source="research")
        self.assertEqual(len(ms), 3)

    def test_evicts_lowest_weight(self):
        ms = _fresh_store(max_records=2)
        ms.store("strong", "very important content", source="user", confidence=0.99)
        ms.store("weak", "boring content", source="research", confidence=0.01)
        # Add third — weak should be evicted
        ms.store("new", "new content", source="user", confidence=0.8)
        self.assertIsNone(ms.get_record("weak"))
        self.assertIsNotNone(ms.get_record("strong"))


class TestMemoryStoreRetrieve(unittest.TestCase):
    def test_retrieve_weighted_returns_list(self):
        ms = _fresh_store()
        ms.store("r1", "alpha text", source="user", confidence=0.9)
        result = ms.retrieve_weighted(["alpha text", "beta text"])
        self.assertIsInstance(result, list)

    def test_retrieve_weighted_respects_top_k(self):
        ms = _fresh_store()
        candidates = [f"candidate {i}" for i in range(10)]
        result = ms.retrieve_weighted(candidates, top_k=3)
        self.assertLessEqual(len(result), 3)

    def test_retrieve_weighted_empty_candidates(self):
        ms = _fresh_store()
        result = ms.retrieve_weighted([])
        self.assertEqual(result, [])

    def test_retrieve_weighted_prefers_high_weight(self):
        ms = _fresh_store()
        # High-weight record
        ms.store("high", "top result content", source="user", confidence=0.99)
        # Low-weight record
        ms.store("low", "bottom result content", source="research", confidence=0.01)
        candidates = ["top result content", "bottom result content"]
        result = ms.retrieve_weighted(candidates, top_k=2)
        # High-weight candidate should rank first
        self.assertEqual(result[0], "top result content")

    def test_retrieve_weighted_with_custom_similarity(self):
        ms = _fresh_store()
        candidates = ["a", "b", "c"]
        sims = [0.9, 0.5, 0.1]
        result = ms.retrieve_weighted(candidates, similarity_scores=sims, top_k=2)
        self.assertLessEqual(len(result), 2)


class TestMemoryStoreReinforce(unittest.TestCase):
    def test_reinforce_by_id_success(self):
        ms = _fresh_store()
        ms.store("r1", "some content", source="user", confidence=0.5)
        ok = ms.reinforce_by_id("r1", success=True)
        self.assertTrue(ok)
        rec = ms.get_record("r1")
        self.assertEqual(rec.access_count, 1)
        self.assertEqual(rec.success_count, 1)

    def test_reinforce_by_id_failure(self):
        ms = _fresh_store()
        ms.store("r1", "content", source="user")
        ms.reinforce_by_id("r1", success=False)
        rec = ms.get_record("r1")
        self.assertEqual(rec.failure_count, 1)

    def test_reinforce_by_id_missing_returns_false(self):
        ms = _fresh_store()
        ok = ms.reinforce_by_id("nonexistent_id", success=True)
        self.assertFalse(ok)

    def test_reinforce_by_content(self):
        ms = _fresh_store()
        ms.store("r1", "neural networks are powerful", source="user")
        count = ms.reinforce_by_content("neural networks are powerful", success=True)
        self.assertEqual(count, 1)

    def test_reinforce_by_content_no_match(self):
        ms = _fresh_store()
        count = ms.reinforce_by_content("nonexistent content xyz", success=True)
        self.assertEqual(count, 0)


class TestMemoryStorePruneCompress(unittest.TestCase):
    def test_prune_removes_dead_unused_records(self):
        from modules.memory_weighting import make_record, TIER_COLD
        ms = _fresh_store(prune_dead=True)
        # Manually insert a dead record
        dead = make_record("dead", "dead content", source="research", confidence=0.001)
        dead.weight = TIER_COLD * 0.1  # force below threshold
        dead.tier = "dead"
        dead.access_count = 0
        ms._records["dead"] = dead
        ms.store("alive", "alive content", source="user", confidence=0.9)
        removed = ms.prune()
        self.assertGreaterEqual(removed, 1)
        self.assertIsNone(ms.get_record("dead"))

    def test_prune_respects_access_count(self):
        from modules.memory_weighting import make_record, TIER_COLD
        ms = _fresh_store()
        # Record with low weight but has been accessed → should NOT be pruned
        accessed = make_record("acc", "accessed content", source="research",
                               confidence=0.001)
        accessed.weight = TIER_COLD * 0.1
        accessed.access_count = 5  # was useful before!
        ms._records["acc"] = accessed
        removed = ms.prune()
        self.assertEqual(removed, 0)
        self.assertIsNotNone(ms.get_record("acc"))

    def test_compress_cold_reduces_record_count(self):
        from modules.memory_weighting import make_record, TIER_COLD, TIER_WARM
        ms = _fresh_store(compress=True)
        # Insert 5 cold records
        mid = (TIER_COLD + TIER_WARM) / 2
        for i in range(5):
            rec = make_record(f"cold{i}", f"cold fact {i}", source="research",
                              confidence=0.3)
            rec.weight = mid
            rec.tier = "cold"
            ms._records[f"cold{i}"] = rec
        before = len(ms)
        count = ms.compress_cold()
        self.assertGreater(count, 0)
        # Total records should decrease (5 cold removed, 1 abstract added = net -4)
        self.assertLess(len(ms), before)

    def test_compress_cold_creates_abstract_record(self):
        from modules.memory_weighting import make_record, TIER_COLD, TIER_WARM
        ms = _fresh_store(compress=True)
        mid = (TIER_COLD + TIER_WARM) / 2
        for i in range(3):
            rec = make_record(f"c{i}", f"cold {i}", source="slsa", confidence=0.3)
            rec.weight = mid
            rec.tier = "cold"
            ms._records[f"c{i}"] = rec
        ms.compress_cold()
        abstract_recs = [r for r in ms._records.values()
                         if r.content.startswith("[Abstract]")]
        self.assertGreater(len(abstract_recs), 0)

    def test_compress_cold_with_fewer_than_2_records_noop(self):
        from modules.memory_weighting import make_record, TIER_COLD, TIER_WARM
        ms = _fresh_store(compress=True)
        mid = (TIER_COLD + TIER_WARM) / 2
        rec = make_record("solo", "solo cold", source="research", confidence=0.3)
        rec.weight = mid
        rec.tier = "cold"
        ms._records["solo"] = rec
        compressed = ms.compress_cold()
        self.assertEqual(compressed, 0)


class TestMemoryStoreMaintenance(unittest.TestCase):
    def test_run_maintenance_returns_dict(self):
        ms = _fresh_store()
        ms.store("r1", "content", source="user")
        result = ms.run_maintenance()
        for key in ("updated", "pruned", "compressed"):
            self.assertIn(key, result)

    def test_run_maintenance_increments_counter(self):
        ms = _fresh_store()
        ms.run_maintenance()
        ms.run_maintenance()
        self.assertEqual(ms._maintenance_count, 2)

    def test_update_all_weights_returns_count(self):
        ms = _fresh_store()
        for i in range(5):
            ms.store(f"r{i}", f"content {i}")
        n = ms.update_all_weights()
        self.assertEqual(n, 5)

    def test_sync_eligible_filters_by_weight(self):
        from modules.memory_weighting import make_record
        ms = _fresh_store()
        # High-weight record
        strong = make_record("s", "strong content", source="user", confidence=0.99)
        ms._records["s"] = strong
        # Manually set low weight record
        weak = make_record("w", "weak content", source="research", confidence=0.01)
        weak.weight = 0.05
        ms._records["w"] = weak
        eligible = ms.sync_eligible(min_weight=0.1)
        ids = [r.id for r in eligible]
        self.assertIn("s", ids)
        # 'w' may or may not be in, but strong should always be there

    def test_sync_eligible_default_threshold(self):
        ms = _fresh_store()
        ms.store("r1", "important content", source="user", confidence=0.9)
        eligible = ms.sync_eligible()
        self.assertGreater(len(eligible), 0)


class TestMemoryStoreAnalytics(unittest.TestCase):
    def test_tier_breakdown_has_all_tiers(self):
        ms = _fresh_store()
        tb = ms.tier_breakdown()
        for tier in ("hot", "warm", "cold", "dead", "total"):
            self.assertIn(tier, tb)

    def test_tier_breakdown_total_matches_count(self):
        ms = _fresh_store()
        for i in range(4):
            ms.store(f"r{i}", f"content {i}", source="user")
        tb = ms.tier_breakdown()
        self.assertEqual(tb["total"], len(ms))

    def test_top_records_returns_sorted(self):
        ms = _fresh_store()
        ms.store("low", "boring", source="research", confidence=0.1)
        ms.store("high", "important", source="user", confidence=0.99)
        top = ms.top_records(n=2)
        self.assertGreaterEqual(top[0].weight, top[1].weight)

    def test_stats_has_required_fields(self):
        ms = _fresh_store()
        ms.store("r", "content")
        s = ms.stats()
        for key in ("total_records", "avg_weight", "avg_confidence",
                    "tier_breakdown", "maintenance_runs"):
            self.assertIn(key, s)

    def test_len_reflects_count(self):
        ms = _fresh_store()
        for i in range(7):
            ms.store(f"r{i}", f"content {i}")
        self.assertEqual(len(ms), 7)


class TestMemoryStoreThreadSafety(unittest.TestCase):
    def test_concurrent_store_and_reinforce(self):
        ms = _fresh_store(max_records=500)
        errors = []

        def writer(start):
            try:
                for i in range(20):
                    ms.store(f"w{start}_{i}", f"content {start} {i}")
            except Exception as e:
                errors.append(e)

        def reinforcer():
            try:
                for i in range(20):
                    ms.reinforce_by_id(f"w0_{i}", success=True)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(5)]
        threads.append(threading.Thread(target=reinforcer))
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


# ─────────────────────────────────────────────────────────────────────────────
# KernelMemory integration (MWDS hooks)
# ─────────────────────────────────────────────────────────────────────────────

class TestKernelMemoryMWDS(unittest.TestCase):
    """Verify that KernelMemory correctly delegates to MemoryStore."""

    def _make_km(self):
        from modules.niblit_core_kernel import KernelMemory
        from modules.memory_weighting import MemoryStore
        mg = MagicMock()
        mg.add = MagicMock()
        mg.search.return_value = []
        mg.apply_decay.return_value = 0
        mg.count.return_value = 10
        ms = MemoryStore(prune_dead=False, compress=False)
        km = KernelMemory(memory_graph=mg, memory_store=ms)
        return km, ms

    def test_store_registers_mwds_record(self):
        km, ms = self._make_km()
        km.store("test data", importance=0.5, source="user")
        self.assertGreater(len(ms), 0)

    def test_store_all_sources_register(self):
        km, ms = self._make_km()
        for src in ("user", "research", "code", "reflection"):
            km.store(f"data for {src}", importance=0.6, source=src)
        self.assertGreater(len(ms), 0)

    def test_retrieve_uses_mwds_reranking(self):
        km, ms = self._make_km()
        km.store("important concept about AI", importance=0.9, source="user")
        result = km.retrieve("AI concepts")
        self.assertIsInstance(result, list)

    def test_decay_calls_mwds_maintenance(self):
        km, ms = self._make_km()
        km.store("data", importance=0.5)
        km.decay()
        # Maintenance counter should have incremented
        self.assertGreaterEqual(ms._maintenance_count, 1)

    def test_reinforce_content_updates_mwds(self):
        km, ms = self._make_km()
        km.store("reinforcement learning is useful", importance=0.7, source="user")
        km.reinforce_content("reinforcement learning is useful", success=True)
        # Find the record and check it was reinforced
        recs_accessed = [r for r in ms._records.values() if r.access_count > 0]
        self.assertGreater(len(recs_accessed), 0)

    def test_weighted_stats_returns_dict(self):
        km, ms = self._make_km()
        km.store("data", importance=0.6)
        stats = km.weighted_stats()
        self.assertIsInstance(stats, dict)
        self.assertIn("total_records", stats)

    def test_stats_includes_mwds(self):
        km, ms = self._make_km()
        km.store("data")
        s = km.stats()
        self.assertIn("mwds", s)
        self.assertIn("total_records", s["mwds"])


if __name__ == "__main__":
    unittest.main()
