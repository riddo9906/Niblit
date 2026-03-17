#!/usr/bin/env python3
"""
modules/searchcode_search.py — searchcode.com code-search client for Niblit.

Provides a unified interface over two complementary transports:

1. **REST API** — ``https://searchcode.com/api/`` — no authentication required.
   Returns indexed code snippets from open-source repositories (GitHub, Bitbucket,
   GitLab, Google Code, etc.) with full file context.

2. **MCP endpoint** — ``https://api.searchcode.com/v1/mcp`` — the official
   searchcode MCP server.  Any MCP-compatible client can discover and call it
   directly.  Niblit uses it programmatically via JSON-RPC POST when the URL is
   reachable.

   To register it in Claude Desktop / other MCP clients::

       claude mcp add searchcode \\
         --transport http \\
         https://api.searchcode.com/v1/mcp

Both transports are optional — the class degrades gracefully:

* When ``SEARCHCODE_MCP_URL`` is set *and* reachable, MCP calls are used for
  ``search_code()``.
* Otherwise the public REST API is used (no key needed).
* All methods return normalised ``{"text", "url", "filename", "language", "source"}``
  dicts compatible with the format used by :class:`~modules.github_code_search.GitHubCodeSearch`
  so downstream consumers (ALE, MCP tools) can treat all code-search backends
  uniformly.

Configuration (env vars)
------------------------
``SEARCHCODE_API_URL``  — REST base URL (default: ``https://searchcode.com/api``).
``SEARCHCODE_MCP_URL``  — MCP endpoint URL (default: ``https://api.searchcode.com/v1/mcp``).

Usage::

    from modules.searchcode_search import SearchcodeSearch
    sc = SearchcodeSearch()
    results = sc.search_code("async context manager python")
    patterns = sc.discover_patterns("python", "decorator")
    research = sc.research_for_code_generation("python", "asyncio")
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("SearchcodeSearch")

# ── API constants ─────────────────────────────────────────────────────────────
_DEFAULT_REST_URL = "https://searchcode.com/api"
_DEFAULT_MCP_URL = "https://api.searchcode.com/v1/mcp"

SEARCHCODE_API_URL: str = os.getenv("SEARCHCODE_API_URL", _DEFAULT_REST_URL).rstrip("/")
SEARCHCODE_MCP_URL: str = os.getenv("SEARCHCODE_MCP_URL", _DEFAULT_MCP_URL)

# searchcode REST endpoints
_REST_CODE_SEARCH = f"{SEARCHCODE_API_URL}/codesearch_I/"
_REST_CODE_RESULT = f"{SEARCHCODE_API_URL}/result/"

# Request throttle — searchcode public API has no documented rate limit but is
# a shared public service; 1 s between calls is polite and avoids 429s.
_MIN_REQUEST_INTERVAL: float = 1.0
_MAX_ITEMS_PER_REQUEST: int = 10
_MAX_FRAGMENT_LENGTH: int = 500
_REQUEST_TIMEOUT: int = 10

# ── Language aliases → searchcode language filter values ──────────────────────
_LANG_MAP: Dict[str, str] = {
    "python":     "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "java":       "Java",
    "go":         "Go",
    "rust":       "Rust",
    "c":          "C",
    "cpp":        "C++",
    "csharp":     "C#",
    "ruby":       "Ruby",
    "php":        "PHP",
    "bash":       "Bash",
    "shell":      "Bash",
    "html":       "HTML",
    "css":        "CSS",
    "sql":        "SQL",
    "kotlin":     "Kotlin",
    "swift":      "Swift",
}

# ── Pattern query templates ────────────────────────────────────────────────────
_PATTERN_QUERIES: Dict[str, List[str]] = {
    "decorator":       ["decorator pattern example", "@decorator function class"],
    "context_manager": ["context manager __enter__ __exit__", "with statement contextlib"],
    "async":           ["async await asyncio example", "coroutine gather task"],
    "error_handling":  ["try except finally custom exception", "error handling best practice"],
    "type_hints":      ["type hints annotation Optional Union", "TypedDict dataclass"],
    "generator":       ["generator yield expression", "itertools lazy evaluation"],
    "singleton":       ["singleton pattern class", "__new__ instance creation"],
    "factory":         ["factory method create instance", "classmethod factory pattern"],
    "observer":        ["observer pattern event listener", "callback subscribe emit"],
    "dataclass":       ["dataclass field default", "@dataclass frozen slots"],
}


class SearchcodeSearch:
    """
    Code-search client for searchcode.com.

    Combines the public REST API with the optional MCP endpoint for maximum
    coverage.  All results are normalised to dicts matching the format used
    by :class:`~modules.github_code_search.GitHubCodeSearch`.

    Args:
        api_url:  searchcode REST base URL.  Defaults to ``SEARCHCODE_API_URL``
                  env var or ``https://searchcode.com/api``.
        mcp_url:  searchcode MCP endpoint URL.  Defaults to ``SEARCHCODE_MCP_URL``
                  env var or ``https://api.searchcode.com/v1/mcp``.
        timeout:  HTTP request timeout in seconds.
        prefer_mcp: When True, attempt MCP transport first (falls back to REST
                    automatically if MCP is unreachable).
    """

    def __init__(
        self,
        api_url: Optional[str] = None,
        mcp_url: Optional[str] = None,
        timeout: int = _REQUEST_TIMEOUT,
        prefer_mcp: bool = True,
    ) -> None:
        self.api_url: str = (api_url or SEARCHCODE_API_URL).rstrip("/")
        self.mcp_url: str = mcp_url or SEARCHCODE_MCP_URL
        self.timeout: int = timeout
        self.prefer_mcp: bool = prefer_mcp
        self._last_request_time: float = 0.0
        self._mcp_available: Optional[bool] = None  # None = not yet probed

    # ── availability ─────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Always True — the public REST API requires no authentication."""
        return True

    def mcp_is_available(self) -> bool:
        """Return True if the MCP endpoint is reachable (lazy-probed once)."""
        if self._mcp_available is not None:
            return self._mcp_available
        try:
            resp = requests.post(
                self.mcp_url,
                json={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
                timeout=5,
            )
            self._mcp_available = resp.status_code in (200, 204)
        except Exception:
            self._mcp_available = False
        return bool(self._mcp_available)

    # ── rate limiting ─────────────────────────────────────────────────────────

    def _rate_limit_wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_time = time.monotonic()

    # ── MCP transport ─────────────────────────────────────────────────────────

    def _mcp_search(self, query: str, language: str = "", max_results: int = 5) -> List[Dict[str, Any]]:
        """Call the searchcode MCP endpoint via JSON-RPC (tools/call)."""
        arguments: Dict[str, Any] = {"query": query, "per_page": min(max_results, _MAX_ITEMS_PER_REQUEST)}
        if language:
            arguments["language"] = _LANG_MAP.get(language.lower(), language)
        try:
            resp = requests.post(
                self.mcp_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "search_code", "arguments": arguments},
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.debug("[Searchcode/MCP] request failed: %s", exc)
            self._mcp_available = False
            return []

        # Unwrap MCP content array
        result = data.get("result") or {}
        content = result.get("content") or []
        items: List[Dict[str, Any]] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            text = block.get("text", "")
            if text and len(text) > 10:
                items.append({
                    "source": "searchcode_mcp",
                    "text": text[:_MAX_FRAGMENT_LENGTH],
                    "url": block.get("url", ""),
                    "filename": block.get("filename", ""),
                    "language": block.get("language", language),
                })
        return items[:max_results]

    # ── REST transport ────────────────────────────────────────────────────────

    def _rest_search(self, query: str, language: str = "", max_results: int = 5) -> List[Dict[str, Any]]:
        """Call the searchcode REST codesearch_I endpoint."""
        self._rate_limit_wait()
        params: Dict[str, Any] = {
            "q": query,
            "per_page": min(max_results, _MAX_ITEMS_PER_REQUEST),
            "p": 0,
        }
        if language:
            # searchcode accepts language as a filter parameter
            lang_value = _LANG_MAP.get(language.lower(), language)
            params["lan"] = lang_value

        try:
            resp = requests.get(
                f"{self.api_url}/codesearch_I/",
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.debug("[Searchcode/REST] search request failed: %s", exc)
            return []

        results: List[Dict[str, Any]] = []
        for item in (data.get("results") or []):
            if not isinstance(item, dict):
                continue
            filename = item.get("filename") or item.get("name") or ""
            repo = item.get("repo") or ""
            lang = item.get("language") or language
            url = item.get("url") or ""

            # Build a text snippet from the 'lines' map (line_number → code_line)
            lines_map = item.get("lines") or {}
            snippet_lines = [str(v) for _, v in sorted(lines_map.items())][:20]
            snippet = "\n".join(snippet_lines).strip()
            if not snippet:
                snippet = item.get("snippet") or f"[{filename}]"

            results.append({
                "source": "searchcode_rest",
                "text": snippet[:_MAX_FRAGMENT_LENGTH],
                "url": url,
                "filename": filename,
                "repo": repo,
                "language": lang,
            })

        log.debug("[Searchcode/REST] %r → %d results", query, len(results))
        return results[:max_results]

    # ── public API ────────────────────────────────────────────────────────────

    def search_code(
        self,
        query: str,
        language: str = "",
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Search for code snippets matching *query*.

        Uses MCP transport if ``prefer_mcp=True`` and the endpoint is
        reachable, otherwise falls back to the public REST API.

        Args:
            query:       Natural-language or keyword code-search query.
            language:    Optional language filter (e.g. ``"python"``).
            max_results: Maximum number of results.

        Returns:
            List of ``{"source", "text", "url", "filename", "language"}`` dicts.
        """
        if not query:
            return []
        if self.prefer_mcp and self.mcp_is_available():
            results = self._mcp_search(query, language=language, max_results=max_results)
            if results:
                return results
        # Fall back to REST
        return self._rest_search(query, language=language, max_results=max_results)

    def discover_patterns(
        self,
        language: str,
        pattern_type: str = "decorator",
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Discover idiomatic code patterns for *language* from searchcode.

        Uses curated query templates analogous to GitHub Code Search's
        ``discover_patterns()`` so ALE can use both backends interchangeably.

        Args:
            language:     Target programming language.
            pattern_type: One of the keys in ``_PATTERN_QUERIES`` or free text.
            max_results:  Maximum results.

        Returns:
            List of result dicts tagged ``"source": "searchcode_pattern"``.
        """
        queries = _PATTERN_QUERIES.get(pattern_type, [f"{pattern_type} {language}"])
        combined: List[Dict[str, Any]] = []
        seen_urls: set = set()
        for q in queries[:2]:
            for r in self.search_code(f"{q}", language=language, max_results=max_results):
                key = r.get("url") or r.get("text", "")[:50]
                if key not in seen_urls:
                    seen_urls.add(key)
                    r["source"] = "searchcode_pattern"
                    r["pattern_type"] = pattern_type
                    combined.append(r)
        log.debug("[Searchcode] discover_patterns(%s/%s) → %d", language, pattern_type, len(combined))
        return combined[:max_results]

    def research_for_code_generation(
        self,
        language: str,
        topic: str,
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        One-stop helper used by the ALE code-research step.

        Combines :meth:`discover_patterns` with a plain :meth:`search_code`
        call so the result set covers both structured patterns and real-world
        usage examples — analogous to
        :meth:`~modules.github_code_search.GitHubCodeSearch.research_for_code_generation`.

        Args:
            language:    Target language (e.g. ``"python"``).
            topic:       Research topic (e.g. ``"decorators"``, ``"async io"``).
            max_results: Total result cap.

        Returns:
            Merged, de-duplicated list of result dicts.
        """
        half = max(2, max_results // 2)
        pattern_results = self.discover_patterns(language, topic[:30], max_results=half)
        code_results = self.search_code(f"{topic} example", language=language, max_results=half)

        seen_urls: set = set()
        merged: List[Dict[str, Any]] = []
        for r in pattern_results + code_results:
            key = r.get("url") or r.get("text", "")[:50]
            if key not in seen_urls:
                seen_urls.add(key)
                merged.append(r)

        log.debug("[Searchcode] research_for_code_generation(%s/%s) → %d merged", language, topic, len(merged))
        return merged[:max_results]


# ── module-level self-test ────────────────────────────────────────────────────
if __name__ == "__main__":
    import json
    sc = SearchcodeSearch()
    print("MCP available:", sc.mcp_is_available())
    results = sc.search_code("async context manager python", language="python", max_results=3)
    print(json.dumps(results, indent=2, default=str))
