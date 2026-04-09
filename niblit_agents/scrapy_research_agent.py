# niblit_agents/scrapy_research_agent.py
"""
Niblit ScrapyResearchAgent — DuckDuckGo web research via Scrapy, first-class.

Architecture::

    NiblitBrain / ALE / SelfResearcher
         │
         ▼
    ScrapyResearchAgent
         │   uses directly
         ▼
    ScrapySearchEngine  →  DuckDuckGo HTML scraping (subprocess)
         │
         ▼
    _process_results()
         │
    ┌────┴──────────────────────────────────────┐
    │                                           │
    KnowledgeStore.store_search_results()   VectorStore.add()
    (SQLite persistence)                    (Qdrant embedding, optional)

Unlike :class:`~niblit_agents.research_agent.ResearchAgent`, this agent
communicates directly with :class:`~niblit_tools.scrapy_search.ScrapySearchEngine`
without routing through the :class:`~niblit_tools.serpex_api.SerpexAPI` shim.
No external API key is required.

Usage::

    from niblit_agents.scrapy_research_agent import ScrapyResearchAgent
    agent = ScrapyResearchAgent()
    results = agent.search_web("python asyncio patterns")
    # → [{"title": ..., "url": ..., "snippet": ...}]
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Niblit.ScrapyResearchAgent")

# ---------------------------------------------------------------------------
# Scrapy availability check
# ---------------------------------------------------------------------------

try:
    import scrapy as _scrapy  # noqa: F401
    _SCRAPY_AVAILABLE = True
except ImportError:
    _SCRAPY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Relevance helper (mirrors niblit_agents.research_agent.is_relevant)
# ---------------------------------------------------------------------------

def _is_relevant(query: str, text: str, threshold: float = 0.4) -> bool:
    """Return *True* when *text* is semantically relevant to *query*.

    Uses a simple term-overlap ratio.  The threshold is slightly more
    lenient (0.4 vs 0.5) than :func:`~niblit_agents.research_agent.is_relevant`
    to compensate for shorter snippets that Scrapy sometimes returns.

    Args:
        query:     The original search query.
        text:      Candidate text to evaluate.
        threshold: Minimum overlap score in ``[0, 1]``.  Default ``0.4``.
    """
    query_terms = set(query.lower().split())
    if not query_terms:
        return True
    text_lower = text.lower()
    overlap = sum(1 for term in query_terms if term in text_lower)
    return (overlap / len(query_terms)) >= threshold


# ---------------------------------------------------------------------------
# ScrapyResearchAgent
# ---------------------------------------------------------------------------

class ScrapyResearchAgent:
    """DuckDuckGo web research agent backed directly by :class:`~niblit_tools.scrapy_search.ScrapySearchEngine`.

    Provides ``search_web()`` and ``search_news()`` with relevance filtering,
    KnowledgeStore persistence, and optional Qdrant vector embedding.  Unlike
    :class:`~niblit_agents.research_agent.ResearchAgent`, this class bypasses
    the :class:`~niblit_tools.serpex_api.SerpexAPI` shim and uses
    :class:`~niblit_tools.scrapy_search.ScrapySearchEngine` directly, making
    Scrapy a first-class research backend.

    No external API key or environment variable is required — Scrapy scrapes
    DuckDuckGo HTML results directly.

    Args:
        knowledge_store: Optional pre-built KnowledgeStore instance.
        qdrant_url:      Qdrant server URL for optional vector embedding.
        qdrant_api_key:  Qdrant API key.
        max_results:     Maximum results returned per query (default: 10).
    """

    def __init__(
        self,
        knowledge_store: Optional[Any] = None,
        qdrant_url: str = "",
        qdrant_api_key: str = "",
        max_results: int = 10,
    ) -> None:
        self._qdrant_url = qdrant_url
        self._qdrant_api_key = qdrant_api_key
        self._knowledge_store: Optional[Any] = knowledge_store
        self._vector_store: Optional[Any] = None
        self._max_results = max_results

        # Build ScrapySearchEngine directly — no SerpexAPI shim
        self._engine: Optional[Any] = self._build_engine()

        # Build optional Qdrant VectorStore
        if self._qdrant_url:
            try:
                from modules.vector_store import VectorStore
                self._vector_store = VectorStore(
                    collection="niblit_scrapy_research",
                    qdrant_url=self._qdrant_url,
                    qdrant_api_key=self._qdrant_api_key,
                )
            except Exception as exc:
                logger.debug("ScrapyResearchAgent: VectorStore unavailable: %s", exc)

    # ── builder ──────────────────────────────────────────────────────────────

    def _build_engine(self) -> Optional[Any]:
        """Construct a :class:`~niblit_tools.scrapy_search.ScrapySearchEngine`."""
        try:
            from niblit_tools.scrapy_search import ScrapySearchEngine
            return ScrapySearchEngine(max_results=self._max_results)
        except Exception as exc:
            logger.debug("ScrapyResearchAgent: ScrapySearchEngine unavailable: %s", exc)
            return None

    # ── public API ────────────────────────────────────────────────────────────

    def is_configured(self) -> bool:
        """Return ``True`` when Scrapy is importable and the engine is ready."""
        return _SCRAPY_AVAILABLE and self._engine is not None

    def search_web(self, query: str) -> List[Dict[str, Any]]:
        """Search DuckDuckGo for general web results.

        Args:
            query: Natural-language search query.

        Returns:
            List of ``{"title": str, "url": str, "snippet": str}`` dicts.
        """
        logger.info("[ScrapyResearchAgent] search_web: %r", query)
        if self._engine is None:
            return []
        data = self._engine.search(query, category="web")
        return self._process_results(data, query=query)

    def search_news(self, query: str) -> List[Dict[str, Any]]:
        """Search DuckDuckGo for news results.

        Args:
            query: Natural-language search query.

        Returns:
            List of ``{"title": str, "url": str, "snippet": str}`` dicts.
        """
        logger.info("[ScrapyResearchAgent] search_news: %r", query)
        if self._engine is None:
            return []
        data = self._engine.search(query, category="news")
        return self._process_results(data, query=query)

    # ── internals ────────────────────────────────────────────────────────────

    def _knowledge_store_client(self) -> Optional[Any]:
        """Lazily build KnowledgeStore."""
        if self._knowledge_store is None:
            try:
                from niblit_memory import KnowledgeStore
                self._knowledge_store = KnowledgeStore()
            except Exception as exc:
                logger.debug("ScrapyResearchAgent: KnowledgeStore unavailable: %s", exc)
        return self._knowledge_store

    def _process_results(
        self,
        data: Dict[str, Any],
        query: str = "",
        _skip_relevance_check: bool = False,
    ) -> List[Dict[str, Any]]:
        """Extract, filter, persist and embed items from a ScrapySearchEngine response.

        Args:
            data:                  Search response dict (has ``"results"`` key).
            query:                 Original query string (used for relevance check).
            _skip_relevance_check: When *True*, accept all items regardless of
                                   relevance score (used internally to avoid
                                   infinite retry loops).

        Returns:
            List of normalised ``{"title", "url", "snippet"}`` dicts.
        """
        if "error" in data:
            logger.warning("[ScrapyResearchAgent] search returned error: %s", data["error"])
            return [{"error": data["error"]}]

        raw_items = data.get("results") or []

        extracted: List[Dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            snippet = (
                item.get("snippet")
                or item.get("description")
                or item.get("text")
                or ""
            )
            if not snippet:
                continue
            if query and not _skip_relevance_check and not _is_relevant(query, snippet):
                continue
            extracted.append({
                "title":   item.get("title", ""),
                "url":     item.get("url") or "local://kb",
                "snippet": snippet,
            })

        # If no relevant results on first pass, retry with a broader query
        if not extracted and raw_items and not _skip_relevance_check and self._engine is not None:
            retry_query = f"{query} definition explanation"
            retry_data = self._engine.search(retry_query, category="web")
            for item in (retry_data.get("results") or []):
                if not isinstance(item, dict):
                    continue
                snippet = item.get("snippet") or item.get("description") or ""
                if not snippet:
                    continue
                extracted.append({
                    "title":   item.get("title", ""),
                    "url":     item.get("url") or "local://kb",
                    "snippet": snippet,
                })

        # Persist to KnowledgeStore
        ks = self._knowledge_store_client()
        if ks is not None and extracted:
            try:
                ks.store_search_results(query, extracted)
            except Exception as exc:
                logger.debug("[ScrapyResearchAgent] KnowledgeStore store failed: %s", exc)

        # Embed to vector store
        if self._vector_store is not None:
            for item in extracted:
                snippet = item.get("snippet", "")
                if snippet:
                    try:
                        self._vector_store.add(snippet, metadata=item)
                    except Exception as exc:
                        logger.debug("[ScrapyResearchAgent] VectorStore add failed: %s", exc)

        return extracted


if __name__ == "__main__":
    print('Running scrapy_research_agent.py')
