#!/usr/bin/env python3
"""
modules/stackoverflow_search.py — Stack Exchange / Stack Overflow search client.

Mirrors the GitHubCodeSearch module's design: a standalone class with an
``is_available()`` check, graceful degradation, and normalised result dicts.

Activation::

    STACKOVERFLOW_API_KEY=...   # Optional — set in .env for higher rate limits
                                # Unauthenticated requests are also supported.

Key uses
--------
* Bug solutions and error message lookup during autonomous code research
* Code explanation and pattern discovery
* Technology/library Q&A to supplement GitHub Code Search results

References
----------
Stack Exchange API v2.3: https://api.stackexchange.com/docs
App registration: https://stackapps.com/apps/oauth/register
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("StackOverflowSearch")

_BASE_URL = "https://api.stackexchange.com/2.3"
_SEARCH_URL = f"{_BASE_URL}/search/advanced"
_QUESTIONS_URL = f"{_BASE_URL}/questions"
_SITE = "stackoverflow"

# Request throttle: SO allows 30 unauthenticated / 300 authenticated per 24 h.
# We stay conservative to avoid 429s.
_MIN_REQUEST_INTERVAL = 2.0  # seconds between requests


class StackOverflowSearch:
    """
    Search Stack Overflow (via Stack Exchange API v2.3).

    Args:
        api_key:  Stack Exchange API key. Falls back to ``STACKOVERFLOW_API_KEY``
                  env var.  Unauthenticated requests work but are rate-limited.
        timeout:  HTTP request timeout in seconds.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: int = 10,
    ) -> None:
        self.api_key: str = (
            api_key if api_key is not None else os.getenv("STACKOVERFLOW_API_KEY", "")
        )
        self.timeout = timeout
        self._last_request_ts: float = 0.0

    # ── public helpers ────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Always True — unauthenticated tier is always accessible."""
        return True

    # ── private helpers ───────────────────────────────────────────────────────

    def _rate_limit_wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_ts = time.monotonic()

    def _base_params(self) -> Dict[str, Any]:
        params: Dict[str, Any] = {"site": _SITE, "order": "desc", "sort": "relevance"}
        if self.api_key:
            params["key"] = self.api_key
        return params

    @staticmethod
    def _clean_html(text: str) -> str:
        """Very light HTML tag stripping — avoids a beautifulsoup dependency."""
        import re
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = re.sub(r"&quot;", '"', text)
        text = re.sub(r"&#39;", "'", text)
        return " ".join(text.split()).strip()

    # ── core search methods ───────────────────────────────────────────────────

    def search(
        self,
        query: str,
        tags: Optional[List[str]] = None,
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Search Stack Overflow for questions matching *query*.

        Args:
            query:      Free-text search string.
            tags:       Optional list of SO tags to filter by (e.g. ``["python"]``).
            max_results: Maximum number of results to return.

        Returns:
            List of normalised result dicts::

                {
                    "source": "stackoverflow",
                    "title":  str,
                    "text":   str,     # question excerpt
                    "url":    str,
                    "score":  int,
                    "tags":   list[str],
                    "is_answered": bool,
                    "answer_count": int,
                }
        """
        self._rate_limit_wait()

        params = self._base_params()
        params.update({
            "q": query,
            "pagesize": min(max_results, 10),
            "filter": "withbody",  # include body for snippet extraction
        })
        if tags:
            params["tagged"] = ";".join(tags)

        try:
            resp = requests.get(_SEARCH_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.debug("[SO] search failed: %s", exc)
            return []

        results: List[Dict[str, Any]] = []
        for item in (data.get("items") or [])[:max_results]:
            if not isinstance(item, dict):
                continue
            body = self._clean_html(item.get("body") or "")
            title = self._clean_html(item.get("title") or "")
            # Truncate body to a useful snippet
            snippet = body[:400].rstrip() + ("…" if len(body) > 400 else "")
            results.append({
                "source": "stackoverflow",
                "title": title,
                "text": f"{title} | {snippet}",
                "url": item.get("link", ""),
                "score": item.get("score", 0),
                "tags": item.get("tags") or [],
                "is_answered": bool(item.get("is_answered")),
                "answer_count": item.get("answer_count", 0),
            })

        log.debug("[SO] search(%r) → %d results", query, len(results))
        return results

    def search_for_code_pattern(
        self,
        language: str,
        pattern: str,
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Search for code patterns in a given programming language.

        Key use — code pattern discovery.
        """
        query = f"{language} {pattern} best practice example"
        return self.search(query, tags=[language.lower()], max_results=max_results)

    def search_for_error(
        self,
        error_message: str,
        language: str = "python",
        max_results: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Look up a bug / error message.

        Key use — automated bug fixing in ALE code reflection.
        """
        query = f"{language} {error_message}"
        return self.search(query, tags=[language.lower()], max_results=max_results)

    def research_for_code_generation(
        self,
        language: str,
        topic: str,
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Combined research helper consumed by the ALE code-research step.

        Returns merged pattern + general results tagged with
        ``source="stackoverflow"`` for uniform KB storage.
        """
        pattern_results = self.search_for_code_pattern(language, topic, max_results=max_results)
        return pattern_results
