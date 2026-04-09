"""KnowledgeAPI — knowledge query/submit for the civilisation API gateway.

Usage example::

    api = KnowledgeAPI()
    resp = api.submit_knowledge("Transformer models use attention mechanisms.", ["nlp"])
    results = api.query("attention")
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

log = logging.getLogger("GatewayKnowledgeAPI")


class KnowledgeAPI:
    """Lightweight knowledge store for the API gateway layer."""

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}

    # ── public API ──

    def query(self, q: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Return knowledge items whose content contains *q*."""
        q_lower = q.lower()
        results = [
            entry for entry in self._store.values()
            if q_lower in entry.get("content", "").lower()
            or any(q_lower in t.lower() for t in entry.get("tags", []))
        ]
        return results[:top_k]

    def submit_knowledge(
        self,
        content: str,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Store *content* and return {key, status}."""
        key = str(uuid.uuid4())
        self._store[key] = {
            "key": key,
            "content": content,
            "tags": tags or [],
            "stored_at": time.time(),
        }
        log.info("GatewayKnowledgeAPI: stored key %s", key)
        return {"key": key, "status": "stored"}

    def get_knowledge(self, key: str) -> Optional[Dict[str, Any]]:
        """Return stored item for *key* or None."""
        return self._store.get(key)


if __name__ == "__main__":
    print('Running knowledge_api.py')
