#!/usr/bin/env python3
"""
niblit_agents/semantic_agent.py — Semantic storage and retrieval agent for Niblit.

Bridges the research pipeline (Serpex, Searchcode, internet scrapers) with the
vector store so that all collected knowledge becomes semantically searchable.

Architecture role::

    ResearchAgent / SearchcodeSearch / InternetManager
               │
               ▼
         SemanticAgent
               │
         ┌─────┴──────┐
         │             │
    QdrantEngine   (SQLite via KnowledgeStore)
     (VectorStore)

Usage::

    from niblit_agents.semantic_agent import SemanticAgent
    agent = SemanticAgent()
    agent.store_knowledge(results, source="serpex")
    context = agent.retrieve_context("python asyncio patterns")
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Niblit.SemanticAgent")


class SemanticAgent:
    """
    Semantic knowledge agent — stores research results in the vector store
    and retrieves relevant context for query enrichment.

    Args:
        qdrant_engine:  Pre-built :class:`~niblit_memory.qdrant_engine.QdrantEngine`.
                        When *None*, one is created lazily.
        vector_store:   Pre-built :class:`~modules.vector_store.VectorStore` to
                        reuse (passed through to QdrantEngine when provided).
        qdrant_url:     Qdrant URL override.  Falls back to ``QDRANT_URL`` env var.
        qdrant_api_key: Qdrant API key override.  Falls back to ``QDRANT_API_KEY``.
    """

    def __init__(
        self,
        qdrant_engine: Optional[Any] = None,
        vector_store: Optional[Any] = None,
        qdrant_url: str = "",
        qdrant_api_key: str = "",
    ) -> None:
        self._engine = qdrant_engine
        self._vector_store = vector_store
        self._qdrant_url = qdrant_url
        self._qdrant_api_key = qdrant_api_key
        self._engine_initialised = qdrant_engine is not None

    # ── lazy init ─────────────────────────────────────────────────────────────

    def _get_engine(self) -> Optional[Any]:
        """Lazily initialise the underlying QdrantEngine."""
        if self._engine_initialised:
            return self._engine
        self._engine_initialised = True
        try:
            from niblit_memory.qdrant_engine import QdrantEngine
            self._engine = QdrantEngine(
                qdrant_url=self._qdrant_url,
                qdrant_api_key=self._qdrant_api_key,
                vector_store=self._vector_store,
            )
            logger.debug("[SemanticAgent] QdrantEngine ready (backend=%s)", self._engine.backend)
        except Exception as exc:
            logger.debug("[SemanticAgent] QdrantEngine unavailable: %s", exc)
            self._engine = None
        return self._engine

    # ── public API ────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return True when the underlying vector store is reachable."""
        engine = self._get_engine()
        return engine is not None and engine.is_available()

    def store_knowledge(
        self,
        results: List[Dict[str, Any]],
        source: str = "serpex",
        query: str = "",
    ) -> int:
        """
        Embed and store a list of research results in the vector store.

        Accepts the standard result format used by ResearchAgent, SearchcodeSearch,
        and InternetManager::

            [{"title": "...", "url": "...", "snippet": "...", ...}]

        Also handles Searchcode-style results::

            [{"name": "...", "url": "...", "lines": {"1": "..."}, ...}]

        And InternetManager-style results::

            [{"source": "serpex", "text": "...", "url": "..."}]

        Args:
            results: List of result dicts.
            source:  Source label (e.g. ``"serpex"``, ``"searchcode"``,
                     ``"wikipedia"``).
            query:   Original search query — used for relevance filtering.

        Returns:
            Number of documents stored.
        """
        engine = self._get_engine()
        if engine is None or not results:
            return 0

        documents = []
        for r in results:
            if not isinstance(r, dict) or "error" in r:
                continue

            # Normalise text field across different result shapes
            text = (
                r.get("snippet")
                or r.get("text")
                or r.get("extract")
                or r.get("description")
                or r.get("content")
                or ""
            )
            # Searchcode: reconstruct snippet from lines dict
            if not text and "lines" in r:
                lines = r.get("lines", {})
                if isinstance(lines, dict):
                    text = " ".join(str(v) for v in lines.values())[:500]

            if not text:
                continue

            # Optional relevance pre-filter
            if query and not engine.is_relevant(query, text):
                continue

            title = (
                r.get("title")
                or r.get("name")
                or r.get("filename")
                or ""
            )
            url = r.get("url") or r.get("repo") or ""

            documents.append({
                "text": text[:800],
                "metadata": {
                    "title": title,
                    "url": url,
                    "source": source,
                    "query": query,
                },
            })

        return engine.upsert_documents(documents)

    def retrieve_context(
        self,
        query: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve the most semantically relevant documents for *query*.

        Args:
            query: Natural-language query or topic.
            limit: Maximum number of results to return.

        Returns:
            List of ``{"score": float, "text": str, "metadata": dict}`` dicts.
        """
        engine = self._get_engine()
        if engine is None:
            return []
        return engine.query(query, limit=limit)

    def store_and_retrieve(
        self,
        results: List[Dict[str, Any]],
        query: str,
        source: str = "mixed",
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Convenience method: store *results* then immediately retrieve context
        for *query*.

        Useful in pipeline steps where you want to both persist new knowledge
        and enrich the current response in one call.
        """
        self.store_knowledge(results, source=source, query=query)
        return self.retrieve_context(query, limit=limit)


if __name__ == "__main__":
    agent = SemanticAgent()
    print(f"SemanticAgent available: {agent.is_available()}")
    stored = agent.store_knowledge(
        [{"snippet": "Python asyncio allows concurrent I/O", "title": "asyncio docs", "url": "https://docs.python.org"}],
        source="test",
        query="asyncio",
    )
    print(f"Stored {stored} documents")
    ctx = agent.retrieve_context("asyncio concurrent")
    print(f"Context: {ctx}")
