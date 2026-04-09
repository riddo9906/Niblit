"""VectorMemory — cosine-similarity vector memory for the knowledge ecosystem.

Usage example::

    mem = VectorMemory()
    mem.store("concept1", [0.1]*64, {"source": "research"})
    results = mem.recall([0.1]*64, top_k=3)
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional

log = logging.getLogger("VectorMemory")


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


class VectorMemory:
    """Stores and retrieves vectors with cosine similarity."""

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}

    # ── public API ──

    def store(
        self,
        key: str,
        vector: List[float],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Store *vector* under *key* with optional *metadata*."""
        self._store[key] = {"key": key, "vector": vector, "metadata": metadata or {}}
        log.debug("VectorMemory: stored %s", key)

    def recall(
        self, query: List[float], top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Return top-*k* most similar entries."""
        if not self._store:
            return []
        scored = [
            {**entry, "score": _cosine(query, entry["vector"])}
            for entry in self._store.values()
        ]
        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def forget(self, key: str) -> None:
        """Remove *key* from memory."""
        self._store.pop(key, None)

    def size(self) -> int:
        """Return number of stored vectors."""
        return len(self._store)


if __name__ == "__main__":
    print('Running vector_memory.py')
