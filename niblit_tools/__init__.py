"""niblit_tools — Niblit external-API tool wrappers.

Public API
----------
``tool``            — decorator to register a function as a Niblit tool
``get_registry``    — return the module-level :class:`ToolRegistry` singleton
``ToolRegistry``    — class for managing and invoking registered tools
``SerpexAPI``       — Scrapy-backed web-search client
``niblit_serpex_search`` — tool function for NiblitBrain / MCP
``NIBLIT_SERPEX_TOOL``   — OpenAI-style tool definition dict

Built-in tools (auto-registered, LangChain-inspired)
-----------------------------------------------------
``calculator``      — Safely evaluate arithmetic / math expressions
``get_datetime``    — Return the current UTC date and/or time
``word_count``      — Count words, characters, and lines in text
``kb_query``        — Search Niblit's knowledge base for stored facts
``list_commands``   — List all Niblit shell commands
``summarise_text``  — Truncate long text to a concise excerpt
"""

from niblit_tools.tool_registry import tool, get_registry, ToolRegistry
from niblit_tools.serpex_api import (
    SerpexAPI,
    niblit_serpex_search,
    NIBLIT_SERPEX_TOOL,
)
from niblit_tools.builtin_tools import (
    calculator,
    get_datetime,
    word_count,
    kb_query,
    list_commands,
    summarise_text,
)

__all__ = [
    "tool",
    "get_registry",
    "ToolRegistry",
    "SerpexAPI",
    "niblit_serpex_search",
    "NIBLIT_SERPEX_TOOL",
    "calculator",
    "get_datetime",
    "word_count",
    "kb_query",
    "list_commands",
    "summarise_text",
]
if __name__ == "__main__":
    print('Running __init__.py')
