#!/usr/bin/env python3
"""
modules/knowledge_engine/embedding_pipeline.py

Convert code knowledge into vector embeddings and store them via VectorStore.

Delegates to the existing ``modules.vector_store.VectorStore`` abstraction which
supports Qdrant → FAISS → in-memory fallback.  This module adds the code-specific
pre-processing: chunking long code files, generating stable IDs, and enriching
metadata with structural information from CodeParser.

Usage::

    from modules.knowledge_engine.embedding_pipeline import EmbeddingPipeline
    pipeline = EmbeddingPipeline()
    pipeline.ingest_snippet("fastapi-router", "from fastapi import APIRouter ...")
    pipeline.ingest_parse_result(code_parser_result)
    results = pipeline.search("async REST endpoint", top_k=3)
"""

import hashlib
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("EmbeddingPipeline")

# Maximum characters per stored chunk.  Larger snippets are split.
_CHUNK_SIZE = 512


class EmbeddingPipeline:
    """
    Preprocess code artifacts and persist them in the vector store.

    Args:
        vector_store:  An optional pre-built VectorStore instance.  When None,
                       a new VectorStore is created with default settings.
        chunk_size:    Maximum characters per stored chunk.
    """

    def __init__(
        self,
        vector_store: Optional[Any] = None,
        chunk_size: int = _CHUNK_SIZE,
    ) -> None:
        self.chunk_size = chunk_size

        if vector_store is not None:
            self._vs = vector_store
        else:
            try:
                from modules.vector_store import VectorStore  # type: ignore[import]
                self._vs = VectorStore()
            except Exception as exc:  # noqa: BLE001
                log.warning("EmbeddingPipeline: VectorStore unavailable (%s) — using fallback", exc)
                self._vs = _InMemoryFallback()

    # ── public API ────────────────────────────────────────────────────────────

    def ingest_snippet(
        self,
        name: str,
        code: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """
        Chunk *code* and store each chunk in the vector store.

        Returns the list of generated chunk IDs.
        """
        chunks = self._split(code)
        ids: List[str] = []
        for idx, chunk in enumerate(chunks):
            uid = self._make_id(name, idx)
            enriched = f"[{name}] {chunk}"
            try:
                self._vs.add(uid, enriched)
                ids.append(uid)
            except Exception as exc:  # noqa: BLE001
                log.debug("EmbeddingPipeline.ingest_snippet: add failed: %s", exc)
        return ids

    def ingest_parse_result(self, parse_result: Dict[str, Any]) -> int:
        """
        Ingest code snippets from a CodeParser.parse_file() result.

        Stores each function and class body as a separate chunk.
        Returns the number of chunks added.
        """
        count = 0
        path = parse_result.get("path", "unknown")
        for func in parse_result.get("functions", []):
            text = f"function {func['name']} in {path}"
            if func.get("docstring"):
                text += f": {func['docstring'][:200]}"
            self.ingest_snippet(f"{path}::{func['name']}", text)
            count += 1
        for cls in parse_result.get("classes", []):
            text = f"class {cls['name']} in {path} methods: {', '.join(cls.get('methods', []))}"
            if cls.get("docstring"):
                text += f" | {cls['docstring'][:200]}"
            self.ingest_snippet(f"{path}::{cls['name']}", text)
            count += 1
        return count

    def ingest_batch(self, parse_results: List[Dict[str, Any]]) -> int:
        """Ingest a list of parse results.  Returns total chunks added."""
        total = 0
        for result in parse_results:
            total += self.ingest_parse_result(result)
        return total

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Semantic search over ingested code knowledge."""
        try:
            return self._vs.search(query, top_k=top_k)
        except Exception as exc:  # noqa: BLE001
            log.debug("EmbeddingPipeline.search: %s", exc)
            return []

    def is_available(self) -> bool:
        return not isinstance(self._vs, _InMemoryFallback)

    # ── internals ─────────────────────────────────────────────────────────────

    def _split(self, text: str) -> List[str]:
        if len(text) <= self.chunk_size:
            return [text]
        chunks = []
        for i in range(0, len(text), self.chunk_size):
            chunks.append(text[i: i + self.chunk_size])
        return chunks

    @staticmethod
    def _make_id(name: str, idx: int) -> str:
        raw = f"{name}:{idx}"
        return hashlib.md5(raw.encode()).hexdigest()[:16]  # noqa: S324


class _InMemoryFallback:
    """Minimal in-memory fallback when VectorStore cannot be imported."""

    def __init__(self) -> None:
        self._store: List[Dict[str, Any]] = []

    def add(self, uid: str, text: str, metadata: Dict[str, Any] = None) -> None:  # type: ignore[assignment]
        self._store.append({"id": uid, "text": text, "metadata": metadata or {}})

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        q = query.lower()
        scored = [(sum(1 for w in q.split() if w in item["text"].lower()), item)
                  for item in self._store]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:top_k]]
