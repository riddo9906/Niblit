"""VectorStore — pure-Python cosine-similarity vector store.

No faiss or other external dependencies required.

Usage example::

    store = VectorStore()
    store.add("doc1", [0.1, 0.2, 0.3])
    results = store.search([0.1, 0.2, 0.3], top_k=3)
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

log = logging.getLogger("VectorStore")


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


class VectorStore:
    """In-memory vector store with cosine-similarity search."""

    def __init__(self) -> None:
        self._vectors: Dict[str, List[float]] = {}

    # ── public API ──

    def add(self, key: str, vector: List[float]) -> None:
        """Store *vector* under *key*."""
        self._vectors[key] = vector
        log.debug("VectorStore: added key %s (dim=%d)", key, len(vector))

    def search(self, query: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
        """Return top-*k* most similar entries as list of {key, score} dicts."""
        if not self._vectors:
            return []
        scored = [
            {"key": k, "score": _cosine(query, v)}
            for k, v in self._vectors.items()
        ]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def remove(self, key: str) -> None:
        """Delete *key* from the store."""
        self._vectors.pop(key, None)

    def size(self) -> int:
        """Return number of stored vectors."""
        return len(self._vectors)

    def clear(self) -> None:
        """Remove all vectors."""
        self._vectors.clear()
