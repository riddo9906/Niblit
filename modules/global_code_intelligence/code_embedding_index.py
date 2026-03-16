#!/usr/bin/env python3
"""
modules/global_code_intelligence/code_embedding_index.py

Convert code and code-related text to semantic vectors for similarity search.

Wraps the existing ``modules.vector_store.VectorStore`` abstraction with
GCIM-specific preprocessing:
    - language-tagged chunk IDs for deduplication
    - structural metadata (framework, domain, language)
    - batch ingestion from EcosystemScanner records

Usage::

    from modules.global_code_intelligence.code_embedding_index import CodeEmbeddingIndex
    idx = CodeEmbeddingIndex()
    idx.add_snippet("fastapi-router", "from fastapi import APIRouter", lang="python")
    idx.add_repo_records(ecosystem_scanner_results)
    hits = idx.search("async REST endpoint", top_k=5)
"""

import hashlib
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("CodeEmbeddingIndex")

_CHUNK_SIZE = 400


class CodeEmbeddingIndex:
    """
    Semantic vector index for global code intelligence.

    Delegates storage to VectorStore (Qdrant → FAISS → in-memory fallback).
    """

    def __init__(self, vector_store: Optional[Any] = None) -> None:
        if vector_store is not None:
            self._vs = vector_store
        else:
            try:
                from modules.vector_store import VectorStore  # type: ignore[import]
                self._vs = VectorStore()
            except Exception as exc:  # noqa: BLE001
                log.warning("CodeEmbeddingIndex: VectorStore unavailable (%s) — fallback", exc)
                self._vs = _MemFallback()

    # ── public API ────────────────────────────────────────────────────────────

    def add_snippet(
        self,
        name: str,
        code: str,
        lang: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """
        Add a code snippet (optionally chunked) to the index.

        Returns list of stored chunk IDs.
        """
        chunks = [code[i: i + _CHUNK_SIZE] for i in range(0, len(code), _CHUNK_SIZE)] or [code]
        ids: List[str] = []
        meta = metadata or {}
        if lang:
            meta["language"] = lang
        for idx, chunk in enumerate(chunks):
            uid = self._uid(name, idx)
            text = f"[{lang}:{name}] {chunk}" if lang else f"[{name}] {chunk}"
            try:
                self._vs.add(uid, text)
                ids.append(uid)
            except Exception as exc:  # noqa: BLE001
                log.debug("CodeEmbeddingIndex.add_snippet: %s", exc)
        return ids

    def add_repo_records(
        self, records: List[Dict[str, Any]]
    ) -> int:
        """
        Ingest EcosystemScanner records into the index.

        Each record is stored as: "<name> — <domain> — <language> — topics: ..."
        Returns number of entries added.
        """
        count = 0
        for rec in records:
            name = rec.get("name", "unknown")
            lang = rec.get("language", "")
            domain = rec.get("domain", "")
            topics = ", ".join(rec.get("topics", [])[:10])
            text = f"{name} — {domain} — {lang}"
            if topics:
                text += f" — topics: {topics}"
            ids = self.add_snippet(name, text, lang=lang, metadata={"domain": domain, "source": rec.get("source", "")})
            count += len(ids)
        return count

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Semantic search.  Returns list of result dicts."""
        try:
            return self._vs.search(query, top_k=top_k)
        except Exception as exc:  # noqa: BLE001
            log.debug("CodeEmbeddingIndex.search: %s", exc)
            return []

    def is_available(self) -> bool:
        return not isinstance(self._vs, _MemFallback)

    # ── internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _uid(name: str, idx: int) -> str:
        raw = f"gcim:{name}:{idx}"
        return hashlib.md5(raw.encode()).hexdigest()[:16]  # noqa: S324


class _MemFallback:
    """Minimal in-memory fallback."""

    def __init__(self) -> None:
        self._items: List[Dict[str, Any]] = []

    def add(self, uid: str, text: str, metadata: Dict[str, Any] = None) -> None:  # type: ignore[assignment]
        self._items.append({"id": uid, "text": text, "metadata": metadata or {}})

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        q = query.lower()
        scored = [(sum(1 for w in q.split() if w in it["text"].lower()), it)
                  for it in self._items]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [it for _, it in scored[:top_k]]
