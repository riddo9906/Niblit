#!/usr/bin/env python3
"""Atomic persistence tests for KnowledgeDB governed save architecture."""

from __future__ import annotations

import json
import os
import threading
import time


def _fresh_knowledge_db(path):
    from niblit_memory import KnowledgeDB

    KnowledgeDB._instance = None
    return KnowledgeDB(path=str(path), autosave_interval=1, dump_interval=1)


def test_atomic_commit_manager_rotates_backup_and_snapshot(tmp_path):
    from niblit_memory import AtomicCommitManager

    primary = tmp_path / "kb.json"
    backup = tmp_path / "kb.json.backup"
    snapshot = tmp_path / "kb.json.snapshot"
    primary.write_text(json.dumps({"facts": [{"key": "old"}]}), encoding="utf-8")

    manager = AtomicCommitManager()
    manager.commit_json(
        path=str(primary),
        payload={"facts": [{"key": "new"}], "meta": {"schema_version": "2.0"}},
        backup_path=str(backup),
        snapshot_path=str(snapshot),
        snapshot_write_enabled=True,
    )

    current = json.loads(primary.read_text(encoding="utf-8"))
    prev = json.loads(backup.read_text(encoding="utf-8"))
    snap = json.loads(snapshot.read_text(encoding="utf-8"))

    assert current["facts"][0]["key"] == "new"
    assert prev["facts"][0]["key"] == "old"
    assert snap["facts"][0]["key"] == "new"


def test_knowledge_db_single_writer_flush_preserves_valid_json(tmp_path):
    mem = tmp_path / "kb.json"
    db = _fresh_knowledge_db(mem)

    db._save(blocking=True)
    db.add_fact("k1", {"value": "v1"}, tags=["unit"])
    db.store_learning({"trace_id": "t-1", "input": "hello", "response": "world"})
    db.queue_learning("atomic queue test")
    db._save(blocking=True)

    parsed = json.loads(mem.read_text(encoding="utf-8"))
    assert isinstance(parsed.get("facts"), list)
    assert isinstance(parsed.get("learning_log"), list)
    assert isinstance(parsed.get("learning_queue"), list)
    assert parsed.get("meta", {}).get("schema_version") == "2.0"
    assert mem.with_suffix(".json.backup").exists()
    assert not mem.with_suffix(".json.snapshot").exists()
    db.shutdown()


def test_atomic_commit_manager_skips_snapshot_when_guard_disabled(tmp_path):
    from niblit_memory import AtomicCommitManager

    primary = tmp_path / "kb.json"
    backup = tmp_path / "kb.json.backup"
    snapshot = tmp_path / "kb.json.snapshot"
    primary.write_text(json.dumps({"facts": [{"key": "old"}]}), encoding="utf-8")

    manager = AtomicCommitManager()
    manager.commit_json(
        path=str(primary),
        payload={"facts": [{"key": "new"}], "meta": {"schema_version": "2.0"}},
        backup_path=str(backup),
        snapshot_path=str(snapshot),
    )

    assert json.loads(primary.read_text(encoding="utf-8"))["facts"][0]["key"] == "new"
    assert json.loads(backup.read_text(encoding="utf-8"))["facts"][0]["key"] == "old"
    assert not snapshot.exists()


def test_replay_safe_hooks_populate_lineage_fields():
    from niblit_memory import ReplaySafePersistenceHooks

    payload = ReplaySafePersistenceHooks().apply({"meta": {}})
    meta = payload["meta"]

    assert "replay_metadata" in meta
    assert "trace_id" in meta["replay_metadata"]
    assert "lineage" in meta["replay_metadata"]
    assert "governance_state" in meta
    assert "runtime_mode" in meta


def test_atomic_commit_manager_falls_back_to_direct_write_when_replace_fails(tmp_path, monkeypatch):
    from niblit_memory import AtomicCommitManager
    import niblit_memory as memory_module

    primary = tmp_path / "kb.json"
    manager = AtomicCommitManager()

    original_replace = memory_module.os.replace

    def fail_replace(src, dst):
        raise PermissionError("simulated replace failure")

    monkeypatch.setattr(memory_module.os, "replace", fail_replace)
    try:
        manager.commit_json(
            path=str(primary),
            payload={"facts": [], "meta": {"schema_version": "2.0"}},
        )
    finally:
        monkeypatch.setattr(memory_module.os, "replace", original_replace)

    assert json.loads(primary.read_text(encoding="utf-8"))["meta"]["schema_version"] == "2.0"


