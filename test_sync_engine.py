"""test_sync_engine.py — unit tests for LCSP v1 SyncEngine.

All tests are offline-safe: no network calls, no cloud endpoint needed.

Run with::

    pytest test_sync_engine.py -v
"""

import hashlib
import json
import math
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Import sanity
# ─────────────────────────────────────────────────────────────────────────────

class TestImports(unittest.TestCase):
    def test_module_importable(self):
        from modules import sync_engine  # noqa: F401

    def test_public_symbols(self):
        from modules.sync_engine import (
            SyncArtifact, SyncQueue, ChangeDetector, ConflictResolver,
            RESTTransport, SyncEngine, get_sync_engine,
            should_sync, compress_artifact,
        )
        for sym in (SyncArtifact, SyncQueue, ChangeDetector, ConflictResolver,
                    RESTTransport, SyncEngine, get_sync_engine,
                    should_sync, compress_artifact):
            self.assertTrue(callable(sym) or isinstance(sym, type))

    def test_singleton_is_same_instance(self):
        import modules.sync_engine as m
        m._sync_engine = None
        k1 = m.get_sync_engine()
        k2 = m.get_sync_engine()
        self.assertIs(k1, k2)
        m._sync_engine = None  # cleanup


# ─────────────────────────────────────────────────────────────────────────────
# SyncArtifact
# ─────────────────────────────────────────────────────────────────────────────

class TestSyncArtifact(unittest.TestCase):
    def _make(self, **kwargs):
        from modules.sync_engine import SyncArtifact
        return SyncArtifact(**kwargs)

    def test_defaults(self):
        from modules.sync_engine import SyncArtifact, SYNC_STATE_PENDING
        a = SyncArtifact()
        self.assertEqual(a.type, "memory")
        self.assertEqual(a.version, 1)
        self.assertEqual(a.source, "local")
        self.assertEqual(a.sync_state, SYNC_STATE_PENDING)

    def test_id_auto_generated(self):
        from modules.sync_engine import SyncArtifact
        a = SyncArtifact()
        b = SyncArtifact()
        self.assertNotEqual(a.id, b.id)

    def test_update_hash(self):
        from modules.sync_engine import SyncArtifact
        a = SyncArtifact(content={"text": "hello"})
        a.update_hash()
        expected = hashlib.sha256(
            json.dumps({"text": "hello"}, sort_keys=True).encode()
        ).hexdigest()
        self.assertEqual(a.hash, expected)

    def test_to_dict_and_from_dict_roundtrip(self):
        from modules.sync_engine import SyncArtifact
        a = SyncArtifact(id="abc", type="code", content={"code": "x=1"}, priority=0.8)
        d = a.to_dict()
        b = SyncArtifact.from_dict(d)
        self.assertEqual(b.id, "abc")
        self.assertEqual(b.type, "code")
        self.assertAlmostEqual(b.priority, 0.8)

    def test_from_dict_ignores_unknown_keys(self):
        from modules.sync_engine import SyncArtifact
        a = SyncArtifact.from_dict({"id": "xyz", "unknown_key": "ignored"})
        self.assertEqual(a.id, "xyz")

    def test_mark_synced(self):
        from modules.sync_engine import SyncArtifact, SYNC_STATE_SYNCED
        a = SyncArtifact()
        a.mark_synced()
        self.assertEqual(a.sync_state, SYNC_STATE_SYNCED)

    def test_mark_failed(self):
        from modules.sync_engine import SyncArtifact, SYNC_STATE_FAILED
        a = SyncArtifact()
        a.mark_failed()
        self.assertEqual(a.sync_state, SYNC_STATE_FAILED)

    def test_origin_device_set(self):
        from modules.sync_engine import SyncArtifact
        a = SyncArtifact()
        self.assertIsInstance(a.origin_device, str)
        self.assertTrue(len(a.origin_device) > 0)


# ─────────────────────────────────────────────────────────────────────────────
# SyncQueue
# ─────────────────────────────────────────────────────────────────────────────

