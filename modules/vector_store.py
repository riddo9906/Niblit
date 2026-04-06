#!/usr/bin/env python3
"""
modules/vector_store.py — Vector store abstraction for Niblit (Phase 3).

Provides a unified interface for semantic search over the knowledge base.
Supports three backends in priority order:

1. **Qdrant** (cloud or self-hosted) — when ``QDRANT_URL`` is set
2. **FAISS** (local in-process) — when ``faiss`` is installed
3. **In-memory linear scan** — always available, no dependencies

Activation::

    # Qdrant cloud
    QDRANT_URL=https://your-cluster.cloud.qdrant.io
    QDRANT_API_KEY=your-qdrant-api-key
    QDRANT_COLLECTION=niblit_knowledge
    EMBEDDING_MODEL=all-MiniLM-L6-v2

    # Self-hosted Qdrant (Docker)
    # docker run -p 6333:6333 qdrant/qdrant
    QDRANT_URL=http://localhost:6333

Usage::

    from modules.vector_store import VectorStore
    vs = VectorStore()
    vs.add("unique-id-1", "Python decorators allow wrapping functions...")
    results = vs.search("decorator pattern", top_k=3)

See SETUP.md for full setup instructions.
"""

import hashlib
import logging
import os
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("VectorStore")

# ── optional dependency flags ─────────────────────────────────────────────────
try:
    from sentence_transformers import SentenceTransformer as _SentenceTransformer
    _ST_AVAILABLE = True
except ImportError:
    _ST_AVAILABLE = False
    _SentenceTransformer = None  # type: ignore[assignment,misc]

try:
    import numpy as _np
    _NP_AVAILABLE = True
except ImportError:
    _np = None  # type: ignore[assignment]
    _NP_AVAILABLE = False

try:
    import faiss as _faiss
    _FAISS_AVAILABLE = True
except ImportError:
    _faiss = None  # type: ignore[assignment]
    _FAISS_AVAILABLE = False

try:
    from qdrant_client import QdrantClient as _QdrantClient
    from qdrant_client.models import (
        Distance as _Distance,
        VectorParams as _VectorParams,
        PointStruct as _PointStruct,
    )
    _QDRANT_AVAILABLE = True
except ImportError:
    _QdrantClient = None  # type: ignore[assignment,misc]
    _QDRANT_AVAILABLE = False


_EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
_EMBEDDING_DIM = 384       # default dim for all-MiniLM-L6-v2
_MAX_STORED_ITEMS = 10_000  # in-memory/FAISS safety cap


# ─────────────────────────────────────────────────────────────────────────────
# Embedding helper
# ─────────────────────────────────────────────────────────────────────────────

class _EmbeddingService:
    """Lazy-loaded sentence-transformer embedding service."""

    def __init__(self, model_name: str = _EMBEDDING_MODEL_NAME) -> None:
        self.model_name = model_name
        self._model: Optional[Any] = None

    def is_available(self) -> bool:
        return _ST_AVAILABLE

    def _load(self) -> None:
        if self._model is None and _ST_AVAILABLE:
            try:
                self._model = _SentenceTransformer(self.model_name)
                log.info("[VectorStore] Embedding model '%s' loaded", self.model_name)
            except Exception as exc:
                log.warning("[VectorStore] Failed to load embedding model: %s", exc)

    def encode(self, text: str) -> Optional[List[float]]:
        if not _ST_AVAILABLE or not _NP_AVAILABLE:
            return None
        self._load()
        if self._model is None:
            return None
        try:
            vec = self._model.encode(text, convert_to_numpy=True, show_progress_bar=False)
            return vec.tolist()
        except Exception as exc:
            log.debug("[VectorStore] encode failed: %s", exc)
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Backends
# ─────────────────────────────────────────────────────────────────────────────

