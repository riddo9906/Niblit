"""EmbeddingService — deterministic hash-based text embeddings (64-dim).

No external ML libraries required.  Uses character-level hashing to produce
a reproducible 64-dimensional float vector.

Usage example::

    svc = EmbeddingService()
    vec = svc.embed("neural networks")
    sim = svc.similarity(vec, svc.embed("deep learning"))
"""

from __future__ import annotations

import hashlib
import logging
import math
from typing import List

log = logging.getLogger("EmbeddingService")

_DIM = 64


def _hash_text(text: str, dim: int = _DIM) -> List[float]:
    """Produce a deterministic *dim*-dimensional float vector for *text*."""
    vec: List[float] = []
    for i in range(dim):
        digest = hashlib.sha256(f"{text}::{i}".encode()).hexdigest()
        raw = int(digest[:8], 16)
        vec.append((raw / 0xFFFFFFFF) * 2.0 - 1.0)
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


class EmbeddingService:
    """Produces 64-dim deterministic embeddings from text."""

    # ── public API ──

    def embed(self, text: str) -> List[float]:
        """Return 64-dim normalised vector for *text*."""
        return _hash_text(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Return embeddings for each item in *texts*."""
        return [self.embed(t) for t in texts]

    def similarity(self, vec_a: List[float], vec_b: List[float]) -> float:
        """Cosine similarity between *vec_a* and *vec_b* → [-1, 1]."""
        dot = sum(a * b for a, b in zip(vec_a, vec_b))
        na = math.sqrt(sum(a * a for a in vec_a)) or 1.0
        nb = math.sqrt(sum(b * b for b in vec_b)) or 1.0
        return dot / (na * nb)


if __name__ == "__main__":
    print('Running embedding_service.py')
