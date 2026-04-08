"""KnowledgeAPI — unified knowledge store for the civilisation ecosystem.

Usage example::

    from civilization.knowledge_ecosystem import VectorMemory, GraphMemory, EmbeddingService
    api = KnowledgeAPI(VectorMemory(), GraphMemory(), EmbeddingService())
    key = api.store_knowledge("Transformers revolutionised NLP.", tags=["nlp"])
    results = api.search_knowledge("NLP", top_k=5)
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

log = logging.getLogger("CivilizationKnowledgeAPI")


class KnowledgeAPI:
    """Combines vector memory, graph memory, and embeddings for knowledge management.

    Args:
        vector_memory: VectorMemory instance.
        graph_memory: GraphMemory instance.
        embedding_service: EmbeddingService instance.
    """

    def __init__(
        self,
        vector_memory: Any,
        graph_memory: Any,
        embedding_service: Any,
    ) -> None:
        self._vectors = vector_memory
        self._graph = graph_memory
        self._embedder = embedding_service
        self._metadata: Dict[str, Dict[str, Any]] = {}

    # ── public API ──

    def store_knowledge(
        self, content: str, tags: Optional[List[str]] = None
    ) -> str:
        """Embed and store *content*; return its key."""
        key = str(uuid.uuid4())
        vec = self._embedder.encode(content)
        self._vectors.store(key, vec, {"content": content, "tags": tags or []})
        self._metadata[key] = {
            "key": key,
            "content": content,
            "tags": tags or [],
            "stored_at": time.time(),
        }
        log.info("KnowledgeAPI: stored key %s", key)
        return key

    def search_knowledge(
        self, query: str, top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Return top-*k* knowledge items similar to *query*."""
        query_vec = self._embedder.encode(query)
        results = self._vectors.recall(query_vec, top_k=top_k)
        enriched: List[Dict[str, Any]] = []
        for r in results:
            meta = self._metadata.get(r["key"], {})
            enriched.append({**r, **meta})
        return enriched

    def get_knowledge(self, key: str) -> Optional[Dict[str, Any]]:
        """Return metadata for *key* or None."""
        return self._metadata.get(key)

    def delete_knowledge(self, key: str) -> bool:
        """Delete *key* from storage; return True if found."""
        if key in self._metadata:
            self._vectors.forget(key)
            self._metadata.pop(key)
            log.info("KnowledgeAPI: deleted %s", key)
            return True
        return False

    def vector_count(self) -> int:
        """Return number of vectors currently stored in VectorMemory."""
        return self._vectors.size()