class _InMemoryBackend:
    """O(n) linear-scan fallback — no external dependencies."""

    def __init__(self) -> None:
        # List of (id, text, vector_or_None)
        self._items: List[Dict[str, Any]] = []

    def add(self, doc_id: str, text: str, vector: Optional[List[float]]) -> None:
        # Replace if exists
        for item in self._items:
            if item["id"] == doc_id:
                item["text"] = text
                item["vector"] = vector
                return
        if len(self._items) >= _MAX_STORED_ITEMS:
            self._items.pop(0)
        self._items.append({"id": doc_id, "text": text, "vector": vector})

    def search(
        self, query_vector: Optional[List[float]], query_text: str, top_k: int
    ) -> List[Dict[str, Any]]:
        if not self._items:
            return []

        if query_vector is not None and _NP_AVAILABLE:
            import numpy as np
            qv = np.array(query_vector, dtype="float32")
            scored = []
            for item in self._items:
                if item["vector"] is not None:
                    iv = np.array(item["vector"], dtype="float32")
                    norm_q = np.linalg.norm(qv)
                    norm_i = np.linalg.norm(iv)
                    if norm_q > 0 and norm_i > 0:
                        score = float(np.dot(qv, iv) / (norm_q * norm_i))
                    else:
                        score = 0.0
                    scored.append((score, item))
            scored.sort(key=lambda x: x[0], reverse=True)
            return [
                {"id": it["id"], "text": it["text"], "score": sc}
                for sc, it in scored[:top_k]
            ]

        # Fallback: keyword overlap
        q_words = set(query_text.lower().split())
        scored = []
        for item in self._items:
            words = set(item["text"].lower().split())
            score = len(q_words & words) / max(1, len(q_words))
            scored.append((score, item))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {"id": it["id"], "text": it["text"], "score": sc}
            for sc, it in scored[:top_k]
        ]

    def count(self) -> int:
        return len(self._items)


# ─────────────────────────────────────────────────────────────────────────────
# Public interface
# ─────────────────────────────────────────────────────────────────────────────

