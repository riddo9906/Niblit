# niblit_tools/serpex_api.py
"""
Niblit Search API — Scrapy-backed search engine.

:class:`SerpexAPI` now uses :class:`~niblit_tools.scrapy_search.ScrapySearchEngine`
under the hood, scraping DuckDuckGo HTML results directly.  No external API
key is required.

Architecture::

    NiblitBrain
         │  tool call
         ▼
    niblit_serpex_search()
         │
         ▼
    ResearchAgent  (niblit_agents/research_agent.py)
         │  uses
         ▼
    SerpexAPI  →  ScrapySearchEngine  →  DuckDuckGo HTML scraping
         │
         ▼
    KnowledgeStore  (niblit_memory)  +  (optional) Qdrant
"""

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger("Niblit.SearchAPI")


# ── ResearchAgent import — used by niblit_serpex_search ─────────────────────
try:
    from niblit_agents.research_agent import ResearchAgent as _ResearchAgent
    _RESEARCH_AGENT_AVAILABLE = True
except Exception:
    _ResearchAgent = None  # type: ignore[assignment,misc]
    _RESEARCH_AGENT_AVAILABLE = False


# ── shared ScrapySearchEngine singleton ─────────────────────────────────────
_scrapy_engine = None


def _get_scrapy_engine() -> Any:
    """Return a shared :class:`ScrapySearchEngine` (created once on first call)."""
    global _scrapy_engine
    if _scrapy_engine is None:
        try:
            from niblit_tools.scrapy_search import ScrapySearchEngine
            _scrapy_engine = ScrapySearchEngine()
        except Exception as exc:
            logger.debug("ScrapySearchEngine unavailable: %s", exc)
    return _scrapy_engine


# ─────────────────────────────────────────────────────────────────────────────
# SerpexAPI  — Scrapy-backed search (replaces former api.serpex.dev HTTP calls)
# ─────────────────────────────────────────────────────────────────────────────

class SerpexAPI:
    """Scrapy-backed search client.

    Previously called the Serpex HTTP API; now scrapes DuckDuckGo via Scrapy
    so no external API key is required.  The public interface is fully
    preserved — all callers (NiblitBrain, ALE, ResearchAgent, tests, etc.)
    work without modification.

    Args:
        api_key: Accepted for interface compatibility; no longer required or used.
    """

    def __init__(self, api_key: str = None) -> None:
        # api_key kept as an accepted parameter for backward compat; not used.
        self._engine = _get_scrapy_engine()

    def is_configured(self) -> bool:
        """Always ``True`` — Scrapy is always available, no API key needed."""
        return True

    def search(
        self,
        query: str,
        category: str = "web",
        engine: str = "auto",
        time_range: str = "day",
    ) -> Dict[str, Any]:
        """Search DuckDuckGo via Scrapy and return a normalised result dict.

        Args:
            query:      Search query string.
            category:   ``"web"`` or ``"news"``.
            engine:     Ignored (kept for interface compatibility).
            time_range: Ignored (kept for interface compatibility).

        Returns:
            ``{"results": [{"title": str, "url": str, "snippet": str}, ...]}``
            or ``{"results": [], "error": str}`` on failure.
        """
        scrapy_engine = self._engine or _get_scrapy_engine()
        if scrapy_engine is None:
            return {"results": [], "error": "ScrapySearchEngine unavailable"}
        return scrapy_engine.search(query, category=category)


# ── SQLiteAPI kept for backward compat imports ───────────────────────────────

class SQLiteAPI:
    """Local-database search backend (fallback when Scrapy is unavailable)."""

    def __init__(self, api_key: str = None) -> None:
        self._researcher = None
        try:
            from modules.sqlite_researcher import SQLiteResearcher
            self._researcher = SQLiteResearcher()
        except Exception as exc:
            logger.debug("SQLiteResearcher unavailable: %s", exc)

    def is_configured(self) -> bool:
        return True

    def search(
        self,
        query: str,
        category: str = "web",
        engine: str = "auto",
        time_range: str = "day",
    ) -> Dict[str, Any]:
        if self._researcher is None:
            return {"results": [], "error": "KnowledgeDB unavailable"}
        return self._researcher.search(query, category=category)


# ─────────────────────────────────────────────────────────────────────────────
# Tool function for NiblitBrain (GPT)
# ─────────────────────────────────────────────────────────────────────────────

def niblit_serpex_search(query: str, category: str = "web") -> List[Dict[str, Any]]:
    """Tool function exposed to NiblitBrain.

    Delegates to ResearchAgent (which now uses ScrapySearchEngine internally)
    so results are normalised, stored in KnowledgeStore, and optionally
    embedded in Qdrant.

    Args:
        query:    Search query string.
        category: ``"web"`` (default) or ``"news"``.

    Returns:
        List of ``{"title", "url", "snippet"}`` dicts, or an error dict.
    """
    if _RESEARCH_AGENT_AVAILABLE and _ResearchAgent is not None:
        try:
            agent = _ResearchAgent()
            if category == "news":
                return agent.search_news(query)
            return agent.search_web(query)
        except Exception as exc:
            logger.debug("[niblit_serpex_search] ResearchAgent failed: %s", exc)
            return [{"error": str(exc)}]

    # Fallback: direct ScrapySearchEngine
    scrapy_engine = _get_scrapy_engine()
    if scrapy_engine:
        try:
            data = scrapy_engine.search(query, category=category)
            return data.get("results", [])
        except Exception as exc:
            logger.error("[niblit_serpex_search] ScrapySearchEngine failed: %s", exc)

    return [{"error": "Search backend unavailable"}]


# ─────────────────────────────────────────────────────────────────────────────
# GPT tool definition (for NiblitBrain tool registry)
# ─────────────────────────────────────────────────────────────────────────────

NIBLIT_SERPEX_TOOL: Dict[str, Any] = {
    "name": "niblit_serpex_search",
    "description": (
        "Search the web for information on a topic using Scrapy. "
        "Returns structured results scraped from DuckDuckGo."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "category": {
                "type": "string",
                "enum": ["web", "news"],
                "description": "Search type: 'web' for general search, 'news' for recent news.",
            },
        },
        "required": ["query"],
    },
}

if __name__ == "__main__":
    print("niblit_tools/serpex_api.py — Scrapy-backed search (DuckDuckGo)")

