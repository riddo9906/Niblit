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


def is_relevant(query: str, text: str, threshold: float = 0.5) -> bool:
    """Return *True* when *text* is semantically relevant to *query*.

    Uses simple term-overlap: the fraction of query terms that appear in *text*
    must meet or exceed *threshold*.

    Args:
        query:     The original search query.
        text:      The candidate text (e.g. a snippet) to evaluate.
        threshold: Minimum overlap score in ``[0, 1]``.  Defaults to ``0.5``.

    Returns:
        ``True`` if the overlap score ≥ threshold, ``False`` otherwise.
    """
    query_terms = set(query.lower().split())
    if not query_terms:
        return True  # nothing to filter on
    text_lower = text.lower()
    overlap = sum(1 for term in query_terms if term in text_lower)
    score = overlap / len(query_terms)
    return score >= threshold


def should_reflect(results: list) -> bool:
    """Return *True* only when *results* is non-empty (safe to reflect).

    Args:
        results: List of research result items.

    Returns:
        ``True`` if there is at least one result, ``False`` otherwise.
    """
    return len(results) > 0


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

    def is_configured(self) -> bool:
        """Return True if a Serpex API key is available (agent can make real searches)."""
        return bool(self._serpex_key)

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
        _skip_relevance_check: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Extract structured knowledge from a Serpex response, persist to
        KnowledgeStore, and optionally embed into Qdrant.

        Args:
            data:  Raw Serpex API response dict.
            query: Original query (used as the knowledge-store key prefix and
                   for relevance filtering).
            _skip_relevance_check: Internal flag used by the retry path to
                                   bypass the relevance filter on the second
                                   pass so we don't loop indefinitely.

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
            snippet = (
                item.get("snippet")
                or item.get("description")
                or item.get("content")
                or item.get("text")
                or ""
            )

            # Relevance gate: skip snippets that are unrelated to the query
            if query and snippet and not _skip_relevance_check and not is_relevant(query, snippet):
                logger.debug(
                    "[ResearchAgent] Filtered irrelevant snippet for query %r: %.80s",
                    query, snippet,
                )
                continue

            extracted.append({
                "title": item.get("title", ""),
                "url": item.get("link") or item.get("url", ""),
                "snippet": snippet,
            })

        # Fallback retry when every result was filtered out
        if not extracted and query and not _skip_relevance_check:
            refined_query = f"{query} explanation computer science"
            logger.warning(
                "[ResearchAgent] No relevant results for %r — retrying with refined query: %r",
                query, refined_query,
            )
            retry_data = self._serpex_client().search(
                query=refined_query,
                category="web",
                engine="auto",
                time_range="day",
            )
            # Use _skip_relevance_check=True to avoid recursive retries
            return self._process_results(retry_data, query=query, _skip_relevance_check=True)

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
