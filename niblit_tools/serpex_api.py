# niblit_tools/serpex_api.py
"""
Niblit Search API — SerpexAPI (HTTP) + SQLiteAPI (local fallback).

Architecture::

    NiblitBrain
         │  tool call
         ▼
    niblit_serpex_search()
         │
         ├─ ResearchAgent (uses SerpexAPI HTTP when key is configured)
         │
         └─ SQLiteResearcher (local KB fallback when no key)
"""

import logging
import os

import requests  # noqa: F401 — kept at module level so tests can patch it

from typing import Any, Dict, List

logger = logging.getLogger("Niblit.SearchAPI")

_SERPEX_API_URL = os.getenv("SERPEX_API_URL", "https://api.serpex.dev/api/search")

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


# ── ResearchAgent import — used by niblit_serpex_search ─────────────────────
try:
    from niblit_agents.research_agent import ResearchAgent as _ResearchAgent
    _RESEARCH_AGENT_AVAILABLE = True
except Exception:
    _ResearchAgent = None  # type: ignore[assignment,misc]
    _RESEARCH_AGENT_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# SerpexAPI  — HTTP-based search client for api.serpex.dev
# ─────────────────────────────────────────────────────────────────────────────

class SerpexAPI:
    """HTTP client for the Serpex search API (api.serpex.dev).

    Requires ``SERPEX_API_KEY`` either via the *api_key* constructor argument
    or the environment variable of the same name.

    Args:
        api_key: Serpex API key.  Falls back to ``SERPEX_API_KEY`` env var.

    Raises:
        ValueError: When no API key is available.
    """

    def __init__(self, api_key: str = None) -> None:
        resolved = api_key or os.getenv("SERPEX_API_KEY", "") or ""
        if not resolved:
            raise ValueError(
                "SERPEX_API_KEY is required.  Pass api_key= or set the "
                "SERPEX_API_KEY environment variable."
            )
        self.api_key: str = resolved

    def is_configured(self) -> bool:
        """Return *True* when an API key is present."""
        return bool(self.api_key)

    def search(
        self,
        query: str,
        category: str = "web",
        engine: str = "auto",
        time_range: str = "day",
    ) -> Dict[str, Any]:
        """Send a search request to the Serpex API.

        Args:
            query:      Search query string.
            category:   ``"web"`` or ``"news"``.
            engine:     Search engine hint (e.g. ``"google"``).
            time_range: Time filter for web results (e.g. ``"day"``, ``"week"``).
                        Omitted for news searches.

        Returns:
            Parsed JSON dict from the Serpex API, or ``{"error": ...}`` on
            failure.
        """
        params: Dict[str, Any] = {"q": query, "category": category}
        if engine and engine != "auto":
            params["engine"] = engine
        if category != "news":
            params["time_range"] = time_range

        headers = {"Authorization": f"Bearer {self.api_key}"}
        try:
            resp = requests.get(_SERPEX_API_URL, params=params, headers=headers, timeout=10)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error("[SerpexAPI] search failed: %s", exc)
            return {"error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# SQLiteAPI  — local-database search backend (no API key required)
# ─────────────────────────────────────────────────────────────────────────────

class SQLiteAPI:
    """Local-database search backend backed by Niblit's KnowledgeDB (SQLite).

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
        """Search local KnowledgeDB, returning a Serpex-envelope-compatible dict."""
        researcher = self._researcher or _get_sqlite_researcher()
        if researcher is None:
            return {"results": [], "organic_results": [], "source": "sqlite", "error": "KnowledgeDB unavailable"}
        return researcher.search(query, category=category)


# ─────────────────────────────────────────────────────────────────────────────
# Tool function for NiblitBrain (GPT)
# ─────────────────────────────────────────────────────────────────────────────

def niblit_serpex_search(query: str, category: str = "web") -> List[Dict[str, Any]]:
    """Tool function exposed to NiblitBrain.

    Delegates to ResearchAgent (which uses SerpexAPI when configured, otherwise
    falls back to SQLiteResearcher) so results are normalised, stored in
    KnowledgeStore, and optionally embedded in Qdrant.

    Args:
        query:    Search query string.
        category: ``"web"`` (default) or ``"news"``.

    Returns:
        List of ``{"title", "url", "snippet"}`` dicts.
    """
    # Prefer the full ResearchAgent pipeline
    if _RESEARCH_AGENT_AVAILABLE and _ResearchAgent is not None:
        try:
            agent = _ResearchAgent()
            if category == "news":
                return agent.search_news(query)
            return agent.search_web(query)
        except Exception as exc:
            logger.debug("[niblit_serpex_search] ResearchAgent failed: %s", exc)
            return [{"error": str(exc)}]

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
# GPT tool definition (for NiblitBrain tool registry)
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
    print("niblit_tools/serpex_api.py — SerpexAPI (HTTP) + SQLiteAPI (local fallback)")

