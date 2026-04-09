"""KnowledgeAPI — unified read/write interface for the knowledge node.

Usage example::

    api = KnowledgeAPI()
    api.store("key1", "Some knowledge text", tags=["ai", "research"])
    result = api.retrieve("key1")
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("KnowledgeAPI")


class KnowledgeAPI:
    """Key-value + tag-based knowledge store."""

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}

    # ── public API ──

    def store(self, key: str, value: Any, tags: Optional[List[str]] = None) -> None:
        """Persist *value* under *key* with optional *tags*."""
        self._store[key] = {"key": key, "value": value, "tags": tags or [], "stored_at": time.time()}
        log.debug("KnowledgeAPI: stored key %s", key)

    def retrieve(self, key: str) -> Optional[Dict[str, Any]]:
        """Return stored entry for *key* or None."""
        return self._store.get(key)

    def search(self, query: str) -> List[Dict[str, Any]]:
        """Return entries whose key or value string contains *query*."""
        q = query.lower()
        results = []
        for entry in self._store.values():
            if q in str(entry.get("key", "")).lower() or q in str(entry.get("value", "")).lower():
                results.append(entry)
        return results

    def delete(self, key: str) -> None:
        """Remove *key* from the store."""
        self._store.pop(key, None)
        log.debug("KnowledgeAPI: deleted key %s", key)

    def count(self) -> int:
        """Return total stored entries."""
        return len(self._store)


if __name__ == "__main__":
    print('Running knowledge_api.py')
