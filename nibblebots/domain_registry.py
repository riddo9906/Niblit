#!/usr/bin/env python3
"""
nibblebots/domain_registry.py — Phase 5 Domain Execution Registry

Defines explicit execution *domains* — bounded areas the evolution agent is
allowed to observe and modify.  Each domain declares:

  name          : unique identifier string
  observe_fn    : callable() → list of raw issues for this domain
  execute_fn    : callable(issue) → bool — apply the fix
  rollback_fn   : callable(issue) → bool — undo the fix
  safe_fix_types: fix types considered safe in this domain
  risk_fix_types: fix types that require extra scrutiny
  protected_paths: path substrings that are always off-limits

Phase 5 ships three built-in domains:

  code          — Python source files (already wired by Phase 3)
  workflow_config — GitHub Actions YAML hygiene
  dependency_pins — requirements.txt version drift (pinned vs. unpinned)

The ``evolution_planner`` becomes domain-aware by calling
``domain_registry.get_all_domains()`` and merging plans per domain.

Public API
----------
``Domain``      — NamedTuple describing one execution domain
``register(domain)``       — add a domain to the registry
``get_domain(name)``       — retrieve a domain by name
``get_all_domains()``      — return all registered domains
``MAX_CROSS_DOMAIN_FIXES`` — total cap on fixes across all domains per cycle
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, List, NamedTuple, Optional


# ---------------------------------------------------------------------------
# Cross-domain safety cap
# ---------------------------------------------------------------------------

MAX_CROSS_DOMAIN_FIXES: int = int(
    os.environ.get("EVOLUTION_MAX_CROSS_DOMAIN_FIXES", "8")
)


# ---------------------------------------------------------------------------
# Domain data structure
# ---------------------------------------------------------------------------

class Domain(NamedTuple):
    name: str
    observe_fn: Optional[Callable[..., List[Any]]]
    execute_fn: Optional[Callable[..., bool]]
    rollback_fn: Optional[Callable[..., bool]]
    safe_fix_types: FrozenSet[str]
    risk_fix_types: FrozenSet[str]
    protected_paths: FrozenSet[str]
    description: str = ""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_registry: Dict[str, Domain] = {}


def register(domain: Domain) -> None:
    """Add *domain* to the registry (overwrites if name already exists)."""
    _registry[domain.name] = domain


def get_domain(name: str) -> Optional[Domain]:
    """Return the domain with *name*, or None."""
    return _registry.get(name)


def get_all_domains() -> List[Domain]:
    """Return all registered domains."""
    return list(_registry.values())


# ---------------------------------------------------------------------------
# Built-in domain: code
# ---------------------------------------------------------------------------

def _observe_code(workspace: Optional[Path] = None) -> List[Any]:
    """Delegate to the Phase 3 code scanner."""
    try:
        from nibblebots.autonomous_evolution_agent import (  # noqa: PLC0415
            collect_python_files,
            find_batch_issues,
        )
        ws = workspace or Path(os.environ.get("GITHUB_WORKSPACE", "."))
        files = collect_python_files(ws)
        return find_batch_issues(files)
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠ domain[code].observe_fn error: {exc}", file=sys.stderr)
        return []


def _execute_code(issue: Any) -> bool:
    """Delegate to the Phase 3 apply_fix."""
    try:
        from nibblebots.autonomous_evolution_agent import apply_fix  # noqa: PLC0415
        return apply_fix(issue)
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠ domain[code].execute_fn error: {exc}", file=sys.stderr)
        return False


def _rollback_code(issue: Any) -> bool:
    """Git checkout the file to undo the fix (best-effort)."""
    try:
        import subprocess  # noqa: PLC0415
        result = subprocess.run(
            ["git", "checkout", "--", str(issue.file_path)],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠ domain[code].rollback_fn error: {exc}", file=sys.stderr)
        return False


register(Domain(
    name="code",
    observe_fn=_observe_code,
    execute_fn=_execute_code,
    rollback_fn=_rollback_code,
    safe_fix_types=frozenset({
        "bare_except", "bare_except_pass",
        "trailing_whitespace", "double_blank_lines", "eof_newline",
    }),
    risk_fix_types=frozenset(),
    protected_paths=frozenset({
        "modules/decision_engine",
        "modules/meta_engine",
        "modules/policy_optimizer",
        "NiblitSignalStrategy",
        "freqtrade_adapter",
    }),
    description="Python source file improvements (Phase 3 fix catalogue)",
))


# ---------------------------------------------------------------------------
# Built-in domain: workflow_config
# ---------------------------------------------------------------------------

# Lines in workflow YAML that are considered hygiene fixes
_WORKFLOW_REDUNDANT_ECHO = re.compile(r"^\s+echo\s+\"(DEBUG|TODO|FIXME|test).*\"", re.IGNORECASE)


def _observe_workflow(workspace: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Scan .github/workflows/*.yml for simple hygiene issues."""
    ws = workspace or Path(os.environ.get("GITHUB_WORKSPACE", "."))
    issues: List[Dict[str, Any]] = []
    workflow_dir = ws / ".github" / "workflows"
    if not workflow_dir.is_dir():
        return issues

    for yml_file in sorted(workflow_dir.glob("*.yml")):
        try:
            text = yml_file.read_text(encoding="utf-8")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _WORKFLOW_REDUNDANT_ECHO.match(line):
                issues.append({
                    "domain": "workflow_config",
                    "fix_type": "redundant_debug_echo",
                    "file_path": yml_file,
                    "lineno": lineno,
                    "line": line,
                    "count": 1,
                })
    return issues


