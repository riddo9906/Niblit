import json

import pytest

from modules.memory_laboratory.consolidation import Consolidator
from modules.memory_laboratory.migration import apply, plan, reconcile, rollback
from test_memory_laboratory_gateway import Backend, gateway, ingest


def test_migration_dry_run_backup_reconciliation_rollback(tmp_path):
    original = {"facts": [{"key": "Aurora", "value": "amber"}], "preferences": {"private": "not imported"}}
    source = tmp_path / "legacy.json"
    source.write_text(json.dumps(original), encoding="utf-8")
    p = plan(source, format="knowledge-json", namespace="fresh", principal="operator")
    assert p["dry_run"] and len(p["entries"]) == 1
    backend = Backend()
    g = gateway(tmp_path, backend)
    assert not backend.points
    manifest = apply(g, p, tmp_path / "backups")
    assert manifest["complete"]
    assert (tmp_path / "backups/legacy.json").read_bytes() == source.read_bytes()
    assert (tmp_path / "backups/ledger-before.sqlite3").is_file()
    assert reconcile(g, manifest)["pending"] == 0
    assert rollback(g, manifest)["audit_retained"]
    assert not g.retrieve("Aurora", namespace="fresh", principal="operator")["results"]
    assert json.loads(source.read_text()) == original


def test_changed_source_and_nonfresh_namespace_rejected(tmp_path):
    source = tmp_path / "legacy.json"
    source.write_text(json.dumps({"facts": [{"key": "a", "value": "b"}]}))
    p = plan(source, format="knowledge-json", namespace="test", principal="operator")
    g = gateway(tmp_path, Backend())
    ingest(g)
    with pytest.raises(ValueError):
        apply(g, p, tmp_path / "backup")
    source.write_text('{"facts":[]}')
    with pytest.raises(ValueError):
        apply(g, p, tmp_path / "changed")


def test_sensitive_facts_require_private_review(tmp_path):
    source = tmp_path / "legacy.json"
    source.write_text(json.dumps({"facts": [{"key": "API_TOKEN", "value": "private"}]}))
    with pytest.raises(PermissionError):
        plan(source, format="knowledge-json", namespace="test", principal="operator")


def test_consolidation_only_proposes_and_preserves_original_evidence(tmp_path):
    g = gateway(tmp_path, Backend())
    ingest(g)
    ingest(g, "Correction: Aurora is amber-73.")
    with g.db() as db:
        before = [tuple(r) for r in db.execute("SELECT * FROM records")]
    result = Consolidator(g, namespace="test", principal="operator", max_records=2).tick()
    assert result["scanned"] <= 2
    assert any(p["kind"] == "source_correction_requires_review" for p in result["proposals"])
    assert all(p["verification"] == "unverified" for p in result["proposals"])
    with g.db() as db:
        assert [tuple(r) for r in db.execute("SELECT * FROM records")] == before
