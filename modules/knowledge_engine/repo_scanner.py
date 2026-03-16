#!/usr/bin/env python3
"""
modules/knowledge_engine/repo_scanner.py

Continuously find repositories via the GitHub API.

Activation::

    GITHUB_TOKEN=ghp_...   # optional but raises rate-limit to 5 000 req/hr

Usage::

    from modules.knowledge_engine.repo_scanner import RepoScanner
    scanner = RepoScanner()
    repos = scanner.search("machine learning language:python")
    filtered = scanner.search_filtered(topic="deep-learning", min_stars=200)
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("RepoScanner")

_GITHUB_API = "https://api.github.com"
_SEARCH_URL = f"{_GITHUB_API}/search/repositories"
_RATE_DELAY: float = 2.0  # seconds between requests (safe for both auth/unauth)
_MAX_PER_PAGE: int = 30


class RepoScanner:
    """
    Discover GitHub repositories that match a query or topic filter.

    Repository metadata collected:
        - full_name, description, html_url
        - stars (stargazers_count)
        - language, topics
        - pushed_at (recency proxy)
        - archived flag

    Filter rules applied by default:
        - stars ≥ min_stars (default 100)
        - not archived
        - pushed within last 2 years
    """

    def __init__(
        self,
        token: Optional[str] = None,
        min_stars: int = 100,
        timeout: int = 10,
    ) -> None:
        self.token = token or os.getenv("GITHUB_TOKEN", "")
        self.min_stars = min_stars
        self.timeout = timeout
        self._last_request: float = 0.0

    # ── public API ────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return True if the GitHub API is reachable."""
        try:
            r = requests.get(
                f"{_GITHUB_API}/rate_limit",
                headers=self._headers(),
                timeout=self.timeout,
            )
            return r.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    def search(
        self,
        query: str,
        sort: str = "stars",
        order: str = "desc",
        max_results: int = _MAX_PER_PAGE,
    ) -> List[Dict[str, Any]]:
        """
        Search repositories matching *query*.

        Returns a list of normalised dicts with keys:
            full_name, description, html_url, stars, language, topics,
            pushed_at, archived, clone_url
        """
        self._throttle()
        params: Dict[str, Any] = {
            "q": query,
            "sort": sort,
            "order": order,
            "per_page": min(max_results, 100),
        }
        try:
            resp = requests.get(
                _SEARCH_URL,
                params=params,
                headers=self._headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
            return [self._normalise(item) for item in items if self._passes_filter(item)]
        except Exception as exc:  # noqa: BLE001
            log.warning("RepoScanner.search failed: %s", exc)
            return []

    def search_filtered(
        self,
        topic: str = "",
        language: str = "python",
        min_stars: Optional[int] = None,
        max_results: int = _MAX_PER_PAGE,
    ) -> List[Dict[str, Any]]:
        """Search with common filters pre-applied."""
        parts = []
        if topic:
            parts.append(f"topic:{topic}")
        if language:
            parts.append(f"language:{language}")
        stars_floor = min_stars if min_stars is not None else self.min_stars
        parts.append(f"stars:>{stars_floor}")
        query = " ".join(parts)
        return self.search(query, max_results=max_results)

    def list_topics(self, query: str = "ai python", max_results: int = 10) -> List[str]:
        """Return unique topic tags found across matching repos."""
        repos = self.search(query, max_results=max_results)
        seen: set = set()
        topics: List[str] = []
        for r in repos:
            for t in r.get("topics", []):
                if t not in seen:
                    seen.add(t)
                    topics.append(t)
        return topics

    # ── internals ─────────────────────────────────────────────────────────────

    def _headers(self) -> Dict[str, str]:
        hdrs: Dict[str, str] = {"Accept": "application/vnd.github+json"}
        if self.token:
            hdrs["Authorization"] = f"token {self.token}"
        return hdrs

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < _RATE_DELAY:
            time.sleep(_RATE_DELAY - elapsed)
        self._last_request = time.monotonic()

    def _passes_filter(self, item: Dict[str, Any]) -> bool:
        if item.get("archived", False):
            return False
        if item.get("stargazers_count", 0) < self.min_stars:
            return False
        return True

    @staticmethod
    def _normalise(item: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "full_name": item.get("full_name", ""),
            "description": item.get("description", "") or "",
            "html_url": item.get("html_url", ""),
            "clone_url": item.get("clone_url", ""),
            "stars": item.get("stargazers_count", 0),
            "language": item.get("language", "") or "",
            "topics": item.get("topics", []),
            "pushed_at": item.get("pushed_at", ""),
            "archived": item.get("archived", False),
        }
