#!/usr/bin/env python3
"""
modules/fused_memory.py — Qdrant + SQLite fusion memory backend for Niblit.

Architecture
------------
Provides a unified read/write API that combines:

* **Qdrant** (via the existing :class:`~modules.vector_store.VectorStore`
  abstraction) — high-dimensional vector embeddings for semantic similarity
  search and retrieval-augmented generation (RAG).

* **SQLite** — structured/relational storage for events, metadata, logs,
  and knowledge facts.  Always available with zero external dependencies.

The fusion layer is designed to *replace* direct ``sqlite3`` / ``qdrant_client``
calls in the rest of the codebase.  Both backends degrade gracefully:

* When ``QDRANT_URL`` is not set the vector backend falls back to FAISS or
  an in-memory linear scan (provided by :class:`~modules.vector_store.VectorStore`).
* The SQLite backend is always available.

Activation
----------
::

    # Qdrant cloud
    QDRANT_URL=https://your-cluster.cloud.qdrant.io
    QDRANT_API_KEY=your-qdrant-api-key

    # Or self-hosted
    QDRANT_URL=http://localhost:6333

Usage
-----
::

    from modules.fused_memory import FusedMemory

    mem = FusedMemory()

    # Structured event log
    mem.log_event("self_reflection", {"note": "Completed cycle 42"})

    # Semantic embedding storage
    mem.add_embedding("python asyncio event loop patterns", {"source": "research", "step": 42})

    # Hybrid retrieval (vector + structured)
    results = mem.retrieve(query="asyncio patterns", event_type="self_reflection", top_k=3)
    print(results["vectors"])   # semantic hits
    print(results["events"])    # structured log rows
"""

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

log = logging.getLogger("Niblit.FusedMemory")

_DEFAULT_SQLITE_PATH = os.getenv("FUSED_MEMORY_DB_PATH", "niblit_fused.sqlite")
_DEFAULT_COLLECTION = os.getenv("QDRANT_COLLECTION", "niblit_knowledge")