def test_atomic_commit_manager_serializes_concurrent_commits_for_same_path(tmp_path):
    from niblit_memory import AtomicCommitManager

    primary = tmp_path / "kb.json"
    manager_a = AtomicCommitManager()
    manager_b = AtomicCommitManager()

    first_started = threading.Event()
    release_first = threading.Event()
    overlap_detected = threading.Event()

    original_atomic_write_text = AtomicCommitManager._atomic_write_text

    def blocking_atomic_write_text(self, path, text):
        if os.path.abspath(path) != os.path.abspath(str(primary)):
            return original_atomic_write_text(self, path, text)
        if not first_started.is_set():
            first_started.set()
            release_first.wait(timeout=2.0)
            return original_atomic_write_text(self, path, text)
        overlap_detected.set()
        return original_atomic_write_text(self, path, text)

    AtomicCommitManager._atomic_write_text = blocking_atomic_write_text
    try:
        def commit_a():
            manager_a.commit_json(path=str(primary), payload={"facts": [], "meta": {"schema_version": "2.0"}})

        def commit_b():
            manager_b.commit_json(path=str(primary), payload={"facts": [], "meta": {"schema_version": "2.0"}})

        thread_a = threading.Thread(target=commit_a)
        thread_b = threading.Thread(target=commit_b)
        thread_a.start()
        assert first_started.wait(timeout=2.0)
        thread_b.start()
        time.sleep(0.1)
        assert not overlap_detected.is_set()
        release_first.set()
        thread_a.join(timeout=5.0)
        thread_b.join(timeout=5.0)
    finally:
        AtomicCommitManager._atomic_write_text = original_atomic_write_text


def test_runtime_manager_exposes_runtime_owned_persistence_manager():
    from core.runtime_manager import RuntimeManager
    import niblit_memory

    runtime = RuntimeManager()
    persistence = runtime.get_persistence_manager()
    knowledge_db = runtime.get_knowledge_db()

    assert persistence is not None
    assert persistence in runtime.get_runtime_services()["services"].values() or runtime.get_diagnostics()["services"].get("knowledge_db")
    assert isinstance(knowledge_db, niblit_memory.KnowledgeDB)
    assert knowledge_db._persistence is persistence.get_coordinator(knowledge_db.path, knowledge_db.backup_path, knowledge_db.snapshot_path)


def test_persistence_manager_initializes_required_runtime_directories(tmp_path):
    from niblit_memory import PersistenceManager

    manager = PersistenceManager(root_dir=str(tmp_path / "runtime"), memory_path=str(tmp_path / "runtime" / "niblit_memory.json"))
    diagnostics = manager.initialize_runtime_assets()

    assert diagnostics["status"] == "ready"
    assert (tmp_path / "runtime" / "memory").exists()
    assert (tmp_path / "runtime" / "cache").exists()
    assert (tmp_path / "runtime" / "logs").exists()
    assert (tmp_path / "runtime" / "snapshots").exists()
    assert (tmp_path / "runtime" / "backups").exists()
    assert (tmp_path / "runtime" / "indexes").exists()
    assert (tmp_path / "runtime" / "niblit_memory.json").exists()


def test_embedding_middleware_returns_deterministic_384_vectors():
    from niblit_memory import EmbeddingMiddleware

    middleware = EmbeddingMiddleware()
    v1 = middleware.embed_text("Niblit persistence durability")
    v2 = middleware.embed_text("Niblit persistence durability")
    batch = middleware.embed_batch(["A", "B"])

    assert len(v1) == 384
    assert v1 == v2
    assert len(batch) == 2
    assert all(len(v) == 384 for v in batch)


if __name__ == "__main__":
    print('Running test_knowledge_db_atomic_persistence.py')
