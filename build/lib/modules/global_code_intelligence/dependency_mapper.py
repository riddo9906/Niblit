#!/usr/bin/env python3
"""
modules/global_code_intelligence/dependency_mapper.py

Map technology dependency relationships to reveal ecosystem clusters,
framework families, and technology evolution paths.

Combines:
    - PyPI ``requires_dist`` metadata
    - npm ``dependencies`` fields
    - Static import analysis (from CodeParser results)

Example output::

    FastAPI → starlette  (depends_on)
    FastAPI → pydantic   (depends_on)
    starlette → anyio    (depends_on)

Usage::

    from modules.global_code_intelligence.dependency_mapper import DependencyMapper
    mapper = DependencyMapper()
    mapper.add_package_deps("fastapi", ["starlette", "pydantic", "uvicorn"])
    tree = mapper.get_dependency_tree("fastapi", depth=2)
    clusters = mapper.find_clusters()
"""

import logging
import re
from collections import defaultdict
from typing import Any, Dict, List, Set, Tuple

import requests

log = logging.getLogger("DependencyMapper")

_PYPI_API = "https://pypi.org/pypi/{}/json"
_NPM_API  = "https://registry.npmjs.org/{}"

# Regex to strip version constraints from PEP-508 strings
_REQ_NAME_RE = re.compile(r"^([A-Za-z0-9_\-\.]+)")

class DependencyMapper:
    """
    Build and query a dependency graph across package ecosystems.

    The graph is a dict: package_name → set of direct dependency names.
    """

    def __init__(self) -> None:
        self._deps: Dict[str, Set[str]] = defaultdict(set)

    # ── public API ────────────────────────────────────────────────────────────

    def add_package_deps(self, package: str, deps: List[str]) -> None:
        """Register *deps* as direct dependencies of *package*."""
        clean_pkg = package.lower().replace("-", "_")
        for dep in deps:
            m = _REQ_NAME_RE.match(dep)
            if m:
                self._deps[clean_pkg].add(m.group(1).lower().replace("-", "_"))

    def fetch_pypi_deps(self, package: str, timeout: int = 8) -> List[str]:
        """
        Fetch direct dependencies from PyPI and register them.

        Returns the list of dependency names.
        """
        try:
            resp = requests.get(
                _PYPI_API.format(package),
                timeout=timeout,
            )
            if resp.status_code == 200:
                requires = resp.json().get("info", {}).get("requires_dist") or []
                names = [_REQ_NAME_RE.match(r).group(1) for r in requires if _REQ_NAME_RE.match(r)]
                self.add_package_deps(package, names)
                return names
        except Exception as exc:  # noqa: BLE001
            log.debug("DependencyMapper.fetch_pypi_deps(%s): %s", package, exc)
        return []

    def fetch_npm_deps(self, package: str, timeout: int = 8) -> List[str]:
        """Fetch direct npm dependencies."""
        try:
            resp = requests.get(_NPM_API.format(package), timeout=timeout)
            if resp.status_code == 200:
                latest = resp.json().get("dist-tags", {}).get("latest", "")
                versions = resp.json().get("versions", {})
                if latest and latest in versions:
                    deps = list(versions[latest].get("dependencies", {}).keys())
                    self.add_package_deps(package, deps)
                    return deps
        except Exception as exc:  # noqa: BLE001
            log.debug("DependencyMapper.fetch_npm_deps(%s): %s", package, exc)
        return []

    def add_from_imports(
        self, package: str, import_list: List[str]
    ) -> None:
        """Register imports from CodeParser output as dependencies."""
        self.add_package_deps(package, import_list)

    def get_direct_deps(self, package: str) -> List[str]:
        """Return direct dependencies of *package*."""
        return sorted(self._deps.get(package.lower().replace("-", "_"), set()))

    def get_dependency_tree(
        self,
        package: str,
        depth: int = 2,
    ) -> Dict[str, Any]:
        """
        Return a nested dependency tree up to *depth* levels.

        Example::
            {
                "package": "fastapi",
                "deps": [
                    {"package": "starlette", "deps": [...]},
                    {"package": "pydantic",  "deps": []},
                ]
            }
        """
        return self._build_tree(package.lower().replace("-", "_"), depth, set())

    def find_clusters(self) -> List[List[str]]:
        """
        Group packages into clusters based on shared dependencies (union-find).

        Returns a list of clusters (each a list of package names).
        """
        parent: Dict[str, str] = {}

        def find(x: str) -> str:
            while parent.get(x, x) != x:
                parent[x] = parent.get(parent[x], x)
                x = parent[x]
            return x

        def union(a: str, b: str) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[rb] = ra

        for pkg, deps in self._deps.items():
            for dep in deps:
                union(pkg, dep)

        groups: Dict[str, List[str]] = defaultdict(list)
        all_nodes = set(self._deps.keys()) | {d for deps in self._deps.values() for d in deps}
        for node in all_nodes:
            groups[find(node)].append(node)

        return [sorted(v) for v in groups.values() if len(v) > 1]

    def most_depended_on(self, top_n: int = 10) -> List[Tuple[str, int]]:
        """Return the *top_n* packages most depended on by others."""
        counts: Dict[str, int] = defaultdict(int)
        for deps in self._deps.values():
            for dep in deps:
                counts[dep] += 1
        return sorted(counts.items(), key=lambda x: x[1], reverse=True)[:top_n]

    def summary(self) -> Dict[str, int]:
        return {
            "packages": len(self._deps),
            "total_dep_edges": sum(len(v) for v in self._deps.values()),
        }

    # ── internals ─────────────────────────────────────────────────────────────

    def _build_tree(
        self, package: str, depth: int, visited: Set[str]
    ) -> Dict[str, Any]:
        if package in visited or depth <= 0:
            return {"package": package, "deps": []}
        visited.add(package)
        return {
            "package": package,
            "deps": [
                self._build_tree(dep, depth - 1, visited)
                for dep in sorted(self._deps.get(package, set()))
            ],
        }


if __name__ == "__main__":
    print('Running dependency_mapper.py')
