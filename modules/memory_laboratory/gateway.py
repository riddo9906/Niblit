"""Governed source ledger and rebuildable Qdrant projection, not an orchestrator.

Evidence is committed locally before projection. Only verified projections are
retrievable. Failed/partial writes stay pending and can be retried idempotently.
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from .contracts import CATEGORIES, MemoryRecord
from .setup import QdrantSetup, validate_vector


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def permission(action, namespace, principal):
    # Use the existing file-backed operator permissions. No model can grant one.
    from modules.core_tool_runtime import _permission_manager
    return _permission_manager().check(f"memory.{action}.{namespace}")


class MemoryGateway:
    def __init__(self, config, ledger, *, authorize=permission, setup=None, event_bus=None):
        self.config = config
        self.path = Path(ledger)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.authorize = authorize
        self.backend = setup or QdrantSetup(config)
        self.event_bus = event_bus
        self.lock = threading.RLock()
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS records(
                  id TEXT PRIMARY KEY, namespace TEXT NOT NULL, principal TEXT NOT NULL,
                  source TEXT NOT NULL, payload TEXT NOT NULL, projection TEXT NOT NULL,
                  collection TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS source_scope ON records(namespace,principal,source);
                CREATE VIRTUAL TABLE IF NOT EXISTS lexical USING fts5(id UNINDEXED,content);
                CREATE TABLE IF NOT EXISTS audit(
                  seq INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, action TEXT NOT NULL,
                  record_id TEXT, metadata TEXT NOT NULL);
            """)

    def db(self):
        # A context manager below closes SQLite handles on both success/failure.
        from contextlib import contextmanager
        @contextmanager
        def connection():
            db = sqlite3.connect(self.path, timeout=15)
            db.row_factory = sqlite3.Row
            try:
                with db:
                    yield db
            finally:
                db.close()
        return connection()

    def close(self):
        self.backend.close()

    def require(self, action, namespace, principal):
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", namespace) or not principal.strip():
            raise ValueError("invalid caller scope")
        if not self.authorize(action, namespace, principal):
            raise PermissionError(f"memory.{action}.{namespace}")

    @staticmethod
    def audit(db, action, record_id, **metadata):
        db.execute("INSERT INTO audit(timestamp,action,record_id,metadata) VALUES(?,?,?,?)",
                   (now(), action, record_id, json.dumps(metadata)))

    def ingest_file(self, rel_path, *, namespace, principal, category="semantic"):
        self.require("ingest", namespace, principal)
        from modules import workspace_tools as workspace
        root = workspace._default_root()
        target = workspace._safe_resolve(root, rel_path)
        if target.suffix.lower() == ".pdf":
            parsed = workspace.read_workspace_pdf(rel_path)
            if parsed.get("truncated"):
                raise ValueError("partial PDF cannot replace complete source")
            segments = [(p["text"][start:start+1000],
                         f"{target.as_uri()}#page={p['page']}&offset={start}")
                        for p in parsed.get("pages", [])
                        for start in range(0, len(p["text"]), 1000)]
        else:
            parsed = workspace.read_workspace(rel_path)
            if parsed.get("truncated"):
                raise ValueError("partial text cannot replace complete source")
            # Keep exact line citations while grouping bounded chunks.
            segments = []
            lines = parsed.get("content", "").splitlines(keepends=True)
            start, buf = 1, ""
            for number, line in enumerate(lines, 1):
                if len(line) > 1000:
                    raise ValueError("source line exceeds bounded chunk size")
                if buf and len(buf) + len(line) > 1000:
                    segments.append((buf, f"{target.as_uri()}#L{start}-L{number-1}"))
                    start, buf = number, ""
                buf += line
            if buf:
                segments.append((buf, f"{target.as_uri()}#L{start}-L{len(lines)}"))
        if parsed.get("error"):
            raise ValueError("source_parser_rejected")
        if not segments:
            raise ValueError("empty_source")
        if any(len(text) > 1000 for text, _ in segments):
            raise ValueError("source page requires bounded chunking")
        return self.ingest(segments, source=target.as_uri(), namespace=namespace,
                           principal=principal, category=category)

    def ingest(self, segments, *, source, namespace, principal, category="semantic"):
        self.require("ingest", namespace, principal)
        if category not in CATEGORIES or not source.strip() or not 0 < len(segments) <= 200:
            raise ValueError("invalid bounded ingestion")
        for text, location in segments:
            if not text.strip() or len(text) > 1000 or not location:
                raise ValueError("invalid source chunk")
            if re.search(r'(?:gh[pousr]_|hf_|sk-(?:proj-|ant-)?)[A-Za-z0-9_-]{20,}|-----BEGIN .*PRIVATE KEY-----', text):
                raise PermissionError("credential-like source content")
        # Precompute bounded embeddings before changing authoritative state.
        vectors = [validate_vector(self.backend.embedder.embed(text)) for text, _ in segments]
        dimension = len(vectors[0])
        if any(len(vector) != dimension for vector in vectors):
            raise ValueError("embedding dimensions changed within document")
        collection = self.config.collection(category, dimension)
        stamp = now()
        version = digest(json.dumps(segments, ensure_ascii=False))
        records = []
        for index, ((text, location), vector) in enumerate(zip(segments, vectors)):
            key = json.dumps([namespace, principal, source, version, index, collection])
            record = MemoryRecord(
                memory_id=uuid5(NAMESPACE_URL, key), category=category, namespace=namespace,
                content=text, source_id=digest(source), source_location=location,
                source_type="document", provenance={"source": source, "version": version, "actor": principal},
                created_at=stamp, observed_at=stamp, updated_at=stamp, confidence=0.5,
                access_principals=[principal], embedding_model=self.config.model,
                embedding_version=self.config.revision, content_hash=digest(text), idempotency_key=digest(key))
            records.append((record, vector))
        with self.lock:
            with self.db() as db:
                for record, _ in records:
                    db.execute("INSERT OR IGNORE INTO records VALUES(?,?,?,?,?,?,?,0)",
                        (str(record.memory_id), namespace, principal, source,
                         record.model_dump_json(), "pending", collection))
                    self.audit(db, "ingestion.prepared", str(record.memory_id), source_hash=digest(source))
            path = f"/collections/{collection}/points"
            points = [{"id": str(r.memory_id), "vector": v,
                       "payload": r.model_dump(mode="json")} for r, v in records]
            self.backend.request("PUT", path + "?wait=true", json={"points": points})
            retrieved = self.backend.request("POST", path, json={
                "ids": [str(r.memory_id) for r, _ in records], "with_payload": True})
            expected = {str(r.memory_id): r.content_hash for r, _ in records}
            if {str(p["id"]): p.get("payload", {}).get("content_hash") for p in retrieved} != expected:
                raise ValueError("Qdrant projection verification failed")
            # Commit the new visible source version only after every point verifies.
            with self.db() as db:
                superseded = db.execute(
                    "SELECT * FROM records WHERE namespace=? AND principal=? AND source=? AND active=1",
                    (namespace, principal, source)).fetchall()
                db.execute("UPDATE records SET active=0 WHERE namespace=? AND principal=? AND source=?",
                           (namespace, principal, source))
                for record, _ in records:
                    key = str(record.memory_id)
                    db.execute("UPDATE records SET active=1, projection='verified' WHERE id=?", (key,))
                    db.execute("DELETE FROM lexical WHERE id=?", (key,))
                    db.execute("INSERT INTO lexical(id,content) VALUES(?,?)", (key, record.content))
                    self.audit(db, "ingestion.verified", key)
                for row in superseded:
                    if row["id"] in expected:
                        continue
                    payload = json.loads(row["payload"])
                    payload.update(lifecycle="superseded", superseded_by=next(iter(expected)), updated_at=now())
                    db.execute("UPDATE records SET payload=?,projection='supersede_pending' WHERE id=?",
                               (json.dumps(payload), row["id"]))
                    db.execute("DELETE FROM lexical WHERE id=?", (row["id"],))
                    self.audit(db, "source.superseded", row["id"], replacement=next(iter(expected)))
            warnings = []
            for row in superseded:
                if row["id"] in expected:
                    continue
                try:
                    self.backend.request("POST", f"/collections/{row['collection']}/points/payload?wait=true",
                        json={"points": [row["id"]], "payload": {
                            "lifecycle": "superseded", "superseded_by": next(iter(expected))}})
                    with self.db() as db:
                        db.execute("UPDATE records SET projection='superseded' WHERE id=?", (row["id"],))
                except Exception:
                    warnings.append("supersession_projection_pending")
        return {"verified": True, "ids": list(expected), "collection": collection,
                "version": version, "warnings": warnings}

    def retrieve(self, query, *, namespace, principal, limit=5, category=None):
        self.require("read", namespace, principal)
        if category is not None and category not in CATEGORIES:
            raise ValueError("invalid category")
        if not query.strip() or len(query) > 4000 or not 1 <= limit <= 20:
            raise ValueError("invalid bounded query")
        issues, ranks = [], {}
        tokens = re.findall(r"\w+", query)[:40]
        with self.db() as db:
            rows = db.execute("SELECT * FROM records WHERE namespace=? AND principal=? AND active=1 AND projection='verified'",
                              (namespace, principal)).fetchall()
            eligible = {r["id"]: json.loads(r["payload"]) for r in rows}
            eligible = {key: p for key, p in eligible.items()
                        if p["lifecycle"] == "active" and (not category or p["category"] == category)
                        and principal in p["access_principals"]}
            if tokens:
                lexical = db.execute("""SELECT lexical.id FROM lexical JOIN records ON lexical.id=records.id
                    WHERE lexical MATCH ? AND records.namespace=? AND records.principal=?
                    AND records.active=1 AND records.projection='verified'
                    ORDER BY lexical.rank LIMIT 200""",
                    (" OR ".join('"' + t + '"' for t in tokens), namespace, principal)).fetchall()
                lexical = [r[0] for r in lexical if r[0] in eligible]
                for rank, key in enumerate(lexical):
                    ranks[key] = 1 / (60 + rank + 1)
        try:
            vector = validate_vector(self.backend.embedder.embed(query, query=True))
            collections = {r["collection"] for r in rows if r["id"] in eligible}
            # Old model revisions require a separate migration; never query with
            # a new embedding against old vectors just because dimensions match.
            permitted = {self.config.collection(c, len(vector)) for c in CATEGORIES}
            if collections - permitted:
                issues.append("embedding_migration_required")
            for collection in collections & permitted:
                hits = self.backend.request("POST", f"/collections/{collection}/points/query", json={
                    "query": vector, "limit": min(limit * 4, 80), "with_payload": True,
                    "filter": {"must": [
                        {"key": "namespace", "match": {"value": namespace}},
                        {"key": "access_principals", "match": {"value": principal}},
                        {"key": "lifecycle", "match": {"value": "active"}}]}})["points"]
                for rank, hit in enumerate(hits):
                    key = str(hit["id"])
                    if key in eligible:
                        ranks[key] = ranks.get(key, 0) + 1 / (60 + rank + 1)
        except Exception:
            issues.append("dense_retrieval_unavailable")
        results, seen = [], set()
        for key, score in ranks.items():
            payload = eligible[key]
            age = max(0, (datetime.now(timezone.utc) - datetime.fromisoformat(payload["updated_at"])).total_seconds())
            weight = 1 + .1 * payload["importance"] + .05 / (1 + age / 86400)
            if payload["verification"] == "verified":
                weight += .1
            results.append({"id": key, "content": payload["content"],
                "citation": payload["source_location"], "score": score * weight,
                "confidence": payload["confidence"], "verification": payload["verification"],
                "content_hash": payload["content_hash"], "provenance": payload["provenance"]})
        selected = []
        for hit in sorted(results, key=lambda h: h["score"], reverse=True):
            if hit["content_hash"] not in seen:
                seen.add(hit["content_hash"])
                selected.append(hit)
            if len(selected) == limit:
                break
        return {"results": selected, "issues": issues, "mode": "hybrid" if not issues else "lexical_degraded"}

    def delete_source(self, source, *, namespace, principal):
        self.require("delete", namespace, principal)
        with self.lock, self.db() as db:
            rows = db.execute("SELECT * FROM records WHERE namespace=? AND principal=? AND source=?",
                              (namespace, principal, source)).fetchall()
            # Local revocation happens first, even if the projection is offline.
            for row in rows:
                payload = json.loads(row["payload"])
                payload.update(lifecycle="deleted", deleted_at=now(), updated_at=now())
                db.execute("UPDATE records SET active=0,projection='delete_pending',payload=? WHERE id=?",
                           (json.dumps(payload), row["id"]))
                db.execute("DELETE FROM lexical WHERE id=?", (row["id"],))
                self.audit(db, "source.deleted", row["id"])
        for row in rows:
            self.backend.request("POST", f"/collections/{row['collection']}/points/delete?wait=true",
                                 json={"points": [row["id"]]})
            with self.db() as db:
                db.execute("UPDATE records SET projection='deleted' WHERE id=?", (row["id"],))
        return {"deleted": len(rows), "original_evidence_retained": True}