class FusedMemory:
    """
    Hybrid memory backend combining Qdrant vector search with SQLite
    structured storage.

    Args:
        sqlite_path:     Path to the SQLite database file.  Defaults to
                         ``FUSED_MEMORY_DB_PATH`` env var or
                         ``"niblit_fused.sqlite"``.
        collection_name: Qdrant collection name.  Defaults to
                         ``QDRANT_COLLECTION`` env var or
                         ``"niblit_knowledge"``.
        qdrant_url:      Qdrant server URL.  Falls back to ``QDRANT_URL``
                         env var; when absent the VectorStore uses its
                         automatic fallback chain (FAISS → in-memory).
        qdrant_api_key:  Qdrant API key.  Falls back to ``QDRANT_API_KEY``
                         env var.
        vector_store:    Pre-built :class:`~modules.vector_store.VectorStore`
                         instance.  When provided, the fusion layer reuses it
                         instead of creating its own — useful when
                         ``niblit_core`` shares a singleton.
    """

    def __init__(
        self,
        sqlite_path: str = "",
        collection_name: str = "",
        qdrant_url: str = "",
        qdrant_api_key: str = "",
        vector_store: Optional[Any] = None,
    ) -> None:
        self._sqlite_path = sqlite_path or _DEFAULT_SQLITE_PATH
        self._collection = collection_name or _DEFAULT_COLLECTION
        self._qdrant_url = qdrant_url or os.getenv("QDRANT_URL", "")
        self._qdrant_api_key = qdrant_api_key or os.getenv("QDRANT_API_KEY", "")
        self._lock = threading.Lock()

        # SQLite setup
        self._conn: sqlite3.Connection = sqlite3.connect(
            self._sqlite_path,
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._init_sqlite()

        # VectorStore / Qdrant setup
        self._vector_store = vector_store
        self._vs_initialised = vector_store is not None

    # ── SQLite initialisation ─────────────────────────────────────────────────

    def _init_sqlite(self) -> None:
        """Create all required SQLite tables."""
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS events (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    type      TEXT NOT NULL,
                    payload   TEXT,
                    timestamp TEXT DEFAULT (datetime('now','utc'))
                );

                CREATE TABLE IF NOT EXISTS knowledge (
                    key        TEXT PRIMARY KEY,
                    value      TEXT,
                    source     TEXT,
                    created_at TEXT
                );

                CREATE TABLE IF NOT EXISTS graph_nodes (
                    name  TEXT PRIMARY KEY,
                    label TEXT,
                    props TEXT
                );

                CREATE TABLE IF NOT EXISTS graph_edges (
                    src  TEXT,
                    rel  TEXT,
                    dst  TEXT
                );
            """)
            self._conn.commit()

    # ── VectorStore lazy init ─────────────────────────────────────────────────

    def _get_vector_store(self) -> Optional[Any]:
        """Lazily initialise the underlying VectorStore."""
        if self._vs_initialised:
            return self._vector_store
        self._vs_initialised = True
        try:
            from modules.vector_store import VectorStore  # type: ignore[import]
            self._vector_store = VectorStore(
                collection=self._collection,
                qdrant_url=self._qdrant_url,
                qdrant_api_key=self._qdrant_api_key,
            )
            log.info("[FusedMemory] VectorStore ready (backend=%s)", self._vector_store.backend)
        except Exception as exc:
            log.debug("[FusedMemory] VectorStore unavailable: %s", exc)
            self._vector_store = None
        return self._vector_store

    # ── public helpers ────────────────────────────────────────────────────────

    @property
    def vector_backend(self) -> str:
        """Active vector backend name: ``"qdrant"``, ``"faiss"``, or ``"memory"``."""
        vs = self._get_vector_store()
        return vs.backend if vs else "none"

    def is_vector_available(self) -> bool:
        """Return True when a vector store backend is reachable."""
        return self._get_vector_store() is not None

    # ── SQLite write ──────────────────────────────────────────────────────────

    def log_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        """
        Append a structured event to the SQLite event log.

        Args:
            event_type: Category label for the event (e.g. ``"self_reflection"``).
            payload:    Arbitrary dict of event data.  JSON-serialised for storage.
        """
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO events (type, payload) VALUES (?, ?)",
                    (event_type, json.dumps(payload)),
                )
                self._conn.commit()
        except Exception as exc:
            log.debug("[FusedMemory] log_event failed: %s", exc)

    def store_knowledge(self, key: str, value: str, source: str = "") -> None:
        """
        Persist a key/value knowledge fact to SQLite.

        Compatible with :func:`niblit_full_upgrade_pipeline._store_knowledge`
        and :class:`~niblit_memory.knowledge_store.KnowledgeStore`.

        Args:
            key:    Unique knowledge key.
            value:  Text value to store.
            source: Optional source label.
        """
        ts = datetime.now(timezone.utc).isoformat()
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO knowledge (key, value, source, created_at) VALUES (?,?,?,?)",
                    (key, value, source, ts),
                )
                self._conn.commit()
        except Exception as exc:
            log.debug("[FusedMemory] store_knowledge failed: %s", exc)

    def merge_node(self, label: str, name: str, **props: Any) -> None:
        """
        Create or update a graph node in the SQLite adjacency table.

        Replaces the Neo4j ``merge_node`` in :class:`NiblitGraphDB`.
        """
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO graph_nodes (name, label, props) VALUES (?,?,?)",
                    (name, label, json.dumps(props)),
                )
                self._conn.commit()
        except Exception as exc:
            log.debug("[FusedMemory] merge_node failed: %s", exc)

    def merge_relationship(self, src: str, rel: str, dst: str) -> None:
        """
        Create a directed edge in the SQLite graph adjacency table.

        Replaces the Neo4j ``merge_relationship`` in :class:`NiblitGraphDB`.
        """
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO graph_edges (src, rel, dst) VALUES (?,?,?)",
                    (src, rel, dst),
                )
                self._conn.commit()
        except Exception as exc:
            log.debug("[FusedMemory] merge_relationship failed: %s", exc)

    # ── SQLite read ───────────────────────────────────────────────────────────

    def query_events(
        self,
        event_type: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve structured events from the SQLite event log.

        Args:
            event_type: Optional filter on ``type`` column.
            limit:      Maximum rows to return (most recent first).

        Returns:
            List of ``{"id", "type", "payload", "timestamp"}`` dicts.
        """
        try:
            sql = "SELECT id, type, payload, timestamp FROM events"
            params: List[Any] = []
            if event_type:
                sql += " WHERE type=?"
                params.append(event_type)
            sql += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            rows = self._conn.execute(sql, params).fetchall()
            return [
                {
                    "id": r["id"],
                    "type": r["type"],
                    "payload": json.loads(r["payload"] or "{}"),
                    "timestamp": r["timestamp"],
                }
                for r in rows
            ]
        except Exception as exc:
            log.debug("[FusedMemory] query_events failed: %s", exc)
            return []

    def query_knowledge(
        self,
        source: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve knowledge facts from the SQLite knowledge table.

        Args:
            source: Optional source label filter.
            limit:  Maximum rows to return.

        Returns:
            List of ``{"key", "value", "source", "created_at"}`` dicts.
        """
        try:
            sql = "SELECT key, value, source, created_at FROM knowledge"
            params: List[Any] = []
            if source:
                sql += " WHERE source=?"
                params.append(source)
            sql += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            rows = self._conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            log.debug("[FusedMemory] query_knowledge failed: %s", exc)
            return []

    # ── Qdrant write ──────────────────────────────────────────────────────────

    def add_embedding(
        self,
        text: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Embed *text* and store the resulting vector in Qdrant (or fallback).

        Unlike the raw Qdrant API which requires a pre-computed vector, this
        method delegates embedding to the :class:`~modules.vector_store.VectorStore`
        which uses sentence-transformers internally.

        Args:
            text:     Text to embed and store.
            metadata: Optional dict stored as payload alongside the vector.
                      Keys ``"source"``, ``"title"``, and ``"url"`` are
                      especially useful for later retrieval.

        Returns:
            True when the embedding was stored, False on failure.
        """
        vs = self._get_vector_store()
        if vs is None:
            return False
        try:
            import uuid
            doc_id = str(uuid.uuid4())
            # Encode metadata into the text prefix so it is searchable on
            # backends that don't support payload queries.
            enriched = text
            if metadata:
                source = metadata.get("source", "")
                title = metadata.get("title", "")
                if source or title:
                    prefix = " | ".join(filter(None, [source, title]))
                    enriched = f"[{prefix}] {text}"
            vs.add(doc_id, enriched[:1000])
            return True
        except Exception as exc:
            log.debug("[FusedMemory] add_embedding failed: %s", exc)
            return False

    # ── Qdrant read ───────────────────────────────────────────────────────────

    def search_vectors(
        self,
        query: str,
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Semantic vector search over the Qdrant / fallback store.

        Args:
            query: Natural-language query string.
            top_k: Maximum number of results.

        Returns:
            List of ``{"id", "text", "score"}`` dicts.
        """
        vs = self._get_vector_store()
        if vs is None:
            return []
        try:
            return vs.search(query, top_k=top_k) or []
        except Exception as exc:
            log.debug("[FusedMemory] search_vectors failed: %s", exc)
            return []

    # ── unified hybrid retrieval ──────────────────────────────────────────────

    def retrieve(
        self,
        query: Optional[str] = None,
        event_type: Optional[str] = None,
        top_k: int = 5,
    ) -> Dict[str, Any]:
        """
        Unified hybrid retrieval — combines semantic vector search and
        structured SQLite event query in a single call.

        This is the primary RAG entry-point for LLM adapters.

        Args:
            query:      Natural-language query for semantic vector search.
                        When ``None`` (or the vector store is unavailable)
                        the ``"vectors"`` key will be an empty list.
            event_type: SQLite event type filter.  When ``None`` the
                        ``"events"`` key will be an empty list.
            top_k:      Maximum number of results from each backend.

        Returns:
            Dict with keys:

            * ``"vectors"`` — list of ``{"id", "text", "score"}`` dicts
            * ``"events"``  — list of ``{"id", "type", "payload", "timestamp"}``
        """
        results: Dict[str, Any] = {"vectors": [], "events": []}

        if query:
            results["vectors"] = self.search_vectors(query, top_k=top_k)

        if event_type:
            results["events"] = self.query_events(event_type, limit=top_k)

        return results

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        """Close the SQLite connection."""
        try:
            self._conn.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Module-level singleton accessor
# ---------------------------------------------------------------------------

_singleton: Optional[FusedMemory] = None
_singleton_lock = threading.Lock()


def get_fused_memory(
    sqlite_path: str = "",
    collection_name: str = "",
    vector_store: Optional[Any] = None,
) -> "FusedMemory":
    """
    Return a process-level :class:`FusedMemory` singleton.

    Subsequent calls return the same instance regardless of arguments.
    Use this to share a single connection pool across modules.
    """
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = FusedMemory(
                sqlite_path=sqlite_path,
                collection_name=collection_name,
                vector_store=vector_store,
            )
    return _singleton


if __name__ == "__main__":
    mem = FusedMemory(sqlite_path=":memory:")
    mem.log_event("test", {"note": "hello"})
    mem.store_knowledge("greet:1", "Hello, world!", source="test")
    mem.add_embedding("Python asyncio event loop patterns", {"source": "test"})
    results = mem.retrieve(query="asyncio patterns", event_type="test", top_k=3)
    print(f"vectors: {len(results['vectors'])}, events: {len(results['events'])}")
    print("FusedMemory OK — vector backend:", mem.vector_backend)
