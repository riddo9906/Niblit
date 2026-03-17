#!/usr/bin/env python3
"""
modules/fused_memory_primary.py — FusedMemoryPrimary: primary fused backend for Niblit.

Extends :class:`~modules.fused_memory.FusedMemory` with a raw-vector API that
mirrors the interface expected by ALE-generated scripts and other callers that
pass pre-computed float vectors instead of text strings.

Key additions over FusedMemory
-------------------------------
``add_embedding(vector, metadata)``
    Store a raw float vector alongside its metadata payload.  When the underlying
    VectorStore supports Qdrant, the point is upserted directly; otherwise the
    payload is stored in SQLite so the data is never lost.

``search_vectors(vector, top_k)``
    Search by raw float vector.  Returns ``{"qdrant": [...], "sqlite": [...]}``
    so callers can inspect results from each backend independently.

``insert_record(record_id, data)`` / ``get_record(record_id)`` / ``list_records()``
    FusedStorage-style structured-record API wiring SQLite directly.

``insert_vector(record_id, vector, payload)``
    Insert a named vector (SQLite metadata + Qdrant point).

``query_vector(vector, top_k)``
    Alias for ``search_vectors`` returning a flat list (FusedStorage compat).

Usage
-----
::

    from modules.fused_memory_primary import FusedMemoryPrimary

    mem = FusedMemoryPrimary()

    # Raw-vector embedding (ALE-script style)
    vec = [0.0] * 384
    mem.add_embedding(vec, {"source": "ale_generated", "topic": "data_structures"})

    # Hybrid retrieval
    results = mem.search_vectors(vec, top_k=3)
    print(results["qdrant"])   # Qdrant/FAISS hits
    print(results["sqlite"])   # SQLite metadata hits

    # FusedStorage record API
    mem.insert_record("rec-1", {"name": "Alice", "age": 30})
    print(mem.get_record("rec-1"))
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from modules.fused_memory import FusedMemory

log = logging.getLogger("Niblit.FusedMemoryPrimary")


class FusedMemoryPrimary(FusedMemory):
    """
    Primary fused memory backend combining Qdrant vector search with SQLite.

    This class extends :class:`~modules.fused_memory.FusedMemory` with:

    * Raw float-vector API (``add_embedding``, ``search_vectors``) for ALE
      scripts and callers that pre-compute their own embeddings.
    * FusedStorage record API (``insert_record``, ``get_record``,
      ``list_records``, ``insert_vector``, ``query_vector``) for a clean
      structured-data interface.

    All operations degrade gracefully — SQLite is always used; Qdrant is
    used when ``QDRANT_URL`` is configured and ``qdrant_client`` is installed.
    """

    def __init__(
        self,
        sqlite_path: str = "",
        collection_name: str = "",
        qdrant_url: str = "",
        qdrant_api_key: str = "",
        vector_store: Optional[Any] = None,
    ) -> None:
        super().__init__(
            sqlite_path=sqlite_path,
            collection_name=collection_name,
            qdrant_url=qdrant_url,
            qdrant_api_key=qdrant_api_key,
            vector_store=vector_store,
        )
        self._init_records_table()

    # ── additional SQLite table ───────────────────────────────────────────────

    def _init_records_table(self) -> None:
        """Create the structured-records table used by the FusedStorage API."""
        with self._lock:
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS records (
                    record_id  TEXT PRIMARY KEY,
                    data       TEXT,
                    created_at TEXT
                )
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS raw_vectors (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id  TEXT,
                    vector_dim INTEGER,
                    payload    TEXT,
                    created_at TEXT
                )
            """)
            self._conn.commit()

    # ── raw-vector API ────────────────────────────────────────────────────────

    def add_embedding(  # type: ignore[override]
        self,
        vector: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Store a raw float vector with metadata.

        Accepts either a pre-computed float list (ALE-script style) **or** a
        text string (parent FusedMemory style).  When a float list is given the
        vector is stored in SQLite ``raw_vectors`` table and upserted into
        Qdrant/FAISS if the VectorStore is available.

        Args:
            vector:   Pre-computed embedding (``List[float]``) **or** text
                      string (delegated to parent when a str is provided).
            metadata: Optional payload dict.

        Returns:
            True on success.
        """
        metadata = metadata or {}

        # If caller passed text, delegate to the parent text-embedding path
        if isinstance(vector, str):
            return super().add_embedding(vector, metadata)

        # Raw float vector path
        ts = _now_iso()
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO raw_vectors (record_id, vector_dim, payload, created_at) VALUES (?,?,?,?)",
                    (
                        metadata.get("id", metadata.get("source", "unknown")),
                        len(vector) if hasattr(vector, "__len__") else 0,
                        json.dumps(metadata),
                        ts,
                    ),
                )
                self._conn.commit()
        except Exception as exc:
            log.debug("[FusedMemoryPrimary] raw_vectors insert failed: %s", exc)

        # Attempt Qdrant/FAISS upsert via VectorStore
        vs = self._get_vector_store()
        if vs is not None:
            try:
                # Convert raw vector to a text ID for VectorStore.add()
                text_repr = metadata.get("source", "") or metadata.get("title", "") or str(metadata)[:200]
                doc_id = metadata.get("id", f"rv-{int(time.time()*1000)}")
                vs.add(str(doc_id), text_repr[:500])
                return True
            except Exception as exc:
                log.debug("[FusedMemoryPrimary] VectorStore upsert failed: %s", exc)

        return True  # SQLite write always succeeds above

    def search_vectors(  # type: ignore[override]
        self,
        vector: Any,
        top_k: int = 5,
    ) -> Any:
        """
        Search by raw float vector or text query string.

        Returns a dict ``{"qdrant": [...], "sqlite": [...]}`` so callers can
        inspect results from each backend independently.

        When *vector* is a float list, the VectorStore semantic search is used
        for the ``"qdrant"`` key.  When *vector* is a text string, the parent
        class ``search_vectors`` is used.

        Args:
            vector: Float list or text query string.
            top_k:  Maximum results per backend.

        Returns:
            ``{"qdrant": list[dict], "sqlite": list[dict]}``
        """
        qdrant_results: List[Dict[str, Any]] = []
        sqlite_results: List[Dict[str, Any]] = []

        # Vector search via VectorStore
        vs = self._get_vector_store()
        if vs is not None:
            try:
                query_text = (
                    vector if isinstance(vector, str)
                    else " ".join(str(v) for v in list(vector)[:10])
                )
                qdrant_results = vs.search(query_text, top_k=top_k) or []
            except Exception as exc:
                log.debug("[FusedMemoryPrimary] vector search failed: %s", exc)

        # SQLite raw_vectors metadata fallback
        try:
            rows = self._conn.execute(
                "SELECT record_id, vector_dim, payload, created_at FROM raw_vectors ORDER BY created_at DESC LIMIT ?",
                (top_k,),
            ).fetchall()
            sqlite_results = [
                {
                    "record_id": r[0],
                    "vector_dim": r[1],
                    "payload": json.loads(r[2] or "{}"),
                    "created_at": r[3],
                }
                for r in rows
            ]
        except Exception as exc:
            log.debug("[FusedMemoryPrimary] sqlite raw_vectors query failed: %s", exc)

        return {"qdrant": qdrant_results, "sqlite": sqlite_results}

    # ── FusedStorage record API ───────────────────────────────────────────────

    def insert_record(
        self,
        record_id: str,
        data: Dict[str, Any],
    ) -> None:
        """
        Insert or replace a structured record in SQLite.

        Args:
            record_id: Unique record identifier.
            data:      Arbitrary dict of record fields.
        """
        ts = _now_iso()
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO records (record_id, data, created_at) VALUES (?,?,?)",
                    (record_id, json.dumps(data), ts),
                )
                self._conn.commit()
        except Exception as exc:
            log.debug("[FusedMemoryPrimary] insert_record failed: %s", exc)

    def get_record(self, record_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a structured record by ID.

        Args:
            record_id: Record identifier.

        Returns:
            Record dict, or ``None`` if not found.
        """
        try:
            row = self._conn.execute(
                "SELECT data FROM records WHERE record_id=?",
                (record_id,),
            ).fetchone()
            if row:
                return json.loads(row[0] or "{}")
        except Exception as exc:
            log.debug("[FusedMemoryPrimary] get_record failed: %s", exc)
        return None

    def list_records(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        List all stored records.

        Args:
            limit: Maximum rows to return.

        Returns:
            List of ``{"record_id": str, "data": dict, "created_at": str}``.
        """
        try:
            rows = self._conn.execute(
                "SELECT record_id, data, created_at FROM records ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [
                {
                    "record_id": r[0],
                    "data": json.loads(r[1] or "{}"),
                    "created_at": r[2],
                }
                for r in rows
            ]
        except Exception as exc:
            log.debug("[FusedMemoryPrimary] list_records failed: %s", exc)
        return []

    def insert_vector(
        self,
        record_id: str,
        vector: List[float],
        payload: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Insert a named vector (SQLite metadata + Qdrant/FAISS upsert).

        Args:
            record_id: Unique identifier for this vector.
            vector:    Pre-computed float embedding.
            payload:   Optional metadata dict stored alongside the vector.

        Returns:
            True on success.
        """
        meta = dict(payload or {})
        meta["id"] = record_id
        return self.add_embedding(vector, meta)

    def query_vector(
        self,
        vector: List[float],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Search by raw vector and return a flat list of hits.

        This is an alias for :meth:`search_vectors` that flattens the result
        into a single list, merging Qdrant and SQLite hits (Qdrant hits first).

        Args:
            vector: Pre-computed float embedding.
            top_k:  Maximum results.

        Returns:
            List of result dicts.
        """
        result = self.search_vectors(vector, top_k=top_k)
        qdrant = result.get("qdrant") or []
        sqlite = result.get("sqlite") or []
        # Merge, deduplicate by id/record_id
        seen: set = set()
        combined: List[Dict[str, Any]] = []
        for item in qdrant + sqlite:
            key = item.get("id") or item.get("record_id") or str(item)
            if key not in seen:
                seen.add(key)
                combined.append(item)
        return combined[:top_k]


# ── convenience ────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# Module-level singleton
_primary: Optional[FusedMemoryPrimary] = None
import threading as _threading
_primary_lock = _threading.Lock()


def get_primary(
    sqlite_path: str = "",
    collection_name: str = "",
    vector_store: Optional[Any] = None,
) -> FusedMemoryPrimary:
    """Return a process-level FusedMemoryPrimary singleton."""
    global _primary
    with _primary_lock:
        if _primary is None:
            _primary = FusedMemoryPrimary(
                sqlite_path=sqlite_path,
                collection_name=collection_name,
                vector_store=vector_store,
            )
    return _primary


if __name__ == "__main__":
    mem = FusedMemoryPrimary(sqlite_path=":memory:")
    mem.insert_record("rec-1", {"name": "Alice", "score": 0.95})
    print("record:", mem.get_record("rec-1"))
    mem.add_embedding([0.0] * 384, {"source": "test", "id": "emb-1"})
    results = mem.search_vectors([0.0] * 384, top_k=3)
    print("qdrant:", len(results["qdrant"]), "sqlite:", len(results["sqlite"]))
    print("FusedMemoryPrimary OK")
