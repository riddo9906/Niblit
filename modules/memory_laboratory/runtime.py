"""Durable ingestion outbox shared by Core facts, documents and trading evidence.

SQLite owns queued source evidence; Qdrant is a rebuildable projection. Nothing
here grants model execution, invents verification, or trains a model. A single
bounded worker owns embedding work, outside the UI and Core memory locks.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
import time
from pathlib import Path

from .gateway import digest, now

SCOPE = {"namespace": "desktop", "principal": "desktop_operator"}
SECRET = re.compile(r"(?:gh[pousr]_|hf_|sk-(?:proj-|ant-)?)[A-Za-z0-9_-]{20,}|-----BEGIN .*PRIVATE KEY-----")


def readable(value):
    """Extract prose without Python repr wrappers or unrelated metadata."""
    if isinstance(value, str):
        if value.lstrip().startswith("{") and len(value) < 20000:
            try:
                import ast
                parsed = ast.literal_eval(value)
                if isinstance(parsed, dict):
                    return readable(parsed)
            except (ValueError, SyntaxError, RecursionError):
                pass
        return value.strip()
    if isinstance(value, dict):
        for key in ("content_text", "content", "definition", "explanation", "summary", "text"):
            candidate = value.get(key)
            if isinstance(candidate, (str, dict)):
                text = readable(candidate)
                if text:
                    return text
    return ""


def confidence(value):
    try:
        number = float(value.get("confidence_score", value.get("confidence", .5))) if isinstance(value, dict) else .5
        return min(1., max(0., number)) if math.isfinite(number) else .5
    except (TypeError, ValueError):
        return .5


class MemoryRuntime:
    def __init__(self, gateway, *, scope=None):
        self.gateway = gateway
        self.scope = dict(scope or SCOPE)
        self.stop_event = threading.Event()
        self.thread = None
        self.source_mtime = None
        self.source_error = None
        with gateway.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS ingestion_outbox(
                  id TEXT PRIMARY KEY, source TEXT NOT NULL, body TEXT NOT NULL,
                  state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                  next_attempt REAL NOT NULL DEFAULT 0, error TEXT, updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS outbox_ready ON ingestion_outbox(state,next_attempt);
                CREATE TABLE IF NOT EXISTS source_heads(
                  namespace TEXT NOT NULL, principal TEXT NOT NULL, source TEXT NOT NULL,
                  id TEXT NOT NULL, PRIMARY KEY(namespace,principal,source));
            """)

    def enqueue(self, *, source, content, category="semantic", metadata=None, _db=None):
        if _db is None:
            self.gateway.require("ingest", **self.scope)
        content = content.strip()
        if not source or not content or len(content) > 200000:
            raise ValueError("invalid bounded source")
        if SECRET.search(content) or re.search(r"(?:^|[/\\])\.env(?:\.|$)", source):
            raise PermissionError("credential-like source rejected")
        body = {"source": source, "content": content, "category": category,
                "metadata": metadata or {}, **self.scope}
        if category not in ("working", "semantic", "episodic", "procedural"):
            raise ValueError("invalid memory category")
        # Stable content+source+metadata identity: replaying a saved fact is free.
        encoded = json.dumps(body, sort_keys=True, ensure_ascii=False, allow_nan=False)
        key = digest(encoded)
        from contextlib import nullcontext
        with (self.gateway.db() if _db is None else nullcontext(_db)) as db:
            head = db.execute("SELECT id FROM source_heads WHERE namespace=? AND principal=? AND source=?",
                              (self.scope["namespace"], self.scope["principal"], source)).fetchone()
            db.execute("UPDATE ingestion_outbox SET state='superseded' WHERE source=? AND state='pending' AND id<>? AND json_extract(body,'$.namespace')=? AND json_extract(body,'$.principal')=?",
                       (source, key, self.scope["namespace"], self.scope["principal"]))
            db.execute("INSERT OR IGNORE INTO ingestion_outbox(id,source,body,updated_at) VALUES(?,?,?,?)",
                       (key, source, encoded, now()))
            if head is not None and head["id"] != key:
                db.execute("UPDATE ingestion_outbox SET state='pending',next_attempt=0,error=NULL,updated_at=? WHERE id=? AND state<>'processing'", (now(), key))
            db.execute("INSERT INTO source_heads VALUES(?,?,?,?) ON CONFLICT(namespace,principal,source) DO UPDATE SET id=excluded.id",
                       (self.scope["namespace"], self.scope["principal"], source, key))
        return key

    def enqueue_fact(self, fact, *, source_root="knowledge://core", _db=None):
        value = fact.get("value")
        text = readable(value)
        key = str(fact.get("key", ""))
        if not text or not key:
            return None
        if re.search(r"password|secret|api.?key|credential", key, re.I):
            return None
        # Keep original key and topic as evidence metadata, never as verification.
        meta = {"confidence": confidence(value), "source_type": "legacy_knowledge",
                "provenance": {"legacy_key": key, "topic": value.get("topic", "") if isinstance(value, dict) else ""}}
        if isinstance(value, dict):
            for field in ("url", "source_url", "title", "source", "source_type", "last_verified_at"):
                item = value.get(field)
                if isinstance(item, (str, int, float)):
                    meta["provenance"][field] = item
        return self.enqueue(source=source_root + "/" + digest(key), content=text, metadata=meta, _db=_db)

    def tick(self, limit=8):
        """One bounded pass. Multiple processes claim jobs atomically in SQLite."""
        completed, failed = 0, 0
        for _ in range(max(1, min(limit, 32))):
            with self.gateway.db() as db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute("""SELECT * FROM ingestion_outbox AS job WHERE (state='pending' OR state='processing') AND next_attempt<=?
                    AND json_extract(body,'$.namespace')=? AND json_extract(body,'$.principal')=?
                    AND NOT EXISTS(SELECT 1 FROM ingestion_outbox AS busy WHERE busy.source=job.source AND busy.state='processing' AND busy.next_attempt>? AND busy.id<>job.id)
                    ORDER BY rowid LIMIT 1""", (time.time(), self.scope["namespace"], self.scope["principal"], time.time())).fetchone()
                if row is None:
                    break
                # A lease recovers interrupted workers after five minutes.
                db.execute("UPDATE ingestion_outbox SET state='processing',next_attempt=?,attempts=attempts+1 WHERE id=?", (time.time()+300, row["id"]))
            try:
                body = json.loads(row["body"])
                text = body.pop("content")
                source = body["source"]
                segments = [(text[i:i+1000], source + f"#offset={i}") for i in range(0, len(text), 1000)]
                self.gateway.ingest(segments, **body)
                with self.gateway.db() as db:
                    db.execute("UPDATE ingestion_outbox SET state='complete',error=NULL,updated_at=? WHERE id=?", (now(), row["id"]))
                completed += 1
            except Exception as exc:
                # Store error class only: request exceptions can contain keys.
                with self.gateway.db() as db:
                    head = db.execute("SELECT id FROM source_heads WHERE namespace=? AND principal=? AND source=?", (self.scope["namespace"], self.scope["principal"], row["source"])).fetchone()
                    state = "superseded" if head and head["id"] != row["id"] else "pending"
                    db.execute("UPDATE ingestion_outbox SET state=?,next_attempt=?,error=?,updated_at=? WHERE id=?",
                               (state, time.time()+min(300, 2**min(row["attempts"]+1, 8)), type(exc).__name__, now(), row["id"]))
                failed += 1
                break  # avoid hammering an unavailable backend
        return {"completed": completed, "failed": failed}

    def status(self):
        with self.gateway.db() as db:
            counts = db.execute("SELECT state,count(*) AS count FROM ingestion_outbox GROUP BY state").fetchall()
            errors = db.execute("SELECT error,count(*) AS count FROM ingestion_outbox WHERE error IS NOT NULL GROUP BY error").fetchall()
        return {**self.gateway.status(**self.scope), "queue": [dict(r) for r in counts],
                "errors": [dict(r) for r in errors], "worker_running": bool(self.thread and self.thread.is_alive()),
                "legacy_source_error": self.source_error}

    def sync_knowledge_file(self, path):
        """Read existing atomic JSON snapshots; never modify original memory."""
        source = Path(path).resolve(strict=True)
        stat = source.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        if self.source_mtime == signature:
            return 0
        if source.name.startswith(".env") or stat.st_size > 128_000_000:
            raise ValueError("restricted or oversized knowledge snapshot")
        data = json.loads(source.read_text(encoding="utf-8-sig"))
        facts = data.get("facts")
        if not isinstance(facts, list):
            raise ValueError("expected knowledge facts")
        count = 0
        self.gateway.require("ingest", **self.scope)
        with self.gateway.db() as db:
            for fact in facts:
                if not isinstance(fact, dict):
                    continue
                try:
                    count += self.enqueue_fact(fact, _db=db) is not None
                except (PermissionError, ValueError):
                    continue  # credential-like content is never imported
        self.source_mtime = signature
        self.source_error = None
        return count

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        def work():
            last_sync = 0
            while not self.stop_event.wait(2):
                try:
                    source = os.getenv("NIBLIT_MEMORY_SYNC_SOURCE", "")
                    if source and time.monotonic()-last_sync > 15:
                        try:
                            self.sync_knowledge_file(source)
                        except Exception as exc:
                            self.source_error = type(exc).__name__
                        last_sync = time.monotonic()
                    self.tick(32)
                    from .market import MarketJournal
                    MarketJournal(self.gateway).repair_pending()
                except Exception as exc:
                    self.source_error = type(exc).__name__
                    self.stop_event.wait(5)
        self.thread = threading.Thread(target=work, name="MemoryProjectionWorker", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=15)

    def backup(self, destination):
        """Consistent SQLite backup, including source evidence, queue and audit."""
        import sqlite3
        target = Path(destination).resolve()
        if target.exists() or target == self.gateway.path.resolve():
            raise ValueError("backup destination must be a new file")
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.gateway.db() as source, sqlite3.connect(target) as dest:
            source.backup(dest)
        return {"path": str(target), "qdrant_rebuildable": True}

    def rebuild(self, limit=100, after=""):
        """Repair active projections from original ledger, never from generated text."""
        self.gateway.require("ingest", **self.scope)
        with self.gateway.db() as db:
            rows = db.execute("SELECT * FROM records WHERE namespace=? AND principal=? AND active=1 AND id>? ORDER BY id LIMIT ?", (self.scope["namespace"], self.scope["principal"], after, max(1, min(limit, 1000)))).fetchall()
        repaired = 0
        from .setup import validate_vector
        for row in rows:
            p = json.loads(row["payload"])
            if p["embedding_model"] != self.gateway.config.model or p["embedding_version"] != self.gateway.config.revision:
                raise ValueError("explicit embedding migration required")
            vector = validate_vector(self.gateway.backend.embedder.embed(p["content"]))
            path = f"/collections/{row['collection']}/points"
            self.gateway.backend.request("PUT", path+"?wait=true", json={"points": [{"id": row["id"], "vector": vector, "payload": p}]})
            check = self.gateway.backend.request("POST", path, json={"ids": [row["id"]], "with_payload": True})
            if len(check) != 1 or check[0].get("payload", {}).get("content_hash") != p["content_hash"]:
                raise ValueError("projection readback mismatch")
            repaired += 1
        return {"repaired": repaired, "limit": limit, "after": rows[-1]["id"] if rows else after}


_runtime = None
_lock = threading.Lock()


def runtime_memory():
    global _runtime
    if os.getenv("NIBLIT_MEMORY_LAB_ENABLED", "0") != "1":
        return None
    with _lock:
        if _runtime is None:
            from .context import runtime_gateway
            _runtime = MemoryRuntime(runtime_gateway(), scope={
                "namespace": os.getenv("NIBLIT_MEMORY_LAB_NAMESPACE", "desktop"),
                "principal": os.getenv("NIBLIT_MEMORY_LAB_PRINCIPAL", "desktop_operator")})
            _runtime.start()
        return _runtime


def queue_core_fact(key, value, tags=None):
    """Best effort mirror; original KnowledgeDB remains intact if queue fails."""
    try:
        runtime = runtime_memory()
        if runtime:
            runtime.enqueue_fact({"key": key, "value": value, "tags": tags or []})
    except Exception:
        import logging
        logging.getLogger(__name__).warning("memory projection enqueue failed; original fact retained")
