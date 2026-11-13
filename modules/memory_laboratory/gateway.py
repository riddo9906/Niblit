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
import time
from collections import OrderedDict
import os
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


def market_namespace(parent, identity, strategy_scope):
    return "market." + digest(json.dumps([parent, identity, strategy_scope], sort_keys=True))[:40]


class MemoryGateway:
    def __init__(self, config, ledger, *, authorize=permission, setup=None, event_bus=None):
        self.config = config
        self.path = Path(ledger)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.authorize = authorize
        self.backend = setup or QdrantSetup(config)
        self.event_bus = event_bus
        self._wal_anchor = None
        self._wal_anchor_lock = threading.Lock()
        self.lock = threading.RLock()
        self._embedding_cache = OrderedDict()
        self._embedding_cache_lock = threading.RLock()
        self._cache_adapter = self.backend.embedder
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS records(
                  id TEXT PRIMARY KEY, namespace TEXT NOT NULL, principal TEXT NOT NULL,
                  source TEXT NOT NULL, payload TEXT NOT NULL, projection TEXT NOT NULL,
                  collection TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS source_scope ON records(namespace,principal,source);
                CREATE VIRTUAL TABLE IF NOT EXISTS lexical USING fts5(id UNINDEXED,content);
                CREATE TABLE IF NOT EXISTS market_partitions(
                  namespace TEXT PRIMARY KEY, parent TEXT NOT NULL,
                  principal TEXT NOT NULL, binding TEXT NOT NULL);
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
                self._keep_wal_open(db)
                with db:
                    yield db
            finally:
                db.close()
        return connection()

    def _keep_wal_open(self, db):
        # Short-lived operation connections otherwise checkpoint/delete WAL on
        # every last close. This idle read-only handle starts no transaction,
        # performs no projection, and never blocks normal checkpoints.
        if self._wal_anchor is not None or db.execute('PRAGMA journal_mode').fetchone()[0] != 'wal':
            return
        with self._wal_anchor_lock:
            if self._wal_anchor is None:
                anchor=sqlite3.connect(self.path.resolve().as_uri()+'?mode=ro',uri=True,
                    timeout=15,isolation_level=None,check_same_thread=False)
                try:
                    anchor.execute('PRAGMA schema_version').fetchone()
                except Exception:
                    anchor.close();raise
                self._wal_anchor=anchor

    def close(self):
        try:
            self.backend.close()
        finally:
            with self._wal_anchor_lock:
                if self._wal_anchor is not None:
                    self._wal_anchor.close();self._wal_anchor=None

    def require(self, action, namespace, principal):
        if not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", namespace) or not principal.strip():
            raise ValueError("invalid caller scope")
        if self.authorize(action, namespace, principal):
            return
        # Only the existing file-backed operator authority supports inherited
        # partitions. Opaque/custom authorizers never gain implicit permission.
        if self.authorize is permission:
            from modules.core_tool_runtime import _permission_manager
            manager = _permission_manager()
            child_key = f"memory.{action}.{namespace}"
            # An explicit child denial is absolute, even if the parent allows.
            if child_key not in manager.perms:
                with self.db() as db:
                    row = db.execute(
                        "SELECT * FROM market_partitions WHERE namespace=? AND principal=?",
                        (namespace, principal)).fetchone()
                if row:
                    binding = json.loads(row["binding"])
                    if (not row["parent"].startswith("market.") and
                            namespace == market_namespace(row["parent"], binding["identity"], binding["strategy_scope"])
                            and manager.check(f"memory.{action}.{row['parent']}")):
                        return
        raise PermissionError(f"memory.{action}.{namespace}")

    def register_market_partition(self, parent, identity, strategy_scope, principal):
        """Bind an isolated view of already authorized parent memory.

        This changes no permission file and creates no grant. Every operation
        rechecks current parent/child operator permissions, including revocation.
        """
        if not isinstance(parent,str) or parent.startswith("market."):
            raise ValueError("invalid parent scope")
        self.require("ingest", parent, principal)
        if not isinstance(identity,list) or len(identity)!=5 or not all(
                isinstance(value,str) and value.strip() for value in identity):
            raise ValueError("invalid market partition identity")
        namespace = market_namespace(parent, identity, strategy_scope)
        binding = json.dumps({"identity":identity,"strategy_scope":strategy_scope},sort_keys=True,allow_nan=False)
        with self.db() as db:
            previous = db.execute("SELECT * FROM market_partitions WHERE namespace=?",(namespace,)).fetchone()
            if previous and (previous["parent"]!=parent or previous["principal"]!=principal or previous["binding"]!=binding):
                raise ValueError("immutable partition conflict")
            db.execute("INSERT OR IGNORE INTO market_partitions VALUES(?,?,?,?)",
                       (namespace,parent,principal,binding))
        return namespace

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

    def prime_small_events(self, bodies, *, cancelled=None):
        """Warm bounded vectors for <=4 same-scope events; publish nothing.

        This is the existing pure embedding cache, not another source authority.
        Every event is still individually authorized/projected by ingest().
        """
        started = time.perf_counter()
        profile = {'generated':0,'adapter_calls':0,'seconds':0.0}
        try:
            if not 1 < len(bodies) <= 4:
                return profile
            scope = (bodies[0]['namespace'],bodies[0]['principal'])
            texts = []
            for body in bodies:
                if (body['namespace'],body['principal']) != scope:
                    raise ValueError('incompatible prefetch scope')
                self.require('ingest',*scope)
                text = body['content']
                if (body.get('category','semantic') not in CATEGORIES or not body['source'].strip()
                        or not isinstance(text,str) or not text.strip() or len(text)>1000):
                    raise ValueError('invalid small event')
                if re.search(r'(?:gh[pousr]_|hf_|sk-(?:proj-|ant-)?)[A-Za-z0-9_-]{20,}|-----BEGIN .*PRIVATE KEY-----',text):
                    raise PermissionError('credential-like source content')
                texts.append(text)
            try:limit=max(0,min(int(os.getenv('NIBLIT_MEMORY_EMBEDDING_CACHE_SIZE','256')),256))
            except ValueError:limit=256
            if limit<len(bodies):return profile
            unique=list(dict.fromkeys(texts))
            keys=[(*scope,self.config.model,self.config.revision,id(self.backend.embedder),digest(t)) for t in unique]
            with self._embedding_cache_lock:
                if self._cache_adapter is not self.backend.embedder:
                    self._embedding_cache.clear();self._cache_adapter=self.backend.embedder
                missing=[i for i,key in enumerate(keys) if key not in self._embedding_cache]
            if not missing:return profile
            if cancelled and cancelled():raise RuntimeError('Projection cancelled')
            inputs=[unique[i] for i in missing]
            batch_api=getattr(self.backend.embedder,'embed_many',None)
            if callable(batch_api):
                try:encoded=batch_api(inputs);profile['adapter_calls']=1
                except NotImplementedError:batch_api=None
            if not callable(batch_api):
                encoded=[self.backend.embedder.embed(t) for t in inputs];profile['adapter_calls']=len(inputs)
            if len(encoded)!=len(inputs):raise ValueError('incomplete embedding batch')
            vectors=[validate_vector(v) for v in encoded]
            with self._embedding_cache_lock:
                existing=[self._embedding_cache[key] for key in keys if key in self._embedding_cache]
                if any(len(v)!=len(vectors[0]) for v in vectors+existing):
                    raise ValueError('embedding dimensions changed within group')
                if cancelled and cancelled():raise RuntimeError('Projection cancelled')
                for i,vector in zip(missing,vectors):
                    self._embedding_cache[keys[i]]=list(vector);self._embedding_cache.move_to_end(keys[i])
                while len(self._embedding_cache)>limit:self._embedding_cache.popitem(last=False)
            profile['generated']=len(vectors)
            return profile
        finally:
            profile['seconds']=time.perf_counter()-started
            self.last_prefetch_profile=dict(profile)


    def project_remote(self, *, source, namespace, principal, manager=None):
        """Mirror approved synthetic records only; SQLite/local stay authoritative."""
        self.require('read',namespace,principal);self.require('ingest',namespace,principal)
        allowed=set(os.getenv('NIBLIT_QDRANT_REMOTE_SCOPES','').split(','))
        if namespace not in allowed:raise PermissionError('Remote namespace not approved')
        if manager is None:
            from modules.hybrid_qdrant_manager import get_hybrid_manager
            manager=get_hybrid_manager()
        target=digest(manager._url)
        with self.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS remote_projection_receipts(target TEXT,id TEXT,payload_hash TEXT,state TEXT,PRIMARY KEY(target,id))')
            rows=db.execute("SELECT * FROM records WHERE source=? AND namespace=? AND principal=? AND active=1 AND projection='verified' ORDER BY id LIMIT 9",(source,namespace,principal)).fetchall()
        if not rows or len(rows)>8:raise ValueError('Local canonical projection missing or exceeds remote bound')
        total=0
        for row in rows:
            p=json.loads(row['payload'])
            if p['source_type']!='synthetic_acceptance' or p['sensitivity']!='public' or p['provenance'].get('remote_sync')!='synthetic_approved':raise PermissionError('Historical/private memory not approved')
            payload_hash=digest(json.dumps(p,sort_keys=True))
            with self.db() as db:
                receipt=db.execute('SELECT payload_hash,state FROM remote_projection_receipts WHERE target=? AND id=?',(target,row['id'])).fetchone()
            if receipt and tuple(receipt)==(payload_hash,'verified'):total+=1;continue
            local=self.backend.request('POST','/collections/'+row['collection']+'/points',json={'ids':[row['id']],'with_payload':True,'with_vector':True})
            if len(local)!=1 or local[0]['payload']!=p:raise ValueError('Local projection mismatch; remote not sent')
            vector=local[0].get('vector')
            from .setup import validate_vector
            validate_vector(vector) # validate without changing the original local vector
            vector=[float(x) for x in vector]
            manager.canonical_project(row['collection'],[{'id':row['id'],'payload':p,'vector':vector}],dimension=len(vector),distance=self.config.distance,prefix=self.config.prefix)
            with self.db() as db:db.execute('INSERT INTO remote_projection_receipts VALUES(?,?,?,?) ON CONFLICT(target,id) DO UPDATE SET payload_hash=excluded.payload_hash,state=excluded.state',(target,row['id'],payload_hash,'verified'))
            total+=1
        return {'verified':total,'canonical':'sqlite','local_replaced':False}

    def read_remote(self, ids, *, namespace, principal, manager=None):
        self.require('read',namespace,principal)
        if not 1<=len(ids)<=8 or len(set(ids))!=len(ids):raise ValueError('Bounded original IDs required')
        if namespace not in set(os.getenv('NIBLIT_QDRANT_REMOTE_SCOPES','').split(',')):raise PermissionError('Remote namespace not approved')
        if manager is None:
            from modules.hybrid_qdrant_manager import get_hybrid_manager
            manager=get_hybrid_manager()
        result=[]
        for ident in ids:
            with self.db() as db:row=db.execute("SELECT * FROM records WHERE id=? AND namespace=? AND principal=? AND active=1 AND projection='verified'",(ident,namespace,principal)).fetchone()
            if not row:continue
            p=json.loads(row['payload'])
            if p['source_type']!='synthetic_acceptance' or p['sensitivity']!='public' or p['provenance'].get('remote_sync')!='synthetic_approved':continue
            points=manager.canonical_request('POST',row['collection'],suffix='/points',body={'ids':[ident],'with_payload':True}) or []
            for point in points:
                if str(point['id'])==ident and point.get('payload')==p and principal in p['access_principals']:result.append(point)
        return {'results':result,'authority':'canonical_sqlite_scope'}

    def ingest(self, segments, *, source, namespace, principal, category="semantic", metadata=None, cancelled=None, profile_sink=None, _prepare_sink=None):
        started = mark = time.perf_counter()
        profile = {}
        try:
            self.require("ingest", namespace, principal)
            metadata = metadata or {}
            if category not in CATEGORIES or not source.strip() or not 0 < len(segments) <= 200:
                raise ValueError("invalid bounded ingestion")
            for text, location in segments:
                if not text.strip() or len(text) > 1000 or not location:
                    raise ValueError("invalid source chunk")
                if re.search(r'(?:gh[pousr]_|hf_|sk-(?:proj-|ant-)?)[A-Za-z0-9_-]{20,}|-----BEGIN .*PRIVATE KEY-----', text):
                    raise PermissionError("credential-like source content")
            profile['permission_validation'] = time.perf_counter()-mark
            mark = time.perf_counter()
            unique = list(dict.fromkeys(text for text,_ in segments))
            positions = {text:i for i,text in enumerate(unique)}
            profile.update(chunks=len(segments), unique_chunks=len(unique))
            profile['hash_dedup'] = time.perf_counter()-mark
            mark = time.perf_counter()
            from .setup import embedding_batch_size
            size = embedding_batch_size()
            profile.update(batch_size=size, adapter_calls=0, cache_hits=0, embedding_mode="cache")
            try:
                cache_size = max(0,min(int(os.getenv('NIBLIT_MEMORY_EMBEDDING_CACHE_SIZE','256')),256))
            except ValueError:
                cache_size = 256
            cache_keys = [(namespace,principal,self.config.model,self.config.revision,
                           id(self.backend.embedder),digest(text)) for text in unique]
            vectors_unique = [None]*len(unique)
            missing = []
            with self._embedding_cache_lock:
                if self._cache_adapter is not self.backend.embedder:
                    self._embedding_cache.clear()
                    self._cache_adapter = self.backend.embedder
                while len(self._embedding_cache)>cache_size:
                    self._embedding_cache.popitem(last=False)
                for index,key in enumerate(cache_keys):
                    if cache_size and key in self._embedding_cache:
                        vectors_unique[index] = list(self._embedding_cache[key])
                        self._embedding_cache.move_to_end(key)
                        profile['cache_hits'] += 1
                    else:
                        missing.append(index)
            batch_api = getattr(self.backend.embedder, 'embed_many', None)
            def check():
                if cancelled and cancelled():
                    raise RuntimeError('Projection cancelled; original outbox remains authoritative')
            check()
            for start in range(0,len(missing),size):
                check()
                indexes = missing[start:start+size]
                batch = [unique[index] for index in indexes]
                if callable(batch_api):
                    try:
                        encoded = batch_api(batch)
                        profile['adapter_calls'] += 1
                        profile['embedding_mode'] = 'batch'
                    except NotImplementedError:
                        batch_api = None
                if not callable(batch_api):
                    encoded = [self.backend.embedder.embed(text) for text in batch]
                    profile['adapter_calls'] += len(batch)
                    profile['embedding_mode'] = 'scalar_fallback'
                if len(encoded) != len(batch):
                    raise ValueError('incomplete embedding batch')
                normalized = [validate_vector(v) for v in encoded]
                for index,vector in zip(indexes,normalized):
                    vectors_unique[index] = vector
                check()
            vectors = [vectors_unique[positions[text]] for text,_ in segments]
            profile['embedding'] = time.perf_counter()-mark
            mark = time.perf_counter()
            dimension = len(vectors[0])
            if any(len(vector) != dimension for vector in vectors):
                raise ValueError("embedding dimensions changed within document")
            # Do not retain any new vectors from an incomplete/invalid batch.
            if cache_size:
                with self._embedding_cache_lock:
                    for index in missing:
                        self._embedding_cache[cache_keys[index]] = list(vectors_unique[index])
                        self._embedding_cache.move_to_end(cache_keys[index])
                        while len(self._embedding_cache)>cache_size:
                            self._embedding_cache.popitem(last=False)
            collection = self.config.collection(category, dimension)
            stamp = now()
            version = digest(json.dumps([segments, metadata], ensure_ascii=False, sort_keys=True))
            records = []
            for index, ((text, location), vector) in enumerate(zip(segments, vectors)):
                key = json.dumps([namespace, principal, source, version, index, collection])
                record = MemoryRecord(
                    memory_id=uuid5(NAMESPACE_URL, key), category=category, namespace=namespace,
                    content=text, source_id=digest(source), source_location=location,
                    sensitivity=metadata.get("sensitivity", "private"), source_type=metadata.get("source_type", "document"), provenance={"source": source, "version": version, "actor": principal, **metadata.get("provenance", {})},
                    created_at=stamp, observed_at=metadata.get("observed_at", stamp), updated_at=stamp,
                    confidence=metadata.get("confidence", 0.5), structured=metadata.get("structured"),
                    access_principals=[principal], embedding_model=self.config.model,
                    embedding_version=self.config.revision, content_hash=digest(text), idempotency_key=digest(key))
                records.append((record, vector))
            profile['record_identity'] = time.perf_counter()-mark
            if _prepare_sink is not None:
                _prepare_sink({'source':source,'namespace':namespace,'principal':principal,
                               'collection':collection,'version':version,'records':records})
                return {'verified':False,'prepared_only':True}
            mark = time.perf_counter()
            with self.lock:
                profile['gateway_lock_wait'] = time.perf_counter()-mark
                check()
                mark = time.perf_counter()
                with self.db() as db:
                    for record, _ in records:
                        db.execute("INSERT OR IGNORE INTO records VALUES(?,?,?,?,?,?,?,0)",
                            (str(record.memory_id), namespace, principal, source,
                             record.model_dump_json(), "pending", collection))
                        self.audit(db, "ingestion.prepared", str(record.memory_id), source_hash=digest(source))
                profile['sqlite_prepare'] = time.perf_counter()-mark
                path = f"/collections/{collection}/points"
                points = [{"id": str(r.memory_id), "vector": v,
                           "payload": r.model_dump(mode="json")} for r, v in records]
                check()
                mark = time.perf_counter()
                self.backend.request("PUT", path + "?wait=true", json={"points": points})
                profile['qdrant_write'] = time.perf_counter()-mark
                mark = time.perf_counter()
                retrieved = self.backend.request("POST", path, json={
                    "ids": [str(r.memory_id) for r, _ in records], "with_payload": True})
                expected = {str(r.memory_id): r.content_hash for r, _ in records}
                if {str(p["id"]): p.get("payload", {}).get("content_hash") for p in retrieved} != expected:
                    raise ValueError("Qdrant projection verification failed")
                profile['qdrant_verify'] = time.perf_counter()-mark
                check()
                mark = time.perf_counter()
                # Commit the new visible source version only after every point verifies.
                with self.db() as db:
                    superseded = db.execute(
                        "SELECT * FROM records WHERE namespace=? AND principal=? AND source=? AND active=1",
                        (namespace, principal, source)).fetchall()
                    db.execute("UPDATE records SET active=0 WHERE namespace=? AND principal=? AND source=?",
                               (namespace, principal, source))
                    if len(records)>1:self._prepare_lexical_rowids(db)
                    for record, _ in records:
                        key = str(record.memory_id)
                        existing = db.execute("SELECT payload FROM records WHERE id=?", (key,)).fetchone()
                        canonical = json.loads(existing["payload"])
                        canonical.update(lifecycle="active", superseded_by=None)
                        db.execute("UPDATE records SET active=?, projection='verified',payload=? WHERE id=?",
                                   (int(canonical["verification"] != "rejected"), json.dumps(canonical), key))
                        self._delete_lexical(db, key)
                        self._insert_lexical(db,key,record.content)
                        self.audit(db, "ingestion.verified", key)
                    for row in superseded:
                        if row["id"] in expected:
                            continue
                        payload = json.loads(row["payload"])
                        payload.update(lifecycle="superseded", superseded_by=next(iter(expected)), updated_at=now())
                        db.execute("UPDATE records SET payload=?,projection='supersede_pending' WHERE id=?",
                                   (json.dumps(payload), row["id"]))
                        self._delete_lexical(db, row["id"])
                        self.audit(db, "source.superseded", row["id"], replacement=next(iter(expected)))
                profile['sqlite_activate'] = time.perf_counter()-mark
                mark = time.perf_counter()
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
            profile['supersession_projection'] = time.perf_counter()-mark
            return {"verified": True, "ids": list(expected), "collection": collection,
                    "version": version, "warnings": warnings}
        except Exception as exc:
            exc.ingestion_profile = profile
            raise
        finally:
            profile['total'] = time.perf_counter()-started
            self.last_ingestion_profile = dict(profile)
            if profile_sink is not None:
                profile_sink(dict(profile))

    def ingest_small_events(self, bodies, *, cancelled=None):
        """Same record builder, bounded shared I/O; verify all before activation."""
        started=time.perf_counter();profile={'chunks':0,'unique_chunks':0,'adapter_calls':0,'cache_hits':0,'small_events':len(bodies)};plans=[]
        def check():
            if cancelled and cancelled():raise RuntimeError('Projection cancelled')
        def add(part):
            for key,value in part.items():
                if isinstance(value,(int,float)) and key not in ('batch_size','total'):
                    profile[key]=profile.get(key,0)+value
        try:
            if not 1<len(bodies)<=4:raise ValueError('invalid event group size')
            scope=(bodies[0]['namespace'],bodies[0]['principal'])
            if len({b['source'] for b in bodies})!=len(bodies):raise ValueError('duplicate event source')
            for original in bodies:
                if (original['namespace'],original['principal'])!=scope:raise ValueError('incompatible event scope')
                body=dict(original);text=body.pop('content')
                if not isinstance(text,str) or not 0<len(text)<=1000:raise ValueError('invalid small event')
                check()
                self.ingest([(text,body['source']+'#offset=0')],**body,cancelled=cancelled,
                            profile_sink=add,_prepare_sink=plans.append)
            collections={}
            for plan in plans:
                collections.setdefault(plan['collection'],[]).extend(plan['records'])
            mark=time.perf_counter()
            with self.lock:
                profile['gateway_lock_wait']=profile.get('gateway_lock_wait',0)+time.perf_counter()-mark
                check();mark=time.perf_counter()
                with self.db() as db:
                    for plan in plans:
                        for record,_ in plan['records']:
                            db.execute('INSERT OR IGNORE INTO records VALUES(?,?,?,?,?,?,?,0)',
                                (str(record.memory_id),plan['namespace'],plan['principal'],plan['source'],record.model_dump_json(),'pending',plan['collection']))
                            self.audit(db,'ingestion.prepared',str(record.memory_id),source_hash=digest(plan['source']))
                profile['sqlite_prepare']=time.perf_counter()-mark
                for collection,records in collections.items():
                    check();path=f'/collections/{collection}/points';mark=time.perf_counter()
                    points=[{'id':str(rec.memory_id),'vector':v,'payload':rec.model_dump(mode='json')} for rec,v in records]
                    self.backend.request('PUT',path+'?wait=true',json={'points':points})
                    profile['qdrant_write']=profile.get('qdrant_write',0)+time.perf_counter()-mark
                    mark=time.perf_counter()
                    retrieved=self.backend.request('POST',path,json={'ids':[p['id'] for p in points],'with_payload':True})
                    expected={str(rec.memory_id):rec.content_hash for rec,_ in records}
                    if {str(p['id']):p.get('payload',{}).get('content_hash') for p in retrieved}!=expected:
                        raise ValueError('Qdrant projection verification failed')
                    profile['qdrant_verify']=profile.get('qdrant_verify',0)+time.perf_counter()-mark
                check();mark=time.perf_counter();superseded=[]
                with self.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    self._prepare_lexical_rowids(db)
                    for plan in plans:
                        ns,actor,source=plan['namespace'],plan['principal'],plan['source']
                        old=db.execute('SELECT * FROM records WHERE namespace=? AND principal=? AND source=? AND active=1',(ns,actor,source)).fetchall()
                        db.execute('UPDATE records SET active=0 WHERE namespace=? AND principal=? AND source=?',(ns,actor,source))
                        expected={str(rec.memory_id) for rec,_ in plan['records']};replacement=next(iter(expected))
                        for record,_ in plan['records']:
                            key=str(record.memory_id);canonical=json.loads(db.execute('SELECT payload FROM records WHERE id=?',(key,)).fetchone()['payload'])
                            canonical.update(lifecycle='active',superseded_by=None)
                            db.execute("UPDATE records SET active=?,projection='verified',payload=? WHERE id=?",(int(canonical['verification']!='rejected'),json.dumps(canonical),key))
                            self._delete_lexical(db,key);self._insert_lexical(db,key,record.content);self.audit(db,'ingestion.verified',key)
                        for row in old:
                            if row['id'] in expected:continue
                            payload=json.loads(row['payload']);payload.update(lifecycle='superseded',superseded_by=replacement,updated_at=now())
                            db.execute("UPDATE records SET payload=?,projection='supersede_pending' WHERE id=?",(json.dumps(payload),row['id']))
                            self._delete_lexical(db,row['id']);self.audit(db,'source.superseded',row['id'],replacement=replacement)
                            superseded.append((row,replacement))
                profile['sqlite_activate']=time.perf_counter()-mark
                mark=time.perf_counter();projected=[];warnings=[]
                for row,replacement in superseded:
                    try:
                        self.backend.request('POST',f"/collections/{row['collection']}/points/payload?wait=true",json={'points':[row['id']],'payload':{'lifecycle':'superseded','superseded_by':replacement}})
                        projected.append((row['id'],))
                    except Exception:warnings.append('supersession_projection_pending')
                if projected:
                    with self.db() as db:db.executemany("UPDATE records SET projection='superseded' WHERE id=?",projected)
                profile['supersession_projection']=time.perf_counter()-mark
            return {'verified':True,'profile':profile,'results':[{'verified':True,'ids':[str(rec.memory_id) for rec,_ in plan['records']],'collection':plan['collection'],'version':plan['version'],'warnings':warnings} for plan in plans]}
        except Exception as exc:
            exc.ingestion_profile=profile;raise
        finally:
            profile['total']=time.perf_counter()-started;self.last_ingestion_profile=dict(profile)

    @staticmethod
    def _prepare_lexical_rowids(db):
        # Transaction-local lookup for FTS's UNINDEXED id. No schema migration,
        # persistent authority, or cross-transaction cache that can become stale.
        db.execute('CREATE TEMP TABLE lexical_rowids(id TEXT NOT NULL,rid INTEGER PRIMARY KEY)')
        db.execute('INSERT INTO lexical_rowids SELECT id,rowid FROM lexical')
        db.execute('CREATE INDEX temp.lexical_lookup ON lexical_rowids(id)')

    @staticmethod
    def _delete_lexical(db, key):
        if db.execute("SELECT 1 FROM sqlite_temp_master WHERE name='lexical_rowids'").fetchone():
            db.execute('DELETE FROM lexical WHERE rowid IN (SELECT rid FROM lexical_rowids WHERE id=?)',(key,))
            db.execute('DELETE FROM lexical_rowids WHERE id=?',(key,))
        else:
            db.execute('DELETE FROM lexical WHERE id=?',(key,))

    @staticmethod
    def _insert_lexical(db, key, content):
        cursor=db.execute('INSERT INTO lexical(id,content) VALUES(?,?)',(key,content))
        if db.execute("SELECT 1 FROM sqlite_temp_master WHERE name='lexical_rowids'").fetchone():
            db.execute('INSERT INTO lexical_rowids VALUES(?,?)',(key,cursor.lastrowid))

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
                        if p["lifecycle"] == "active" and p["verification"] != "rejected" and (not category or p["category"] == category)
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

    def status(self, *, namespace, principal):
        self.require("read", namespace, principal)
        with self.db() as db:
            counts = db.execute("SELECT projection,active,count(*) AS count FROM records WHERE namespace=? AND principal=? GROUP BY projection,active", (namespace, principal)).fetchall()
            categories = db.execute("SELECT json_extract(payload,'$.category') AS category,count(*) AS count FROM records WHERE namespace=? AND principal=? AND active=1 GROUP BY category", (namespace, principal)).fetchall()
        return {"storage": "sqlite_source_ledger_and_qdrant_projection", "counts": [dict(r) for r in counts],
                "categories": [dict(r) for r in categories], "embedding_model": self.config.model,
                "embedding_revision": self.config.revision, "verification_policy": "imported_claims_are_unverified"}

    def review_record(self, record_id, *, namespace, principal, verification, confidence, evidence):
        """Explicit operator review, never inferred from recurrence or similarity."""
        self.require("verify", namespace, principal)
        import math
        if verification not in {"verified", "rejected"} or not math.isfinite(confidence) or not 0 <= confidence <= 1 or not evidence.strip():
            raise ValueError("review requires verification, bounded confidence and evidence")
        with self.lock, self.db() as db:
            row = db.execute("SELECT * FROM records WHERE id=? AND namespace=? AND principal=? AND active=1", (record_id, namespace, principal)).fetchone()
            if not row:
                raise ValueError("active scoped record not found")
            payload = json.loads(row["payload"])
            payload.update(verification=verification, confidence=confidence, updated_at=now())
            payload["provenance"]["operator_review"] = {"reviewer": principal, "evidence": evidence, "at": now()}
            db.execute("UPDATE records SET payload=?,active=? WHERE id=?", (json.dumps(payload), int(verification != "rejected"), record_id))
            if verification == "rejected":
                self._delete_lexical(db, record_id)
            self.audit(db, "record.reviewed", record_id, verification=verification, reviewer=principal)
        # Local authoritative filters take effect even if projection is offline.
        try:
            self.backend.request("POST", f"/collections/{row['collection']}/points/payload?wait=true", json={"points": [record_id], "payload": payload})
            projected = True
        except Exception:
            projected = False
        return {"reviewed": True, "projection_updated": projected}

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
                self._delete_lexical(db, row["id"])
                self.audit(db, "source.deleted", row["id"])
        for row in rows:
            self.backend.request("POST", f"/collections/{row['collection']}/points/delete?wait=true",
                                 json={"points": [row["id"]]})
            with self.db() as db:
                db.execute("UPDATE records SET projection='deleted' WHERE id=?", (row["id"],))
        return {"deleted": len(rows), "original_evidence_retained": True}
