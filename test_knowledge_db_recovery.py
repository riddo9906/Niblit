#!/usr/bin/env python3
"""Recovery tests for KnowledgeDB corruption handling."""

from __future__ import annotations

from pathlib import Path


def _fresh_knowledge_db(path: Path):
    from niblit_memory import KnowledgeDB

    KnowledgeDB._instance = None  # reset singleton for isolated test instances
    return KnowledgeDB(path=str(path))


def test_knowledge_db_repairs_single_quotes_and_trailing_commas(tmp_path):
    mem = tmp_path / "kb.json"
    mem.write_text("{'facts': [], 'interactions': [],}", encoding="utf-8")

    db = _fresh_knowledge_db(mem)

    assert isinstance(db.get("facts"), list)
    assert (tmp_path / "kb.json.quarantine.jsonl").exists()


def test_knowledge_db_falls_back_to_backup_when_primary_unrecoverable(tmp_path):
    mem = tmp_path / "kb.json"
    backup = tmp_path / "kb.json.backup"
    mem.write_text('{"facts": [', encoding="utf-8")
    backup.write_text('{"facts": [{"key":"k","value":"v"}]}', encoding="utf-8")

    db = _fresh_knowledge_db(mem)
    facts = db.get("facts", [])

    assert any(isinstance(item, dict) and item.get("key") == "k" for item in facts)
