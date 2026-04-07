#!/usr/bin/env python3
"""
modules/hybrid_qdrant_manager.py — Multi-Model Qdrant Inference Manager
────────────────────────────────────────────────────────────────────────
Manages four complementary inference providers against a single Qdrant
cluster, routing queries and upserts to the appropriate model(s) based
on the nature of the text.

Providers
─────────
  ColBERT Small V1  (answerdotai/answerai-colbert-small-v1)
      Late-interaction dense retrieval; best for deep semantic / code / RAG
      workloads where per-token precision matters.

  BM25  (qdrant/bm25)
      Sparse keyword model; acts as a reliable lexical fallback that recalls
      exact terms even when dense embeddings under-rank them.

  intfloat multilingual-e5-small  (intfloat/multilingual-e5-small)
      Multilingual dense model; supports 100 languages. Used for
      general dense retrieval, chat context, and multilingual text.

Public API
──────────
  get_hybrid_manager()          — module-level singleton getter
  HybridQdrantManager.upsert()  — insert/update a document using selected models
  HybridQdrantManager.query()   — search, deduplicate, and re-rank results
  HybridQdrantManager.upsert_knowledge_item()  — dict-based upsert convenience
  HybridQdrantManager.select_models()          — route text to appropriate model set
  HybridQdrantManager.get_stats()              — per-model operation counters
  HybridQdrantManager.model_stats()            — human-readable stats string

Configuration (environment variables)
──────────────────────────────────────
  QDRANT_URL                Qdrant cluster URL (default: http://localhost:6333)
  QDRANT_API_KEY            Optional API key for Qdrant Cloud
  QDRANT_COLLECTION_PREFIX  Prefix prepended to every collection name (default: "niblit")

Graceful degradation
────────────────────
  All qdrant-client interactions are wrapped in try/except blocks.  If
  ``qdrant-client`` is not installed or the cluster is unreachable the module
  continues to function; operations are logged as warnings and return empty
  results rather than raising.

Usage::

    from modules.hybrid_qdrant_manager import get_hybrid_manager

    mgr = get_hybrid_manager()
    mgr.upsert("def fibonacci(n): ...", {"lang": "python"}, "code_docs")
    results = mgr.query("fibonacci implementation", "code_docs", top_k=3)
    print(mgr.model_stats())
"""

from __future__ import annotations

import logging
import os
import hashlib
import threading
import time
import unicodedata
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("HybridQdrantManager")

# ── Configuration from environment ────────────────────────────────────────────
_QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
_QDRANT_API_KEY = os.environ.get("QDRANT_API_KEY", None)
_COLLECTION_PREFIX = os.environ.get("QDRANT_COLLECTION_PREFIX", "niblit")

# ── Optional qdrant-client import ─────────────────────────────────────────────
# We import lazily so the module loads cleanly even when qdrant-client is absent.
try:
    from qdrant_client import QdrantClient  # type: ignore[import]
    from qdrant_client.models import (  # type: ignore[import]
        Distance,
        NamedSparseVector,
        NamedVector,
        PointStruct,
        SparseVector,
        VectorParams,
    )
    _QDRANT_AVAILABLE = True
except ImportError:
    _QDRANT_AVAILABLE = False
    QdrantClient = None  # type: ignore[assignment,misc]
    log.debug("qdrant-client not installed — HybridQdrantManager running in stub mode")

# ── Optional fastembed import (used by qdrant-client for local embeddings) ────
try:
    from fastembed import TextEmbedding, SparseTextEmbedding  # type: ignore[import]
    _FASTEMBED_AVAILABLE = True
except ImportError:
    _FASTEMBED_AVAILABLE = False
    log.debug("fastembed not installed — will attempt qdrant-client's built-in embedder")


# ══════════════════════════════════════════════════════════════════════════════
# Model registry
# ══════════════════════════════════════════════════════════════════════════════

