#!/usr/bin/env python3
"""Embedding middleware for NRR-v2."""

from __future__ import annotations

import logging
import math
import threading
from typing import Any, List

log = logging.getLogger("Niblit.EmbeddingEngine")

EMBEDDING_MODEL_NAME = "intfloat/multilingual-e5-small"
EMBEDDING_DIM = 384

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None  # type: ignore[assignment]

try:
    from sentence_transformers import SentenceTransformer
except ImportError:  # pragma: no cover
    SentenceTransformer = None  # type: ignore[assignment,misc]


class EmbeddingEngine:
    """Singleton-backed embedding generator with strict vector validation."""

    _instance: "EmbeddingEngine | None" = None
    _instance_lock = threading.Lock()

    def __new__(cls) -> "EmbeddingEngine":
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._model = None
                    cls._instance._model_lock = threading.Lock()
        return cls._instance

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model
        if SentenceTransformer is None:
            raise RuntimeError("sentence-transformers is not installed")
        with self._model_lock:
            if self._model is None:
                self._model = SentenceTransformer(EMBEDDING_MODEL_NAME)
                log.info("[EmbeddingEngine] loaded %s", EMBEDDING_MODEL_NAME)
        return self._model

    @staticmethod
    def _validate_and_normalize(vector: List[float]) -> List[float]:
        if len(vector) != EMBEDDING_DIM:
            raise ValueError(f"invalid embedding dimension: expected {EMBEDDING_DIM}, got {len(vector)}")
        if not all(math.isfinite(v) for v in vector):
            raise ValueError("invalid embedding: non-finite value found")
        norm = math.sqrt(sum(v * v for v in vector))
        if norm <= 0.0:
            raise ValueError("invalid embedding: zero norm vector")
        return [float(v / norm) for v in vector]

    def embed(self, text: str) -> List[float]:
        """Embed text into an exact 384-dimensional normalized vector."""
        if not isinstance(text, str) or not text.strip():
            raise ValueError("text must be a non-empty string")

        model = self._load_model()
        encoded = model.encode(text, convert_to_numpy=True, show_progress_bar=False)

        if np is not None and isinstance(encoded, np.ndarray):
            vector = encoded.flatten().astype("float32").tolist()
        elif isinstance(encoded, list):
            vector = [float(v) for v in encoded]
        else:
            raise ValueError("invalid embedding output format")

        return self._validate_and_normalize(vector)


def get_embedding_engine() -> EmbeddingEngine:
    """Return process-wide embedding engine singleton."""
    return EmbeddingEngine()


def embed(text: str) -> List[float]:
    """Public embed API for middleware usage."""
    return get_embedding_engine().embed(text)
