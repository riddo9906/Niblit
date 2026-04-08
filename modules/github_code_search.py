#!/usr/bin/env python3
# modules/github_code_search.py
"""
GitHub Code Search API client for Niblit.

Provides three core capabilities wired into the autonomous research pipeline:

1. **Code pattern discovery** — find language-specific patterns (e.g. decorators,
   context managers, error handling idioms) by querying GitHub's code-search
   endpoint.  Results feed directly into the ALE code-generation step so that
   generated modules contain real, idiomatic patterns pulled from high-quality
   open-source repositories.

2. **Training datasets** — locate well-known datasets, annotation helpers, and
   benchmark files on GitHub so the brain-trainer and self-teacher can build
   richer training corpora.

3. **Automated refactoring** — discover battle-tested refactoring patterns and
   best-practice rewrites (e.g. list-comprehension replacements, async migration
   helpers, type-hint additions) that the code-generator can apply when improving
   its own output.

Authentication:
    Set the ``GITHUB_TOKEN`` environment variable (a fine-grained or classic PAT
    with the ``public_repo`` scope is sufficient) or pass it explicitly.  Without
    a token the API still works but is rate-limited to 10 unauthenticated requests
    per minute.

Usage::

    from modules.github_code_search import GitHubCodeSearch
    gcs = GitHubCodeSearch()
    results = gcs.search_code("async context manager", language="python")
    patterns = gcs.discover_patterns("python", "decorator")
    datasets = gcs.find_training_data("nlp sentiment")
    refactors = gcs.find_refactoring_patterns("python", "list_comprehension")
"""

import os
import logging
import time
import requests
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ── API constants ────────────────────────────────────────────────────────────
GITHUB_API_BASE = "https://api.github.com"
GITHUB_SEARCH_CODE_URL = f"{GITHUB_API_BASE}/search/code"
GITHUB_SEARCH_REPOS_URL = f"{GITHUB_API_BASE}/search/repositories"

# Minimum delay between consecutive API calls (GitHub enforces 30/min with auth,
# 10/min without).  2 s keeps us safely under both limits.
_RATE_LIMIT_DELAY_SECONDS: float = 2.0
# Hard cap per individual API request
_MAX_ITEMS_PER_REQUEST: int = 10
# Stable accept header required for code-search text matches
_ACCEPT_HEADER = "application/vnd.github+json"
_TEXT_MATCH_HEADER = "application/vnd.github.text-match+json"
# Maximum characters kept from a single text-match fragment
_MAX_FRAGMENT_LENGTH: int = 400

# ── Curated query templates ───────────────────────────────────────────────────
# Used by discover_patterns(); maps pattern_type → search query suffix list.
_PATTERN_QUERIES: Dict[str, List[str]] = {
    "decorator":        ["decorator pattern example", "@decorator class function"],
    "context_manager":  ["context manager with statement", "__enter__ __exit__ contextmanager"],
    "async":            ["async await coroutine example", "asyncio gather aiohttp"],
    "error_handling":   ["try except finally best practice", "custom exception class"],
    "type_hints":       ["type hints annotation Optional List Dict", "dataclass TypedDict"],
    "generator":        ["generator yield expression lazy", "itertools chain islice"],
    "singleton":        ["singleton pattern class instance", "__new__ instance_lock"],
    "factory":          ["factory method pattern create", "classmethod factory"],
    "observer":         ["observer pattern event emit", "callback listener subscribe"],
    "dataclass":        ["dataclass field default factory", "@dataclass frozen slots"],
}

_TRAINING_DATA_QUERIES: List[str] = [
    "training dataset labeled examples annotations",
    "nlp corpus benchmark evaluation dataset",
    "machine learning dataset csv json labels",
    "text classification sentiment training data",
    "question answering dataset fine-tuning",
    "code generation training samples pairs",
]

# Maps refactoring technique name → search query list.
_REFACTORING_QUERIES: Dict[str, List[str]] = {
    "list_comprehension":   ["replace for loop list comprehension refactor"],
    "dict_comprehension":   ["replace for loop dict comprehension refactor"],
    "walrus_operator":      ["walrus operator := assignment expression python3.8"],
    "pathlib":              ["replace os.path pathlib Path refactor"],
    "fstring":              ["replace % format f-string fstring refactor"],
    "type_annotations":     ["add type hints annotations mypy refactor"],
    "async_migration":      ["migrate sync to async asyncio aiohttp refactor"],
    "context_manager":      ["refactor resource cleanup with statement contextmanager"],
    "dataclass_migration":  ["replace __init__ dataclass @dataclass refactor"],
    "exception_chaining":   ["raise from exception chaining refactor"],
}

