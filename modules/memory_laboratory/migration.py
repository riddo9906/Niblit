"""Explicit, dry-run-first import plans with backups and namespace rollback.

Only facts are imported from KnowledgeDB JSON; preferences, conversations and
runtime state are not silently promoted. Lab JSONL records must validate fully.
Every imported value starts unverified. Original files are never modified.
"""
import json
import re
import shutil
import sqlite3
from pathlib import Path

from .contracts import MemoryRecord
from .gateway import digest, now


def plan(source, *, format, namespace, principal):
    path = Path(source).resolve(strict=True)
    if path.name.startswith(".env") or path.stat().st_size > 5_000_000:
        raise ValueError("source restricted or too large")
    text = path.read_text(encoding="utf-8")
    entries = []
    if format == "knowledge-json":
        facts = json.loads(text).get("facts")
        if not isinstance(facts, list):
            raise ValueError("expected KnowledgeDB facts list")
        for index, fact in enumerate(facts):
            if not isinstance(fact, dict) or "key" not in fact or "value" not in fact:
                raise ValueError("invalid legacy fact; explicit adapter required")
            if re.search(r"password|secret|api.?key|token|credential", str(fact["key"]), re.I):
                raise PermissionError("sensitive legacy fact requires private review")
            content = str(fact["key"]) + ": " + json.dumps(fact["value"], ensure_ascii=False)
            entries.append({"source": path.as_uri() + f"#facts/{index}", "content": content,
                            "category": "semantic"})
    elif format == "laboratory-jsonl":
        for number, line in enumerate(text.splitlines(), 1):
            if line.strip():
                record = MemoryRecord.model_validate_json(line)
                entries.append({"source": path.as_uri() + f"#record/{number}",
                                "content": record.content, "category": record.category})
    else:
        raise ValueError("unsupported migration format")
    if not 0 < len(entries) <= 1000:
        raise ValueError("migration requires 1..1000 records")
    return {"schema": "memory-migration.v1", "source": str(path), "source_hash": digest(text),
            "namespace": namespace, "principal": principal, "format": format,
            "entries": entries, "dry_run": True, "original_source_unchanged": True}


def apply(gateway, migration_plan, backup_dir):
    namespace, principal = migration_plan["namespace"], migration_plan["principal"]
    gateway.require("ingest", namespace, principal)
    source = Path(migration_plan["source"])
    if digest(source.read_text(encoding="utf-8")) != migration_plan["source_hash"]:
        raise ValueError("source changed after dry-run")
    # A fresh namespace makes rollback precise without replacing older evidence.
    with gateway.db() as db:
        if db.execute("SELECT 1 FROM records WHERE namespace=? LIMIT 1", (namespace,)).fetchone():
            raise ValueError("migration requires a fresh namespace")
    backup = Path(backup_dir).resolve()
    backup.mkdir(parents=True, exist_ok=False)
    shutil.copy2(source, backup / source.name)
    with gateway.db() as db, sqlite3.connect(backup / "ledger-before.sqlite3") as dest:
        db.backup(dest)
    manifest = {"namespace": namespace, "principal": principal, "source_hash": migration_plan["source_hash"],
                "created_at": now(), "sources": [], "outcomes": [], "complete": False}
    manifest_path = backup / "migration-manifest.json"
    def save():
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    save()
    for entry in migration_plan["entries"]:
        # Record intent before writing so even partial projection failures can
        # be reconciled/revoked by this exact source, namespace and principal.
        manifest["sources"].append(entry["source"])
        save()
        text = entry["content"]
        if len(text) > 200000:
            raise ValueError("migration fact exceeds bounds")
        chunks = [(text[i:i+1000], entry["source"] + f"&char={i}")
                  for i in range(0, len(text), 1000)]
        outcome = gateway.ingest(chunks, source=entry["source"], namespace=namespace,
                                 principal=principal, category=entry["category"])
        manifest["outcomes"].append(outcome)
        save()
    manifest["complete"] = True
    save()
    return manifest


def reconcile(gateway, manifest):
    gateway.require("read", manifest["namespace"], manifest["principal"])
    with gateway.db() as db:
        rows = db.execute("SELECT id,source,projection,active FROM records WHERE namespace=? AND principal=?",
                          (manifest["namespace"], manifest["principal"])).fetchall()
    return {"expected_sources": len(manifest["sources"]), "records": [dict(r) for r in rows],
            "pending": sum(r["projection"] not in {"verified", "deleted", "superseded"} for r in rows)}


def rollback(gateway, manifest):
    results = []
    for source in manifest["sources"]:
        results.append(gateway.delete_source(source, namespace=manifest["namespace"],
                                              principal=manifest["principal"]))
    return {"sources_revoked": len(results), "source_files_restored": False,
            "reason": "original source files were never modified", "audit_retained": True}