def _tmp_queue():
    """Return a SyncQueue backed by a temp file."""
    from modules.sync_engine import SyncQueue
    f = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
    f.close()
    return SyncQueue(queue_path=f.name), f.name


class TestSyncQueue(unittest.TestCase):
    def tearDown(self):
        # clean up temp files
        for attr in ("_qpath",):
            p = getattr(self, attr, None)
            if p:
                try:
                    Path(p).unlink(missing_ok=True)
                except Exception:
                    pass

    def test_push_and_drain(self):
        from modules.sync_engine import SyncArtifact
        q, self._qpath = _tmp_queue()
        a = SyncArtifact(id="test1")
        q.push(a)
        items = q.drain()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].id, "test1")

    def test_size(self):
        from modules.sync_engine import SyncArtifact
        q, self._qpath = _tmp_queue()
        for _ in range(3):
            q.push(SyncArtifact())
        self.assertEqual(q.size(), 3)

    def test_commit_drained_removes_items(self):
        from modules.sync_engine import SyncArtifact
        q, self._qpath = _tmp_queue()
        for _ in range(5):
            q.push(SyncArtifact())
        q.commit_drained(3)
        self.assertEqual(q.size(), 2)

    def test_clear(self):
        from modules.sync_engine import SyncArtifact
        q, self._qpath = _tmp_queue()
        q.push(SyncArtifact())
        q.clear()
        self.assertEqual(q.size(), 0)

    def test_drain_max_items(self):
        from modules.sync_engine import SyncArtifact
        q, self._qpath = _tmp_queue()
        for _ in range(10):
            q.push(SyncArtifact())
        items = q.drain(max_items=3)
        self.assertEqual(len(items), 3)

    def test_persists_to_disk(self):
        from modules.sync_engine import SyncArtifact, SyncQueue
        f = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        f.close()
        self._qpath = f.name
        q1 = SyncQueue(queue_path=f.name)
        q1.push(SyncArtifact(id="persist_me"))

        # Reload from same file
        q2 = SyncQueue(queue_path=f.name)
        self.assertEqual(q2.size(), 1)
        self.assertEqual(q2.drain()[0].id, "persist_me")

    def test_drain_is_nondestructive(self):
        from modules.sync_engine import SyncArtifact
        q, self._qpath = _tmp_queue()
        q.push(SyncArtifact(id="nd"))
        q.drain()
        q.drain()
        self.assertEqual(q.size(), 1)

    def test_thread_safe_push(self):
        from modules.sync_engine import SyncArtifact
        q, self._qpath = _tmp_queue()
        errors = []

        def push_many():
            try:
                for _ in range(10):
                    q.push(SyncArtifact())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=push_many) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(q.size(), 50)


# ─────────────────────────────────────────────────────────────────────────────
# ChangeDetector
# ─────────────────────────────────────────────────────────────────────────────

class TestChangeDetector(unittest.TestCase):
    def setUp(self):
        from modules.sync_engine import ChangeDetector
        self.cd = ChangeDetector()

    def test_first_call_is_changed(self):
        self.assertTrue(self.cd.has_changed("a1", {"x": 1}))

    def test_second_call_same_content_not_changed(self):
        self.cd.has_changed("a2", {"x": 1})
        self.assertFalse(self.cd.has_changed("a2", {"x": 1}))

    def test_different_content_is_changed(self):
        self.cd.has_changed("a3", {"x": 1})
        self.assertTrue(self.cd.has_changed("a3", {"x": 2}))

    def test_compute_is_deterministic(self):
        h1 = self.cd.compute({"key": "value"})
        h2 = self.cd.compute({"key": "value"})
        self.assertEqual(h1, h2)

    def test_compute_different_content(self):
        h1 = self.cd.compute({"a": 1})
        h2 = self.cd.compute({"a": 2})
        self.assertNotEqual(h1, h2)

    def test_mark_seen(self):
        h = self.cd.compute({"x": 1})
        self.cd.mark_seen("a4", h)
        self.assertFalse(self.cd.has_changed("a4", {"x": 1}))

    def test_forget(self):
        self.cd.has_changed("a5", {"x": 1})
        self.cd.forget("a5")
        self.assertTrue(self.cd.has_changed("a5", {"x": 1}))

    def test_snapshot_returns_dict(self):
        self.cd.has_changed("a6", {"x": 1})
        snap = self.cd.snapshot()
        self.assertIsInstance(snap, dict)
        self.assertIn("a6", snap)