# Each entry defines an inference provider that HybridQdrantManager can route to.
# "vector_name" is the named-vector key used in the multi-vector Qdrant collection.
# "dim" is the embedding dimensionality (used when creating collections).
# "distance" is the similarity metric appropriate for the model.
# "sparse" True → BM25-style sparse vector; False → dense float vector.

_MODEL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "colbert": {
        "model_id":    "answerdotai/answerai-colbert-small-v1",
        "vector_name": "colbert",
        "dim":         96,        # ColBERT Small V1 single-token projection dim
        "distance":    "Cosine",
        "sparse":      False,
        "description": "Deep semantic / code / RAG late-interaction retrieval",
    },
    "bm25": {
        "model_id":    "qdrant/bm25",
        "vector_name": "bm25",
        "dim":         0,         # sparse — no fixed dim
        "distance":    "Dot",
        "sparse":      True,
        "description": "Keyword / lexical BM25 fallback",
    },
    "e5": {
        "model_id":    "intfloat/multilingual-e5-small",
        "vector_name": "e5",
        "dim":         384,
        "distance":    "Cosine",
        "sparse":      False,
        "description": "Multilingual dense retrieval (100 languages, chat & general text)",
    },
}

_ALL_MODEL_KEYS = list(_MODEL_REGISTRY.keys())  # canonical ordering


# ══════════════════════════════════════════════════════════════════════════════
# Language / routing helpers
# ══════════════════════════════════════════════════════════════════════════════

def _contains_non_ascii(text: str) -> bool:
    """Return True if *text* contains characters outside the ASCII range."""
    try:
        text.encode("ascii")
        return False
    except UnicodeEncodeError:
        return True


def _normalize_text(text: str) -> str:
    """Normalize Unicode text before embedding.

    Uses ``unicodedata.normalize`` (NFC form) to canonicalise combining
    characters so that visually identical strings produce identical embeddings.
    Also strips leading/trailing whitespace.
    """
    return unicodedata.normalize("NFC", text).strip()


def _looks_like_code(text: str) -> bool:
    """Heuristic: does *text* look like source code?"""
    code_signals = ("def ", "class ", "import ", "return ", "function ", "const ",
                    "=>", "->", "::", "##", "//", "/*", "*/", "{", "}", ";")
    sample = text[:300]
    hits = sum(1 for s in code_signals if s in sample)
    return hits >= 2


def _is_long(text: str, threshold: int = 256) -> bool:
    """Return True when *text* exceeds *threshold* characters."""
    return len(text) > threshold


# ══════════════════════════════════════════════════════════════════════════════
# HybridQdrantManager
# ══════════════════════════════════════════════════════════════════════════════

