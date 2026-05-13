#!/usr/bin/env python3
"""Recovery tests for KnowledgeDB corruption handling."""

from __future__ import annotations

import json
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
    qf = tmp_path / "kb.json.quarantine.jsonl"
    assert qf.exists()
    lines = [json.loads(line) for line in qf.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(entry.get("reason") == "json_repaired" for entry in lines)
    assert any("single_quote_keys_fixed" in str(entry.get("details", "")) for entry in lines)
    assert any("trailing_commas_removed" in str(entry.get("details", "")) for entry in lines)


def test_knowledge_db_falls_back_to_backup_when_primary_unrecoverable(tmp_path):
    mem = tmp_path / "kb.json"
    backup = tmp_path / "kb.json.backup"
    mem.write_text('{"facts": [', encoding="utf-8")
    backup.write_text('{"facts": [{"key":"k","value":"v"}]}', encoding="utf-8")

    db = _fresh_knowledge_db(mem)
    facts = db.get("facts", [])

    assert any(isinstance(item, dict) and item.get("key") == "k" for item in facts)
    qf = tmp_path / "kb.json.quarantine.jsonl"
    lines = [json.loads(line) for line in qf.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert any(entry.get("reason") == "json_corruption_unrecoverable" for entry in lines)