# ─────────────────────────────────────────────────────────────────────────────
# ConflictResolver
# ─────────────────────────────────────────────────────────────────────────────

def _make_artifact(updated_at=None, weight=0.5, **kwargs):
    from modules.sync_engine import SyncArtifact
    a = SyncArtifact(**kwargs)
    if updated_at is not None:
        a.updated_at = updated_at
    a.weight = weight
    return a


class TestConflictResolver(unittest.TestCase):
    def setUp(self):
        from modules.sync_engine import ConflictResolver
        self.resolver = ConflictResolver()

    def test_newer_local_wins_on_timestamp(self):
        now = time.time()
        local = _make_artifact(id="x", updated_at=now + 10)
        remote = _make_artifact(id="x", updated_at=now)
        winner, reason = self.resolver.resolve(local, remote)
        self.assertEqual(winner.id, local.id)
        self.assertIn("timestamp", reason)
        self.assertIn("local", reason)

    def test_newer_remote_wins_on_timestamp(self):
        now = time.time()
        local = _make_artifact(id="x", updated_at=now)
        remote = _make_artifact(id="x", updated_at=now + 10)
        winner, reason = self.resolver.resolve(local, remote)
        self.assertIn("remote", reason)

    def test_heavier_weight_wins_when_timestamps_equal(self):
        now = time.time()
        local = _make_artifact(id="x", updated_at=now, weight=0.9)
        remote = _make_artifact(id="x", updated_at=now, weight=0.3)
        winner, reason = self.resolver.resolve(local, remote)
        self.assertAlmostEqual(winner.weight, 0.9)
        self.assertIn("weight", reason)

    def test_merge_when_equal(self):
        now = time.time()
        local = _make_artifact(id="x", updated_at=now, weight=0.5, content={"a": 1})
        remote = _make_artifact(id="x", updated_at=now, weight=0.5, content={"b": 2})
        winner, reason = self.resolver.resolve(local, remote)
        self.assertIn("merge", reason)
        self.assertIn("a", winner.content)
        self.assertIn("b", winner.content)

    def test_merge_version_incremented(self):
        now = time.time()
        local = _make_artifact(id="x", updated_at=now, weight=0.5, version=3)
        remote = _make_artifact(id="x", updated_at=now, weight=0.5, version=4)
        winner, _ = self.resolver.resolve(local, remote)
        self.assertGreater(winner.version, 4)

    def test_resolve_returns_tuple(self):
        a = _make_artifact(id="x")
        b = _make_artifact(id="x")
        result = self.resolver.resolve(a, b)
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)


# ─────────────────────────────────────────────────────────────────────────────
# should_sync
# ─────────────────────────────────────────────────────────────────────────────

class TestShouldSync(unittest.TestCase):
    def _should(self, **kwargs):
        from modules.sync_engine import should_sync, SyncArtifact
        return should_sync(SyncArtifact(**kwargs))

    def test_high_priority_memory(self):
        self.assertTrue(self._should(type="memory", priority=0.8))

    def test_below_threshold(self):
        self.assertFalse(self._should(type="memory", priority=0.1))

    def test_temp_type_excluded(self):
        self.assertFalse(self._should(type="temp", priority=0.9))

    def test_exactly_at_threshold(self):
        from modules.sync_engine import should_sync, SyncArtifact
        a = SyncArtifact(type="memory", priority=0.3)
        self.assertTrue(should_sync(a, min_priority=0.3))

    def test_slsa_type_included(self):
        self.assertTrue(self._should(type="slsa", priority=0.7))