def _execute_workflow(issue: Dict[str, Any]) -> bool:
    """Remove the identified redundant debug echo line."""
    path: Path = issue["file_path"]
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        lineno = issue["lineno"] - 1  # 0-indexed
        if 0 <= lineno < len(lines):
            del lines[lineno]
            path.write_text("".join(lines), encoding="utf-8")
            return True
    except OSError as exc:
        print(f"  ⚠ domain[workflow_config].execute_fn error: {exc}", file=sys.stderr)
    return False


def _rollback_workflow(issue: Dict[str, Any]) -> bool:
    """Git checkout the YAML file."""
    try:
        import subprocess  # noqa: PLC0415
        result = subprocess.run(
            ["git", "checkout", "--", str(issue["file_path"])],
            capture_output=True, timeout=10,
        )
        return result.returncode == 0
    except Exception as exc:  # noqa: BLE001
        print(f"  ⚠ domain[workflow_config].rollback_fn error: {exc}", file=sys.stderr)
        return False


register(Domain(
    name="workflow_config",
    observe_fn=_observe_workflow,
    execute_fn=_execute_workflow,
    rollback_fn=_rollback_workflow,
    safe_fix_types=frozenset({"redundant_debug_echo"}),
    risk_fix_types=frozenset(),
    protected_paths=frozenset(),
    description="GitHub Actions YAML hygiene fixes",
))


# ---------------------------------------------------------------------------
# Built-in domain: dependency_pins
# ---------------------------------------------------------------------------

_UNPINNED_RE = re.compile(r"^([A-Za-z0-9_\-\.\[\]]+)\s*$")   # bare package, no version
_LOOSE_RE = re.compile(r"^([A-Za-z0-9_\-\.\[\]]+)\s*>=?\s*[\d.]+\s*$")  # lower-bound only


def _observe_deps(workspace: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Find unpinned or loosely pinned dependencies in requirements*.txt."""
    ws = workspace or Path(os.environ.get("GITHUB_WORKSPACE", "."))
    issues: List[Dict[str, Any]] = []
    for req_file in sorted(ws.glob("requirements*.txt")):
        try:
            for lineno, line in enumerate(
                req_file.read_text(encoding="utf-8").splitlines(), start=1
            ):
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("-"):
                    continue
                if _UNPINNED_RE.match(line):
                    issues.append({
                        "domain": "dependency_pins",
                        "fix_type": "unpinned_dependency",
                        "file_path": req_file,
                        "lineno": lineno,
                        "package": line,
                        "count": 1,
                    })
                elif _LOOSE_RE.match(line):
                    issues.append({
                        "domain": "dependency_pins",
                        "fix_type": "loosely_pinned_dependency",
                        "file_path": req_file,
                        "lineno": lineno,
                        "package": line,
                        "count": 1,
                    })
        except OSError:
            continue
    return issues


def _execute_deps(_issue: Dict[str, Any]) -> bool:
    """Dependency pinning changes require human review — always returns False."""
    return False   # Safe: never auto-pin; report only


def _rollback_deps(_issue: Dict[str, Any]) -> bool:
    return True   # Nothing to undo


register(Domain(
    name="dependency_pins",
    observe_fn=_observe_deps,
    execute_fn=_execute_deps,
    rollback_fn=_rollback_deps,
    safe_fix_types=frozenset(),
    risk_fix_types=frozenset({"unpinned_dependency", "loosely_pinned_dependency"}),
    protected_paths=frozenset(),
    description="Dependency version drift audit (report-only — no auto-pin)",
))


if __name__ == "__main__":
    print('Running domain_registry.py')