class VectorStore:
    """
    Unified vector store with automatic backend selection.

    Priority: Qdrant → FAISS → in-memory linear scan.

    Args:
        collection:      Collection / index name.
        embedding_model: Sentence-transformer model name or HF repo ID.
        qdrant_url:      Qdrant server URL. Falls back to ``QDRANT_URL`` env var.
        qdrant_api_key:  Qdrant API key. Falls back to ``QDRANT_API_KEY`` env var.
    """

    def __init__(
        self,
        collection: str = "niblit_knowledge",
        embedding_model: str = _EMBEDDING_MODEL_NAME,
        qdrant_url: Optional[str] = None,
        qdrant_api_key: Optional[str] = None,
    ) -> None:
        self.collection = collection
        self._embedder = _EmbeddingService(embedding_model)
        self._qdrant_url: str = (
            qdrant_url if qdrant_url is not None
            else os.getenv("QDRANT_URL", "")
        )
        self._qdrant_api_key: str = (
            qdrant_api_key if qdrant_api_key is not None
            else os.getenv("QDRANT_API_KEY", "")
        )

        self._backend_name: str = "memory"
        self._qdrant_client: Optional[Any] = None
        self._faiss_index: Optional[Any] = None
        self._faiss_items: List[Dict[str, Any]] = []   # parallel list of {id, text}
        self._memory_backend = _InMemoryBackend()

        self._init_backend()

    # ── backend selection ─────────────────────────────────────────────────────

    def _init_backend(self) -> None:
        if self._qdrant_url and _QDRANT_AVAILABLE:
            self._init_qdrant()
        elif _FAISS_AVAILABLE and _NP_AVAILABLE:
            self._init_faiss()
        else:
            log.info("[VectorStore] Using in-memory fallback backend")

    def _init_qdrant(self) -> None:
        try:
            kwargs: Dict[str, Any] = {"url": self._qdrant_url, "timeout": 10}
            if self._qdrant_api_key:
                kwargs["api_key"] = self._qdrant_api_key
            self._qdrant_client = _QdrantClient(**kwargs)
            # Ensure collection exists
            existing = [c.name for c in self._qdrant_client.get_collections().collections]
            if self.collection not in existing:
                self._qdrant_client.create_collection(
                    collection_name=self.collection,
                    vectors_config=_VectorParams(
                        size=_EMBEDDING_DIM, distance=_Distance.COSINE
                    ),
                )
                log.info("[VectorStore] Created Qdrant collection '%s'", self.collection)
            self._backend_name = "qdrant"
            log.info("[VectorStore] Qdrant backend initialised (%s)", self._qdrant_url)
        except Exception as exc:
            log.warning("[VectorStore] Qdrant init failed (%s) — falling back", exc)
            self._qdrant_client = None
            if _FAISS_AVAILABLE and _NP_AVAILABLE:
                self._init_faiss()

    def _init_faiss(self) -> None:
        try:
            self._faiss_index = _faiss.IndexFlatIP(_EMBEDDING_DIM)  # inner-product
            self._backend_name = "faiss"
            log.info("[VectorStore] FAISS backend initialised (dim=%d)", _EMBEDDING_DIM)
        except Exception as exc:
            log.warning("[VectorStore] FAISS init failed (%s) — using memory", exc)

    # ── public API ────────────────────────────────────────────────────────────

    @property
    def backend(self) -> str:
        """Active backend: ``"qdrant"``, ``"faiss"``, or ``"memory"``."""
        return self._backend_name

    def is_available(self) -> bool:
        """Always True — memory backend is always available."""
        return True

    def add(self, doc_id: str, text: str) -> bool:
        """
        Store a text document.

        Args:
            doc_id:  Unique identifier for this document.
            text:    Text content to embed and store.

        Returns:
            True on success, False on failure.
        """
        vector = self._embedder.encode(text)

        if self._backend_name == "qdrant" and self._qdrant_client is not None:
            return self._add_qdrant(doc_id, text, vector)
        if self._backend_name == "faiss" and self._faiss_index is not None:
            return self._add_faiss(doc_id, text, vector)
        self._memory_backend.add(doc_id, text, vector)
        return True

    def timed_search(self, query: str, top_k: int = 5) -> Dict[str, Any]:
        """Run a semantic search and include wall-clock timing in the result.

        Uses ``time.time()`` to measure search latency so callers can track
        performance over time and detect slow-downs as the vector index grows.

        Returns a dict with keys ``results`` (the normal search output),
        ``latency_ms`` (float), and ``backend`` (str).
        """
        t0 = time.time()
        results = self.search(query, top_k=top_k)
        latency_ms = round((time.time() - t0) * 1000, 2)
        return {
            "results": results,
            "latency_ms": latency_ms,
            "backend": self._backend_name,
        }

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """
        Semantically search the store.

        Args:
            query: Natural-language query string.
            top_k: Maximum number of results to return.

        Returns:
            List of ``{"id", "text", "score"}`` dicts, best-match first.
        """
        vector = self._embedder.encode(query)

        if self._backend_name == "qdrant" and self._qdrant_client is not None:
            return self._search_qdrant(vector, query, top_k)
        if self._backend_name == "faiss" and self._faiss_index is not None:
            return self._search_faiss(vector, query, top_k)
        return self._memory_backend.search(vector, query, top_k)

    def count(self) -> int:
        """Return the number of stored documents."""
        if self._backend_name == "qdrant" and self._qdrant_client is not None:
            try:
                info = self._qdrant_client.get_collection(self.collection)
                return info.vectors_count or 0
            except Exception:
                return 0
        if self._backend_name == "faiss" and self._faiss_index is not None:
            return self._faiss_index.ntotal
        return self._memory_backend.count()

    # ── backend-specific implementations ─────────────────────────────────────

    def _add_qdrant(
        self, doc_id: str, text: str, vector: Optional[List[float]]
    ) -> bool:
        if vector is None:
            return False
        try:
            # Use a stable integer ID derived from the doc_id string
            int_id = int(hashlib.md5(doc_id.encode()).hexdigest(), 16) % (2**63)
            self._qdrant_client.upsert(
                collection_name=self.collection,
                points=[_PointStruct(id=int_id, vector=vector, payload={"id": doc_id, "text": text})],
            )
            return True
        except Exception as exc:
            log.debug("[VectorStore/Qdrant] add failed: %s", exc)
            return False

    def _add_faiss(
        self, doc_id: str, text: str, vector: Optional[List[float]]
    ) -> bool:
        if vector is None or not _NP_AVAILABLE:
            return False
        try:
            import numpy as np
            if self._faiss_index.ntotal >= _MAX_STORED_ITEMS:
                log.debug("[VectorStore/FAISS] capacity reached, dropping oldest")
                if self._faiss_items:
                    self._faiss_items.pop(0)
                    # FAISS IndexFlatIP doesn't support removal; rebuild
                    vecs = []
                    for item in self._faiss_items:
                        v = self._embedder.encode(item["text"])
                        if v is not None:
                            vecs.append(v)
                    self._faiss_index.reset()
                    if vecs:
                        self._faiss_index.add(np.array(vecs, dtype="float32"))
            vec_np = np.array([vector], dtype="float32")
            self._faiss_index.add(vec_np)
            self._faiss_items.append({"id": doc_id, "text": text})
            return True
        except Exception as exc:
            log.debug("[VectorStore/FAISS] add failed: %s", exc)
            return False

    def _search_qdrant(
        self, vector: Optional[List[float]], query_text: str, top_k: int
    ) -> List[Dict[str, Any]]:
        if vector is None:
            return []
        try:
            hits = self._qdrant_client.search(
                collection_name=self.collection,
                query_vector=vector,
                limit=top_k,
                with_payload=True,
            )
            return [
                {
                    "id": h.payload.get("id", str(h.id)) if h.payload else str(h.id),
                    "text": h.payload.get("text", "") if h.payload else "",
                    "score": h.score,
                }
                for h in hits
            ]
        except Exception as exc:
            log.debug("[VectorStore/Qdrant] search failed: %s", exc)
            return []

    def _search_faiss(
        self, vector: Optional[List[float]], query_text: str, top_k: int
    ) -> List[Dict[str, Any]]:
        if vector is None or not _NP_AVAILABLE or self._faiss_index.ntotal == 0:
            return []
        try:
            import numpy as np
            qv = np.array([vector], dtype="float32")
            k = min(top_k, self._faiss_index.ntotal)
            scores, indices = self._faiss_index.search(qv, k)
            results = []
            for score, idx in zip(scores[0], indices[0]):
                if 0 <= idx < len(self._faiss_items):
                    item = self._faiss_items[idx]
                    results.append({"id": item["id"], "text": item["text"], "score": float(score)})
            return results
        except Exception as exc:
            log.debug("[VectorStore/FAISS] search failed: %s", exc)
            return []


