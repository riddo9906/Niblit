# niblit_agents/research_agent.py
"""
Niblit ResearchAgent — Scrapy-backed web research with KnowledgeStore persistence.

Architecture::

    NiblitBrain / ALE / SelfResearcher
         │
         ▼
    ResearchAgent
         │   uses
         ▼
    SerpexAPI  →  ScrapySearchEngine  →  DuckDuckGo HTML scraping
         │
         ▼
    _process_results()
         │
    ┌────┴──────────────────────────────────────┐
    │                                           │
    KnowledgeStore.store_search_results()   VectorStore.add()
    (SQLite persistence)                    (Qdrant embedding, optional)

No external API key is required — Scrapy scrapes DuckDuckGo HTML directly.

Usage::

    from niblit_agents.research_agent import ResearchAgent
    agent = ResearchAgent()
    results = agent.search_web("python asyncio patterns")
    # → [{"title": ..., "url": ..., "snippet": ...}]
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Niblit.ResearchAgent")


# ── is_relevant / should_reflect kept as public API ─────────────────────────

def is_relevant(query: str, text: str, threshold: float = 0.5) -> bool:
    """Return *True* when *text* is semantically relevant to *query*.

    Improvements over the previous simple term-overlap ratio:

    * **Stop-word filtering** — short function words ("is", "the", "a",
      "what", "how", …) are excluded from the query term set before scoring.
      A query like "what is asyncio" should match on "asyncio", not on "what"
      or "is" which appear in almost every English sentence.

    * **At least one substantive match required** — even when threshold is low,
      the text must contain at least one meaningful query term (not just stop
      words) to be considered relevant.

    The caller-supplied *threshold* is always honoured; this function does not
    raise it internally, ensuring existing call sites behave as expected.

    Args:
        query:     The original search query.
        text:      Candidate text to evaluate.
        threshold: Minimum overlap score in [0, 1].  Default 0.5.
    """
    _QUERY_STOP = frozenset({
        "what", "is", "are", "how", "the", "a", "an", "do", "does",
        "you", "know", "about", "tell", "me", "explain", "can", "i",
        "to", "of", "in", "for", "on", "and", "or", "with", "at",
        "by", "from", "its", "it", "this", "that", "will", "would",
        "could", "should", "have", "has", "had", "be", "been", "being",
        "was", "were", "may", "might",
    })

    if not text or not query:
        return not bool(query)

    # Build the set of substantive query terms (≥ 3 chars, not a stop word)
    query_terms = {
        t for t in query.lower().split()
        if len(t) >= 3 and t not in _QUERY_STOP
    }
    # Fallback: use all terms when every word was filtered out (e.g. "a b")
    if not query_terms:
        query_terms = set(query.lower().split())
    if not query_terms:
        return True

    text_lower = text.lower()
    matched = sum(1 for term in query_terms if term in text_lower)

    # Require at least 1 matching substantive term regardless of threshold
    if matched == 0:
        return False

    return (matched / len(query_terms)) >= threshold


def should_reflect(results: list) -> bool:
    """Return *True* when *results* is non-empty (safe to reflect on)."""
    return len(results) > 0


# ─────────────────────────────────────────────────────────────────────────────

class ResearchAgent:
    """Scrapy-backed research agent with KnowledgeStore persistence.

    Searches DuckDuckGo via :class:`~niblit_tools.serpex_api.SerpexAPI` (which
    delegates to :class:`~niblit_tools.scrapy_search.ScrapySearchEngine`) and
    stores results in the Niblit KnowledgeStore.  No external API key is needed.

    The ``serpex_api_key`` parameter is accepted for backward compatibility but
    is no longer required or used.

    Args:
        serpex_api_key:  Accepted for interface compat; ignored.
        knowledge_store: Optional pre-built KnowledgeStore instance.
        qdrant_url:      Qdrant server URL (for optional vector embedding).
        qdrant_api_key:  Qdrant API key.
    """

    def __init__(
        self,
        serpex_api_key: str = "",
        knowledge_store: Optional[Any] = None,
        qdrant_url: str = "",
        qdrant_api_key: str = "",
    ) -> None:
        # serpex_api_key is no longer used but kept for backward compat
        self._serpex_api_key = serpex_api_key
        self._qdrant_url = qdrant_url
        self._qdrant_api_key = qdrant_api_key
        self._knowledge_store: Optional[Any] = knowledge_store
        self._vector_store: Optional[Any] = None

        # Build Scrapy-backed search engine via SerpexAPI shim
        self._serpex: Optional[Any] = self._build_search_engine()

        # Build optional Qdrant VectorStore
        if self._qdrant_url:
            try:
                from modules.vector_store import VectorStore
                self._vector_store = VectorStore(
                    collection="niblit_research",
                    qdrant_url=self._qdrant_url,
                    qdrant_api_key=self._qdrant_api_key,
                )
            except Exception as exc:
                logger.debug("ResearchAgent: VectorStore unavailable: %s", exc)

    # ── builder ──────────────────────────────────────────────────────────────

    @staticmethod
    def _build_search_engine() -> Optional[Any]:
        """Construct a :class:`SerpexAPI` (Scrapy-backed) instance."""
        try:
            from niblit_tools.serpex_api import SerpexAPI
            return SerpexAPI()
        except Exception as exc:
            logger.debug("ResearchAgent: SerpexAPI unavailable: %s", exc)
            return None

    # ── public API ────────────────────────────────────────────────────────────

    def is_configured(self) -> bool:
        """Always ``True`` — Scrapy needs no external API key."""
        return True

    def search_web(self, query: str) -> List[Dict[str, Any]]:
        """Search the web via Scrapy and return normalised result items.

        Args:
            query: Natural-language search query.

        Returns:
            List of ``{"title": str, "url": str, "snippet": str}`` dicts.
        """
        logger.info("[ResearchAgent] search_web: %r", query)
        if self._serpex is None:
            return []
        data = self._serpex.search(query, category="web")
        return self._process_results(data, query=query)

    def search_news(self, query: str) -> List[Dict[str, Any]]:
        """Search for news via Scrapy and return normalised result items.

        Args:
            query: Natural-language search query.

        Returns:
            List of ``{"title": str, "url": str, "snippet": str}`` dicts.
        """
        logger.info("[ResearchAgent] search_news: %r", query)
        if self._serpex is None:
            return []
        data = self._serpex.search(query, category="news", engine="google")
        return self._process_results(data, query=query)

    # ── internals ────────────────────────────────────────────────────────────

    def _knowledge_store_client(self) -> Optional[Any]:
        """Lazily build KnowledgeStore."""
        if self._knowledge_store is None:
            try:
                from niblit_memory import KnowledgeStore
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
        """Extract, filter, persist and embed items from a Serpex API response.

        Args:
            data:                  Serpex response dict (has ``"results"`` key).
            query:                 Original query string (used for relevance check).
            _skip_relevance_check: When *True*, accept all items regardless of
                                   relevance score (used internally to avoid
                                   infinite retry loops).

        Returns:
            List of normalised ``{"title", "url", "snippet"}`` dicts.
        """
        if "error" in data:
            logger.warning("[ResearchAgent] search returned error: %s", data["error"])
            return [{"error": data["error"]}]

        raw_items = (
            data.get("organic_results")
            or data.get("results")
            or []
        )

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
            if query and not _skip_relevance_check and not is_relevant(query, snippet):
                continue
            extracted.append({
                "title":   item.get("title", ""),
                "url":     item.get("url") or item.get("link") or "local://kb",
                "snippet": snippet,
            })

        # When no relevant results found, try a more specific retry query
        if not extracted and raw_items and not _skip_relevance_check and self._serpex is not None:
            retry_query = f"{query} definition explanation"
            retry_data = self._serpex.search(retry_query, category="web")
            retry_raw = (
                retry_data.get("organic_results")
                or retry_data.get("results")
                or []
            )
            for item in retry_raw:
                if not isinstance(item, dict):
                    continue
                snippet = item.get("snippet") or item.get("description") or ""
                if not snippet:
                    continue
                extracted.append({
                    "title":   item.get("title", ""),
                    "url":     item.get("url") or item.get("link") or "local://kb",
                    "snippet": snippet,
                })

        # Persist to KnowledgeStore
        ks = self._knowledge_store_client()
        if ks is not None and extracted:
            try:
                ks.store_search_results(query, extracted)
            except Exception as exc:
                logger.debug("[ResearchAgent] KnowledgeStore store failed: %s", exc)

        # Embed to vector store
        if self._vector_store is not None:
            for item in extracted:
                snippet = item.get("snippet", "")
                if snippet:
                    try:
                        self._vector_store.add(snippet, metadata=item)
                    except Exception as exc:
                        logger.debug("[ResearchAgent] VectorStore add failed: %s", exc)

        return extracted


if __name__ == "__main__":
    print('Running research_agent.py')
