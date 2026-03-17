#!/usr/bin/env python3
"""
niblit_memory/qdrant_engine.py — Upgraded Qdrant inference pipeline for Niblit.

Key improvements over the raw VectorStore:
  - Dynamic collection creation via VectorStore's auto-backend selection
  - Proper embedding abstraction (sentence-transformers / HF, graceful fallback)
  - Payload enrichment (text + metadata stored together)
  - Semantic validation hooks (relevance check before upsert)
  - Reusable query interface with rich return format

Activation::

    QDRANT_URL=https://your-cluster.cloud.qdrant.io
    QDRANT_API_KEY=your-qdrant-api-key

Degrades transparently to FAISS → in-memory when Qdrant is unavailable.

Usage::

    from niblit_memory.qdrant_engine import QdrantEngine
    engine = QdrantEngine()
    engine.upsert_documents([{"text": "...", "metadata": {"source": "serpex"}}])
    results = engine.query("python asyncio patterns", limit=5)
"""

import logging
import os
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Niblit.QdrantEngine")

_COLLECTION = os.getenv("QDRANT_COLLECTION", "niblit_knowledge")


class QdrantEngine:
    """
    High-level vector-store interface for Niblit's inference pipeline.

    Wraps :class:`~modules.vector_store.VectorStore` and adds richer document
    ingestion (``upsert_documents``) and query (``query``) interfaces that
    preserve per-document metadata alongside the embedding.

    Args:
        collection:     Collection / index name (defaults to ``QDRANT_COLLECTION``
                        env var or ``"niblit_knowledge"``).
        qdrant_url:     Qdrant server URL.  Falls back to ``QDRANT_URL`` env var.
        qdrant_api_key: Qdrant API key.  Falls back to ``QDRANT_API_KEY`` env var.
        vector_store:   Pre-built :class:`~modules.vector_store.VectorStore`
                        instance.  When provided, the engine reuses it instead of
                        creating its own — useful when niblit_core shares a singleton.
    """

    def __init__(
        self,
        collection: str = "",
        qdrant_url: str = "",
        qdrant_api_key: str = "",
        vector_store: Optional[Any] = None,
    ) -> None:
        self.collection_name: str = collection or _COLLECTION
        self._qdrant_url = qdrant_url or os.getenv("QDRANT_URL", "")
        self._qdrant_api_key = qdrant_api_key or os.getenv("QDRANT_API_KEY", "")

        # Accept an injected vector store or build one lazily
        self._vector_store = vector_store
        self._vs_initialised = vector_store is not None

    # ── backend initialisation ────────────────────────────────────────────────

    def _ensure_vector_store(self) -> Optional[Any]:
        """Lazily initialise the underlying VectorStore."""
        if self._vs_initialised:
            return self._vector_store
        self._vs_initialised = True
        try:
            from modules.vector_store import VectorStore  # type: ignore[import]
            self._vector_store = VectorStore(
                collection=self.collection_name,
                qdrant_url=self._qdrant_url,
                qdrant_api_key=self._qdrant_api_key,
            )
            logger.info(
                "[QdrantEngine] VectorStore ready (backend=%s)",
                self._vector_store.backend,
            )
        except Exception as exc:
            logger.debug("[QdrantEngine] VectorStore unavailable: %s", exc)
            self._vector_store = None
        return self._vector_store

    # ── public API ────────────────────────────────────────────────────────────

    @property
    def backend(self) -> str:
        """Active backend name: ``"qdrant"``, ``"faiss"``, or ``"memory"``."""
        vs = self._ensure_vector_store()
        return vs.backend if vs else "none"

    def is_available(self) -> bool:
        """Return True when a vector-store backend is reachable."""
        return self._ensure_vector_store() is not None

    def upsert_documents(self, documents: List[Dict[str, Any]]) -> int:
        """
        Embed and upsert a list of documents into the vector store.

        Each document must contain at least a ``"text"`` key.  An optional
        ``"metadata"`` dict is stored as payload alongside the vector.

        Args:
            documents: List of ``{"text": str, "metadata": dict}`` dicts.

        Returns:
            Number of documents successfully upserted.
        """
        vs = self._ensure_vector_store()
        if vs is None:
            return 0

        count = 0
        for doc in documents:
            text = doc.get("text", "")
            if not text:
                continue
            metadata = doc.get("metadata", {})
            # Build a stable-ish doc_id from a UUID so repeated calls don't
            # deduplicate by accident (same snippet from two different runs
            # should both be stored for richer context).
            doc_id = str(uuid.uuid4())
            # Encode metadata into the text field via a prefix so it is
            # searchable even on backends that don't support payload queries.
            enriched_text = text
            if metadata:
                source = metadata.get("source", "")
                title = metadata.get("title", "")
                if source or title:
                    prefix = " | ".join(filter(None, [source, title]))
                    enriched_text = f"[{prefix}] {text}"

            try:
                vs.add(doc_id, enriched_text[:1000])
                count += 1
            except Exception as exc:
                logger.debug("[QdrantEngine] upsert failed for doc %s: %s", doc_id, exc)

        if count:
            logger.info("[QdrantEngine] Upserted %d documents", count)
        return count

    def query(self, query_text: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Semantic search over the vector store.

        Args:
            query_text: Natural-language query.
            limit:      Maximum number of results to return.

        Returns:
            List of ``{"score": float, "text": str, "metadata": dict}`` dicts,
            ordered by relevance (highest first).
        """
        vs = self._ensure_vector_store()
        if vs is None:
            return []

        try:
            hits = vs.search(query_text, top_k=limit)
            results = []
            for h in hits:
                text = h.get("text", "")
                score = h.get("score", 0.0)
                # Attempt to parse back the source prefix we encoded at upsert
                metadata: Dict[str, Any] = {}
                if text.startswith("[") and "]" in text:
                    end = text.index("]")
                    prefix = text[1:end]
                    text = text[end + 2:]  # strip "] "
                    parts = prefix.split(" | ", 1)
                    if len(parts) == 2:
                        metadata["source"] = parts[0]
                        metadata["title"] = parts[1]
                    else:
                        metadata["source"] = parts[0]
                results.append({"score": score, "text": text, "metadata": metadata})
            return results
        except Exception as exc:
            logger.debug("[QdrantEngine] query failed: %s", exc)
            return []

    # ── semantic validation hook ──────────────────────────────────────────────

    def is_relevant(self, query: str, text: str, threshold: float = 0.4) -> bool:
        """
        Simple term-overlap relevance gate.

        Returns True when enough query terms appear in *text*.  Used as a
        pre-filter before storing low-quality snippets.
        """
        terms = set(query.lower().split())
        if not terms:
            return True
        text_lower = text.lower()
        hits = sum(1 for t in terms if t in text_lower)
        return (hits / len(terms)) >= threshold


if __name__ == "__main__":
    engine = QdrantEngine()
    print(f"QdrantEngine backend: {engine.backend}")
    engine.upsert_documents([
        {"text": "Python asyncio patterns for concurrent programming", "metadata": {"source": "test"}},
    ])
    results = engine.query("asyncio")
    print(f"Query results: {results}")
