#!/usr/bin/env python3
"""Atomic persistence tests for KnowledgeDB governed save architecture."""

from __future__ import annotations

import json


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
