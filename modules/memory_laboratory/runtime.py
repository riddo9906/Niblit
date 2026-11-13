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
        self.phase_status = {}
        self.last_cycle = None
        self._last_sync = 0
        self._start_lock = threading.Lock()
        self.projection_totals = {'completed':0,'failed':0,'chunks':0,'unique_chunks':0,'adapter_calls':0,'cache_hits':0,'prefetch_generated':0,'stages':{}}
        with gateway.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS ingestion_outbox(
                  id TEXT PRIMARY KEY, source TEXT NOT NULL, body TEXT NOT NULL,
                  state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                  next_attempt REAL NOT NULL DEFAULT 0, error TEXT, updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS outbox_ready ON ingestion_outbox(state,next_attempt);
                CREATE INDEX IF NOT EXISTS outbox_source_state ON ingestion_outbox(source,state);
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
            if head is not None and head["id"] == key:
                current = db.execute("SELECT state FROM ingestion_outbox WHERE id=?", (key,)).fetchone()
                if current and current["state"] in ("pending", "processing", "complete"):
                    # An unchanged snapshot must not rescan/rewrite the outbox.
                    # Permissions were checked above; retry/lease state is retained.
                    return key
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
        """Serial, durable groups of <=4 small events; large sources stay alone.

        Claim/ack commits are shared, but each source keeps its original UUIDs,
        permission checks, verified projection and300s lease. No parallel worker.
        """
        completed=failed=chunks=unique_chunks=calls=cache_hits=prefetch_generated=0
        timings={};remaining=max(1,min(limit,32))
        def record(profile):
            nonlocal chunks,unique_chunks,calls,cache_hits
            chunks+=profile.get('chunks',0);unique_chunks+=profile.get('unique_chunks',0)
            calls+=profile.get('adapter_calls',0);cache_hits+=profile.get('cache_hits',0)
            for key,value in profile.items():
                if isinstance(value,(int,float)) and key not in ('chunks','unique_chunks','adapter_calls','batch_size','cache_hits','small_events'):
                    timings[key]=timings.get(key,0)+value
        while remaining and not self.stop_event.is_set():
            claimed=[];mark=time.perf_counter()
            with self.gateway.db() as db:
                db.execute('BEGIN IMMEDIATE')
                for _ in range(min(4,remaining)):
                    row=db.execute("""SELECT * FROM ingestion_outbox AS job WHERE (state='pending' OR state='processing') AND next_attempt<=?
                        AND json_extract(body,'$.namespace')=? AND json_extract(body,'$.principal')=?
                        AND NOT EXISTS(SELECT 1 FROM ingestion_outbox AS busy WHERE busy.source=job.source AND busy.state='processing' AND busy.next_attempt>? AND busy.id<>job.id)
                        ORDER BY rowid LIMIT 1""",(time.time(),self.scope['namespace'],self.scope['principal'],time.time())).fetchone()
                    if row is None:break
                    parsed_at=time.perf_counter();body=json.loads(row['body'])
                    timings['content_retrieval']=timings.get('content_retrieval',0)+time.perf_counter()-parsed_at
                    small=isinstance(body.get('content'),str) and len(body['content'])<=1000
                    if claimed and not small:break
                    lease=time.time()+300
                    db.execute("UPDATE ingestion_outbox SET state='processing',next_attempt=?,attempts=attempts+1 WHERE id=?",(lease,row['id']))
                    claimed.append((row,body,lease))
                    if not small:break
            timings['outbox_acquire']=timings.get('outbox_acquire',0)+time.perf_counter()-mark
            if not claimed:break
            successes=[];failures=[];unattempted=[]
            try:
                if len(claimed)>1:
                    pre=self.gateway.prime_small_events([b for _,b,_ in claimed],cancelled=self.stop_event.is_set)
                    calls+=pre['adapter_calls'];prefetch_generated+=pre['generated']
                    timings['embedding_prefetch']=timings.get('embedding_prefetch',0)+pre['seconds']
                    result=self.gateway.ingest_small_events([b for _,b,_ in claimed],cancelled=self.stop_event.is_set)
                    record(result['profile']);successes.extend(claimed)
                for index,(row,original,lease) in enumerate([] if len(claimed)>1 else claimed):
                    if self.stop_event.is_set():
                        unattempted.extend(claimed[index:]);break
                    body=dict(original);text=body.pop('content');source=body['source'];mark=time.perf_counter()
                    segments=[(text[i:i+1000],source+f'#offset={i}') for i in range(0,len(text),1000)]
                    timings['chunk_construction']=timings.get('chunk_construction',0)+time.perf_counter()-mark
                    try:
                        profile={}
                        self.gateway.ingest(segments,**body,cancelled=self.stop_event.is_set,profile_sink=profile.update)
                        record(profile);successes.append((row,original,lease))
                    except Exception as exc:
                        record(getattr(exc,'ingestion_profile',{}));failures.append((row,original,lease,type(exc).__name__))
                        unattempted.extend(claimed[index+1:]);break
            except Exception as exc:
                record(getattr(exc,'ingestion_profile',{}))
                pre=getattr(self.gateway,'last_prefetch_profile',{})
                if not pre.get('generated'):
                    calls+=pre.get('adapter_calls',0)
                    timings['embedding_prefetch']=timings.get('embedding_prefetch',0)+pre.get('seconds',0)
                failures=[(row,body,lease,type(exc).__name__) for row,body,lease in claimed]
            mark=time.perf_counter()
            with self.gateway.db() as db:
                db.execute('BEGIN IMMEDIATE')
                for row,body,lease in successes:
                    changed=db.execute("UPDATE ingestion_outbox SET state='complete',error=NULL,updated_at=? WHERE id=? AND state='processing' AND next_attempt=?",(now(),row['id'],lease)).rowcount
                    completed+=changed
                for row,body,lease,error in failures:
                    head=db.execute('SELECT id FROM source_heads WHERE namespace=? AND principal=? AND source=?',(self.scope['namespace'],self.scope['principal'],row['source'])).fetchone()
                    state='superseded' if head and head['id']!=row['id'] else 'pending'
                    changed=db.execute("UPDATE ingestion_outbox SET state=?,next_attempt=?,error=?,updated_at=? WHERE id=? AND state='processing' AND next_attempt=?",(state,time.time()+min(300,2**min(row['attempts']+1,8)),error,now(),row['id'],lease)).rowcount
                    failed+=changed
                for row,body,lease in unattempted:
                    # Restore only our unsubmitted claims, never someone else's lease.
                    db.execute("UPDATE ingestion_outbox SET state='pending',next_attempt=? WHERE id=? AND state='processing' AND next_attempt=?",(row['next_attempt'],row['id'],lease))
            timings['sqlite_ack']=timings.get('sqlite_ack',0)+time.perf_counter()-mark
            remaining-=len(successes)+len(failures)
            if failures or unattempted:break
        metrics={'chunks':chunks,'unique_chunks':unique_chunks,'adapter_calls':calls,'cache_hits':cache_hits,
                 'prefetch_generated':prefetch_generated,'stages':timings}
        self._add_projection_metrics(completed,failed,metrics)
        return {'completed':completed,'failed':failed,'metrics':metrics}

    def _add_projection_metrics(self, completed, failed, metrics):
        old = self.projection_totals
        stages = dict(old['stages'])
        for key,value in metrics.get('stages',{}).items():
            stages[key] = stages.get(key,0)+value
        self.projection_totals = {**old,'completed':old['completed']+completed,'failed':old['failed']+failed,
            'chunks':old['chunks']+metrics.get('chunks',0),'unique_chunks':old['unique_chunks']+metrics.get('unique_chunks',0),
            'adapter_calls':old['adapter_calls']+metrics.get('adapter_calls',0),
            'cache_hits':old['cache_hits']+metrics.get('cache_hits',0),
            'prefetch_generated':old['prefetch_generated']+metrics.get('prefetch_generated',0),'stages':stages}

    def tick_market_partitions(self, limit=8):
        """Oldest-ready scoped feedback with a64-chunk fairness allowance.

        Up to8 scopes remain eligible; a large document is always processed whole.
        No source is discarded or adopted into another scope. General cognition
        gets its turn before another expensive market-history document.
        """
        completed=failed=estimated_chunks=0
        with self.gateway.db() as db:
            scopes=db.execute("""SELECT json_extract(job.body,'$.namespace') AS namespace,MIN(job.rowid) oldest
                FROM ingestion_outbox AS job
                WHERE state IN ('pending','processing') AND next_attempt<=?
                  AND json_extract(job.body,'$.principal')=?
                  AND json_extract(job.body,'$.metadata.source_type') IN ('market_analysis','chart_annotation_delta')
                  AND json_extract(job.body,'$.metadata.parent_namespace')=?
                  AND json_extract(job.body,'$.namespace') LIKE 'market.%'
                  AND NOT EXISTS(SELECT 1 FROM ingestion_outbox AS busy WHERE busy.source=job.source
                      AND busy.state='processing' AND busy.next_attempt>? AND busy.id<>job.id)
                GROUP BY json_extract(job.body,'$.namespace') ORDER BY oldest LIMIT ?""",
                (time.time(),self.scope['principal'],self.scope['namespace'],time.time(),max(1,min(limit,8)))).fetchall()
        for row in scopes:
            if self.stop_event.is_set():break
            with self.gateway.db() as db:
                size=db.execute("SELECT length(json_extract(body,'$.content')) FROM ingestion_outbox WHERE rowid=?",(row['oldest'],)).fetchone()[0]
            cost=max(1,(size+999)//1000)
            if estimated_chunks and estimated_chunks+cost>64:break
            scoped=MemoryRuntime(self.gateway,scope={'namespace':row['namespace'],'principal':self.scope['principal']})
            result=scoped.tick(1);completed+=result['completed'];failed+=result['failed']
            if result['completed'] or result['failed']:estimated_chunks+=cost
            self._add_projection_metrics(result['completed'],result['failed'],result.get('metrics',{}))
        return {'completed':completed,'failed':failed,'estimated_chunks_serviced':estimated_chunks}

    def status(self):
        with self.gateway.db() as db:
            sqlite_settings = {'journal_mode':db.execute('PRAGMA journal_mode').fetchone()[0],
                               'synchronous':db.execute('PRAGMA synchronous').fetchone()[0]}
            counts = db.execute("SELECT state,count(*) AS count FROM ingestion_outbox GROUP BY state").fetchall()
            errors = db.execute("SELECT error,count(*) AS count FROM ingestion_outbox WHERE error IS NOT NULL GROUP BY error").fetchall()
        return {**self.gateway.status(**self.scope), "queue": [dict(r) for r in counts],
                "errors": [dict(r) for r in errors], "worker_running": bool(self.thread and self.thread.is_alive()),
                "legacy_source_error": self.source_error,
                "worker_phases": {k:dict(v) for k,v in self.phase_status.copy().items()},
                "last_cycle": self.last_cycle,
                "projection_totals":self.projection_totals,
                "sqlite_settings":sqlite_settings,
                "last_ingestion_profile":getattr(self.gateway,'last_ingestion_profile',{}),
                "last_prefetch_profile":getattr(self.gateway,'last_prefetch_profile',{})}

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

    @staticmethod
    def _safe_error(exc):
        # Never expose exception messages, URLs, source text or credentials.
        import sqlite3
        error = {"error_type": type(exc).__name__}
        if isinstance(exc, sqlite3.Error):
            code = getattr(exc, "sqlite_errorcode", None)
            if isinstance(code, int):
                error["sqlite_errorcode"] = code
                error["sqlite_errorname"] = {
                    sqlite3.SQLITE_BUSY:"SQLITE_BUSY", sqlite3.SQLITE_LOCKED:"SQLITE_LOCKED",
                    sqlite3.SQLITE_FULL:"SQLITE_FULL", sqlite3.SQLITE_READONLY:"SQLITE_READONLY",
                    sqlite3.SQLITE_IOERR:"SQLITE_IOERR", sqlite3.SQLITE_CORRUPT:"SQLITE_CORRUPT",
                    sqlite3.SQLITE_ERROR:"SQLITE_ERROR"}.get(code & 255,"SQLITE_OTHER")
        return error

    def _phase(self, name, fn):
        previous = self.phase_status.get(name, {})
        start = time.monotonic()
        try:
            result = fn()
            failed = isinstance(result, dict) and bool(result.get("failed"))
            state = {"state":"retry_pending" if failed else "ok", "checked_at":time.time(),
                     "elapsed_seconds":time.monotonic()-start, "result":result,
                     "last_error":previous.get("last_error")}
            if previous.get("error") and not failed:
                state["recovered_at"] = time.time()
            self.phase_status[name] = state
            if name == "knowledge_sync":
                self.source_error = None
            return result
        except Exception as exc:
            error = self._safe_error(exc)
            self.phase_status[name] = {"state":"error", "checked_at":time.time(),
                "elapsed_seconds":time.monotonic()-start, "error":error,
                "last_error":{**error,"at":time.time()}}
            if name == "knowledge_sync":
                self.source_error = error["error_type"]
            return {"failed":1,"error":error}


    def tick_remote(self, limit=2):
        # Delivery state extends the ORIGINAL outbox; one existing worker only.
        if not os.getenv('NIBLIT_QDRANT_REMOTE_SCOPES'):return {'state':'not_configured','verified':0}
        from modules.hybrid_qdrant_manager import get_hybrid_manager
        manager=get_hybrid_manager();target=digest(manager._url)
        with self.gateway.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS remote_projection_outbox(target TEXT,id TEXT,state TEXT,attempts INTEGER,next_attempt REAL,error TEXT,PRIMARY KEY(target,id))")
            rows=db.execute("""SELECT job.id,job.body FROM ingestion_outbox AS job
                LEFT JOIN remote_projection_outbox AS remote ON remote.id=job.id AND remote.target=?
                WHERE job.state='complete' AND json_extract(job.body,'$.metadata.remote_projection')=1
                  AND json_extract(job.body,'$.metadata.source_type')='synthetic_acceptance'
                  AND coalesce(remote.state,'pending')<>'complete' AND coalesce(remote.next_attempt,0)<=?
                ORDER BY job.rowid LIMIT ?""",(target,time.time(),max(1,min(limit,2)))).fetchall()
        done=failed=0
        for row in rows:
            if self.stop_event.is_set():break
            body=json.loads(row['body']);error=None
            try:
                result=self.gateway.project_remote(source=body['source'],namespace=body['namespace'],principal=body['principal'],manager=manager)
                done+=result['verified'];state='complete';delay=0
            except Exception as exc:
                error=type(exc).__name__;failed+=1;state='pending';delay=time.time()+60
            with self.gateway.db() as db:
                db.execute("INSERT INTO remote_projection_outbox VALUES(?,?,?,1,?,?) ON CONFLICT(target,id) DO UPDATE SET state=excluded.state,attempts=attempts+1,next_attempt=excluded.next_attempt,error=excluded.error",(target,row['id'],state,delay,error))
        return {'verified':done,'failed':failed,'synthetic_only':True}

    def run_once(self):
        """One fair pass of the existing worker; never another worker/authority.

        Preserve32 general jobs/8 market partitions, but service market feedback
        after4 general jobs. Faults in one phase cannot skip unrelated phases.
        Existing outbox retries and ownership leases remain unchanged.
        """
        source = os.getenv("NIBLIT_MEMORY_SYNC_SOURCE", "")
        if source and time.monotonic()-self._last_sync > 15:
            self._phase("knowledge_sync", lambda:self.sync_knowledge_file(source))
            self._last_sync = time.monotonic()
        if self.stop_event.is_set():
            return
        head = self._phase("general_projection", lambda:self.tick(4))
        if self.stop_event.is_set():
            return
        self._phase("market_partitions", lambda:self.tick_market_partitions(8))
        if self.stop_event.is_set():
            return
        # A failed general backend pass already has a durable retry/backoff.
        if not (isinstance(head,dict) and head.get("failed")):
            self._phase("general_projection_tail", lambda:self.tick(28))
        if self.stop_event.is_set():
            return
        from .market import MarketJournal
        self._phase("market_journal", lambda:MarketJournal(self.gateway).repair_pending())
        if not self.stop_event.is_set():self._phase('remote_projection',lambda:self.tick_remote(2))
        self.last_cycle = time.time()

    def start(self):
        with self._start_lock:
            if self.thread and self.thread.is_alive():
                return
            self.stop_event.clear()
            def work():
                while not self.stop_event.wait(2):
                    try:
                        self.run_once()
                    except Exception as exc:
                        # Retain a sanitized unexpected-loop fault separately.
                        self.phase_status["worker"] = {"state":"error", "checked_at":time.time(),
                                                       "error":self._safe_error(exc)}
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


def stop_runtime_memory():
    """Stop only the projection worker already owned by this process."""
    with _lock:
        runtime = _runtime
    if runtime is not None:
        runtime.stop()
        return not (runtime.thread and runtime.thread.is_alive())
    return True


def queue_core_fact(key, value, tags=None):
    """Best effort mirror; original KnowledgeDB remains intact if queue fails."""
    try:
        runtime = runtime_memory()
        if runtime:
            runtime.enqueue_fact({"key": key, "value": value, "tags": tags or []})
    except Exception:
        import logging
        logging.getLogger(__name__).warning("memory projection enqueue failed; original fact retained")
