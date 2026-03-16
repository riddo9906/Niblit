#!/usr/bin/env python3
"""
modules/pypi_search.py — PyPI package intelligence client for Niblit.

Provides package search, dependency inspection, and usage-pattern discovery
via the public PyPI JSON API (no API key required).

Key uses
--------
* Discover new Python libraries during autonomous research
* Build dependency graphs for studied packages
* Understand usage patterns and popular packages in a domain

References
----------
PyPI JSON API: https://warehouse.pypa.io/api-reference/json/
PyPI Simple API: https://warehouse.pypa.io/api-reference/simple/
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("PyPISearch")

_PYPI_SEARCH_URL = os.getenv("PYPI_API_URL", "https://pypi.org/pypi")
_PYPI_SIMPLE_URL = "https://pypi.org/simple"
_PYPI_XMLRPC_URL = "https://pypi.org/pypi"   # XML-RPC endpoint
_MIN_REQUEST_INTERVAL = 0.5  # seconds


class PyPISearch:
    """
    Query the public PyPI JSON API for package intelligence.

    No API key is required.  The class always returns gracefully on
    network errors.
    """

    def __init__(self, timeout: int = 10) -> None:
        self.timeout = timeout
        self._last_request_ts: float = 0.0

    # ── helpers ───────────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """Always True — PyPI is a public API."""
        return True

    def _rate_limit_wait(self) -> None:
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < _MIN_REQUEST_INTERVAL:
            time.sleep(_MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_ts = time.monotonic()

    # ── core methods ──────────────────────────────────────────────────────────

    def get_package_info(self, package_name: str) -> Optional[Dict[str, Any]]:
        """
        Fetch full package metadata from PyPI.

        Returns:
            Dict with keys ``name``, ``version``, ``summary``, ``description``,
            ``requires_dist``, ``home_page``, ``project_url``, ``downloads``
            — or ``None`` on failure.
        """
        self._rate_limit_wait()
        url = f"{_PYPI_SEARCH_URL}/{package_name}/json"
        try:
            resp = requests.get(url, timeout=self.timeout)
            resp.raise_for_status()
            raw = resp.json()
        except Exception as exc:
            log.debug("[PyPI] get_package_info(%r) failed: %s", package_name, exc)
            return None

        info = raw.get("info", {})
        return {
            "source": "pypi",
            "name": info.get("name", package_name),
            "version": info.get("version", ""),
            "summary": info.get("summary", ""),
            "description": (info.get("description") or "")[:600],
            "requires_dist": info.get("requires_dist") or [],
            "home_page": info.get("home_page") or info.get("project_url") or "",
            "project_url": f"https://pypi.org/project/{package_name}/",
            "license": info.get("license") or "",
            "keywords": info.get("keywords") or "",
            "classifiers": (info.get("classifiers") or [])[:10],
        }

    def search_packages(
        self,
        query: str,
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Search PyPI for packages matching *query* via the XML-RPC ``search``
        endpoint (deprecated) — falls back to a simple name-match heuristic
        using the JSON API for well-known package names derived from *query*.

        Because the PyPI search XML-RPC endpoint has been disabled since 2020,
        this method uses a curated domain→package mapping to provide useful
        results for the autonomous learning pipeline without requiring an
        external search service.

        Returns:
            List of normalised result dicts with at least
            ``{source, name, version, summary, project_url, text}``.
        """
        results: List[Dict[str, Any]] = []
        candidate_names = self._infer_package_names(query)

        for name in candidate_names[:max_results]:
            info = self.get_package_info(name)
            if info:
                info["text"] = (
                    f"PyPI: {info['name']} {info['version']} — {info['summary']}"
                )
                results.append(info)

        log.debug("[PyPI] search(%r) → %d results", query, len(results))
        return results

    def get_dependencies(self, package_name: str) -> List[str]:
        """
        Return the list of direct dependencies (``requires_dist``) for *package_name*.
        """
        info = self.get_package_info(package_name)
        if info is None:
            return []
        return info.get("requires_dist") or []

    def research_for_code_generation(
        self,
        language: str,
        topic: str,
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        ALE code-research helper: return PyPI packages relevant to *topic*.

        Results are tagged ``source="pypi"`` for KB storage.
        """
        if language.lower() != "python":
            return []
        return self.search_packages(topic, max_results=max_results)

    # ── internal lookup helpers ───────────────────────────────────────────────

    # Domain → popular PyPI package names mapping used when the XML-RPC search
    # endpoint is unavailable.
    _DOMAIN_PACKAGES: Dict[str, List[str]] = {
        "nlp":         ["transformers", "spacy", "nltk", "sentence-transformers", "gensim"],
        "ml":          ["scikit-learn", "torch", "tensorflow", "xgboost", "lightgbm"],
        "deep_learning": ["torch", "tensorflow", "keras", "fastai", "jax"],
        "api":         ["fastapi", "flask", "django", "httpx", "requests"],
        "async":       ["asyncio", "aiohttp", "anyio", "trio", "uvicorn"],
        "data":        ["pandas", "numpy", "polars", "dask", "pyarrow"],
        "vector":      ["faiss-cpu", "qdrant-client", "annoy", "chromadb", "weaviate-client"],
        "embedding":   ["sentence-transformers", "openai", "cohere", "instructor"],
        "llm":         ["openai", "anthropic", "langchain", "llama-index", "google-generativeai"],
        "testing":     ["pytest", "hypothesis", "coverage", "factory-boy", "respx"],
        "database":    ["sqlalchemy", "alembic", "psycopg2", "pymongo", "redis"],
        "chat":        ["openai", "anthropic", "cohere", "replicate"],
        "code":        ["black", "ruff", "mypy", "pylint", "isort"],
        "security":    ["cryptography", "pyjwt", "passlib", "python-jose", "bcrypt"],
        "networking":  ["requests", "httpx", "aiohttp", "websockets", "paramiko"],
        "memory":      ["redis", "diskcache", "shelve", "joblib", "cachetools"],
        "reasoning":   ["z3-solver", "sympy", "networkx"],
        "binary":      ["pyelftools", "capstone", "pefile", "r2pipe"],
    }

    def _infer_package_names(self, query: str) -> List[str]:
        """Map a free-text query to a list of candidate package names."""
        q = query.lower()
        names: List[str] = []
        for domain, pkgs in self._DOMAIN_PACKAGES.items():
            if domain in q or any(kw in q for kw in domain.split("_")):
                names.extend(pkgs)
        # Also treat words in query as potential package names
        words = [w.strip(".,;") for w in q.split() if len(w) > 3]
        names.extend(words)
        # De-duplicate while preserving order
        seen: set = set()
        unique: List[str] = []
        for n in names:
            if n not in seen:
                seen.add(n)
                unique.append(n)
        return unique
