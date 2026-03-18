# niblit_agents/research_agent.py
"""
Niblit ResearchAgent — SQLite-backed local research agent.

All Serpex HTTP calls have been replaced with queries against Niblit's own
KnowledgeDB (SQLite).  The full public interface is preserved so every
caller (NiblitBrain, ALE, InternetManager, tests, etc.) works unchanged.

Architecture::

    NiblitBrain / ALE / SelfResearcher
         │
         ▼
    ResearchAgent
         │
         ▼
    SQLiteResearcher          ← queries local KnowledgeDB (niblit.db)
         │
    ┌────┴──────────────────────────────────────┐
    │                                           │
    KnowledgeDB.search()              KnowledgeDB.recall()
    (facts + learning_log)            (events + interactions)
         │                                     │
         └──────────────────┬──────────────────┘
                            │
                _process_results()
                            │
                KnowledgeStore (SQLite)   ← store_search_results()
                            │
                (optional) Qdrant embeddings  →  VectorStore

Usage::

    from niblit_agents.research_agent import ResearchAgent
    agent = ResearchAgent()
    results = agent.search_web("python asyncio patterns")
    # → [{"title": ..., "url": "local://kb/...", "snippet": ...}]
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Niblit.ResearchAgent")


# ── is_relevant / should_reflect kept as public API ─────────────────────────

def is_relevant(query: str, text: str, threshold: float = 0.3) -> bool:
    """Return *True* when *text* is semantically relevant to *query*.

    Uses simple term-overlap.  Threshold lowered to 0.3 (vs. 0.5) because
    local KB results are already filtered to Niblit's own research domain.

    Args:
        query:     The original search query.
        text:      Candidate text to evaluate.
        threshold: Minimum overlap score in ``[0, 1]``.  Default ``0.3``.
    """
    query_terms = set(query.lower().split())
    if not query_terms:
        return True
    text_lower = text.lower()
    overlap = sum(1 for term in query_terms if term in text_lower)
    return (overlap / len(query_terms)) >= threshold


def should_reflect(results: list) -> bool:
    """Return *True* when *results* is non-empty (safe to reflect on)."""
    return len(results) > 0


# ─────────────────────────────────────────────────────────────────────────────

class ResearchAgent:
    """SQLite-backed research agent — drop-in replacement for former Serpex agent.

    Args:
        serpex_api_key:  Accepted but ignored (kept for interface compatibility).
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
        # serpex_api_key accepted but not used — kept for compat
        self._qdrant_url = qdrant_url
        self._qdrant_api_key = qdrant_api_key
        self._knowledge_store: Optional[Any] = knowledge_store
        self._vector_store: Optional[Any] = None

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

        # Build the SQLiteResearcher backend
        self._researcher = self._build_researcher(knowledge_store, self._vector_store)

    # ── builder ──────────────────────────────────────────────────────────────

    @staticmethod
    def _build_researcher(knowledge_store=None, vector_store=None):
        try:
            from modules.sqlite_researcher import SQLiteResearcher
            return SQLiteResearcher(
                knowledge_store=knowledge_store,
                vector_store=vector_store,
            )
        except Exception as exc:
            logger.debug("ResearchAgent: SQLiteResearcher unavailable: %s", exc)
            return None

    # ── public API ────────────────────────────────────────────────────────────

    def is_configured(self) -> bool:
        """Always True — SQLite is always available, no API key needed."""
        return True

    def search_web(self, query: str) -> List[Dict[str, Any]]:
        """Search local KnowledgeDB and return normalised result items.

        Compatible with the former Serpex-backed search_web().

        Args:
            query: Natural-language search query.

        Returns:
            List of ``{"title": str, "url": str, "snippet": str}`` dicts.
        """
        logger.info("[ResearchAgent] search_web: %r", query)
        if self._researcher:
            return self._researcher.search_web(query)
        return []

    def search_news(self, query: str) -> List[Dict[str, Any]]:
        """Search local KnowledgeDB for recent entries matching *query*.

        Compatible with the former Serpex-backed search_news().

        Args:
            query: Natural-language search query.

        Returns:
            List of ``{"title": str, "url": str, "snippet": str}`` dicts.
        """
        logger.info("[ResearchAgent] search_news: %r", query)
        if self._researcher:
            return self._researcher.search_news(query)
        return []

    # ── internals kept for backward compat (no longer call Serpex) ───────────

    def _serpex_client(self) -> Any:
        """Return the SQLiteAPI instance (former SerpexAPI replacement)."""
        try:
            from niblit_tools.serpex_api import SQLiteAPI
            return SQLiteAPI()
        except Exception:
            return None

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
        """Extract structured items from a SQLiteAPI search() response envelope.

        Accepts the dict returned by ``SQLiteAPI.search()`` (which has the
        same shape as the former Serpex JSON response) and normalises it into
        ``[{"title", "url", "snippet"}]`` dicts.
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

        return extracted