# ─────────────────────────────────────────────────────────────────────────────
# compress_artifact
# ─────────────────────────────────────────────────────────────────────────────

class TestCompressArtifact(unittest.TestCase):
    def test_truncates_long_text(self):
        from modules.sync_engine import compress_artifact, SyncArtifact
        a = SyncArtifact(type="memory", content={"text": "x" * 1000})
        c = compress_artifact(a)
        self.assertLessEqual(len(c.content["text"]), 503)  # 500 + ellipsis

    def test_removes_embedding(self):
        from modules.sync_engine import compress_artifact, SyncArtifact
        a = SyncArtifact(type="memory", content={"embedding": [0.1] * 384, "text": "hello"})
        c = compress_artifact(a)
        self.assertNotIn("embedding", c.content)

    def test_sets_compressed_flag(self):
        from modules.sync_engine import compress_artifact, SyncArtifact
        a = SyncArtifact(type="memory", content={"text": "x" * 600})
        c = compress_artifact(a)
        self.assertTrue(c.content.get("_compressed"))

    def test_non_memory_returned_unchanged(self):
        from modules.sync_engine import compress_artifact, SyncArtifact
        a = SyncArtifact(type="code", content={"code": "x" * 1000})
        c = compress_artifact(a)
        self.assertEqual(c.content, a.content)

    def test_hash_updated(self):
        from modules.sync_engine import compress_artifact, SyncArtifact
        a = SyncArtifact(type="memory", content={"text": "x" * 600})
        c = compress_artifact(a)
        self.assertTrue(len(c.hash) > 0)


# ─────────────────────────────────────────────────────────────────────────────
# RESTTransport
# ─────────────────────────────────────────────────────────────────────────────

class TestRESTTransport(unittest.TestCase):
    def test_not_configured_without_endpoint(self):
        from modules.sync_engine import RESTTransport
        t = RESTTransport(endpoint="")
        self.assertFalse(t.configured)

    def test_configured_with_endpoint(self):
        from modules.sync_engine import RESTTransport
        t = RESTTransport(endpoint="https://example.com")
        self.assertTrue(t.configured)

    def test_push_returns_false_without_endpoint(self):
        from modules.sync_engine import RESTTransport, SyncArtifact
        t = RESTTransport(endpoint="")
        self.assertFalse(t.push([SyncArtifact()]))

    def test_pull_returns_empty_without_endpoint(self):
        from modules.sync_engine import RESTTransport
        t = RESTTransport(endpoint="")
        self.assertEqual(t.pull(), [])

    def test_push_graceful_on_network_error(self):
        from modules.sync_engine import RESTTransport, SyncArtifact
        t = RESTTransport(endpoint="http://localhost:1")  # nothing listening
        result = t.push([SyncArtifact()])
        self.assertFalse(result)

    def test_pull_graceful_on_network_error(self):
        from modules.sync_engine import RESTTransport
        t = RESTTransport(endpoint="http://localhost:1")
        result = t.pull()
        self.assertEqual(result, [])


# ─────────────────────────────────────────────────────────────────────────────
# SyncEngine (isolated, no real MWDS/kernel)
# ─────────────────────────────────────────────────────────────────────────────

def _make_engine(mode="offline", with_memory_store=False):
    """Return a SyncEngine with mocked transport and temp queue."""
    from modules.sync_engine import SyncEngine, RESTTransport, SyncQueue, ChangeDetector, ConflictResolver
    transport = MagicMock(spec=RESTTransport)
    transport.configured = False
    transport.push.return_value = False
    transport.pull.return_value = []

    f = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
    f.close()
    queue = SyncQueue(queue_path=f.name)

    ms = None
    if with_memory_store:
        ms = MagicMock()
        ms.sync_eligible.return_value = []

    engine = SyncEngine(
        mode=mode,
        interval=9999,  # never fires in tests
        transport=transport,
        queue=queue,
        detector=ChangeDetector(),
        resolver=ConflictResolver(),
        memory_store=ms,
    )
    return engine, transport, queue


