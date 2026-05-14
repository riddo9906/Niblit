#!/usr/bin/env python3
"""Qdrant adapter for strict 384-dimensional governed memory operations."""

from __future__ import annotations

import hashlib
import logging
import math
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from modules.embedding_engine import GovernanceViolationError

log = logging.getLogger("Niblit.VectorMemory.QdrantAdapter")

COLLECTION_NAME = os.getenv("NIBLIT_QDRANT_COLLECTION", "advisor_memory")
VECTOR_DIM = 384

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, PointStruct, VectorParams
except ImportError:  # pragma: no cover
    QdrantClient = None  # type: ignore[assignment,misc]
    Distance = None  # type: ignore[assignment,misc]
    PointStruct = None  # type: ignore[assignment,misc]
    VectorParams = None  # type: ignore[assignment,misc]


class QdrantAdapter:
    """Strict adapter that rejects non-384 vectors and blocks invalid inserts."""

    def __init__(
        self,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        collection_name: str = COLLECTION_NAME,
    ) -> None:
        self.url = url if url is not None else os.getenv("QDRANT_URL", "http://localhost:6333")
        self.api_key = api_key if api_key is not None else os.getenv("QDRANT_API_KEY", "")
        self.collection_name = collection_name
        self._client: Optional[Any] = None

    def _get_client(self) -> Optional[Any]:
        if QdrantClient is None:
            return None
        if self._client is not None:
            return self._client
        kwargs: Dict[str, Any] = {"url": self.url, "timeout": 10}
        if self.api_key:
            kwargs["api_key"] = self.api_key
        try:
            self._client = QdrantClient(**kwargs)
            return self._client
        except Exception as exc:
            log.warning("[QdrantAdapter] failed to connect to Qdrant: %s", exc)
            self._client = None
            return None

    def _ensure_collection(self, client: Any) -> bool:
        try:
            existing = {c.name for c in client.get_collections().collections}
            if self.collection_name in existing:
                return True
            client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
            )
            return True
        except Exception as exc:
            log.warning("[QdrantAdapter] failed to ensure collection '%s': %s", self.collection_name, exc)
            return False

    @staticmethod
    def validate_vector(vector: List[float]) -> List[float]:
        """Validate and normalize a vector, enforcing exact 384 dimensions.

        Raises ``GovernanceViolationError`` on any contract breach — callers
        must not catch this silently; it signals a real governance problem.
        """
        if not isinstance(vector, list):
            raise GovernanceViolationError(
                "Governance contract violated: vector must be a list of floats, "
                f"got {type(vector).__name__}"
            )
        if len(vector) != VECTOR_DIM:
            raise GovernanceViolationError(
                f"Governance contract violated: vector must be {VECTOR_DIM}-dimensional, "
                f"got {len(vector)}"
            )
        cleaned = [float(v) for v in vector]
        if not all(math.isfinite(v) for v in cleaned):
            raise GovernanceViolationError(
                "Governance contract violated: vector contains non-finite values"
            )
        norm = math.sqrt(sum(v * v for v in cleaned))
        if norm <= 0.0:
            raise GovernanceViolationError(
                "Governance contract violated: vector norm must be > 0"
            )
        return [v / norm for v in cleaned]

    @staticmethod
    def _stable_point_id(memory_id: str) -> int:
        digest = hashlib.sha256(memory_id.encode("utf-8")).hexdigest()
        return int(digest, 16) % (2**63)

    def insert_memory(
        self,
        text: str,
        vector: List[float],
        metadata: Optional[Dict[str, Any]] = None,
        memory_id: Optional[str] = None,
    ) -> Optional[str]:
        """Insert a new memory item after strict vector validation."""
        if not text or not text.strip():
            return None
        point_id = memory_id or str(uuid.uuid4())
        ok = self.upsert_memory(point_id, text, vector, metadata)
        return point_id if ok else None

    def upsert_memory(
        self,
        memory_id: str,
        text: str,
        vector: List[float],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Upsert memory while rejecting invalid vectors and schema drift."""
        normalized_vector = self.validate_vector(vector)

        client = self._get_client()
        if client is None:
            return False
        if not self._ensure_collection(client):
            return False

        now = int(time.time())
        payload: Dict[str, Any] = {
            "memory_id": memory_id,
            "text": text,
            "updated_at": now,
            "created_at": now,
            "frequency": 1,
        }
        if metadata:
            payload.update(metadata)
            payload["updated_at"] = now
            payload.setdefault("created_at", now)
            payload["frequency"] = int(payload.get("frequency", 1) or 1)

        try:
            client.upsert(
                collection_name=self.collection_name,
                points=[
                    PointStruct(
                        id=self._stable_point_id(memory_id),
                        vector=normalized_vector,
                        payload=payload,
                    )
                ],
            )
            return True
        except Exception as exc:
            log.warning("[QdrantAdapter] upsert failed: %s", exc)
            return False

    def search_memory(self, query_vector: List[float], limit: int = 5) -> List[Dict[str, Any]]:
        """Search memory using a validated 384-dimensional query vector."""
        normalized_query = self.validate_vector(query_vector)

        client = self._get_client()
        if client is None:
            return []
        if not self._ensure_collection(client):
            return []

        try:
            hits = client.search(
                collection_name=self.collection_name,
                query_vector=normalized_query,
                limit=max(1, int(limit)),
                with_payload=True,
            )
            out: List[Dict[str, Any]] = []
            for hit in hits:
                payload = dict(hit.payload or {})
                out.append(
                    {
                        "id": payload.get("memory_id", str(hit.id)),
                        "score": float(hit.score),
                        "text": payload.get("text", ""),
                        "payload": payload,
                    }
                )
            return out
        except Exception as exc:
            log.warning("[QdrantAdapter] search failed: %s", exc)
            return []
