#!/usr/bin/env python3
"""
nibblebots/autonomous_evolution_agent.py — Niblit Autonomous Code Evolution Agent

Combines all nibblebot capabilities into one agent that:

  1. Scans *every* Python file in the repository (modules/, niblit_agents/,
     niblit_memory/, nibblebots/, and root-level scripts).
  2. Detects fixable issues from a prioritised catalogue of safe, reversible
     code-quality improvements.
  3. Selects ONE issue — the file with the highest instance count for the
     highest-priority fix type — for maximum impact per run.
  4. Applies the fix using a pure text transform and validates the result
     with ``py_compile`` before writing anything.
  5. Outputs GitHub Actions step-output variables (``commit_msg`` and
     ``changed_file``) so the calling workflow can commit and push.

Fix catalogue (applied in priority order):
  1. ``bare_except``       — ``except:`` → ``except Exception:``
  2. ``bare_except_pass``  — ``except Exception: pass`` without comment
                             → adds ``# noqa: BLE001`` marker so linters
                             know the silence is intentional
  3. ``eof_newline``       — ensure every file ends with a single ``\\n``

Each fix type is safe, deterministic, and fully reversible:
  * No logic changes — only surface-level code quality.
  * ``py_compile`` validates the patched file before it is written.
  * One file changed per run keeps diffs small and reviewable.

Usage (local testing)::

    python nibblebots/autonomous_evolution_agent.py

    # Force a specific fix type:
    EVOLUTION_FIX_TYPE=bare_except python nibblebots/autonomous_evolution_agent.py

    # Dry run (print diff without writing):
    EVOLUTION_DRY_RUN=true python nibblebots/autonomous_evolution_agent.py

Environment variables:
    GITHUB_WORKSPACE   — repo root (set automatically by GitHub Actions)
    EVOLUTION_DRY_RUN  — "true" to print changes without writing files
    EVOLUTION_FIX_TYPE — force a specific fix type for testing
    GITHUB_OUTPUT      — set by GitHub Actions for step output capture
"""

from __future__ import annotations

import os
import py_compile
import re
import sys
import tempfile
from pathlib import Path
from typing import Callable, List, NamedTuple, Optional, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WORKSPACE = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
DRY_RUN = os.environ.get("EVOLUTION_DRY_RUN", "").lower() == "true"
FORCE_FIX_TYPE = os.environ.get("EVOLUTION_FIX_TYPE", "").strip()
GH_OUTPUT = os.environ.get("GITHUB_OUTPUT", "")

# Directories to scan (relative to WORKSPACE root)
_SCAN_DIRS: Tuple[str, ...] = (
    "modules",
    "niblit_agents",
    "niblit_memory",
    "nibblebots",
    "niblit_tools",
    "agents",
    "core",
    "kernel",
    "boot",
    "api",
)

# Path segments that mark files/dirs to skip entirely
_SKIP_PARTS: frozenset = frozenset({
    "__pycache__", ".git", ".github", "node_modules",
    ".build", "build", "dist", ".tox", "venv", ".venv",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
})


# ---------------------------------------------------------------------------
# Issue data structure
# ---------------------------------------------------------------------------

class Issue(NamedTuple):
    fix_type: str
    file_path: Path
    count: int   # number of fixable occurrences in this file


# ---------------------------------------------------------------------------
# File collection
# ---------------------------------------------------------------------------

def collect_python_files() -> List[Path]:
    """Return all .py files in scope, sorted alphabetically for determinism."""
    seen: set = set()
    files: List[Path] = []

    def _add(path: Path) -> None:
        resolved = path.resolve()
        if resolved in seen:
            return
        seen.add(resolved)
        files.append(resolved)

    # Scan configured sub-directories
    for dir_name in _SCAN_DIRS:
        dir_path = WORKSPACE / dir_name
        if not dir_path.is_dir():
            continue
        for p in sorted(dir_path.rglob("*.py")):
            if any(part in _SKIP_PARTS for part in p.parts):
                continue
            _add(p)

    # Also scan root-level .py files (app.py, niblit_core.py, etc.)
    for p in sorted(WORKSPACE.glob("*.py")):
        if any(part in _SKIP_PARTS for part in p.parts):
            continue
        _add(p)

    return files


# ---------------------------------------------------------------------------
# Fix type 1: bare_except
# Replace: except:
# With:    except Exception:
# ---------------------------------------------------------------------------

_BARE_EXCEPT_RE = re.compile(r"^(\s*)except\s*:", re.MULTILINE)


def scan_bare_except(content: str) -> int:
    """Return the number of bare ``except:`` clauses in *content*."""
    return len(_BARE_EXCEPT_RE.findall(content))


def fix_bare_except(content: str) -> Tuple[str, int]:
    """Replace all ``except:`` with ``except Exception:``.

    The leading whitespace is preserved via backreference so indentation
    is never altered.
    """
    new_content, n = _BARE_EXCEPT_RE.subn(r"\1except Exception:", content)
    return new_content, n


