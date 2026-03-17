# niblit_agents/research_agent.py
"""
Niblit ResearchAgent — integrates SerpexAPI with memory and semantic storage.

Architecture role::

    NiblitBrain
         │
         ▼
    ResearchAgent
         │
    ┌────┴─────────┐
    │              │
    SerpexAPI   (news)
    (web)          │
         │         │
         └────┬────┘
              │
         _process_results()
              │
         KnowledgeStore (SQLite)
              │
         (optional) Qdrant embeddings  →  SemanticAgent

Usage::

    from niblit_agents.research_agent import ResearchAgent
    agent = ResearchAgent()
    results = agent.search_web("python asyncio patterns")
    news    = agent.search_news("AI trends 2025")
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Niblit.ResearchAgent")


class ResearchAgent:
    """
    Research agent that queries Serpex and stores results in memory/Qdrant.

    Args:
        serpex_api_key:  Serpex API key.  Falls back to ``SERPEX_API_KEY`` env var.
        knowledge_store: Optional pre-built :class:`~niblit_memory.knowledge_store.KnowledgeStore`
                         instance.  When *None*, one is created lazily on first use.
        qdrant_url:      Qdrant server URL.  Falls back to ``QDRANT_URL`` env var.
        qdrant_api_key:  Qdrant API key.  Falls back to ``QDRANT_API_KEY`` env var.
    """

    def __init__(
        self,
        serpex_api_key: str = "",
        knowledge_store: Optional[Any] = None,
        qdrant_url: str = "",
        qdrant_api_key: str = "",
    ) -> None:
        self._serpex_key = serpex_api_key or os.getenv("SERPEX_API_KEY", "")
        self._qdrant_url = qdrant_url or os.getenv("QDRANT_URL", "")
        self._qdrant_api_key = qdrant_api_key or os.getenv("QDRANT_API_KEY", "")

        # Lazy initialise SerpexAPI (raises ValueError if no key on first use)
        self._serpex: Optional[Any] = None

        # KnowledgeStore — accept injected or build one lazily
        self._knowledge_store: Optional[Any] = knowledge_store

        # Qdrant VectorStore for semantic embedding after search
        self._vector_store: Optional[Any] = None
        if self._qdrant_url:
            try:
                from modules.vector_store import VectorStore  # type: ignore[import]
                self._vector_store = VectorStore(
                    collection="niblit_research",
                    qdrant_url=self._qdrant_url,
                    qdrant_api_key=self._qdrant_api_key,
                )
            except Exception as exc:
                logger.debug("ResearchAgent: VectorStore unavailable: %s", exc)

    # ── public API ────────────────────────────────────────────────────────────

    def search_web(self, query: str) -> List[Dict[str, Any]]:
        """Search the web and return normalised result items.

        Args:
            query: Natural-language search query.

        Returns:
            List of ``{"title": str, "url": str, "snippet": str}`` dicts.
        """
        logger.info("[ResearchAgent] web search: %r", query)
        data = self._serpex_client().search(
            query=query,
            category="web",
            engine="auto",
            time_range="day",
        )
        return self._process_results(data, query=query)

    def search_news(self, query: str) -> List[Dict[str, Any]]:
        """Search news and return normalised result items.

        Args:
            query: Natural-language search query.

        Returns:
            List of ``{"title": str, "url": str, "snippet": str}`` dicts.
        """
        logger.info("[ResearchAgent] news search: %r", query)
        data = self._serpex_client().search(
            query=query,
            category="news",
            engine="google",
        )
        return self._process_results(data, query=query)

    # ── internals ─────────────────────────────────────────────────────────────

    def _serpex_client(self) -> Any:
        """Lazily instantiate :class:`~niblit_tools.serpex_api.SerpexAPI`."""
        if self._serpex is None:
            from niblit_tools.serpex_api import SerpexAPI
            self._serpex = SerpexAPI(api_key=self._serpex_key or None)
        return self._serpex

    def _knowledge_store_client(self) -> Optional[Any]:
        """Lazily instantiate :class:`~niblit_memory.knowledge_store.KnowledgeStore`."""
        if self._knowledge_store is None:
            try:
                from niblit_memory.knowledge_store import KnowledgeStore
                self._knowledge_store = KnowledgeStore()
            except Exception as exc:
                logger.debug("ResearchAgent: KnowledgeStore unavailable: %s", exc)
        return self._knowledge_store

    def _process_results(
        self,
        data: Dict[str, Any],
        query: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Extract structured knowledge from a Serpex response, persist to
        KnowledgeStore, and optionally embed into Qdrant.

        Args:
            data:  Raw Serpex API response dict.
            query: Original query (used as the knowledge-store key prefix).

        Returns:
            List of ``{"title": str, "url": str, "snippet": str}`` dicts.
        """
        if "error" in data:
            logger.warning("[ResearchAgent] Serpex returned error: %s", data["error"])
            return [{"error": data["error"]}]

        # Normalise: Serpex can use organic_results, results, or news_results
        raw_items = (
            data.get("organic_results")
            or data.get("results")
            or data.get("news_results")
            or []
        )

        extracted: List[Dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            extracted.append({
                "title": item.get("title", ""),
                "url": item.get("link") or item.get("url", ""),
                "snippet": (
                    item.get("snippet")
                    or item.get("description")
                    or item.get("content")
                    or item.get("text")
                    or ""
                ),
            })

        # 1. Persist to KnowledgeStore (SQLite)
        ks = self._knowledge_store_client()
        if ks is not None:
            try:
                ks.store_search_results(query, extracted)
            except Exception as exc:
                logger.debug("[ResearchAgent] KnowledgeStore persist failed: %s", exc)

        # 2. Embed snippets into Qdrant (upgrade hook)
        if self._vector_store is not None and extracted:
            try:
                import hashlib
                from datetime import datetime, timezone
                ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
                for i, item in enumerate(extracted):
                    text = item.get("snippet", "")
                    if not text:
                        continue
                    url_hash = hashlib.md5(item.get("url", str(i)).encode()).hexdigest()[:10]
                    doc_id = f"serpex:{url_hash}:{ts}"
                    self._vector_store.add(doc_id, text[:500])
            except Exception as exc:
                logger.debug("[ResearchAgent] Qdrant embed failed: %s", exc)

        return extracted
