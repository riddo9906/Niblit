# niblit_tools/serpex_api.py
"""
Niblit Search API — SQLite-backed local research (replaces Serpex).

All external HTTP calls to api.serpex.dev have been replaced with queries
against Niblit's own SQLite KnowledgeDB.  The public interface is fully
preserved so every caller (NiblitBrain, ALE, InternetManager, tests, etc.)
continues to work without modification.

Architecture::

    NiblitBrain
         │  tool call
         ▼
    niblit_serpex_search()          ← same function name kept for compat
         │
         ▼
    SQLiteResearcher               ← new: local KB search, no HTTP
         │
         ▼
    KnowledgeDB (SQLite)  →  KnowledgeStore  →  (optional) Qdrant
"""

import logging
from typing import Any, Dict, List

logger = logging.getLogger("Niblit.SearchAPI")

# ── lazy import of SQLiteResearcher so circular imports are avoided ──────────
_sqlite_researcher = None


def _get_sqlite_researcher():
    """Return a shared SQLiteResearcher instance (built once on first call)."""
    global _sqlite_researcher
    if _sqlite_researcher is None:
        try:
            from modules.sqlite_researcher import SQLiteResearcher
            _sqlite_researcher = SQLiteResearcher()
        except Exception as exc:
            logger.debug("SQLiteResearcher unavailable: %s", exc)
    return _sqlite_researcher


# ── ResearchAgent shim — kept for backward-compat imports ───────────────────
try:
    from niblit_agents.research_agent import ResearchAgent as _ResearchAgent
    _RESEARCH_AGENT_AVAILABLE = True
except Exception:
    _ResearchAgent = None  # type: ignore[assignment,misc]
    _RESEARCH_AGENT_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# SQLiteAPI  (drop-in replacement for the former SerpexAPI class)
# ─────────────────────────────────────────────────────────────────────────────

class SQLiteAPI:
    """Local-database search backend — replaces the former SerpexAPI HTTP wrapper.

    Queries Niblit's KnowledgeDB (SQLite) instead of calling api.serpex.dev.
    Returns the same response envelope so all existing callers work unchanged.

    No API key is required.  ``is_configured()`` always returns ``True``.
    """

    def __init__(self, api_key: str = None) -> None:
        # api_key accepted but ignored — kept for interface compatibility
        self._researcher = _get_sqlite_researcher()

    def is_configured(self) -> bool:
        """Always True — SQLite is always available."""
        return True

    def search(
        self,
        query: str,
        category: str = "web",
        engine: str = "auto",
        time_range: str = "day",
    ) -> Dict[str, Any]:
        """Search local KnowledgeDB and return a Serpex-envelope-compatible dict.

        Args:
            query:      Search query string.
            category:   ``"web"`` or ``"news"`` (both use KnowledgeDB).
            engine:     Ignored (kept for compat).
            time_range: Ignored (kept for compat).

        Returns:
            Dict with ``"organic_results"``, ``"results"``, ``"source": "sqlite"``
            keys — the same shape as the former Serpex JSON response.
        """
        researcher = self._researcher or _get_sqlite_researcher()
        if researcher is None:
            return {"results": [], "organic_results": [], "source": "sqlite", "error": "KnowledgeDB unavailable"}
        return researcher.search(query, category=category)


# ── Keep SerpexAPI as an alias so any ``from niblit_tools.serpex_api import SerpexAPI``
# statement continues to work without modification.
SerpexAPI = SQLiteAPI


# ─────────────────────────────────────────────────────────────────────────────
# Tool function for NiblitBrain (GPT)
# ─────────────────────────────────────────────────────────────────────────────

def niblit_serpex_search(query: str, category: str = "web") -> List[Dict[str, Any]]:
    """Tool function exposed to NiblitBrain.

    Delegates to ResearchAgent (which now uses SQLiteResearcher internally)
    so results are normalised, stored in KnowledgeStore, and optionally
    embedded in Qdrant.

    Args:
        query:    Search query string.
        category: ``"web"`` (default) or ``"news"``.

    Returns:
        List of ``{"title", "url", "snippet"}`` dicts.
    """
    # Prefer the full ResearchAgent pipeline (stores results in KB automatically)
    if _RESEARCH_AGENT_AVAILABLE and _ResearchAgent is not None:
        try:
            agent = _ResearchAgent()
            if category == "news":
                return agent.search_news(query)
            return agent.search_web(query)
        except Exception as exc:
            logger.debug("[niblit_serpex_search] ResearchAgent failed: %s", exc)

    # Fallback: direct SQLiteResearcher
    researcher = _get_sqlite_researcher()
    if researcher:
        try:
            if category == "news":
                return researcher.search_news(query)
            return researcher.search_web(query)
        except Exception as exc:
            logger.error("[niblit_serpex_search] SQLiteResearcher failed: %s", exc)

    return [{"error": "Search backend unavailable"}]


# ─────────────────────────────────────────────────────────────────────────────
# GPT tool definition (for NiblitBrain tool registry) — unchanged
# ─────────────────────────────────────────────────────────────────────────────

NIBLIT_SERPEX_TOOL: Dict[str, Any] = {
    "name": "niblit_serpex_search",
    "description": (
        "Search Niblit's local knowledge base for information on a topic. "
        "Returns structured results from stored research, facts, and learning data."
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
                "description": "Search type: 'web' for general knowledge, 'news' for recent data.",
            },
        },
        "required": ["query"],
    },
}

if __name__ == "__main__":
    print("niblit_tools/serpex_api.py — SQLite-backed search (replaces Serpex)")