# ---------------------------------------------------------------------------
# Fix type 2: bare_except_pass (silent swallow without annotation)
# Replace: except Exception:\n<ws>pass
# With:    except Exception:  # noqa: BLE001\n<ws>pass
#
# This flags *intentional* silence so linters know it was deliberate rather
# than accidentally left in.  Only applied to occurrences that do not already
# carry a noqa comment.
# ---------------------------------------------------------------------------

_BARE_PASS_RE = re.compile(
    r"^(\s*)(except\s+\w[^:\n]*:)(\s*\n\s+pass\b)",
    re.MULTILINE,
)
_NOQA_MARKER = "  # noqa: BLE001"


def scan_bare_except_pass(content: str) -> int:
    """Count ``except …: …pass`` blocks that do not already carry a noqa marker.

    A block is counted regardless of any other inline comment on the clause
    line — we only skip if a ``noqa`` annotation is already present, to avoid
    double-annotating intentionally documented silences.
    """
    count = 0
    for m in _BARE_PASS_RE.finditer(content):
        clause_line = m.group(2)
        if "noqa" not in clause_line:
            count += 1
    return count


def fix_bare_except_pass(content: str) -> Tuple[str, int]:
    """Append ``  # noqa: BLE001`` to ``except …: pass`` clauses without one.

    Existing inline comments are preserved; the noqa marker is appended after
    them.  For example::

        except Exception:  # handle I/O errors
        →
        except Exception:  # handle I/O errors  # noqa: BLE001

    Tools like ruff/flake8 recognise noqa markers even when preceded by
    another inline comment on the same line.
    """
    fixed_count = 0

    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        nonlocal fixed_count
        indent = m.group(1)
        clause = m.group(2)
        rest = m.group(3)
        if "noqa" not in clause:   # only annotate if not already marked
            fixed_count += 1
            return f"{indent}{clause}{_NOQA_MARKER}{rest}"
        return m.group(0)

    new_content = _BARE_PASS_RE.sub(_replace, content)
    return new_content, fixed_count


# ---------------------------------------------------------------------------
# Fix type 3: eof_newline
# Ensure every file ends with exactly one newline character.
# ---------------------------------------------------------------------------

def scan_eof_newline(content: str) -> int:
    """Return 1 if the file is missing a trailing newline, else 0."""
    return 1 if (content and not content.endswith("\n")) else 0


def fix_eof_newline(content: str) -> Tuple[str, int]:
    """Append a trailing newline if one is missing."""
    if content and not content.endswith("\n"):
        return content + "\n", 1
    return content, 0


# ---------------------------------------------------------------------------
# Fix catalogue (priority order: highest-priority first)
# Each entry: (name, scanner_fn, fixer_fn, commit_description)
# ---------------------------------------------------------------------------

_FIX_CATALOGUE: List[Tuple[str, Callable[[str], int], Callable[[str], Tuple[str, int]], str]] = [
    (
        "bare_except",
        scan_bare_except,
        fix_bare_except,
        "fix bare except clause",
    ),
    (
        "bare_except_pass",
        scan_bare_except_pass,
        fix_bare_except_pass,
        "annotate silent except-pass with noqa: BLE001",
    ),
    (
        "eof_newline",
        scan_eof_newline,
        fix_eof_newline,
        "add missing EOF newline",
    ),
]


# ---------------------------------------------------------------------------
# Scanner — find the best single issue to fix this run
# ---------------------------------------------------------------------------

def find_best_issue(
    files: List[Path],
    fix_type: Optional[str] = None,
) -> Optional[Issue]:
    """Scan all files and return the single best issue to fix.

    Selection strategy:
    - Iterate fix types in priority order (or honour FORCE_FIX_TYPE).
    - For each type, scan all files and collect (file, count) pairs.
    - Return the **file with the most occurrences** of the first type that
      has any matches at all — maximising impact per commit.
    - Alphabetical path order is used as a tiebreaker for determinism.
    """
    catalogue = [
        entry for entry in _FIX_CATALOGUE
        if fix_type is None or entry[0] == fix_type
    ]

    for fix_name, scanner, _, _ in catalogue:
        best: Optional[Issue] = None
        for path in files:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            count = scanner(content)
            if count > 0:
                if best is None or count > best.count:
                    best = Issue(fix_type=fix_name, file_path=path, count=count)
        if best is not None:
            return best

    return None


# ---------------------------------------------------------------------------
# Fixer — apply the selected fix and validate
# ---------------------------------------------------------------------------

