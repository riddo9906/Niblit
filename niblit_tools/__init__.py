"""niblit_tools — Niblit external-API tool wrappers.

Public API
----------
``tool``            — decorator to register a function as a Niblit tool
``get_registry``    — return the module-level :class:`ToolRegistry` singleton
``ToolRegistry``    — class for managing and invoking registered tools
``SerpexAPI``       — Scrapy-backed web-search client
``niblit_serpex_search`` — tool function for NiblitBrain / MCP
``NIBLIT_SERPEX_TOOL``   — OpenAI-style tool definition dict
"""

from niblit_tools.tool_registry import tool, get_registry, ToolRegistry
from niblit_tools.serpex_api import (
    SerpexAPI,
    niblit_serpex_search,
    NIBLIT_SERPEX_TOOL,
)

__all__ = [
    "tool",
    "get_registry",
    "ToolRegistry",
    "SerpexAPI",
    "niblit_serpex_search",
    "NIBLIT_SERPEX_TOOL",
]
