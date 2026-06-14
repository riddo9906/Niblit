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
    EMBEDDING_MODEL=intfloat/multilingual-e5-small

    # Self-hosted Qdrant (Docker)
    # docker run -p 6333:6333 qdrant/qdrant
    QDRANT_URL=https://your-self-hosted-qdrant-url

Usage::

    from modules.vector_store import VectorStore
    vs = VectorStore()
    vs.add("unique-id-1", "Python decorators allow wrapping functions...")
    results = vs.search("decorator pattern", top_k=3)

See SETUP.md for full setup instructions.
"""

import hashlib
import io
import logging
import os
import sys
import threading
import time
import warnings
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from modules.config.qdrant_config import QdrantConfig

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


_EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "intfloat/multilingual-e5-small")
# Default dim for intfloat/multilingual-e5-small. Override with EMBEDDING_DIM
# when the active embedding source outputs a different vector size.
_EMBEDDING_DIM = int(os.getenv("EMBEDDING_DIM", "384"))
_MAX_STORED_ITEMS = 10_000   # in-memory/FAISS safety cap
# Maximum characters stored as ``text`` in the Qdrant payload.  Using 6000
# characters ensures rich context is preserved without hitting Qdrant's per-
# document payload size limits on typical cloud configurations.
_QDRANT_TEXT_MAX_CHARS = int(os.getenv("QDRANT_TEXT_MAX_CHARS", "6000"))

# ── Profile / backend selection ───────────────────────────────────────────────
# NIBLIT_PROFILE:              android | core | full  (default: core)
# NIBLIT_EMBEDDINGS_BACKEND:   sentence_transformers | remote | none  (default: auto)
# NIBLIT_VECTOR_BACKEND:       numpy | faiss | qdrant  (default: auto)
_NIBLIT_PROFILE = os.getenv("NIBLIT_PROFILE", "core").lower()
_NIBLIT_EMBEDDINGS_BACKEND = os.getenv("NIBLIT_EMBEDDINGS_BACKEND", "auto").lower()
_NIBLIT_VECTOR_BACKEND = os.getenv("NIBLIT_VECTOR_BACKEND", "auto").lower()

# Emit a one-time startup banner so operators know which backends are active.
def _log_backend_selection() -> None:
    """Log which vector / embedding backends are active at process startup."""
    if not _ST_AVAILABLE:
        log.info(
            "[VectorStore] sentence-transformers not installed; using %s embeddings backend "
            "(set NIBLIT_EMBEDDINGS_BACKEND=remote to use a remote HTTP endpoint, "
            "or install sentence-transformers for local embeddings)",
            "remote" if _NIBLIT_EMBEDDINGS_BACKEND == "remote" else "none",
        )
    else:
        log.info("[VectorStore] sentence-transformers available (local embeddings enabled)")

    if not _FAISS_AVAILABLE:
        log.info("[VectorStore] FAISS not installed; using numpy cosine-similarity backend")
    else:
        log.info("[VectorStore] FAISS available (local ANN index enabled)")

    log.info("[VectorStore] NIBLIT_PROFILE=%s", _NIBLIT_PROFILE)


_log_backend_selection()


# ─────────────────────────────────────────────────────────────────────────────
# Embedding helper — singleton model cache
# ─────────────────────────────────────────────────────────────────────────────

# Module-level cache so ALL VectorStore instances share one loaded model per
# model name.  This prevents the repeated "BertModel LOAD REPORT" and tqdm
# "Loading weights" banners that previously flooded the console when multiple
# VectorStore instances were created (e.g. by niblit_memory, niblit_core,
# research agents, etc.).
_model_cache: Dict[str, Any] = {}
_model_cache_lock = threading.Lock()
_POSITION_IDS_COMPAT_LOGGED = False


@dataclass(frozen=True)
class EmbeddingRuntimeConfig:
    """Governed embedding runtime policy."""

    model_name: str = _EMBEDDING_MODEL_NAME
    memory_relevance_weight: float = 0.45
    reflection_weight: float = 0.20
    replay_weight: float = 0.15
    coherence_factor: float = 0.15
    decay_influence: float = 0.05
    cache_enabled: bool = True
    cache_ttl_seconds: int = 15

    @staticmethod
    def _clamp(value: Any, default: float) -> float:
        try:
            return max(0.0, min(1.0, float(value)))
        except Exception:
            return default

    @classmethod
    def from_env(cls) -> "EmbeddingRuntimeConfig":
        return cls(
            model_name=os.getenv("EMBEDDING_MODEL", _EMBEDDING_MODEL_NAME),
            memory_relevance_weight=cls._clamp(os.getenv("NIBLIT_EMBED_MEMORY_WEIGHT", "0.45"), 0.45),
            reflection_weight=cls._clamp(os.getenv("NIBLIT_EMBED_REFLECTION_WEIGHT", "0.20"), 0.20),
            replay_weight=cls._clamp(os.getenv("NIBLIT_EMBED_REPLAY_WEIGHT", "0.15"), 0.15),
            coherence_factor=cls._clamp(os.getenv("NIBLIT_EMBED_COHERENCE_FACTOR", "0.15"), 0.15),
            decay_influence=cls._clamp(os.getenv("NIBLIT_EMBED_DECAY_INFLUENCE", "0.05"), 0.05),
            cache_enabled=os.getenv("NIBLIT_EMBED_QUERY_CACHE", "1").strip().lower() not in {"0", "false", "no"},
            cache_ttl_seconds=max(1, int(os.getenv("NIBLIT_EMBED_QUERY_CACHE_TTL", "15"))),
        )

    def govern_score(self, base_score: float, metadata: Optional[Dict[str, Any]] = None) -> float:
        meta = metadata or {}
        memory_relevance = self._clamp(meta.get("memory_relevance", base_score), base_score)
        reflection = self._clamp(meta.get("reflection_weight", meta.get("reflection_score", 0.0)), 0.0)
        replay = self._clamp(meta.get("replay_weight", meta.get("replay_score", 0.0)), 0.0)
        coherence = self._clamp(meta.get("coherence_factor", meta.get("coherence_score", 1.0)), 1.0)
        decay = self._clamp(meta.get("decay_influence", meta.get("confidence_decay", 0.0)), 0.0)
        score = (
            self.memory_relevance_weight * memory_relevance
            + self.reflection_weight * reflection
            + self.replay_weight * replay
            + self.coherence_factor * coherence
        )
        score -= self.decay_influence * decay
        return round(max(0.0, min(1.0, score)), 6)


def _push_to_notification_queue(msg: str) -> None:
    """Best-effort push to the notification queue (no-op if unavailable)."""
    try:
        from core.notification_queue import notif_queue
        notif_queue.push(msg)
    except Exception:
        pass


def get_embedding_model_cache() -> Dict[str, Any]:
    """Return the process-wide embedding model cache (public API).

    Other modules (e.g. ``dynamic_topic_manager``) should call this instead
    of importing the private ``_model_cache`` directly.
    """
    return _model_cache


def load_sentence_transformer(model_name: str = _EMBEDDING_MODEL_NAME) -> Any:
    """Load a SentenceTransformer model via the singleton cache (public API).

    Returns the cached model if already loaded; otherwise loads it with
    full stdout/stderr capture and notification-queue routing.

    Other modules should use this instead of importing the private
    ``_load_sentence_transformer`` directly.
    """
    if model_name in _model_cache:
        return _model_cache[model_name]
    with _model_cache_lock:
        if model_name in _model_cache:
            return _model_cache[model_name]
        model = _load_sentence_transformer(model_name)
        _model_cache[model_name] = model
        return model


def _load_sentence_transformer(model_name: str) -> Any:
    """Load a SentenceTransformer model, capturing all console output.

    The safetensors/transformers loader *prints* a "LOAD REPORT" table to
    **stdout** when unexpected keys like ``embeddings.position_ids`` are
    found.  The ``tqdm`` progress bar ("Loading weights: 100%|…") goes to
    **stderr**.  Both are benign — newer transformers dropped
    ``position_ids`` from the state-dict but the intfloat/multilingual-e5-small
    checkpoint still ships it.

    This function:
    1. Redirects **both** stdout *and* stderr during model construction.
    2. Suppresses the ``FutureWarning`` about ``position_ids``.
    3. Routes captured output to the notification queue (viewable via the
       ``notifications`` command) and to the DEBUG logger.
    4. Sets ``SAFETENSORS_LOG_LEVEL=error`` so safetensors itself stays
       silent on benign key mismatches.
    """
    # Tell safetensors to only log errors (suppresses the LOAD REPORT
    # table and the "UNEXPECTED" advisory for position_ids).
    _prev_st_log = os.environ.get("SAFETENSORS_LOG_LEVEL")
    os.environ["SAFETENSORS_LOG_LEVEL"] = "error"

    # Bound the per-request HTTP timeout for the HuggingFace Hub download.
    # huggingface_hub honours HF_HUB_DOWNLOAD_TIMEOUT (seconds, float).
    # We only set it when no caller has already configured it, so that an
    # explicit environment override (e.g. NIBLIT_HF_HUB_DOWNLOAD_TIMEOUT=120)
    # is still respected.
    _timeout_env = "HF_HUB_DOWNLOAD_TIMEOUT"
    _prev_hf_timeout = os.environ.get(_timeout_env)
    if _prev_hf_timeout is None:
        _default_hf_timeout = os.environ.get("NIBLIT_HF_HUB_DOWNLOAD_TIMEOUT", "60")
        os.environ[_timeout_env] = _default_hf_timeout

    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    try:
        sys.stdout = captured_stdout
        sys.stderr = captured_stderr
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r".*position_ids.*",
                category=FutureWarning,
            )
            # Suppress the tqdm-related DeprecationWarning / RuntimeWarning
            warnings.filterwarnings(
                "ignore",
                category=DeprecationWarning,
            )
            model = _SentenceTransformer(model_name)
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr
        # Restore the previous SAFETENSORS_LOG_LEVEL value
        if _prev_st_log is None:
            os.environ.pop("SAFETENSORS_LOG_LEVEL", None)
        else:
            os.environ["SAFETENSORS_LOG_LEVEL"] = _prev_st_log
        # Restore HF_HUB_DOWNLOAD_TIMEOUT
        if _prev_hf_timeout is None:
            os.environ.pop(_timeout_env, None)
        else:
            os.environ[_timeout_env] = _prev_hf_timeout

    # Gather any captured output — route to DEBUG logger and notification
    # queue so it is only visible on demand (``notifications`` command).
    banner_parts = []
    stdout_text = captured_stdout.getvalue().strip()
    stderr_text = captured_stderr.getvalue().strip()
    if stdout_text:
        banner_parts.append(stdout_text)
    if stderr_text:
        banner_parts.append(stderr_text)

    global _POSITION_IDS_COMPAT_LOGGED
    if banner_parts:
        combined = "\n".join(banner_parts)
        log.debug("[VectorStore] Embedding model load report:\n%s", combined)
        _push_to_notification_queue(
            f"[VectorStore] Embedding model '{model_name}' loaded "
            f"(load report captured — this is informational only)"
        )
    if not _POSITION_IDS_COMPAT_LOGGED and model_name == "intfloat/multilingual-e5-small":
        _POSITION_IDS_COMPAT_LOGGED = True
        log.info(
            "[VectorStore] Compatibility note: embeddings.position_ids UNEXPECTED is a non-fatal "
            "artifact for intfloat/multilingual-e5-small and is ignored."
        )

    return model


class _EmbeddingService:
    """Lazy-loaded sentence-transformer embedding service.

    All instances sharing the same *model_name* use a **single** loaded
    model via the module-level ``_model_cache``, so the heavyweight
    download/load (and its console output) happens at most once per
    process, regardless of how many ``VectorStore`` objects are created.
    """

    def __init__(self, model_name: str = _EMBEDDING_MODEL_NAME) -> None:
        self.model_name = model_name

    def is_available(self) -> bool:
        return _ST_AVAILABLE

    @property
    def _model(self) -> Optional[Any]:
        return _model_cache.get(self.model_name)

    def _load(self) -> None:
        if self.model_name in _model_cache:
            return
        if not _ST_AVAILABLE:
            return
        with _model_cache_lock:
            # Double-check after acquiring the lock
            if self.model_name in _model_cache:
                return
            try:
                model = _load_sentence_transformer(self.model_name)
                _model_cache[self.model_name] = model
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
        collection: Optional[str] = None,
        embedding_model: str = _EMBEDDING_MODEL_NAME,
        qdrant_url: Optional[str] = None,
        qdrant_api_key: Optional[str] = None,
    ) -> None:
        qdrant_config = QdrantConfig.load()
        self.collection = collection or qdrant_config.collection
        self._embedder = _EmbeddingService(embedding_model)
        self._qdrant_url: str = (
            qdrant_url if qdrant_url is not None
            else qdrant_config.url
        )
        self._qdrant_api_key: str = (
            qdrant_api_key if qdrant_api_key is not None
            else (qdrant_config.api_key or "")
        )

        self._backend_name: str = "memory"
        self._qdrant_client: Optional[Any] = None
        self._qdrant_collection_dim: Optional[int] = None
        self._qdrant_dim_mismatch_logged: bool = False
        self._faiss_index: Optional[Any] = None
        self._faiss_items: List[Dict[str, Any]] = []   # parallel list of {id, text, vector}
        self._memory_backend = _InMemoryBackend()
        self._effective_embedding_dim: Optional[int] = None
        self._effective_dim_fallback_logged: bool = False
        self._embedding_runtime = EmbeddingRuntimeConfig.from_env()
        self._search_cache: Dict[str, Dict[str, Any]] = {}

        self._init_backend()

    def _get_effective_embedding_dim(self) -> int:
        """Return embedding dimensionality used by the active embedding model."""
        if self._effective_embedding_dim is not None:
            return self._effective_embedding_dim
        dim = _EMBEDDING_DIM
        try:
            probe = self._embedder.encode("dimension probe")
            if probe is not None and len(probe) > 0:
                dim = len(probe)
            elif not self._effective_dim_fallback_logged:
                log.warning(
                    "[VectorStore] Could not probe embedding dimension from model; "
                    "falling back to EMBEDDING_DIM=%d",
                    _EMBEDDING_DIM,
                )
                self._effective_dim_fallback_logged = True
        except Exception as exc:
            if not self._effective_dim_fallback_logged:
                log.warning(
                    "[VectorStore] Embedding dimension probe failed (%s); "
                    "falling back to EMBEDDING_DIM=%d",
                    exc,
                    _EMBEDDING_DIM,
                )
                self._effective_dim_fallback_logged = True
        self._effective_embedding_dim = dim
        return dim

    @staticmethod
    def _extract_qdrant_collection_dim(info: Any) -> Optional[int]:
        """Best-effort extraction of dense vector dimension from Qdrant collection info."""
        try:
            params = getattr(info, "config", None)
            params = getattr(params, "params", params)
            vectors = getattr(params, "vectors", None)
            if vectors is None and isinstance(params, dict):
                vectors = params.get("vectors")

            # Single unnamed dense vector
            size = getattr(vectors, "size", None)
            if isinstance(size, int):
                return size
            if isinstance(vectors, dict) and "size" in vectors:
                try:
                    return int(vectors["size"])
                except Exception:
                    pass

            # Named vectors: return first dense vector size
            if isinstance(vectors, dict):
                for cfg in vectors.values():
                    cfg_size = getattr(cfg, "size", None)
                    if isinstance(cfg_size, int):
                        return cfg_size
                    if isinstance(cfg, dict) and "size" in cfg:
                        try:
                            return int(cfg["size"])
                        except Exception:
                            continue
        except Exception:
            return None
        return None

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
            local_dim = self._get_effective_embedding_dim()
            # Ensure collection exists
            existing = [c.name for c in self._qdrant_client.get_collections().collections]
            if self.collection not in existing:
                self._qdrant_client.create_collection(
                    collection_name=self.collection,
                    vectors_config=_VectorParams(
                        size=local_dim, distance=_Distance.COSINE
                    ),
                )
                log.info("[VectorStore] Created Qdrant collection '%s'", self.collection)
                self._qdrant_collection_dim = local_dim
            else:
                info = self._qdrant_client.get_collection(self.collection)
                remote_dim = self._extract_qdrant_collection_dim(info)
                self._qdrant_collection_dim = remote_dim
                if remote_dim is not None and remote_dim != local_dim:
                    raise ValueError(
                        "Qdrant collection dimension mismatch for "
                        f"'{self.collection}': remote={remote_dim}, local={local_dim}. "
                        "Set EMBEDDING_MODEL/EMBEDDING_DIM to match, or use a separate collection."
                    )
            self._backend_name = "qdrant"
            log.info("[VectorStore] Qdrant backend initialised (%s)", self._qdrant_url)
        except Exception as exc:
            log.debug("[VectorStore] Qdrant init failed (%s) — falling back", exc)
            self._qdrant_client = None
            if _FAISS_AVAILABLE and _NP_AVAILABLE:
                self._init_faiss()

    def _init_faiss(self) -> None:
        try:
            dim = self._get_effective_embedding_dim()
            self._faiss_index = _faiss.IndexFlatIP(dim)  # inner-product
            self._backend_name = "faiss"
            log.info("[VectorStore] FAISS backend initialised (dim=%d)", dim)
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

    def add(self, doc_id: str, text: str, topic: str = "") -> bool:
        """
        Store a text document.

        Args:
            doc_id:  Unique identifier for this document.
            text:    Text content to embed and store.  Stored verbatim in the
                     payload up to ``_QDRANT_TEXT_MAX_CHARS`` characters.
            topic:   Short human-readable topic description (≤ 120 chars).
                     Stored as ``topic`` in the payload.  Callers should use
                     :class:`~modules.qdrant_tools.TopicSummariser` to generate
                     this value.  Defaults to the first 80 chars of *text*.

        Returns:
            True on success, False on failure.
        """
        # Derive a fallback topic from the text when none is supplied
        effective_topic = topic.strip() if topic.strip() else text[:80].split("\n")[0].strip()
        vector = self._embedder.encode(text)

        if self._backend_name == "qdrant" and self._qdrant_client is not None:
            return self._add_qdrant(doc_id, text, vector, effective_topic)
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
        cache_key = f"{query}\x00{top_k}\x00{self._backend_name}"
        now = time.time()
        if self._embedding_runtime.cache_enabled:
            cached = self._search_cache.get(cache_key)
            if cached and (now - float(cached.get("ts", 0.0))) <= self._embedding_runtime.cache_ttl_seconds:
                return list(cached.get("results", []))

        vector = self._embedder.encode(query)

        if self._backend_name == "qdrant" and self._qdrant_client is not None:
            results = self._search_qdrant(vector, query, top_k)
        elif self._backend_name == "faiss" and self._faiss_index is not None:
            results = self._search_faiss(vector, query, top_k)
        else:
            results = self._memory_backend.search(vector, query, top_k)

        governed: List[Dict[str, Any]] = []
        for item in results:
            base_score = max(0.0, min(1.0, float(item.get("score", 0.0))))
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            item["score"] = self._embedding_runtime.govern_score(base_score, metadata)
            governed.append(item)
        governed.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
        if self._embedding_runtime.cache_enabled:
            self._search_cache[cache_key] = {"ts": now, "results": list(governed[:top_k])}
        return governed[:top_k]

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
        self, doc_id: str, text: str, vector: Optional[List[float]], topic: str = ""
    ) -> bool:
        if vector is None:
            return False
        if self._qdrant_collection_dim is not None and len(vector) != self._qdrant_collection_dim:
            if not self._qdrant_dim_mismatch_logged:
                log.warning(
                    "[VectorStore] Qdrant upsert skipped: embedding dimension mismatch "
                    "(collection=%d, vector=%d)",
                    self._qdrant_collection_dim,
                    len(vector),
                )
                self._qdrant_dim_mismatch_logged = True
            return False
        try:
            # Use a stable integer ID derived from the doc_id string.
            # The integer point ID is the sole unique identifier — we do NOT
            # store the topic-derived doc_id string inside the payload so that
            # payload fields always contain human-readable text, never opaque IDs.
            int_id = int(hashlib.md5(doc_id.encode()).hexdigest(), 16) % (2**63)
            # Store the full text (up to _QDRANT_TEXT_MAX_CHARS) and a short
            # topic description.  No topic_id or slug field is persisted.
            payload = {
                "text": text[:_QDRANT_TEXT_MAX_CHARS],
                "topic": topic[:120] if topic else text[:80].split("\n")[0].strip(),
            }
            self._qdrant_client.upsert(
                collection_name=self.collection,
                points=[_PointStruct(id=int_id, vector=vector, payload=payload)],
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

            # Replace existing document with same ID (dedup/upsert semantics)
            existing_idx = next(
                (i for i, item in enumerate(self._faiss_items) if item.get("id") == doc_id),
                -1,
            )
            if existing_idx >= 0:
                self._faiss_items[existing_idx] = {"id": doc_id, "text": text, "vector": vector}
                self._rebuild_faiss_index()
                return True

            if self._faiss_index.ntotal >= _MAX_STORED_ITEMS and self._faiss_items:
                log.debug("[VectorStore/FAISS] capacity reached, dropping oldest")
                self._faiss_items.pop(0)
                # FAISS IndexFlatIP doesn't support removal; rebuild.
                self._rebuild_faiss_index()

            vec_np = np.array([vector], dtype="float32")
            self._faiss_index.add(vec_np)
            self._faiss_items.append({"id": doc_id, "text": text, "vector": vector})
            return True
        except Exception as exc:
            log.debug("[VectorStore/FAISS] add failed: %s", exc)
            return False

    def _rebuild_faiss_index(self) -> None:
        """Rebuild FAISS index from ``_faiss_items`` (used for removals/replacements)."""
        if not _NP_AVAILABLE or self._faiss_index is None:
            return
        try:
            import numpy as np
            vecs: List[List[float]] = []
            rebuilt_items: List[Dict[str, Any]] = []
            for item in self._faiss_items:
                v = item.get("vector")
                if v is None:
                    v = self._embedder.encode(item.get("text", ""))
                if v is None:
                    continue
                item["vector"] = v
                rebuilt_items.append(item)
                vecs.append(v)
            self._faiss_items = rebuilt_items
            self._faiss_index.reset()
            if vecs:
                self._faiss_index.add(np.array(vecs, dtype="float32"))
        except Exception as exc:
            log.debug("[VectorStore/FAISS] rebuild failed: %s", exc)

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
                    "id": str(h.id),
                    "text": h.payload.get("text", "") if h.payload else "",
                    "topic": h.payload.get("topic", "") if h.payload else "",
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
        config = QdrantConfig.load()
        url = qdrant_url or config.url
        api_key = config.api_key or ""

        self._primary = None
        try:
            from niblit_memory import FusedMemoryPrimary  # type: ignore[import]
            self._primary = FusedMemoryPrimary(
                sqlite_path=sqlite_path,
                collection_name=collection_name,
                qdrant_url=url,
                qdrant_api_key=api_key,
            )
        except Exception as exc:
            log.debug("[FusedStorage] FusedMemoryPrimary unavailable: %s", exc)
            # Minimal fallback: in-memory dict + VectorStore
            self._records_fallback: dict = {}
            self._vs_fallback = VectorStore(
                collection=collection_name or config.collection,
                qdrant_url=url,
                qdrant_api_key=api_key,
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


if __name__ == "__main__":
    print('Running vector_store.py')