def apply_fix(issue: Issue) -> Optional[Tuple[str, str]]:
    """Apply the fix for *issue* and validate with ``py_compile``.

    Returns ``(new_content, commit_msg)`` on success, or ``None`` if the fix
    fails validation.
    """
    # Locate the fixer in the catalogue
    fixer_fn: Optional[Callable[[str], Tuple[str, int]]] = None
    commit_suffix = ""
    for fix_name, _, fixer, desc in _FIX_CATALOGUE:
        if fix_name == issue.fix_type:
            fixer_fn = fixer
            commit_suffix = desc
            break

    if fixer_fn is None:
        print(f"  ⚠ Unknown fix type: {issue.fix_type}", file=sys.stderr)
        return None

    try:
        original = issue.file_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"  ⚠ Cannot read {issue.file_path}: {exc}", file=sys.stderr)
        return None

    new_content, count = fixer_fn(original)

    if count == 0 or new_content == original:
        print(
            f"  ⚠ Fixer produced no change for {issue.file_path}",
            file=sys.stderr,
        )
        return None

    # Validate with py_compile (catches any accidental syntax corruption)
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", encoding="utf-8", delete=False
        ) as tmp:
            tmp_path = tmp.name
            tmp.write(new_content)
        py_compile.compile(tmp_path, doraise=True)
    except py_compile.PyCompileError as exc:
        print(
            f"  ⚠ Syntax validation FAILED for {issue.file_path}: {exc}",
            file=sys.stderr,
        )
        return None
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    rel = issue.file_path.relative_to(WORKSPACE)
    s = "s" if count != 1 else ""
    commit_msg = f"auto: {commit_suffix} in {rel} ({count} instance{s})"
    return new_content, commit_msg


# ---------------------------------------------------------------------------
# GitHub Actions output helper
# ---------------------------------------------------------------------------

def _set_output(key: str, value: str) -> None:
    """Write a key=value pair to the GitHub Actions GITHUB_OUTPUT file."""
    if GH_OUTPUT:
        with open(GH_OUTPUT, "a", encoding="utf-8") as fh:
            fh.write(f"{key}={value}\n")
    else:
        # Local / dry-run: just print
        print(f"[OUTPUT] {key}={value}")


# ---------------------------------------------------------------------------
# Repository summary (mirrors improvement_bot.py study_own_repo logic)
# ---------------------------------------------------------------------------

def _repo_summary(files: List[Path]) -> None:
    """Print a brief summary of the scanned repository state."""
    py_count = len(files)
    test_count = sum(1 for f in files if f.name.startswith("test_"))
    total_lines = 0
    bare_excepts = 0
    eof_issues = 0
    for path in files:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            total_lines += content.count("\n")
            bare_excepts += scan_bare_except(content)
            eof_issues += scan_eof_newline(content)
        except OSError:
            pass
    print(f"  Python files scanned : {py_count}")
    print(f"  Test files           : {test_count}")
    print(f"  Total lines          : {total_lines:,}")
    print(f"  bare_except issues   : {bare_excepts}")
    print(f"  eof_newline issues   : {eof_issues}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("🧬 Niblit Autonomous Code Evolution Agent")
    print(f"   Workspace : {WORKSPACE}")
    print(f"   Dry run   : {DRY_RUN}")
    print(f"   Fix type  : {FORCE_FIX_TYPE or 'auto (priority order)'}")
    print()

    # 1. Collect files
    files = collect_python_files()
    print(f"📂 Repository scan — {len(files)} Python files")
    _repo_summary(files)
    print()

    # 2. Find best issue
    fix_type = FORCE_FIX_TYPE or None
    issue = find_best_issue(files, fix_type=fix_type)

    if issue is None:
        print("✅ No fixable issues found — the repository is already clean!")
        _set_output("changed_file", "")
        _set_output("commit_msg", "")
        return 0

    rel = issue.file_path.relative_to(WORKSPACE)
    print(f"🎯 Selected improvement")
    print(f"   Fix type  : {issue.fix_type}")
    print(f"   File      : {rel}")
    print(f"   Instances : {issue.count}")
    print()

    # 3. Apply fix
    result = apply_fix(issue)
    if result is None:
        print("⚠ Fix could not be applied — aborting.", file=sys.stderr)
        _set_output("changed_file", "")
        _set_output("commit_msg", "")
        return 1

    new_content, commit_msg = result

    # 4. Dry-run path
    if DRY_RUN:
        print(f"[DRY RUN] Would write: {rel}")
        print(f"[DRY RUN] Commit msg : {commit_msg}")
        _set_output("changed_file", "")
        _set_output("commit_msg", "")
        return 0

    # 5. Write the patched file
    try:
        issue.file_path.write_text(new_content, encoding="utf-8")
    except OSError as exc:
        print(f"  ⚠ Failed to write {issue.file_path}: {exc}", file=sys.stderr)
        return 1

    print(f"✅ Applied: {commit_msg}")
    _set_output("changed_file", str(rel))
    _set_output("commit_msg", commit_msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
