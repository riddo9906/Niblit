#!/usr/bin/env python3
"""
nibblebots/doc_agent.py — Phase 15 Background Documentation Worker

Ruflo-inspired background worker: scans Python source files for public
functions, methods, and classes that lack docstrings, then emits
AgentObservation events on the EventBus.

Detection logic
---------------
Uses Python's ``ast`` module to find:
  • Module-level ``def`` / ``async def`` without a docstring
  • Module-level ``class`` definitions without a class-level docstring
  • Public methods inside classes without a docstring

Only public symbols (names not starting with ``_``) are checked.
``__init__``, ``__repr__``, ``__str__`` are included because they are
part of the public API contract.

Usage (standalone)::

    python nibblebots/doc_agent.py
    DOC_DRY_RUN=true  python nibblebots/doc_agent.py
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from typing import List, Optional

_ws_root = str(Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve())
if _ws_root not in sys.path:
    sys.path.insert(0, _ws_root)

from nibblebots.agent_registry import AgentObservation  # noqa: E402

_AGENT_NAME = "doc_agent"
_WORKSPACE  = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
_DRY_RUN    = os.environ.get("DOC_DRY_RUN", "").lower() == "true"
_MAX_OBS    = int(os.environ.get("DOC_MAX_OBSERVATIONS", "40"))

_SCAN_DIRS = (
    "modules", "niblit_agents", "niblit_memory",
    "nibblebots", "niblit_tools", "agents", "core", "kernel", "boot", "api",
)
_SKIP_PARTS = frozenset({
    "__pycache__", ".git", ".github", "node_modules",
    ".build", "build", "dist", ".tox", "venv", ".venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
})

# Dunder methods that are public API and should be documented
_DUNDER_DOC_REQUIRED = frozenset({"__init__", "__repr__", "__str__", "__call__"})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_docstring(node: ast.AST) -> bool:
    """Return True if the node starts with a string literal (docstring)."""
    body = getattr(node, "body", [])
    if not body:
        return False
    first = body[0]
    return (
        isinstance(first, ast.Expr)
        and isinstance(getattr(first, "value", None), ast.Constant)
        and isinstance(first.value.value, str)
    )


def _is_public(name: str) -> bool:
    if name.startswith("__") and name.endswith("__"):
        return name in _DUNDER_DOC_REQUIRED
    return not name.startswith("_")


def _count_missing(path: Path) -> int:
    """Return the number of public symbols missing docstrings in *path*."""
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return 0

    missing = 0
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _is_public(node.name) and not _has_docstring(node):
                missing += 1
        elif isinstance(node, ast.ClassDef):
            if _is_public(node.name) and not _has_docstring(node):
                missing += 1
            # Check public methods inside the class
            for item in ast.iter_child_nodes(node):
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if _is_public(item.name) and not _has_docstring(item):
                        missing += 1
    return missing


def _collect_files() -> List[Path]:
    files: List[Path] = []
    for scan_dir in _SCAN_DIRS:
        d = _WORKSPACE / scan_dir
        if d.is_dir():
            for p in sorted(d.rglob("*.py")):
                if not any(part in _SKIP_PARTS for part in p.parts):
                    if not p.name.startswith("test_") and p.name != "conftest.py":
                        files.append(p)
    return files


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------

def run_doc_audit(workspace: Optional[Path] = None) -> List[AgentObservation]:
    """Return AgentObservation list for files with undocumented public symbols."""
    observations: List[AgentObservation] = []

    for path in _collect_files():
        missing = _count_missing(path)
        if missing == 0:
            continue

        severity = min(0.70, 0.30 + missing * 0.04)
        rel = str(path.relative_to(_WORKSPACE))
        observations.append(AgentObservation(
            agent_name=_AGENT_NAME,
            obs_type="missing_docstring",
            file_path=rel,
            count=missing,
            severity=round(severity, 3),
            description=(
                f"{missing} public symbol{'s' if missing != 1 else ''} "
                f"missing docstring{'s' if missing != 1 else ''}"
            ),
        ))

    observations.sort(key=lambda o: (-o.severity, -o.count))
    return observations[:_MAX_OBS]


# ---------------------------------------------------------------------------
# EventBus emission
# ---------------------------------------------------------------------------

def emit_observations(observations: List[AgentObservation]) -> None:
    if not observations:
        return
    try:
        from modules.event_bus import get_event_bus, NiblitEvent, EVENT_AGENT_OBSERVATION  # noqa: PLC0415
        bus = get_event_bus()
        for obs in observations:
            bus.publish(NiblitEvent(
                type=EVENT_AGENT_OBSERVATION,
                source=_AGENT_NAME,
                payload=obs.to_dict(),
            ))
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

def main() -> int:
    print(f"📝 Niblit Doc Agent — workspace: {_WORKSPACE}")
    observations = run_doc_audit()

    if not observations:
        print("✅ All public symbols are documented.")
        return 0

    print(f"\n📋 Documentation observations ({len(observations)}):")
    for obs in observations:
        sev_bar = "🔴" if obs.severity >= 0.60 else ("🟡" if obs.severity >= 0.45 else "🟢")
        print(f"  {sev_bar} [{obs.file_path}] — {obs.description}")

    if not _DRY_RUN:
        emit_observations(observations)
        print(f"\n📡 {len(observations)} observation(s) emitted on EventBus.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