class TestSyncEngineQueueArtifact(unittest.TestCase):
    def test_queues_eligible_artifact(self):
        from modules.sync_engine import SyncArtifact
        engine, _, q = _make_engine()
        a = SyncArtifact(type="memory", priority=0.8)
        result = engine.queue_artifact(a)
        self.assertTrue(result)
        self.assertEqual(q.size(), 1)

    def test_skips_low_priority(self):
        from modules.sync_engine import SyncArtifact
        engine, _, q = _make_engine()
        a = SyncArtifact(type="memory", priority=0.1)
        result = engine.queue_artifact(a)
        self.assertFalse(result)
        self.assertEqual(q.size(), 0)

    def test_skips_temp_type(self):
        from modules.sync_engine import SyncArtifact
        engine, _, q = _make_engine()
        a = SyncArtifact(type="temp", priority=0.9)
        result = engine.queue_artifact(a)
        self.assertFalse(result)

    def test_dedup_unchanged(self):
        from modules.sync_engine import SyncArtifact
        engine, _, q = _make_engine()
        a = SyncArtifact(type="memory", priority=0.8, content={"x": 1})
        engine.queue_artifact(a)
        engine.queue_artifact(a)  # same content
        self.assertEqual(q.size(), 1)

    def test_queues_after_content_change(self):
        from modules.sync_engine import SyncArtifact
        engine, _, q = _make_engine()
        a = SyncArtifact(id="x", type="memory", priority=0.8, content={"x": 1})
        engine.queue_artifact(a)
        a.content = {"x": 2}
        engine.queue_artifact(a)
        self.assertEqual(q.size(), 2)


class TestSyncEngineCycleOffline(unittest.TestCase):
    def test_run_cycle_returns_dict(self):
        engine, _, _ = _make_engine(mode="offline")
        result = engine.run_cycle()
        self.assertIsInstance(result, dict)

    def test_run_cycle_has_required_keys(self):
        engine, _, _ = _make_engine(mode="offline")
        result = engine.run_cycle()
        for k in ("queued", "pushed", "pulled", "latency_ms"):
            self.assertIn(k, result)

    def test_offline_mode_does_not_push(self):
        engine, transport, _ = _make_engine(mode="offline")
        engine.run_cycle()
        transport.push.assert_not_called()

    def test_cycle_increments_stats(self):
        engine, _, _ = _make_engine(mode="offline")
        engine.run_cycle()
        self.assertEqual(engine._stats["cycles_completed"], 1)


class TestSyncEngineCycleBatch(unittest.TestCase):
    def test_batch_mode_calls_push_when_configured(self):
        from modules.sync_engine import SyncArtifact, RESTTransport, SyncQueue, SyncEngine, ChangeDetector, ConflictResolver
        transport = MagicMock(spec=RESTTransport)
        transport.configured = True
        transport.push.return_value = True
        transport.pull.return_value = []

        f = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        f.close()
        queue = SyncQueue(queue_path=f.name)

        engine = SyncEngine(
            mode="batch",
            interval=9999,
            transport=transport,
            queue=queue,
            detector=ChangeDetector(),
            resolver=ConflictResolver(),
        )
        # Queue an artifact manually
        a = SyncArtifact(type="memory", priority=0.8, content={"text": "sync me"})
        queue.push(a)
        engine.run_cycle()
        transport.push.assert_called()
        Path(f.name).unlink(missing_ok=True)


class TestSyncEngineStatus(unittest.TestCase):
    def test_status_returns_dict(self):
        engine, _, _ = _make_engine()
        s = engine.status()
        self.assertIsInstance(s, dict)

    def test_status_has_required_keys(self):
        engine, _, _ = _make_engine()
        s = engine.status()
        for k in ("mode", "interval", "queue_size", "endpoint_configured", "device_id"):
            self.assertIn(k, s)

    def test_status_mode_correct(self):
        engine, _, _ = _make_engine(mode="lazy")
        self.assertEqual(engine.status()["mode"], "lazy")