# ---------------------------------------------------------------------------
# FusedStorage — thin compatibility shim used by niblit_memory.py
# ---------------------------------------------------------------------------

class FusedStorage:
    """
    Compatibility shim that wraps :class:`~modules.fused_memory_primary.FusedMemoryPrimary`
    and exposes the record + vector API expected by :class:`~niblit_memory.NiblitMemory`.

    When ``fused_memory_primary`` is unavailable, falls back to a plain
    :class:`VectorStore` for vector operations and a basic in-memory dict for
    structured records.

    Args:
        sqlite_path:     SQLite database path.
        qdrant_host:     Qdrant hostname (used only when qdrant_url is not set).
        qdrant_port:     Qdrant port.
        qdrant_url:      Full Qdrant URL (overrides qdrant_host/port when set).
        collection_name: Qdrant collection name.
    """

    def __init__(
        self,
        sqlite_path: str = "",
        qdrant_host: str = "",
        qdrant_port: int = 6333,
        qdrant_url: str = "",
        collection_name: str = "",
    ) -> None:
        import os
        url = qdrant_url or os.getenv("QDRANT_URL", "")
        if not url and qdrant_host:
            url = f"http://{qdrant_host}:{qdrant_port}"

        self._primary = None
        try:
            from niblit_memory import FusedMemoryPrimary  # type: ignore[import]
            self._primary = FusedMemoryPrimary(
                sqlite_path=sqlite_path,
                collection_name=collection_name,
                qdrant_url=url,
            )
        except Exception as exc:
            log.debug("[FusedStorage] FusedMemoryPrimary unavailable: %s", exc)
            # Minimal fallback: in-memory dict + VectorStore
            self._records_fallback: dict = {}
            self._vs_fallback = VectorStore(
                collection=collection_name or "niblit_vectors",
                qdrant_url=url,
            )

    def insert_record(self, record_id: str, data: dict) -> None:
        """Insert or replace a structured record."""
        if self._primary is not None:
            self._primary.insert_record(record_id, data)
        else:
            self._records_fallback[record_id] = data

    def get_record(self, record_id: str):
        """Retrieve a structured record by ID."""
        if self._primary is not None:
            return self._primary.get_record(record_id)
        return self._records_fallback.get(record_id)

    def list_records(self, limit: int = 100):
        """List all stored records."""
        if self._primary is not None:
            return self._primary.list_records(limit=limit)
        return [{"record_id": k, "data": v} for k, v in list(self._records_fallback.items())[:limit]]

    def insert_vector(self, record_id: str, vector, payload=None) -> bool:
        """Insert a named vector."""
        if self._primary is not None:
            return self._primary.insert_vector(record_id, vector, payload)
        try:
            text = str(payload or record_id)[:500]
            return self._vs_fallback.add(record_id, text)
        except Exception:
            return False

    def query_vector(self, vector, top_k: int = 5):
        """Search by raw vector."""
        if self._primary is not None:
            return self._primary.query_vector(vector, top_k=top_k)
        # Fallback: text-based search using string repr
        try:
            query_text = " ".join(str(v) for v in list(vector)[:10])
            return self._vs_fallback.search(query_text, top_k=top_k) or []
        except Exception:
            return []