class HybridQdrantManager:
    """
    Multi-model Qdrant inference manager.

    Maintains a single QdrantClient connection and routes document upserts /
    queries across up to four inference models.  All Qdrant API calls are
    wrapped in try/except so the class degrades gracefully when the cluster or
    the qdrant-client package is unavailable.

    Parameters
    ----------
    url:
        Qdrant cluster URL.  Defaults to ``QDRANT_URL`` env var or
        ``http://localhost:6333``.
    api_key:
        Optional API key.  Defaults to ``QDRANT_API_KEY`` env var.
    collection_prefix:
        String prepended to collection names.  Defaults to ``QDRANT_COLLECTION_PREFIX``
        env var or ``"niblit"``.
    """

    def __init__(
        self,
        url: str = _QDRANT_URL,
        api_key: Optional[str] = _QDRANT_API_KEY,
        collection_prefix: str = _COLLECTION_PREFIX,
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._prefix = collection_prefix
        self._lock = threading.Lock()

        # Per-model operation counters: {"model_key": {"upsert": int, "query": int}}
        self._stats: Dict[str, Dict[str, int]] = {
            k: {"upsert": 0, "query": 0} for k in _ALL_MODEL_KEYS
        }

        # Lazily initialised QdrantClient — None until first use
        self._client: Optional[Any] = None

        # Cache of already-created collection names to avoid redundant API calls
        self._known_collections: set = set()

        log.info(
            "[HybridQdrantManager] Initialised (url=%s, prefix=%s, qdrant_available=%s)",
            url, collection_prefix, _QDRANT_AVAILABLE,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _get_client(self) -> Optional[Any]:
        """Return (or lazily create) the QdrantClient.  Returns None on failure."""
        if not _QDRANT_AVAILABLE:
            return None
        if self._client is not None:
            return self._client
        try:
            kwargs: Dict[str, Any] = {"url": self._url}
            if self._api_key:
                kwargs["api_key"] = self._api_key
            self._client = QdrantClient(**kwargs)
            log.debug("[HybridQdrantManager] QdrantClient connected to %s", self._url)
        except Exception as exc:
            log.warning("[HybridQdrantManager] Failed to create QdrantClient: %s", exc)
            self._client = None
        return self._client

    def _prefixed(self, collection: str) -> str:
        """Return *collection* with the configured prefix applied once."""
        if collection.startswith(self._prefix + "_"):
            return collection
        return f"{self._prefix}_{collection}"

    def _ensure_collection(self, full_name: str, models: List[str]) -> bool:
        """
        Create *full_name* in Qdrant if it does not already exist.

        Builds a multi-vector collection with one named vector per model in
        *models*.  Sparse (BM25) vectors use ``sparse_vectors_config``; dense
        vectors are declared in ``vectors_config``.

        Returns True on success, False if Qdrant is unavailable or the call fails.
        """
        if full_name in self._known_collections:
            return True

        client = self._get_client()
        if client is None:
            return False

        try:
            # Check whether the collection already exists
            existing = [c.name for c in client.get_collections().collections]
            if full_name in existing:
                self._known_collections.add(full_name)
                return True

            # Build vectors_config for dense models
            dense_configs: Dict[str, Any] = {}
            sparse_configs: Dict[str, Any] = {}

            for key in models:
                spec = _MODEL_REGISTRY[key]
                if spec["sparse"]:
                    # BM25 sparse vector configuration
                    try:
                        from qdrant_client.models import SparseVectorParams  # type: ignore[import]
                        sparse_configs[spec["vector_name"]] = SparseVectorParams()
                    except ImportError:
                        log.debug("[HybridQdrantManager] SparseVectorParams unavailable; skipping BM25 config")
                else:
                    dist_map = {"Cosine": Distance.COSINE, "Dot": Distance.DOT, "Euclid": Distance.EUCLID}
                    dist = dist_map.get(spec["distance"], Distance.COSINE)
                    dense_configs[spec["vector_name"]] = VectorParams(size=spec["dim"], distance=dist)

            create_kwargs: Dict[str, Any] = {}
            if dense_configs:
                create_kwargs["vectors_config"] = dense_configs
            if sparse_configs:
                create_kwargs["sparse_vectors_config"] = sparse_configs

            client.create_collection(collection_name=full_name, **create_kwargs)
            self._known_collections.add(full_name)
            log.info("[HybridQdrantManager] Created collection '%s' with models %s", full_name, models)
            return True

        except Exception as exc:
            log.warning("[HybridQdrantManager] _ensure_collection('%s') failed: %s", full_name, exc)
            return False

    def _embed(self, model_key: str, text: str) -> Optional[Any]:
        """
        Produce an embedding for *text* using the model identified by *model_key*.

        Delegates to qdrant-client's built-in fastembed integration when
        available.  Returns the raw vector (list[float] or SparseVector) or
        None on failure.
        """
        spec = _MODEL_REGISTRY[model_key]
        model_id = spec["model_id"]

        if not _FASTEMBED_AVAILABLE:
            log.debug("[HybridQdrantManager] fastembed unavailable; cannot embed with %s", model_key)
            return None

        try:
            if spec["sparse"]:
                # BM25 sparse embedding via fastembed SparseTextEmbedding
                embedder = SparseTextEmbedding(model_name=model_id)
                result = list(embedder.embed([text]))[0]
                # fastembed returns an object with .indices and .values attributes
                return SparseVector(indices=list(result.indices), values=list(result.values))
            else:
                # Dense embedding via fastembed TextEmbedding
                embedder = TextEmbedding(model_name=model_id)
                result = list(embedder.embed([text]))[0]
                return list(result)
        except Exception as exc:
            log.warning("[HybridQdrantManager] Embedding failed for model '%s': %s", model_key, exc)
            return None

    # ── Model routing ─────────────────────────────────────────────────────────

    def select_models(
        self,
        text: str,
        context: Optional[str] = None,
    ) -> List[str]:
        """
        Return the list of model keys best suited for *text*.

        Routing rules (applied in priority order):
        1. Non-ASCII / multilingual content       → always include ``e5``
        2. Source code signals                    → always include ``colbert``
        3. Long text (>256 chars) for deep search → always include ``colbert``
        4. Short text / chat                      → always include ``e5``
        5. BM25 included for all cases as lexical safety net

        The returned list always contains at least one model.  ``context``
        is an optional string hint (e.g. ``"code"``, ``"chat"``) that can
        override the automatic detection.
        """
        selected: List[str] = []

        ctx = (context or "").lower()

        if ctx == "code" or _looks_like_code(text):
            selected.append("colbert")

        if ctx == "multilingual" or _contains_non_ascii(text):
            selected.append("e5")

        if ctx == "chat" or (not _is_long(text) and "colbert" not in selected and "e5" not in selected):
            selected.append("e5")

        if _is_long(text) and "colbert" not in selected:
            selected.append("colbert")

        # Always add BM25 as lexical fallback
        selected.append("bm25")

        # Deduplicate while preserving order, then return
        seen: set = set()
        ordered: List[str] = []
        for k in selected:
            if k not in seen:
                seen.add(k)
                ordered.append(k)

        # Guarantee at least e5 as a fallback if everything else was skipped
        if not ordered:
            ordered = ["e5", "bm25"]

        log.debug("[HybridQdrantManager] select_models → %s (len=%d, context=%s)", ordered, len(text), context)
        return ordered

    # ── Core operations ───────────────────────────────────────────────────────

    def upsert(
        self,
        text: str,
        payload: Dict[str, Any],
        collection: str,
        models: Optional[List[str]] = None,
        doc_id: Optional[str] = None,
    ) -> bool:
        """
        Upsert *text* into *collection* using each model in *models*.

        Creates the collection in Qdrant if it does not already exist.  If
        qdrant-client is unavailable the call returns False without raising.

        Parameters
        ----------
        text:
            The document text to embed and store.
        payload:
            Arbitrary metadata attached to the Qdrant point.
        collection:
            Logical collection name (prefix is applied automatically).
        models:
            Subset of model keys to use.  When None, ``select_models`` is
            called automatically.
        doc_id:
            Optional stable ID for the Qdrant point.  Falls back to a
            hash of *text* when not provided.

        Returns
        -------
        bool
            True if at least one model upserted successfully.
        """
        if models is None:
            models = self.select_models(text)

        # Validate model keys
        models = [m for m in models if m in _MODEL_REGISTRY]
        if not models:
            log.warning("[HybridQdrantManager] upsert called with no valid models")
            return False

        # Normalise text before embedding so unicode variants hash/embed consistently
        text = _normalize_text(text)
        full_name = self._prefixed(collection)

        # Ensure collection exists for the requested models
        if not self._ensure_collection(full_name, models):
            log.warning("[HybridQdrantManager] upsert: collection not available (%s)", full_name)
            return False

        client = self._get_client()
        if client is None:
            return False

        # Derive a stable integer point ID from doc_id or text hash.
        # We use SHA-256 (not Python's hash()) to guarantee determinism
        # across processes and restarts regardless of PYTHONHASHSEED.
        seed = doc_id if doc_id is not None else text
        stable_hash = hashlib.sha256(seed.encode("utf-8", errors="replace")).digest()
        # Use the first 8 bytes as a uint64 within Qdrant's unsigned ID range
        point_id = int.from_bytes(stable_hash[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF

        # Build the multi-vector dict: {vector_name: embedding}
        # Dense vectors → NamedVector; sparse vectors → NamedSparseVector.
        # Using the typed wrappers helps qdrant-client infer the correct wire
        # format when the collection uses mixed (dense + sparse) vector schemas.
        vectors: Dict[str, Any] = {}
        success_count = 0

        for model_key in models:
            spec = _MODEL_REGISTRY[model_key]
            vector = self._embed(model_key, text)
            if vector is None:
                log.debug("[HybridQdrantManager] Skipping model '%s' (no embedding)", model_key)
                continue
            if spec.get("sparse"):
                # Sparse vector: list of (index, value) pairs or a SparseVector
                if _QDRANT_AVAILABLE and isinstance(vector, dict):
                    vectors[spec["vector_name"]] = NamedSparseVector(
                        name=spec["vector_name"], vector=vector
                    )
                else:
                    vectors[spec["vector_name"]] = vector
            else:
                # Dense vector: wrap in NamedVector for explicit named-vector upserts
                if _QDRANT_AVAILABLE and isinstance(vector, list):
                    vectors[spec["vector_name"]] = NamedVector(
                        name=spec["vector_name"], vector=vector
                    )
                else:
                    vectors[spec["vector_name"]] = vector

        if not vectors:
            log.warning(
                "[HybridQdrantManager] upsert: no embeddings produced for text (len=%d)", len(text)
            )
            return False

        try:
            # Unwrap NamedVector/NamedSparseVector back to plain dict for PointStruct
            # (some qdrant-client versions don't accept Named* in the vector kwarg).
            plain_vectors = {
                k: (v.vector if hasattr(v, "vector") else v)
                for k, v in vectors.items()
            }
            point = PointStruct(id=point_id, vector=plain_vectors, payload={**payload, "_text": text[:1000]})
            t0 = time.time()
            client.upsert(collection_name=full_name, points=[point])
            latency_ms = round((time.time() - t0) * 1000, 1)
            success_count = len(plain_vectors)
            log.debug(
                "[HybridQdrantManager] Upserted point %d into '%s' with %d vectors (%.1fms)",
                point_id, full_name, success_count, latency_ms,
            )
        except Exception as exc:
            log.warning("[HybridQdrantManager] upsert to '%s' failed: %s", full_name, exc)
            return False

        # Increment per-model stats for each model whose vector was actually embedded
        with self._lock:
            for model_key in models:
                spec = _MODEL_REGISTRY[model_key]
                if spec["vector_name"] in vectors:
                    self._stats[model_key]["upsert"] += 1

        return success_count > 0

    def query(
        self,
        text: str,
        collection: str,
        top_k: int = 5,
        models: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Query *collection* with *text* using each model in *models*.

        Results from all models are merged, deduplicated by point ID (keeping
        the highest score per ID), and sorted by score descending.

        Parameters
        ----------
        text:
            The query string.
        collection:
            Logical collection name.
        top_k:
            Maximum number of results to return.
        models:
            Subset of model keys to query.  When None, ``select_models``
            is called automatically.

        Returns
        -------
        list of dict
            Each dict contains at minimum ``id``, ``score``, ``payload``,
            and ``model`` (the model that produced the top score for that ID).
        """
        if models is None:
            models = self.select_models(text)

        models = [m for m in models if m in _MODEL_REGISTRY]
        if not models:
            return []

        full_name = self._prefixed(collection)
        client = self._get_client()
        if client is None:
            return []

        # Accumulate raw results keyed by point ID → best (score, result_dict)
        best: Dict[int, Tuple[float, Dict[str, Any]]] = {}

        for model_key in models:
            spec = _MODEL_REGISTRY[model_key]
            vector = self._embed(model_key, text)
            if vector is None:
                log.debug("[HybridQdrantManager] query: skipping model '%s' (no embedding)", model_key)
                continue

            try:
                # Use query_points with named vector for multi-vector collections.
                # Both dense and sparse vectors use the same query_points API;
                # qdrant-client infers the vector type from the collection schema.
                results = client.query_points(
                    collection_name=full_name,
                    query=vector,
                    using=spec["vector_name"],
                    limit=top_k,
                ).points

                with self._lock:
                    self._stats[model_key]["query"] += 1

                for hit in results:
                    hit_id = hit.id
                    hit_score = hit.score if hasattr(hit, "score") else 0.0
                    if hit_id not in best or hit_score > best[hit_id][0]:
                        best[hit_id] = (
                            hit_score,
                            {
                                "id": hit_id,
                                "score": hit_score,
                                "payload": hit.payload or {},
                                "model": model_key,
                            },
                        )

            except Exception as exc:
                log.warning(
                    "[HybridQdrantManager] query model '%s' on '%s' failed: %s",
                    model_key, full_name, exc,
                )

        # Sort by score descending, return top_k
        ranked = sorted(best.values(), key=lambda t: t[0], reverse=True)
        return [r for _, r in ranked[:top_k]]

    def upsert_knowledge_item(self, item: Dict[str, Any]) -> bool:
        """
        Convenience wrapper for dict-based knowledge items.

        Expects *item* to contain:
          - ``id``         (str)  — stable document identifier
          - ``text``       (str)  — document text to embed
          - ``payload``    (dict) — metadata to store alongside the vector
          - ``collection`` (str)  — target collection name

        Optional keys:
          - ``models``     (list) — override model selection

        Returns True if upsert succeeded for at least one model.
        """
        doc_id = str(item.get("id", ""))
        text = str(item.get("text", ""))
        payload = item.get("payload") or {}
        collection = str(item.get("collection", "default"))
        models = item.get("models")  # may be None → auto-select

        if not text.strip():
            log.warning("[HybridQdrantManager] upsert_knowledge_item: empty text for id='%s'", doc_id)
            return False

        return self.upsert(
            text=text,
            payload={**payload, "_id": doc_id},
            collection=collection,
            models=models,
            doc_id=doc_id if doc_id else None,
        )

    # ── Statistics ────────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Dict[str, int]]:
        """
        Return per-model operation counters.

        Returns
        -------
        dict
            ``{model_key: {"upsert": int, "query": int}}`` for each model.
        """
        with self._lock:
            return {k: dict(v) for k, v in self._stats.items()}

    def model_stats(self) -> str:
        """Return a formatted multi-line string report of per-model stats."""
        lines = [
            "── HybridQdrantManager Model Stats ──",
            f"  URL:    {self._url}",
            f"  Prefix: {self._prefix}",
            f"  Qdrant available: {_QDRANT_AVAILABLE}",
            "",
        ]
        stats = self.get_stats()
        for key in _ALL_MODEL_KEYS:
            spec = _MODEL_REGISTRY[key]
            s = stats.get(key, {"upsert": 0, "query": 0})
            lines.append(
                f"  [{key:8s}] upserts={s['upsert']:4d}  queries={s['query']:4d}"
                f"  — {spec['description']}"
            )
        lines.append("")
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════════
# Module-level singleton
# ══════════════════════════════════════════════════════════════════════════════

_manager_instance: Optional[HybridQdrantManager] = None
_manager_lock = threading.Lock()


def get_hybrid_manager(
    url: str = _QDRANT_URL,
    api_key: Optional[str] = _QDRANT_API_KEY,
    collection_prefix: str = _COLLECTION_PREFIX,
) -> HybridQdrantManager:
    """
    Return the process-wide :class:`HybridQdrantManager` singleton.

    The first call creates the instance using the supplied parameters (or
    environment variable defaults).  Subsequent calls ignore the parameters and
    return the already-created instance.

    Parameters
    ----------
    url:
        Qdrant cluster URL.
    api_key:
        Optional API key.
    collection_prefix:
        Collection name prefix.
    """
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = HybridQdrantManager(
                    url=url,
                    api_key=api_key,
                    collection_prefix=collection_prefix,
                )
    return _manager_instance
