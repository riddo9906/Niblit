#!/usr/bin/env python3
"""
modules/global_code_intelligence/ecosystem_scanner.py

Continuously scan the global code ecosystem across GitHub, PyPI, and npm.

Each source returns normalised records::

    {
        "name": str,
        "source": "github" | "pypi" | "npm",
        "domain": str,
        "language": str,
        "architecture": str,
        "dependencies": List[str],
        "stars": int,
        "url": str,
    }

Usage::

    from modules.global_code_intelligence.ecosystem_scanner import EcosystemScanner
    scanner = EcosystemScanner()
    repos  = scanner.scan_github("web framework python")
    pkgs   = scanner.scan_pypi("fastapi")
    results = scanner.scan_all("transformer language model")
"""

import logging
import os
import time
from typing import Any, Dict, List, Optional

import requests

log = logging.getLogger("EcosystemScanner")

_GITHUB_SEARCH = "https://api.github.com/search/repositories"
_PYPI_SEARCH   = "https://pypi.org/pypi/{package}/json"
_NPM_SEARCH    = "https://registry.npmjs.org/-/v1/search"
_RATE_DELAY    = 1.5  # seconds

# Domain heuristics — inferred from repo topics / description
_DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    "web_api":       ["api", "rest", "graphql", "fastapi", "flask", "django", "express"],
    "machine_learning": ["ml", "deep learning", "neural", "transformer", "pytorch", "tensorflow"],
    "data_engineering":["etl", "pipeline", "spark", "kafka", "airflow", "dbt"],
    "devops":        ["docker", "kubernetes", "helm", "ci/cd", "terraform", "ansible"],
    "database":      ["database", "sql", "nosql", "orm", "postgres", "mongo"],
    "cli":           ["cli", "command line", "terminal", "shell", "bash"],
}


class EcosystemScanner:
    """
    Scan multiple package ecosystems and return normalised project records.

    Args:
        token:    GitHub token (falls back to GITHUB_TOKEN env var).
        timeout:  HTTP timeout in seconds.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        timeout: int = 10,
    ) -> None:
        self.token = token or os.getenv("GITHUB_TOKEN", "")
        self.timeout = timeout
        self._last_req: float = 0.0

    # ── public API ────────────────────────────────────────────────────────────

    def scan_github(
        self,
        query: str,
        max_results: int = 20,
    ) -> List[Dict[str, Any]]:
        """Search GitHub repositories and return normalised records."""
        self._throttle()
        params = {"q": query, "sort": "stars", "order": "desc", "per_page": min(max_results, 100)}
        try:
            resp = requests.get(
                _GITHUB_SEARCH,
                params=params,
                headers=self._gh_headers(),
                timeout=self.timeout,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
            return [self._normalise_github(item) for item in items]
        except Exception as exc:  # noqa: BLE001
            log.warning("EcosystemScanner.scan_github: %s", exc)
            return []

    def scan_pypi(self, package: str) -> Optional[Dict[str, Any]]:
        """Fetch metadata for a specific PyPI package."""
        self._throttle()
        try:
            resp = requests.get(
                _PYPI_SEARCH.format(package=package),
                timeout=self.timeout,
            )
            if resp.status_code == 200:
                info = resp.json().get("info", {})
                return self._normalise_pypi(package, info)
        except Exception as exc:  # noqa: BLE001
            log.debug("EcosystemScanner.scan_pypi(%s): %s", package, exc)
        return None

    def scan_npm(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """Search the npm registry."""
        self._throttle()
        try:
            resp = requests.get(
                _NPM_SEARCH,
                params={"text": query, "size": min(max_results, 20)},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            objects = resp.json().get("objects", [])
            return [self._normalise_npm(obj.get("package", {})) for obj in objects]
        except Exception as exc:  # noqa: BLE001
            log.debug("EcosystemScanner.scan_npm: %s", exc)
            return []

    def scan_all(
        self,
        query: str,
        max_github: int = 10,
        pypi_packages: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Scan GitHub and optionally PyPI, return a merged list."""
        results = self.scan_github(query, max_results=max_github)
        for pkg in (pypi_packages or []):
            record = self.scan_pypi(pkg)
            if record:
                results.append(record)
        return results

    # ── internals ─────────────────────────────────────────────────────────────

    def _gh_headers(self) -> Dict[str, str]:
        h: Dict[str, str] = {"Accept": "application/vnd.github+json"}
        if self.token:
            h["Authorization"] = f"token {self.token}"
        return h

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_req
        if elapsed < _RATE_DELAY:
            time.sleep(_RATE_DELAY - elapsed)
        self._last_req = time.monotonic()

    @staticmethod
    def _infer_domain(text: str) -> str:
        text_lower = text.lower()
        for domain, keywords in _DOMAIN_KEYWORDS.items():
            if any(kw in text_lower for kw in keywords):
                return domain
        return "general"

    def _normalise_github(self, item: Dict[str, Any]) -> Dict[str, Any]:
        desc = (item.get("description") or "").lower()
        topics = item.get("topics", [])
        return {
            "name": item.get("full_name", ""),
            "source": "github",
            "domain": self._infer_domain(desc + " " + " ".join(topics)),
            "language": item.get("language", "") or "",
            "architecture": "",
            "dependencies": [],
            "stars": item.get("stargazers_count", 0),
            "url": item.get("html_url", ""),
            "topics": topics,
        }

    def _normalise_pypi(self, package: str, info: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": package,
            "source": "pypi",
            "domain": self._infer_domain(info.get("summary", "")),
            "language": "python",
            "architecture": "",
            "dependencies": info.get("requires_dist", []) or [],
            "stars": 0,
            "url": info.get("project_url", f"https://pypi.org/project/{package}/"),
            "topics": info.get("classifiers", []),
        }

    @staticmethod
    def _normalise_npm(pkg: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": pkg.get("name", ""),
            "source": "npm",
            "domain": "javascript",
            "language": "javascript",
            "architecture": "",
            "dependencies": [],
            "stars": 0,
            "url": pkg.get("links", {}).get("npm", ""),
            "topics": pkg.get("keywords", []),
        }


if __name__ == "__main__":
    print('Running ecosystem_scanner.py')
