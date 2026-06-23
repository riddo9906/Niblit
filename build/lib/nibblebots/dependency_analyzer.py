#!/usr/bin/env python3
"""
nibblebots/dependency_analyzer.py — Phase 5 Dependency Graph Awareness

Uses Python ``ast`` to extract ``import`` and ``from … import`` statements
from every scanned file, building a lightweight directed adjacency map:

    {file_path: set_of_imported_module_names}

This map is inverted to produce the *reverse dependency map*:

    {module_name: set_of_files_that_import_it}

The evolution planner calls ``risk_adjustment(file_path)`` before scoring
any fix.  Files with many dependents carry higher risk:

  * Any downstream dependents         → risk += 0.20
  * High-fan-out (> HIGH_FAN_OUT)     → fixed risk 0.50 (move to RISK class)

Public API
----------
``DependencyGraph``
    Dataclass wrapping the adjacency and reverse maps.

``build_graph(files) → DependencyGraph``
    Parse all *files* with ``ast`` and return the populated graph.

``risk_adjustment(file_path, graph) → float``
    Return the additional risk contribution for *file_path* given *graph*.

``is_high_fan_out(file_path, graph) → bool``
    Return True if *file_path* is imported by > HIGH_FAN_OUT other files.
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Set


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HIGH_FAN_OUT: int = int(os.environ.get("EVOLUTION_HIGH_FAN_OUT", "10"))
DEPENDENT_RISK_DELTA: float = 0.20   # added risk when file has any dependents
HIGH_FAN_OUT_RISK: float = 0.50      # fixed risk for high-fan-out files


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class DependencyGraph:
    """Lightweight import-based dependency graph for the repo.

    Attributes
    ----------
    adjacency:  file_path  → set of module name strings imported by that file
    reverse:    module_key → set of file_path strings that import it
    """
    adjacency: Dict[str, Set[str]] = field(default_factory=dict)
    reverse: Dict[str, Set[str]] = field(default_factory=dict)

    def fan_out(self, file_path: Path) -> int:
        """Return the number of files that import the module at *file_path*."""
        key = _path_to_module_key(file_path)
        return len(self.reverse.get(key, set()))

    def dependents(self, file_path: Path) -> FrozenSet[str]:
        """Return the set of file paths that import *file_path*."""
        key = _path_to_module_key(file_path)
        return frozenset(self.reverse.get(key, set()))


# ---------------------------------------------------------------------------
# AST parsing helpers
# ---------------------------------------------------------------------------

def _extract_imports(source: str) -> Set[str]:
    """Return all imported module/name strings from *source* using ast."""
    imported: Set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return imported

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module.split(".")[0])
    return imported


def _path_to_module_key(path: Path) -> str:
    """Derive a simple module key from a file path.

    e.g. ``modules/impact_engine.py`` → ``impact_engine``
    """
    return path.stem


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph(
    files: List[Path],
    workspace: Optional[Path] = None,
) -> DependencyGraph:
    """Parse all *files* and build the dependency graph.

    Parameters
    ----------
    files     : list of Python file paths to analyse
    workspace : repo root (used only to compute relative labels)

    Returns
    -------
    DependencyGraph with adjacency and reverse maps populated.
    """
    graph = DependencyGraph()

    for fpath in files:
        try:
            source = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        imports = _extract_imports(source)
        key = str(fpath)
        graph.adjacency[key] = imports

        # Populate reverse map: each imported module → this file
        for mod in imports:
            if mod not in graph.reverse:
                graph.reverse[mod] = set()
            graph.reverse[mod].add(key)

    return graph


# ---------------------------------------------------------------------------
# Risk helpers
# ---------------------------------------------------------------------------

def risk_adjustment(file_path: Path, graph: DependencyGraph) -> float:
    """Return an additional risk value to add to a fix's risk_level.

    Rules:
      * High-fan-out file (> HIGH_FAN_OUT dependents) → HIGH_FAN_OUT_RISK
      * Any dependents (1 or more)                    → DEPENDENT_RISK_DELTA
      * No dependents                                 → 0.0
    """
    fo = graph.fan_out(file_path)
    if fo > HIGH_FAN_OUT:
        return HIGH_FAN_OUT_RISK
    if fo > 0:
        return DEPENDENT_RISK_DELTA
    return 0.0


def is_high_fan_out(file_path: Path, graph: DependencyGraph) -> bool:
    """Return True if *file_path* is imported by more than HIGH_FAN_OUT files."""
    return graph.fan_out(file_path) > HIGH_FAN_OUT


# ---------------------------------------------------------------------------
# Convenience: build from workspace
# ---------------------------------------------------------------------------

def build_from_workspace(workspace: Optional[Path] = None) -> DependencyGraph:
    """Scan all Python files in *workspace* and return the dependency graph."""
    ws = workspace or Path(os.environ.get("GITHUB_WORKSPACE", "."))
    files = sorted(ws.rglob("*.py"))
    # Exclude common non-source trees
    files = [
        f for f in files
        if ".git" not in f.parts
        and "__pycache__" not in f.parts
        and "node_modules" not in f.parts
    ]
    return build_graph(files, workspace=ws)


if __name__ == "__main__":
    print('Running dependency_analyzer.py')