class TestSyncEngineProviders(unittest.TestCase):
    def test_register_and_collect_provider(self):
        from modules.sync_engine import SyncArtifact
        engine, _, _ = _make_engine()
        artifacts = [SyncArtifact(type="slsa", priority=0.7)]
        engine.register_provider(lambda: artifacts)
        collected = engine.collect_artifacts()
        self.assertTrue(any(a.type == "slsa" for a in collected))

    def test_provider_exception_does_not_crash_collect(self):
        engine, _, _ = _make_engine()

        def bad_provider():
            raise RuntimeError("provider failed")

        engine.register_provider(bad_provider)
        collected = engine.collect_artifacts()
        self.assertIsInstance(collected, list)


class TestSyncEngineMWDS(unittest.TestCase):
    def test_collects_from_memory_store(self):
        from modules.sync_engine import SyncEngine, ChangeDetector, ConflictResolver, RESTTransport, SyncQueue
        ms = MagicMock()

        # Simulate a MemoryRecord-like object
        rec = MagicMock()
        rec.record_id = "rec1"
        rec.content = "important memory text"
        rec.importance = 0.7
        rec.source = "kernel"
        rec.weight = 0.65
        ms.sync_eligible.return_value = [rec]

        f = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        f.close()
        engine = SyncEngine(
            mode="offline",
            interval=9999,
            transport=RESTTransport(endpoint=""),
            queue=SyncQueue(queue_path=f.name),
            detector=ChangeDetector(),
            resolver=ConflictResolver(),
            memory_store=ms,
        )
        collected = engine.collect_artifacts()
        Path(f.name).unlink(missing_ok=True)
        self.assertTrue(any(a.id == "rec1" for a in collected))


class TestSyncEngineKernelFeedback(unittest.TestCase):
    def test_feedback_to_kernel_does_not_raise(self):
        engine, _, _ = _make_engine()
        # Should not raise even if kernel unavailable
        engine.feedback_to_kernel(queued=5, pushed=3, pulled=2, latency_ms=100)

    def test_feedback_writes_to_injected_km(self):
        from modules.sync_engine import SyncEngine, RESTTransport, SyncQueue, ChangeDetector, ConflictResolver
        km = MagicMock()
        km.store.return_value = None
        f = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        f.close()
        engine = SyncEngine(
            mode="offline",
            interval=9999,
            transport=RESTTransport(endpoint=""),
            queue=SyncQueue(queue_path=f.name),
            detector=ChangeDetector(),
            resolver=ConflictResolver(),
            kernel_memory=km,
        )
        engine.feedback_to_kernel(queued=1, pushed=1, pulled=0, latency_ms=50)
        Path(f.name).unlink(missing_ok=True)
        km.store.assert_called_once()
        call_args = km.store.call_args
        args, kwargs = call_args
        stored_event = args[0]
        self.assertEqual(stored_event["event"], "sync_completed")
        self.assertEqual(stored_event["artifacts_queued"], 1)


class TestSyncEngineStop(unittest.TestCase):
    def test_stop_sets_event(self):
        engine, _, _ = _make_engine()
        self.assertFalse(engine._stop_event.is_set())
        engine.stop()
        self.assertTrue(engine._stop_event.is_set())

    def test_background_loop_stops_on_stop(self):
        engine, _, _ = _make_engine(mode="batch")
        engine.interval = 0.1  # fast for test
        t = engine.start_background_loop()
        time.sleep(0.25)
        engine.stop()
        t.join(timeout=2.0)
        self.assertFalse(t.is_alive())


class TestSyncEngineThreadSafety(unittest.TestCase):
    def test_concurrent_queue_artifact(self):
        from modules.sync_engine import SyncArtifact
        engine, _, q = _make_engine()
        errors = []

        def enqueue(i):
            try:
                a = SyncArtifact(id=f"art{i}", type="memory", priority=0.8, content={"i": i})
                engine.queue_artifact(a)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=enqueue, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
