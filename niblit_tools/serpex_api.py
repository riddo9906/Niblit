# niblit_tools/serpex_api.py
"""
Niblit Serpex API Wrapper + NiblitBrain tool function.

Provides:
  - :class:`SerpexAPI`          — thin HTTP wrapper around api.serpex.dev
  - :func:`niblit_serpex_search` — tool function exposed to NiblitBrain (GPT)
  - :data:`NIBLIT_SERPEX_TOOL`  — GPT tool definition dict

Architecture::

    NiblitBrain
         │  tool call
         ▼
    niblit_serpex_search()
         │
         ▼
    ResearchAgent   (niblit_agents/research_agent.py)
         │
         ▼
    SerpexAPI  ──►  api.serpex.dev
         │
         ▼
    KnowledgeStore  (niblit_memory/knowledge_store.py)
         │
         ▼
    (optional) Qdrant embeddings  →  SemanticAgent
"""

import logging
import os
from typing import Any, Dict, List

import requests

logger = logging.getLogger("Niblit.Serpex")

_SERPEX_BASE_URL = "https://api.serpex.dev/api/search"

# Module-level import so tests can patch niblit_tools.serpex_api.ResearchAgent
try:
    from niblit_agents.research_agent import ResearchAgent as _ResearchAgent
    _RESEARCH_AGENT_AVAILABLE = True
except Exception:  # noqa: BLE001 — library may not be on path yet
    _ResearchAgent = None  # type: ignore[assignment,misc]
    _RESEARCH_AGENT_AVAILABLE = False


# ─────────────────────────────────────────────────────────────────────────────
# SerpexAPI wrapper
# ─────────────────────────────────────────────────────────────────────────────

class SerpexAPI:
    """
    Thin HTTP wrapper around the Serpex search API.

    Args:
        api_key: Serpex API key.  Falls back to ``SERPEX_API_KEY`` env var.

    Raises:
        ValueError: when no API key is available.
    """

    def __init__(self, api_key: str = None) -> None:
        self.api_key: str = api_key or os.getenv("SERPEX_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "SERPEX_API_KEY is required. "
                "Set it via the constructor argument or the SERPEX_API_KEY environment variable."
            )
        self.base_url: str = _SERPEX_BASE_URL

    def search(
        self,
        query: str,
        category: str = "web",
        engine: str = "auto",
        time_range: str = "day",
    ) -> Dict[str, Any]:
        """
        Perform a search using the Serpex API.

        Args:
            query:      Search query string.
            category:   ``"web"`` or ``"news"``.
            engine:     ``"auto"``, ``"google"``, etc.
            time_range: ``"day"``, ``"week"``, or ``"month"`` (web only).

        Returns:
            Parsed JSON response dict, or ``{"error": str}`` on failure.
        """
        headers = {"Authorization": f"Bearer {self.api_key}"}
        params: Dict[str, str] = {
            "q": query,
            "engine": engine,
            "category": category,
        }
        # Only apply time_range for web searches
        if category == "web":
            params["time_range"] = time_range

        try:
            response = requests.get(
                self.base_url, headers=headers, params=params, timeout=10
            )
            response.raise_for_status()
            data = response.json()
            logger.info(
                "[Serpex] query=%r category=%s results=%d",
                query,
                category,
                len(data.get("results", [])),
            )
            return data
        except Exception as exc:
            logger.error("[Serpex ERROR] %s", exc)
            return {"error": str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# Tool function for NiblitBrain
# ─────────────────────────────────────────────────────────────────────────────

def niblit_serpex_search(query: str, category: str = "web") -> List[Dict[str, Any]]:
    """
    Tool function exposed to NiblitBrain (GPT).

    Delegates to :class:`~niblit_agents.research_agent.ResearchAgent` so that
    results are automatically normalised, stored in :class:`KnowledgeStore`,
    and optionally embedded in Qdrant.

    Args:
        query:    Search query string.
        category: ``"web"`` (default) or ``"news"``.

    Returns:
        List of ``{"title", "url", "snippet"}`` dicts, or an error dict.
    """
    try:
        agent = _ResearchAgent()
        if category == "news":
            return agent.search_news(query)
        return agent.search_web(query)
    except Exception as exc:
        logger.error("[niblit_serpex_search] %s", exc)
        return [{"error": str(exc)}]


# ─────────────────────────────────────────────────────────────────────────────
# GPT tool definition (for NiblitBrain tool registry)
# ─────────────────────────────────────────────────────────────────────────────

NIBLIT_SERPEX_TOOL: Dict[str, Any] = {
    "name": "niblit_serpex_search",
    "description": "Perform a web or news search using the Serpex API and return structured results.",
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
                "description": "Search type: 'web' for general web search, 'news' for recent news.",
            },
        },
        "required": ["query"],
    },
}

if __name__ == "__main__":
    print("Running niblit_tools/serpex_api.py")
