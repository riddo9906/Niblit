# niblit_memory/knowledge_store.py
"""
Niblit KnowledgeStore — persistent memory for search results.

Persists Serpex search results to SQLite and, when Qdrant is available,
also upserts embeddings so that the :class:`~modules.vector_store.VectorStore`
semantic layer can retrieve them later.

Architecture role::

    ResearchAgent
         │
         ▼
    KnowledgeStore  ──►  SQLite (niblit_knowledge table)
         │
         ├──────────────►  VectorStore / Qdrant  (optional)
         │
         └──────────────►  FusedMemory  (optional hybrid backend)

Usage::

    from niblit_memory.knowledge_store import KnowledgeStore
    ks = KnowledgeStore()
    ks.store_search_results("python asyncio", results)
    rows = ks.get_by_source("serpex", limit=10)
"""

import hashlib
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Niblit.KnowledgeStore")

_DEFAULT_DB_PATH = os.getenv("NIBLIT_SQLITE_DB_PATH", "niblit_data.sqlite")


class KnowledgeStore:
    """
    Persistent store for search results backed by SQLite.

    Optionally syncs new records to a :class:`~modules.vector_store.VectorStore`
    (and therefore to Qdrant when ``QDRANT_URL`` is set) after every
    :meth:`store_search_results` call.

    When a :class:`~modules.fused_memory.FusedMemory` instance is provided via
    *fused_memory*, both the structured event log *and* the vector embedding are
    written through the fusion layer for unified hybrid retrieval.

    Args:
        db_path:        Path to the SQLite database file.  Defaults to the
                        ``NIBLIT_SQLITE_DB_PATH`` env var or ``niblit_data.sqlite``.
        vector_store:   Pre-built :class:`~modules.vector_store.VectorStore`
                        instance.  When *None*, one is created lazily from env vars.
        qdrant_url:     Qdrant server URL.  Falls back to ``QDRANT_URL`` env var.
        qdrant_api_key: Qdrant API key.  Falls back to ``QDRANT_API_KEY`` env var.
        fused_memory:   Optional :class:`~modules.fused_memory.FusedMemory` instance.
                        When provided, results are also stored via the fusion layer.
    """

    # SQLite schema for knowledge records
    _CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS knowledge (
            key        TEXT PRIMARY KEY,
            value      TEXT,
            source     TEXT,
            created_at TEXT
        )
    """

    def __init__(
        self,
        db_path: str = "",
        vector_store: Optional[Any] = None,
        qdrant_url: str = "",
        qdrant_api_key: str = "",
        fused_memory: Optional[Any] = None,
    ) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._vector_store = vector_store
        self._fused_memory = fused_memory

        self._qdrant_url = qdrant_url or os.getenv("QDRANT_URL", "")
        self._qdrant_api_key = qdrant_api_key or os.getenv("QDRANT_API_KEY", "")

        # Ensure the table exists
        try:
            with self._connect() as conn:
                conn.execute(self._CREATE_TABLE_SQL)
        except Exception as exc:
            logger.warning("KnowledgeStore: DB init failed: %s", exc)

    # ── public API ────────────────────────────────────────────────────────────

    def store_search_results(self, query: str, results: List[Dict[str, Any]]) -> None:
        """
        Persist a list of search results.

        Each item ``{"title", "url", "snippet"}`` is stored as a row keyed by
        the result URL (or a hash of title+snippet when URL is absent).  New
        records are also passed to the VectorStore / Qdrant for semantic search.

        Args:
            query:   The original search query (stored as metadata).
            results: List of result dicts from :class:`~niblit_agents.research_agent.ResearchAgent`.
        """
        if not results:
            return

        now = datetime.now(timezone.utc).isoformat()
        rows_to_embed: List[Dict[str, Any]] = []

        try:
            with self._connect() as conn:
                for item in results:
                    if not isinstance(item, dict) or "error" in item:
                        continue
                    url = item.get("url", "")
                    snippet = item.get("snippet", "")
                    title = item.get("title", "")

                    # Stable key: prefer URL; fall back to hash
                    if url:
                        key = url
                    else:
                        key = "sha:" + hashlib.sha1(
                            f"{query}:{title}:{snippet}".encode()
                        ).hexdigest()[:16]

                    value = snippet or title
                    if not value:
                        continue

                    conn.execute(
                        """
                        INSERT OR REPLACE INTO knowledge (key, value, source, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (key, value, "serpex", now),
                    )
                    rows_to_embed.append({"key": key, "text": value, "title": title, "url": url})
        except Exception as exc:
            logger.warning("KnowledgeStore: SQLite write failed: %s", exc)

        # FusedMemory hybrid storage (structured event + vector embedding)
        if rows_to_embed and self._fused_memory:
            self._store_via_fused_memory(query, rows_to_embed)

        # Direct Qdrant embedding hook (used when FusedMemory is not present)
        elif rows_to_embed:
            self._embed_to_qdrant(rows_to_embed)

    def get_by_source(self, source: str = "serpex", limit: int = 20) -> List[Dict[str, Any]]:
        """
        Retrieve stored records by their source label.

        Args:
            source: Source label to filter by (e.g. ``"serpex"``).
            limit:  Maximum number of rows to return.

        Returns:
            List of ``{"key": str, "value": str, "created_at": str}`` dicts.
        """
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT key, value, created_at FROM knowledge WHERE source = ? LIMIT ?",
                    (source, limit),
                ).fetchall()
            return [{"key": r[0], "value": r[1], "created_at": r[2]} for r in rows]
        except Exception as exc:
            logger.warning("KnowledgeStore: SQLite read failed: %s", exc)
            return []

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        event_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Hybrid retrieval via FusedMemory (when available).

        Falls back to a plain SQLite keyword search when FusedMemory is absent.

        Args:
            query:      Natural-language query for semantic search.
            top_k:      Maximum results per backend.
            event_type: Optional event type filter for the structured log.

        Returns:
            Dict with ``"vectors"`` and ``"events"`` keys (matching
            :meth:`~modules.fused_memory.FusedMemory.retrieve`).
        """
        if self._fused_memory:
            return self._fused_memory.retrieve(
                query=query,
                event_type=event_type,
                top_k=top_k,
            )
        # Fallback: simple SQLite LIKE search
        results: Dict[str, Any] = {"vectors": [], "events": []}
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT key, value, created_at FROM knowledge WHERE value LIKE ? LIMIT ?",
                    (f"%{query[:50]}%", top_k),
                ).fetchall()
            results["events"] = [
                {"key": r[0], "value": r[1], "created_at": r[2]} for r in rows
            ]
        except Exception as exc:
            logger.debug("KnowledgeStore.retrieve fallback failed: %s", exc)
        return results

    # ── internals ─────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.isolation_level = None  # autocommit
        return conn

    def _vector_store_client(self) -> Optional[Any]:
        """Lazily initialise a :class:`~modules.vector_store.VectorStore`."""
        if self._vector_store is None and self._qdrant_url:
            try:
                from modules.vector_store import VectorStore  # type: ignore[import]
                self._vector_store = VectorStore(
                    collection="niblit_knowledge",
                    qdrant_url=self._qdrant_url,
                    qdrant_api_key=self._qdrant_api_key,
                )
            except Exception as exc:
                logger.debug("KnowledgeStore: VectorStore unavailable: %s", exc)
        return self._vector_store

    def _embed_to_qdrant(self, rows: List[Dict[str, Any]]) -> None:
        """Upsert *rows* into the VectorStore / Qdrant collection."""
        vs = self._vector_store_client()
        if vs is None:
            return
        for row in rows:
            try:
                vs.add(row["key"], row["text"][:500])
            except Exception as exc:
                logger.debug("KnowledgeStore: Qdrant upsert failed: %s", exc)

    def _store_via_fused_memory(
        self,
        query: str,
        rows: List[Dict[str, Any]],
    ) -> None:
        """Store rows via FusedMemory (structured event log + vector embedding)."""
        fm = self._fused_memory
        if fm is None:
            return
        try:
            fm.log_event("knowledge_store", {"query": query, "count": len(rows)})
        except Exception as exc:
            logger.debug("KnowledgeStore: FusedMemory log_event failed: %s", exc)
        for row in rows:
            try:
                fm.store_knowledge(
                    key=row["key"],
                    value=row["text"][:500],
                    source="serpex",
                )
                fm.add_embedding(
                    row["text"][:500],
                    metadata={
                        "source": "serpex",
                        "title": row.get("title", ""),
                        "url": row.get("url", ""),
                        "query": query,
                    },
                )
            except Exception as exc:
                logger.debug("KnowledgeStore: FusedMemory store failed: %s", exc)


if __name__ == "__main__":
    print("Running niblit_memory/knowledge_store.py")


import hashlib
import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Niblit.KnowledgeStore")

_DEFAULT_DB_PATH = os.getenv("NIBLIT_SQLITE_DB_PATH", "niblit_data.sqlite")


class KnowledgeStore:
    """
    Persistent store for search results backed by SQLite.

    Optionally syncs new records to a :class:`~modules.vector_store.VectorStore`
    (and therefore to Qdrant when ``QDRANT_URL`` is set) after every
    :meth:`store_search_results` call.

    Args:
        db_path:        Path to the SQLite database file.  Defaults to the
                        ``NIBLIT_SQLITE_DB_PATH`` env var or ``niblit_data.sqlite``.
        vector_store:   Pre-built :class:`~modules.vector_store.VectorStore`
                        instance.  When *None*, one is created lazily from env vars.
        qdrant_url:     Qdrant server URL.  Falls back to ``QDRANT_URL`` env var.
        qdrant_api_key: Qdrant API key.  Falls back to ``QDRANT_API_KEY`` env var.
    """

    # SQLite schema for knowledge records
    _CREATE_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS knowledge (
            key        TEXT PRIMARY KEY,
            value      TEXT,
            source     TEXT,
            created_at TEXT
        )
    """

    def __init__(
        self,
        db_path: str = "",
        vector_store: Optional[Any] = None,
        qdrant_url: str = "",
        qdrant_api_key: str = "",
    ) -> None:
        self._db_path = db_path or _DEFAULT_DB_PATH
        self._vector_store = vector_store

        self._qdrant_url = qdrant_url or os.getenv("QDRANT_URL", "")
        self._qdrant_api_key = qdrant_api_key or os.getenv("QDRANT_API_KEY", "")

        # Ensure the table exists
        try:
            with self._connect() as conn:
                conn.execute(self._CREATE_TABLE_SQL)
        except Exception as exc:
            logger.warning("KnowledgeStore: DB init failed: %s", exc)

    # ── public API ────────────────────────────────────────────────────────────

    def store_search_results(self, query: str, results: List[Dict[str, Any]]) -> None:
        """
        Persist a list of search results.

        Each item ``{"title", "url", "snippet"}`` is stored as a row keyed by
        the result URL (or a hash of title+snippet when URL is absent).  New
        records are also passed to the VectorStore / Qdrant for semantic search.

        Args:
            query:   The original search query (stored as metadata).
            results: List of result dicts from :class:`~niblit_agents.research_agent.ResearchAgent`.
        """
        if not results:
            return

        now = datetime.now(timezone.utc).isoformat()
        rows_to_embed: List[Dict[str, Any]] = []

        try:
            with self._connect() as conn:
                for item in results:
                    if not isinstance(item, dict) or "error" in item:
                        continue
                    url = item.get("url", "")
                    snippet = item.get("snippet", "")
                    title = item.get("title", "")

                    # Stable key: prefer URL; fall back to hash
                    if url:
                        key = url
                    else:
                        key = "sha:" + hashlib.sha1(
                            f"{query}:{title}:{snippet}".encode()
                        ).hexdigest()[:16]

                    value = snippet or title
                    if not value:
                        continue

                    conn.execute(
                        """
                        INSERT OR REPLACE INTO knowledge (key, value, source, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (key, value, "serpex", now),
                    )
                    rows_to_embed.append({"key": key, "text": value})
        except Exception as exc:
            logger.warning("KnowledgeStore: SQLite write failed: %s", exc)

        # Qdrant embedding hook
        if rows_to_embed:
            self._embed_to_qdrant(rows_to_embed)

    def get_by_source(self, source: str = "serpex", limit: int = 20) -> List[Dict[str, Any]]:
        """
        Retrieve stored records by their source label.

        Args:
            source: Source label to filter by (e.g. ``"serpex"``).
            limit:  Maximum number of rows to return.

        Returns:
            List of ``{"key": str, "value": str, "created_at": str}`` dicts.
        """
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT key, value, created_at FROM knowledge WHERE source = ? LIMIT ?",
                    (source, limit),
                ).fetchall()
            return [{"key": r[0], "value": r[1], "created_at": r[2]} for r in rows]
        except Exception as exc:
            logger.warning("KnowledgeStore: SQLite read failed: %s", exc)
            return []

    # ── internals ─────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.isolation_level = None  # autocommit
        return conn

    def _vector_store_client(self) -> Optional[Any]:
        """Lazily initialise a :class:`~modules.vector_store.VectorStore`."""
        if self._vector_store is None and self._qdrant_url:
            try:
                from modules.vector_store import VectorStore  # type: ignore[import]
                self._vector_store = VectorStore(
                    collection="niblit_knowledge",
                    qdrant_url=self._qdrant_url,
                    qdrant_api_key=self._qdrant_api_key,
                )
            except Exception as exc:
                logger.debug("KnowledgeStore: VectorStore unavailable: %s", exc)
        return self._vector_store

    def _embed_to_qdrant(self, rows: List[Dict[str, Any]]) -> None:
        """Upsert *rows* into the VectorStore / Qdrant collection."""
        vs = self._vector_store_client()
        if vs is None:
            return
        for row in rows:
            try:
                vs.add(row["key"], row["text"][:500])
            except Exception as exc:
                logger.debug("KnowledgeStore: Qdrant upsert failed: %s", exc)


if __name__ == "__main__":
    print("Running niblit_memory/knowledge_store.py")
