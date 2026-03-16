"""EmbeddingService — deterministic 64-dim text embeddings for knowledge ecosystem.

Usage example::

    svc = EmbeddingService()
    vec = svc.encode("civilisation AI")
    sim = svc.cosine_similarity(vec, svc.encode("agent systems"))
"""

from __future__ import annotations

import hashlib
import logging
import math
from typing import List

log = logging.getLogger("KnowledgeEmbeddingService")

_DIM = 64


def _hash_embed(text: str, dim: int = _DIM) -> List[float]:
    vec: List[float] = []
    for i in range(dim):
        digest = hashlib.sha256(f"{text}::{i}".encode()).hexdigest()
        raw = int(digest[:8], 16)
        vec.append((raw / 0xFFFFFFFF) * 2.0 - 1.0)
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


class EmbeddingService:
    """Produces deterministic 64-dim text embeddings."""

    # ── public API ──

    def encode(self, text: str) -> List[float]:
        """Return 64-dim normalised embedding for *text*."""
        return _hash_embed(text)

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        """Return embeddings for all items in *texts*."""
        return [self.encode(t) for t in texts]

    def cosine_similarity(self, a: List[float], b: List[float]) -> float:
        """Cosine similarity between *a* and *b* → [-1, 1]."""
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a)) or 1.0
        nb = math.sqrt(sum(x * x for x in b)) or 1.0
        return dot / (na * nb)