# Keyword → pattern_type mapping used by _infer_pattern_type()
_TOPIC_TO_PATTERN: Dict[str, str] = {
    "decorator":         "decorator",
    "context":          "context_manager",
    "async":            "async",
    "await":            "async",
    "coroutine":        "async",
    "error":            "error_handling",
    "exception":        "error_handling",
    "type":             "type_hints",
    "annotation":       "type_hints",
    "generator":        "generator",
    "yield":            "generator",
    "singleton":        "singleton",
    "factory":          "factory",
    "observer":         "observer",
    "event":            "observer",
    "dataclass":        "dataclass",
}


def _infer_pattern_type(topic: str) -> str:
    """Infer the closest pattern_type from a free-text topic string."""
    topic_lower = topic.lower()
    for keyword, ptype in _TOPIC_TO_PATTERN.items():
        if keyword in topic_lower:
            return ptype
    return "error_handling"  # sensible general default


class GitHubCodeSearch:
    """GitHub Code Search API client for Niblit's autonomous research pipeline.

    Encapsulates three research modes behind a consistent interface that matches
    the ``{"source": ..., "text": ..., "url": ...}`` dict format used throughout
    the rest of Niblit's internet research pipeline (e.g. InternetManager).

    Args:
        token:   GitHub personal-access-token.  Falls back to the
                 ``GITHUB_TOKEN`` environment variable.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        timeout: int = 10,
    ) -> None:
        # Only fall back to the environment variable when *token* is None
        # (not when an explicit empty string is passed).
        self.token: str = token if token is not None else os.getenv("GITHUB_TOKEN", "")
        self.timeout: int = timeout
        self._last_request_ts: float = 0.0

    # ── public helpers ───────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Return True when a GitHub token is configured."""
        return bool(self.token)

    # ── private helpers ──────────────────────────────────────────────────────

    def _headers(self, text_match: bool = False) -> Dict[str, str]:
        h: Dict[str, str] = {
            "Accept": _TEXT_MATCH_HEADER if text_match else _ACCEPT_HEADER,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _rate_limit_wait(self) -> None:
        """Enforce a minimum inter-request delay to avoid 429 errors."""
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < _RATE_LIMIT_DELAY_SECONDS:
            time.sleep(_RATE_LIMIT_DELAY_SECONDS - elapsed)
        self._last_request_ts = time.monotonic()

    @staticmethod
    def _extract_text(item: Dict[str, Any]) -> str:
        """Build a human-readable summary string from a code-search result item."""
        parts: List[str] = []

        repo = item.get("repository", {})
        repo_name = repo.get("full_name", "") if isinstance(repo, dict) else ""
        repo_desc = repo.get("description", "") if isinstance(repo, dict) else ""
        file_path = item.get("path", "")

        if repo_name:
            parts.append(f"repo:{repo_name}")
        if file_path:
            parts.append(f"path:{file_path}")

        # Text-match fragments (available when the text-match preview header is sent)
        for match in item.get("text_matches", []):
            if not isinstance(match, dict):
                continue
            fragment = (match.get("fragment") or "").strip()
            if fragment:
                parts.append(fragment[:_MAX_FRAGMENT_LENGTH])
                break  # one code fragment per item is enough

        if not parts:
            parts.append(item.get("name") or file_path or repo_name or "unknown")
        if repo_desc:
            parts.append(repo_desc[:120])

        return " | ".join(p for p in parts if p)

    @staticmethod
    def _get_url(item: Dict[str, Any]) -> Optional[str]:
        return item.get("html_url") or item.get("url")

    # ── core search ──────────────────────────────────────────────────────────

    def search_code(
        self,
        query: str,
        language: Optional[str] = None,
        max_results: int = 5,
        sort: str = "indexed",
    ) -> List[Dict[str, Any]]:
        """Search GitHub code and return normalised result dicts.

        Args:
            query:       Free-text code-search query (GitHub search syntax supported).
            language:    Optional language filter (e.g. ``"python"``).
            max_results: Maximum number of results to return.
            sort:        GitHub sort field — ``"indexed"`` (default) or
                         ``"best-match"``.

        Returns:
            List of ``{"source": "github_code", "text": str, "url": str|None,
            "repo": str, "path": str}`` dicts, or empty list on failure.
        """
        q = f"{query} language:{language}" if language else query

        self._rate_limit_wait()
        params: Dict[str, Any] = {
            "q": q,
            "per_page": min(max_results, _MAX_ITEMS_PER_REQUEST),
            "sort": sort,
        }
        try:
            resp = requests.get(
                GITHUB_SEARCH_CODE_URL,
                headers=self._headers(text_match=True),
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.debug("[GH CODE SEARCH] search_code failed: %s", exc)
            return []

        results: List[Dict[str, Any]] = []
        for item in (data.get("items") or [])[:min(max_results, _MAX_ITEMS_PER_REQUEST)]:
            if not isinstance(item, dict):
                continue
            repo = item.get("repository") or {}
            results.append({
                "source": "github_code",
                "text": self._extract_text(item),
                "url": self._get_url(item),
                "repo": repo.get("full_name", "") if isinstance(repo, dict) else "",
                "path": item.get("path", ""),
            })

        log.debug("[GH CODE SEARCH] search_code(%r) → %d results", query, len(results))
        return results

    # ── use-case 1: code pattern discovery ───────────────────────────────────

    def discover_patterns(
        self,
        language: str,
        pattern_type: str = "decorator",
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """Discover idiomatic code patterns on GitHub.

        Results are stored in the KB under ``ale_code_research:{lang}:`` keys
        so that the ALE code-generation step can produce idiomatic code.

        Args:
            language:     Target programming language (e.g. ``"python"``).
            pattern_type: One of the keys in :data:`_PATTERN_QUERIES` or any
                          free-text pattern description.
            max_results:  Maximum number of result items.

        Returns:
            List of ``{"source": "github_pattern", "pattern_type": ..., ...}``
            dicts.
        """
        queries = _PATTERN_QUERIES.get(pattern_type, [f"{pattern_type} pattern example"])
        results = self.search_code(queries[0], language=language, max_results=max_results)
        for r in results:
            r["source"] = "github_pattern"
            r["pattern_type"] = pattern_type
        log.debug("[GH CODE SEARCH] discover_patterns(%s/%s) → %d", language, pattern_type, len(results))
        return results

    # ── use-case 2: training datasets ────────────────────────────────────────

    def find_training_data(
        self,
        topic: str,
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """Locate training datasets and annotated corpora on GitHub.

        Combines code-search (for dataset files) with repository-search (for
        starred dataset repos) to give both file-level and repo-level results.

        Args:
            topic:       Subject area, e.g. ``"nlp sentiment classification"``.
            max_results: Maximum number of combined results.

        Returns:
            List of ``{"source": "github_dataset" | "github_dataset_repo",
            ...}`` dicts.
        """
        half = max(2, max_results // 2)
        query = f"{topic} {_TRAINING_DATA_QUERIES[0]}"
        code_results = self.search_code(query, max_results=half)
        for r in code_results:
            r["source"] = "github_dataset"

        repo_results = self._search_repos(
            f"{topic} dataset", topics=["dataset", "machine-learning"], max_results=half
        )

        combined = code_results + repo_results
        log.debug("[GH CODE SEARCH] find_training_data(%r) → %d", topic, len(combined))
        return combined[:max_results]

    def _search_repos(
        self,
        query: str,
        topics: Optional[List[str]] = None,
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """Search GitHub repositories (internal helper used by find_training_data)."""
        q = query
        if topics:
            q += " " + " ".join(f"topic:{t}" for t in topics)

        self._rate_limit_wait()
        params: Dict[str, Any] = {
            "q": q,
            "per_page": min(max_results, _MAX_ITEMS_PER_REQUEST),
            "sort": "stars",
            "order": "desc",
        }
        try:
            resp = requests.get(
                GITHUB_SEARCH_REPOS_URL,
                headers=self._headers(),
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.debug("[GH CODE SEARCH] _search_repos failed: %s", exc)
            return []

        results: List[Dict[str, Any]] = []
        for item in (data.get("items") or []):
            if not isinstance(item, dict):
                continue
            desc = item.get("description") or ""
            name = item.get("full_name") or item.get("name") or ""
            text = f"repo:{name} — {desc[:200]}" if desc else f"repo:{name}"
            results.append({
                "source": "github_dataset_repo",
                "text": text,
                "url": item.get("html_url"),
                "repo": name,
                "path": "",
                "stars": item.get("stargazers_count", 0),
            })
        return results

    # ── use-case 3: automated refactoring ────────────────────────────────────

    def find_refactoring_patterns(
        self,
        language: str,
        technique: str = "list_comprehension",
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """Discover established refactoring patterns for *language*.

        The returned snippets are stored in the KB under
        ``ale_code_refactor:{lang}:{technique}:`` keys so that the
        code-generation and code-reflection steps can apply them to improve
        generated code.

        When ``USE_GH_MODEL_REPORTS=true`` the raw snippets are additionally
        sent to GitHub Models to produce a generalised **refactoring recipe**
        (before/after pseudo-code, pitfalls, and Niblit-specific suggestions).
        The recipe is attached to each result as ``result["recipe"]``.

        Args:
            language:    Target programming language.
            technique:   One of the keys in :data:`_REFACTORING_QUERIES` or any
                         free-text refactoring description.
            max_results: Maximum number of results.

        Returns:
            List of ``{"source": "github_refactor", "technique": ..., ...}``
            dicts, optionally with a ``"recipe"`` key.
        """
        queries = _REFACTORING_QUERIES.get(technique, [f"{technique} refactor {language}"])
        results = self.search_code(queries[0], language=language, max_results=max_results)
        for r in results:
            r["source"] = "github_refactor"
            r["technique"] = technique
        log.debug("[GH CODE SEARCH] find_refactoring_patterns(%s/%s) → %d", language, technique, len(results))

        # Optionally enrich with GitHub Models recipe
        try:
            from modules.github_models_client import (
                GitHubModelsClient,
                USE_GH_MODEL_REPORTS,
            )
            if USE_GH_MODEL_REPORTS and results:
                client = GitHubModelsClient()
                recipe = client.generate_refactor_recipes(
                    language=language,
                    technique=technique,
                    examples=results[:5],
                )
                if recipe:
                    log.info(
                        "[GH CODE SEARCH] GitHub Models recipe generated for %s/%s",
                        language, technique,
                    )
                    for r in results:
                        r["recipe"] = recipe
        except Exception as exc:  # noqa: BLE001
            log.warning("[GH CODE SEARCH] GitHub Models recipe failed: %s", exc)

        return results

    # ── batch helper used by ALE ─────────────────────────────────────────────

    def research_for_code_generation(
        self,
        language: str,
        topic: str,
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """One-stop helper used by the ALE code-research step.

        Combines :meth:`discover_patterns` (for idiomatic patterns) with a
        plain ``search_code`` call so the result set covers both structured
        patterns and real-world usage examples.

        Args:
            language:    Target language (e.g. ``"python"``).
            topic:       Research topic (e.g. ``"decorators"``, ``"async io"``).
            max_results: Total result cap.

        Returns:
            Merged, de-duplicated list of result dicts.
        """
        half = max(2, max_results // 2)
        pattern_type = _infer_pattern_type(topic)
        pattern_results = self.discover_patterns(language, pattern_type, max_results=half)
        code_results = self.search_code(
            f"{topic} example", language=language, max_results=half
        )

        seen_urls: set = set()
        merged: List[Dict[str, Any]] = []
        for r in pattern_results + code_results:
            key = r.get("url") or r.get("text", "")[:60]
            if key not in seen_urls:
                seen_urls.add(key)
                merged.append(r)

        log.debug(
            "[GH CODE SEARCH] research_for_code_generation(%s/%s) → %d merged",
            language, topic, len(merged),
        )
        return merged[:max_results]


# ── module-level singleton ────────────────────────────────────────────────────
if __name__ == "__main__":
    gcs = GitHubCodeSearch()
    print("GitHub token available:", gcs.is_available())
    for r in gcs.discover_patterns("python", "decorator", max_results=2):
        print(r)
