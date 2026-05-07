#!/usr/bin/env python3
"""
nibblebots/autonomous_evolution_agent.py — Niblit Phase 3 Autonomous Evolution Agent

Phase 3 upgrades over Phase 2 (batch-fix + log-priority baseline):

  SEMANTIC UNDERSTANDING
    Every raw issue is classified by semantic_engine.py into a structured
    SemanticIssue: what kind of problem it is, which Niblit subsystem it
    belongs to, severity (0-1), confidence (0-1), and whether it looks
    intentional.  The agent now knows *what* it is fixing, not just
    *which pattern* matched.

  IMPACT SCORING
    impact_engine.py estimates what will improve *before* applying a fix:
    expected_gain, risk_level, and a confidence-weighted net_score per issue.
    Weights start from a built-in prior and are updated by real CI outcomes
    after each commit -- the system learns from experience.

  EVOLUTION PLANNER
    evolution_planner.py ranks all eligible SemanticIssues by net_score and
    builds a gated EvolutionPlan.  Fixes below the risk threshold or
    confidence gate are skipped.  Protected modules (decision_engine,
    meta_engine, trading logic) are never auto-modified.

  FEEDBACK LEARNING LOOP
    feedback_learner.py queries GitHub Actions after each commit to observe
    whether tests passed and CI failures changed, then feeds that signal
    back into the impact weights so the next run makes better decisions.
    All outcomes are appended to outcome_journal.jsonl for traceability.

Phase 2 features retained:
  * Batch fixes (up to EVOLUTION_MAX_FIXES per run)
  * Enriched commit messages with Category / Reason / Impact
  * GitHub Actions log scan for failure-driven priority
  * Fix catalogue: bare_except, bare_except_pass, trailing_whitespace,
    double_blank_lines, eof_newline
  * py_compile validation before every write

Phase 3 full cycle:
  1.  Scan code + GitHub failure logs
  2.  Detect raw issues (Phase 2 fix catalogue)
  3.  Classify into SemanticIssues
  4.  Score impact per SemanticIssue
  5.  Build ranked EvolutionPlan (gate: confidence + risk threshold)
  6.  Execute safe batch fixes (py_compile validated)
  7.  Emit enriched commit message
  8.  Record outcome + update impact weights

Usage (local testing)::

    python nibblebots/autonomous_evolution_agent.py

    EVOLUTION_DRY_RUN=true   python nibblebots/autonomous_evolution_agent.py
    EVOLUTION_MAX_FIXES=10   python nibblebots/autonomous_evolution_agent.py
    EVOLUTION_FIX_TYPE=bare_except  python nibblebots/autonomous_evolution_agent.py
    EVOLUTION_RISK_THRESHOLD=0.10   python nibblebots/autonomous_evolution_agent.py

Environment variables:
    GITHUB_WORKSPACE              -- repo root (auto-set by GitHub Actions)
    GITHUB_TOKEN                  -- token for GitHub API calls (optional locally)
    GITHUB_REPOSITORY             -- owner/repo (auto-set by GitHub Actions)
    GITHUB_SHA                    -- commit SHA set by Actions after push
    EVOLUTION_DRY_RUN             -- "true" -> print without writing
    EVOLUTION_FIX_TYPE            -- force a specific fix type for testing
    EVOLUTION_MAX_FIXES           -- max files to fix per run (default: 5)
    EVOLUTION_RISK_THRESHOLD      -- min net_score to apply a fix (default: 0.05)
    EVOLUTION_CONFIDENCE_MIN      -- min confidence to apply a fix (default: 0.60)
    GITHUB_OUTPUT                 -- step-output file (auto-set by GitHub Actions)
    EVOLUTION_COMMIT_MSG_FILE     -- commit message file path
                                     (default: /tmp/niblit_commit_msg.txt)
    EVOLUTION_CHANGED_FILES_FILE  -- changed-files list path
                                     (default: /tmp/niblit_changed_files.txt)
"""

from __future__ import annotations

import json
import os
import py_compile
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, List, NamedTuple, Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

# Phase 3 semantic intelligence modules.
# Ensure the workspace root is on sys.path so `nibblebots` resolves correctly
# when the script is invoked as `python nibblebots/autonomous_evolution_agent.py`
# from the repo root (the usual case both locally and in GitHub Actions).
try:
    import sys as _sys
    _workspace_root = str(Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve())
    if _workspace_root not in _sys.path:
        _sys.path.insert(0, _workspace_root)
    from nibblebots import semantic_engine, impact_engine, evolution_planner, feedback_learner
    _PHASE3_AVAILABLE = True
except ImportError as _e:
    _PHASE3_AVAILABLE = False

# Phase 15: agent registry and pattern memory (optional — degrades gracefully)
try:
    from nibblebots import agent_registry as _agent_registry  # noqa: PLC0415
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False

# Phase 16-17: System Interface Layer for mirror + resonance governance (optional)
try:
    from nibblebots import system_interface_layer as _sil  # noqa: PLC0415
    _SIL_AVAILABLE = True
except ImportError:
    _SIL_AVAILABLE = False

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WORKSPACE = Path(os.environ.get("GITHUB_WORKSPACE", ".")).resolve()
DRY_RUN = os.environ.get("EVOLUTION_DRY_RUN", "").lower() == "true"
FORCE_FIX_TYPE = os.environ.get("EVOLUTION_FIX_TYPE", "").strip()
MAX_FIXES = int(os.environ.get("EVOLUTION_MAX_FIXES", "5"))
GH_OUTPUT = os.environ.get("GITHUB_OUTPUT", "")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
COMMIT_MSG_FILE = os.environ.get(
    "EVOLUTION_COMMIT_MSG_FILE", "/tmp/niblit_commit_msg.txt"
)
CHANGED_FILES_FILE = os.environ.get(
    "EVOLUTION_CHANGED_FILES_FILE", "/tmp/niblit_changed_files.txt"
)
GITHUB_SHA = os.environ.get("GITHUB_SHA", "")

# ---------------------------------------------------------------------------
# Phase 16: Dual-lane execution model
# ---------------------------------------------------------------------------

# Fix types that are near-zero risk and can bypass the semantic/impact pipeline
LOW_RISK_FIXES: frozenset = frozenset({
    "trailing_whitespace",
    "double_blank_lines",
    "eof_newline",
})

# Maximum files to fix in the bulk (Lane 2) execution pass
BULK_MAX_FIXES = int(os.environ.get("EVOLUTION_BULK_MAX_FIXES", "50"))

# Set EVOLUTION_BULK_LANE=false to disable the bulk lane entirely
BULK_LANE_ENABLED = os.environ.get("EVOLUTION_BULK_LANE", "true").lower() != "false"


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
# Fix metadata — enriches every commit with reason + impact
# ---------------------------------------------------------------------------

_FIX_METADATA: dict = {
    "bare_except": {
        "category": "Error Handling",
        "reason": (
            "Bare `except:` clauses catch SystemExit and KeyboardInterrupt, "
            "masking crashes and making the system impossible to interrupt "
            "cleanly. They hide the root cause of failures from logs and "
            "the Niblit evaluation engine."
        ),
        "impact": (
            "Improves crash visibility, enables proper interrupt handling, "
            "and satisfies linter rule BLE001 / E722. Failures are now "
            "observable by the SDAL decision loop."
        ),
    },
    "bare_except_pass": {
        "category": "Error Handling",
        "reason": (
            "Silent `except … pass` blocks swallow exceptions without any "
            "trace. Even the Niblit MetaEngine cannot observe or recover "
            "from silenced errors, breaking the evaluation feedback loop."
        ),
        "impact": (
            "Marks intentional silences explicitly so future engineers and "
            "automated tools can distinguish deliberate suppression from "
            "accidental omission. Improves auditability (noqa: BLE001)."
        ),
    },
    "trailing_whitespace": {
        "category": "Code Style",
        "reason": (
            "Trailing whitespace creates noisy diffs — every change to "
            "such a line shows up as two edits — breaks some editors and "
            "Git hooks, and fails whitespace-strict CI checks."
        ),
        "impact": (
            "Cleaner diffs, consistent formatting across all editors, "
            "and compliance with ruff rules W291 / W293."
        ),
    },
    "double_blank_lines": {
        "category": "Code Style",
        "reason": (
            "PEP 8 requires exactly two blank lines between top-level "
            "definitions. Three or more blank lines inflate file length "
            "without adding structural information."
        ),
        "impact": (
            "Reduces visual noise, standardises rhythm, and satisfies "
            "ruff rule E303."
        ),
    },
    "eof_newline": {
        "category": "Code Style",
        "reason": (
            "Files without a terminal newline violate POSIX and cause diff "
            "tools to display a 'No newline at end of file' warning, "
            "polluting code review."
        ),
        "impact": (
            "Eliminates spurious diff noise and satisfies ruff rule W292 "
            "and the POSIX text-file standard."
        ),
    },
}


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

    for dir_name in _SCAN_DIRS:
        dir_path = WORKSPACE / dir_name
        if not dir_path.is_dir():
            continue
        for p in sorted(dir_path.rglob("*.py")):
            if any(part in _SKIP_PARTS for part in p.parts):
                continue
            _add(p)

    for p in sorted(WORKSPACE.glob("*.py")):
        if any(part in _SKIP_PARTS for part in p.parts):
            continue
        _add(p)

    return files


# ---------------------------------------------------------------------------
# Fix type 1: bare_except
# ---------------------------------------------------------------------------

_BARE_EXCEPT_RE = re.compile(r"^(\s*)except\s*:", re.MULTILINE)


def scan_bare_except(content: str) -> int:
    """Return the number of bare ``except:`` clauses in *content*."""
    return len(_BARE_EXCEPT_RE.findall(content))


def fix_bare_except(content: str) -> Tuple[str, int]:
    """Replace ``except:`` with ``except Exception:``, preserving indentation."""
    new_content, n = _BARE_EXCEPT_RE.subn(r"\1except Exception:", content)
    return new_content, n


# ---------------------------------------------------------------------------
# Fix type 2: bare_except_pass
# ---------------------------------------------------------------------------

_BARE_PASS_RE = re.compile(
    r"^(\s*)(except\s+\w[^:\n]*:)(\s*\n\s+pass\b)",
    re.MULTILINE,
)
_NOQA_MARKER = "  # noqa: BLE001"


def scan_bare_except_pass(content: str) -> int:
    """Count ``except …: pass`` blocks that do not already carry a noqa marker."""
    return sum(1 for m in _BARE_PASS_RE.finditer(content) if "noqa" not in m.group(2))


def fix_bare_except_pass(content: str) -> Tuple[str, int]:
    """Append ``  # noqa: BLE001`` to un-annotated ``except …: pass`` clauses."""
    fixed = 0

    def _replace(m: re.Match) -> str:  # type: ignore[type-arg]
        nonlocal fixed
        if "noqa" not in m.group(2):
            fixed += 1
            return f"{m.group(1)}{m.group(2)}{_NOQA_MARKER}{m.group(3)}"
        return m.group(0)

    return _BARE_PASS_RE.sub(_replace, content), fixed


# ---------------------------------------------------------------------------
# Fix type 3: trailing_whitespace  (Phase 2 — NEW)
# Strip trailing spaces/tabs from every line.
# ---------------------------------------------------------------------------

_TRAILING_WS_RE = re.compile(r"[ \t]+$", re.MULTILINE)


def scan_trailing_whitespace(content: str) -> int:
    """Return the number of lines that end with trailing whitespace."""
    return len(_TRAILING_WS_RE.findall(content))


def fix_trailing_whitespace(content: str) -> Tuple[str, int]:
    """Strip trailing spaces and tabs from every line."""
    new_content, n = _TRAILING_WS_RE.subn("", content)
    return new_content, n


# ---------------------------------------------------------------------------
# Fix type 4: double_blank_lines  (Phase 2 — NEW)
# Collapse 3 or more consecutive blank lines to exactly 2 (PEP 8 E303).
# ---------------------------------------------------------------------------

_TRIPLE_BLANK_RE = re.compile(r"\n{4,}")   # 3+ blank lines = 4+ consecutive \n


def scan_double_blank_lines(content: str) -> int:
    """Return the number of 3+-blank-line blocks in *content*."""
    return len(_TRIPLE_BLANK_RE.findall(content))


def fix_double_blank_lines(content: str) -> Tuple[str, int]:
    """Collapse every run of 3+ blank lines to exactly 2."""
    new_content, n = _TRIPLE_BLANK_RE.subn("\n\n\n", content)
    return new_content, n


# ---------------------------------------------------------------------------
# Fix type 5: eof_newline
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
# Fix catalogue  (priority order: highest-impact / most-critical first)
# Each entry: (name, scanner_fn, fixer_fn)
# ---------------------------------------------------------------------------

_FIX_CATALOGUE: List[Tuple[str, Callable[[str], int], Callable[[str], Tuple[str, int]]]] = [
    ("bare_except",        scan_bare_except,        fix_bare_except),
    ("bare_except_pass",   scan_bare_except_pass,   fix_bare_except_pass),
    ("trailing_whitespace", scan_trailing_whitespace, fix_trailing_whitespace),
    ("double_blank_lines", scan_double_blank_lines, fix_double_blank_lines),
    ("eof_newline",        scan_eof_newline,         fix_eof_newline),
]


# ---------------------------------------------------------------------------
# GitHub API helper  (used by log-priority scanner)
# ---------------------------------------------------------------------------

def _gh_get(path: str) -> Any:
    """GET from GitHub REST API v3.  Returns parsed JSON or None.

    Only requests to ``https://api.github.com`` are made; arbitrary URLs
    are rejected so the function cannot be misused as an open HTTP client.
    """
    _API_BASE = "https://api.github.com"
    if path.startswith("http"):
        if not path.startswith(_API_BASE):
            print(
                f"  ⚠ _gh_get: rejected non-GitHub URL: {path!r}",
                file=sys.stderr,
            )
            return None
        url = path
    else:
        url = f"{_API_BASE}{path}"

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Niblit-Evolution-Agent/3.0",
    }
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=15) as resp:  # noqa: S310
            return json.loads(resp.read().decode())
    except URLError as exc:
        print(f"  ⚠ GitHub API network error ({url}): {exc}", file=sys.stderr)
        return None
    except OSError as exc:
        print(f"  ⚠ GitHub API OS error ({url}): {exc}", file=sys.stderr)
        return None
    except json.JSONDecodeError as exc:
        print(f"  ⚠ GitHub API malformed JSON ({url}): {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Log-driven priority scanner  (Phase 2 key feature)
#
# Maps keywords in failed workflow/job names to Python path substrings so
# that files associated with recent CI failures are fixed first.
# ---------------------------------------------------------------------------

_WORKFLOW_PRIORITY_MAP: dict = {
    "test":         ["test_", "modules/", "niblit_core.py", "niblit_router.py"],
    "deploy":       ["app.py", "niblit_core.py", "start.sh"],
    "improve":      ["nibblebots/improvement_bot.py"],
    "research":     ["nibblebots/research_bot.py", "modules/researcher_engine.py"],
    "trading":      ["nibblebots/ai_trading_bot.py", "NiblitSignalStrategy.py",
                     "modules/trade_kb_learner.py"],
    "aios":         ["nibblebots/aios_", "modules/aios_"],
    "llm":          ["nibblebots/llm_engineer_bot.py"],
    "architecture": ["nibblebots/aios_architecture_bot.py"],
    "evolution":    ["nibblebots/autonomous_evolution_agent.py"],
    "copilot":      ["modules/", "niblit_core.py", "nibblebots/"],
}

# ---------------------------------------------------------------------------
# Phase 16: Failure → Fix mapping layer
#
# Maps keywords found in failed CI workflow/job names to the most likely
# fix types.  Allows the agent to react to *what kind* of failure occurred
# rather than relying purely on static fix-type priority.
# ---------------------------------------------------------------------------

_FAILURE_FIX_MAP: dict = {
    "test":     ["bare_except", "bare_except_pass"],
    "copilot":  ["bare_except_pass", "trailing_whitespace"],
    "import":   ["bare_except_pass"],
    "syntax":   ["trailing_whitespace", "eof_newline"],
    "linting":  ["trailing_whitespace", "double_blank_lines", "eof_newline"],
    "quality":  ["trailing_whitespace", "bare_except_pass"],
    "deploy":   ["bare_except", "eof_newline"],
    "runtime":  ["bare_except"],
}


def get_log_priority_files() -> frozenset:
    """Query GitHub Actions for recent failures and return priority path substrings.

    Any file whose repo-relative path contains one of the returned substrings
    is treated as high-priority by ``find_batch_issues()``.

    This is the Phase 2 "failure-driven evolution" capability: runtime CI
    failures feed directly into fix selection so the agent targets actively
    broken code rather than a random file with the most style issues.
    """
    if not TOKEN or not REPO:
        print("  ℹ  Log scan skipped (GITHUB_TOKEN / GITHUB_REPOSITORY not set)")
        return frozenset()

    print("  🔍 Scanning GitHub Actions for recent failures...")
    data = _gh_get(f"/repos/{REPO}/actions/runs?status=failure&per_page=5")
    if not data or "workflow_runs" not in data:
        print("  ℹ  No failure data returned from GitHub API")
        return frozenset()

    priority: set = set()
    failed_names: list = []
    for run in data["workflow_runs"]:
        wf_name = (run.get("name") or "").lower()
        failed_names.append(wf_name)
        for keyword, paths in _WORKFLOW_PRIORITY_MAP.items():
            if keyword in wf_name:
                priority.update(paths)

    if failed_names:
        print(f"  ⚠  Recent failures  : {', '.join(failed_names[:5])}")
        if priority:
            print(f"  🎯 Priority targets : {', '.join(sorted(priority))}")
    else:
        print("  ✅ No recent workflow failures detected")

    return frozenset(priority)


def get_failure_fix_hints() -> List[str]:
    """Phase 16 Failure→Fix mapping layer: map CI failure patterns to fix types.

    Complements the log-priority scan: instead of only returning *which files*
    to prioritise, this function returns *which fix types* to attempt based on
    keywords in the failed workflow and job names.  Job and step names are
    scanned for keywords (test, import, syntax, …) that predict which fix type
    is most likely to reduce the failure rate.

    Returns a priority-ordered list of fix_type strings (most relevant first).
    Falls back to an empty list if the GitHub API is unavailable or no signal
    is found.
    """
    if not TOKEN or not REPO:
        return []

    data = _gh_get(f"/repos/{REPO}/actions/runs?status=failure&per_page=5")
    if not data or "workflow_runs" not in data:
        return []

    hits: dict = {}   # fix_type → relevance score
    for run in data["workflow_runs"][:5]:
        wf_name = (run.get("name") or "").lower()
        for keyword, fix_types in _FAILURE_FIX_MAP.items():
            if keyword in wf_name:
                for ft in fix_types:
                    hits[ft] = hits.get(ft, 0) + 1

        run_id = run.get("id")
        if not run_id:
            continue
        jobs_data = _gh_get(
            f"/repos/{REPO}/actions/runs/{run_id}/jobs?per_page=10"
        )
        if not jobs_data or "jobs" not in jobs_data:
            continue
        for job in jobs_data["jobs"]:
            if job.get("conclusion") not in ("failure", "timed_out"):
                continue
            # Combine job name and failed step names for keyword scanning
            job_text = (job.get("name") or "").lower()
            for step in (job.get("steps") or []):
                if step.get("conclusion") == "failure":
                    job_text += " " + (step.get("name") or "").lower()
            for keyword, fix_types in _FAILURE_FIX_MAP.items():
                if keyword in job_text:
                    for ft in fix_types:
                        hits[ft] = hits.get(ft, 0) + 2  # job signal weighted higher

    ordered = sorted(hits, key=lambda k: -hits[k])
    if ordered:
        print(f"  🔥 Failure→fix hints     : {', '.join(ordered[:3])}")
    return ordered



def find_batch_issues(
    files: List[Path],
    fix_type: Optional[str] = None,
    max_issues: int = MAX_FIXES,
    priority_files: frozenset = frozenset(),
    preferred_fix_types: Optional[List[str]] = None,
) -> List[Issue]:
    """Scan all files and return up to *max_issues* Issues of the same fix type.

    All returned issues share one fix type (the highest-priority type with
    any matches).  Grouping by fix type produces a focused, reviewable commit
    rather than a grab-bag of unrelated changes.

    Sort order:
      1. Files matching a priority path prefix (from log scan) first.
      2. Highest instance count first (maximum impact per file).
      3. Alphabetical as a deterministic tiebreaker.

    Phase 15: if *preferred_fix_types* is supplied (from pre-task memory search
    or the agent registry trust order), those fix types are tried first before
    the default catalogue priority.
    """
    # Phase 15: build an ordered catalogue that respects preferred_fix_types
    base_catalogue = [
        entry for entry in _FIX_CATALOGUE
        if fix_type is None or entry[0] == fix_type
    ]
    if preferred_fix_types:
        pref_lookup = set(preferred_fix_types)   # O(1) membership checks
        # First pass: entries matching a preferred type (preserve preference order)
        ordered: list = [
            e for name in preferred_fix_types
            for e in base_catalogue if e[0] == name
        ]
        # Second pass: everything else from the base catalogue
        ordered += [e for e in base_catalogue if e[0] not in pref_lookup]
        catalogue = ordered
    else:
        catalogue = base_catalogue

    for fix_name, scanner, _ in catalogue:
        matches: List[Issue] = []
        for path in files:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            count = scanner(content)
            if count > 0:
                matches.append(Issue(fix_type=fix_name, file_path=path, count=count))

        if not matches:
            continue

        def _sort_key(issue: Issue) -> tuple:
            rel = str(issue.file_path.relative_to(WORKSPACE))
            is_priority = any(pf in rel for pf in priority_files)
            return (not is_priority, -issue.count, rel)

        matches.sort(key=_sort_key)
        return matches[:max_issues]

    return []


def find_bulk_issues(
    files: List[Path],
    max_issues: int = BULK_MAX_FIXES,
    priority_files: frozenset = frozenset(),
) -> dict:
    """Phase 16 Lane 2: scan for all LOW_RISK_FIXES types simultaneously.

    Unlike ``find_batch_issues`` (which returns ONE fix type), this function
    scans for every type in ``LOW_RISK_FIXES`` and returns a dict mapping
    fix_type → List[Issue].  Each list is independently capped at
    *max_issues* files and sorted by priority (priority_files first, then
    highest instance count, then alphabetical for determinism).

    Results are intentionally NOT run through the semantic/impact pipeline —
    LOW_RISK_FIXES are considered near-zero risk and are applied directly
    without scoring or confidence gating.
    """
    results: dict = {}
    for fix_name, scanner, _ in _FIX_CATALOGUE:
        if fix_name not in LOW_RISK_FIXES:
            continue
        matches: List[Issue] = []
        for path in files:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            count = scanner(content)
            if count > 0:
                matches.append(Issue(fix_type=fix_name, file_path=path, count=count))
        if not matches:
            continue

        def _bulk_sort_key(issue: Issue) -> tuple:
            rel = str(issue.file_path.relative_to(WORKSPACE))
            is_priority = any(pf in rel for pf in priority_files)
            return (not is_priority, -issue.count, rel)

        matches.sort(key=_bulk_sort_key)
        results[fix_name] = matches[:max_issues]
    return results



def _apply_single_fix(issue: Issue) -> Optional[Tuple[str, int]]:
    """Apply the fix for *issue*, validate with py_compile.

    Returns ``(new_content, count)`` on success, ``None`` on failure.
    """
    fixer: Optional[Callable[[str], Tuple[str, int]]] = None
    for fix_name, _, fn in _FIX_CATALOGUE:
        if fix_name == issue.fix_type:
            fixer = fn
            break

    if fixer is None:
        return None

    try:
        original = issue.file_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"    ⚠ Cannot read {issue.file_path.name}: {exc}", file=sys.stderr)
        return None

    new_content, count = fixer(original)
    if count == 0 or new_content == original:
        return None

    # Validate with py_compile — catches accidental syntax corruption
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(
            suffix=".py", mode="w", encoding="utf-8", delete=False
        ) as tmp:
            tmp_path = tmp.name
            tmp.write(new_content)
        py_compile.compile(tmp_path, doraise=True)
    except py_compile.PyCompileError as exc:
        print(
            f"    ⚠ Syntax validation FAILED for {issue.file_path.name}: {exc}",
            file=sys.stderr,
        )
        return None
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError as exc:
                print(
                    f"    ℹ Could not remove temp file {tmp_path}: {exc}",
                    file=sys.stderr,
                )

    return new_content, count


# ---------------------------------------------------------------------------
# Enriched commit message builder  (Phase 2 key feature)
# ---------------------------------------------------------------------------

# Human-readable verb phrase for each fix type (used in commit subject)
_SUBJECT_VERBS: dict = {
    "bare_except":         "fix bare except clause",
    "bare_except_pass":    "annotate silent except-pass",
    "trailing_whitespace": "strip trailing whitespace",
    "double_blank_lines":  "collapse excess blank lines",
    "eof_newline":         "add missing EOF newline",
}


def build_commit_message(
    fix_type: str,
    fixed_files: List[Tuple[Path, int]],   # (path, instance_count)
    total_count: int,
) -> Tuple[str, str]:
    """Build an enriched git commit subject + body.

    The body includes:
      - Category (e.g. "Error Handling")
      - Reason  — why this pattern is harmful
      - Impact  — what improves after the fix
      - Per-file breakdown  — file path and instance count

    Returns ``(subject_line, full_message)``.
    """
    meta = _FIX_METADATA.get(fix_type, {})
    n_files = len(fixed_files)
    s_files = "s" if n_files != 1 else ""
    s_inst = "s" if total_count != 1 else ""

    verb = _SUBJECT_VERBS.get(fix_type, f"apply {fix_type} fix")
    subject = (
        f"auto: {verb} in {n_files} file{s_files} "
        f"({total_count} instance{s_inst})"
    )

    lines = [subject, ""]

    category = meta.get("category", "Code Quality")
    lines.append(f"Category: {category}")

    if "reason" in meta:
        lines += ["", f"Reason: {meta['reason']}"]

    if "impact" in meta:
        lines += ["", f"Impact: {meta['impact']}"]

    lines += ["", f"Files changed ({n_files}):"]
    for path, count in sorted(fixed_files, key=lambda x: -x[1]):
        rel = str(path.relative_to(WORKSPACE))
        s = "s" if count != 1 else ""
        lines.append(f"  {rel:<60} ({count} instance{s})")

    lines += ["", "[Niblit Evolution Agent — Phase 3]"]
    return subject, "\n".join(lines)


def _build_lane2_section(
    lane2_fixed: List[Tuple[Path, int, str]],  # (path, count, fix_type)
) -> str:
    """Phase 16: build the Lane 2 bulk-cleanup section for the commit body.

    Produces a tidy per-fix-type summary that is appended to the intelligent
    lane's commit message when both lanes contributed changes.
    """
    by_type: dict = {}
    for path, count, ft in lane2_fixed:
        by_type.setdefault(ft, []).append((path, count))

    lines = ["Lane 2 — Bulk Low-Risk Cleanup:"]
    for ft, entries in by_type.items():
        n = len(entries)
        total = sum(c for _, c in entries)
        verb = _SUBJECT_VERBS.get(ft, ft)
        meta = _FIX_METADATA.get(ft, {})
        category = meta.get("category", "Code Style")
        s_f = "s" if n != 1 else ""
        s_i = "s" if total != 1 else ""
        lines.append(f"  [{category}] {verb}: {n} file{s_f}, {total} instance{s_i}")
        for path, count in sorted(entries, key=lambda x: -x[1]):
            rel = str(path.relative_to(WORKSPACE))
            lines.append(f"    {rel:<60} ({count} instance{'s' if count != 1 else ''})")
    return "\n".join(lines)


def _build_bulk_commit_message(
    lane2_fixed: List[Tuple[Path, int, str]],  # (path, count, fix_type)
) -> Tuple[str, str]:
    """Phase 16: build a standalone commit message when only Lane 2 ran.

    Used when the intelligent lane planner gated all fixes but the bulk lane
    still has cosmetic cleanup work to do.
    """
    by_type: dict = {}
    for path, count, ft in lane2_fixed:
        by_type.setdefault(ft, []).append((path, count))

    type_parts = []
    for ft, entries in by_type.items():
        n = len(entries)
        verb = _SUBJECT_VERBS.get(ft, ft)
        type_parts.append(f"{verb} in {n} file{'s' if n != 1 else ''}")
    total_inst = sum(c for _, c, _ in lane2_fixed)
    s_inst = "s" if total_inst != 1 else ""
    subject = "auto: " + " + ".join(type_parts) + f" ({total_inst} instance{s_inst})"

    lines = [subject, ""]
    lines.append("Category: Code Style (Bulk Cleanup)")
    lines += [
        "",
        (
            "Reason: Phase 16 bulk execution lane applied low-risk cosmetic fixes that "
            "bypass the semantic scoring pipeline.  These changes (trailing whitespace, "
            "blank lines, EOF newlines) are near-zero risk and improve diff cleanliness."
        ),
        "",
        (
            "Impact: Cleaner diffs, consistent formatting, and compliance with ruff "
            "rules W291/W292/W293/E303.  Enables the intelligent lane to focus on "
            "higher-value semantic fixes on future runs."
        ),
        "",
        _build_lane2_section(lane2_fixed),
        "",
        "[Niblit Evolution Agent — Phase 16]",
    ]
    return subject, "\n".join(lines)



def _set_output(key: str, value: str) -> None:
    """Write a step-output variable to GITHUB_OUTPUT (supports multiline)."""
    if GH_OUTPUT:
        with open(GH_OUTPUT, "a", encoding="utf-8") as fh:
            if "\n" in value:
                fh.write(f"{key}<<NIBLIT_EOF\n{value}\nNIBLIT_EOF\n")
            else:
                fh.write(f"{key}={value}\n")
    else:
        print(f"[OUTPUT] {key}={value!r}")


# ---------------------------------------------------------------------------
# Repository health summary
# ---------------------------------------------------------------------------

def _repo_summary(files: List[Path]) -> None:
    """Print an issue-count table covering all fix types."""
    counts: dict = {name: 0 for name, _, _ in _FIX_CATALOGUE}
    total_lines = 0
    test_count = sum(1 for f in files if f.name.startswith("test_"))

    for path in files:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            total_lines += content.count("\n")
            for fix_name, scanner, _ in _FIX_CATALOGUE:
                counts[fix_name] += scanner(content)
        except OSError as exc:
            print(
                f"  ℹ Summary: could not read {path.name}: {exc}",
                file=sys.stderr,
            )

    print(f"  Python files scanned     : {len(files)}")
    print(f"  Test files               : {test_count}")
    print(f"  Total lines              : {total_lines:,}")
    print()
    print("  Open issues by fix type:")
    for fix_name, _, _ in _FIX_CATALOGUE:
        n = counts[fix_name]
        bar = "█" * min(n, 40)
        print(f"    {fix_name:<24} : {n:>4}  {bar}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("🧬 Niblit Autonomous Evolution Agent — Phase 16")
    print(f"   Workspace  : {WORKSPACE}")
    print(f"   Dry run    : {DRY_RUN}")
    print(f"   Fix type   : {FORCE_FIX_TYPE or 'auto (priority order)'}")
    print(f"   Max fixes  : {MAX_FIXES} files per run (Lane 1)")
    print(f"   Bulk lane  : {'ENABLED — up to ' + str(BULK_MAX_FIXES) + ' files' if BULK_LANE_ENABLED else 'disabled'}")
    if _PHASE3_AVAILABLE:
        print("   Phase 3    : semantic + impact + planner + feedback ACTIVE")
    else:
        print("   Phase 3    : modules unavailable — falling back to Phase 2 mode")
    if _REGISTRY_AVAILABLE:
        print(f"   Phase 15   : agent registry ACTIVE — {_agent_registry.registry_summary()}")
    print()

    # Phase 15 — Step 0: Pre-task memory search (Ruflo "search before starting")
    # Query pattern_memory.jsonl and agent_registry for highest-trust fix types
    # before scanning so the batch scanner is biased toward proven patterns.
    preferred_fix_types: Optional[List[str]] = None
    if _PHASE3_AVAILABLE and _REGISTRY_AVAILABLE and not FORCE_FIX_TYPE:
        try:
            top_patterns = feedback_learner.load_top_patterns(min_confidence=0.70, top_n=5)
            if top_patterns:
                pref = [p["fix_type"] for p in top_patterns]
                print(
                    "🧠 Phase 15: pre-task memory search — top patterns: "
                    + ", ".join(f"{p['fix_type']}({p['avg_outcome']:.2f})" for p in top_patterns[:3])
                )
                preferred_fix_types = pref
        except Exception:  # noqa: BLE001
            pass

        # Complement with registry trust order (registry knows about fix types
        # the memory hasn't seen yet — e.g. on a fresh install)
        try:
            registry_order = _agent_registry.fix_types_by_trust()
            if registry_order:
                if preferred_fix_types:
                    # Append registry-order items that aren't already in the list
                    for ft in registry_order:
                        if ft not in preferred_fix_types:
                            preferred_fix_types.append(ft)
                else:
                    preferred_fix_types = registry_order
                    print(
                        "🧠 Phase 15: registry-driven fix order: "
                        + " → ".join(preferred_fix_types[:5])
                    )
        except Exception:  # noqa: BLE001
            pass
        print()

    # 1. Collect files
    files = collect_python_files()
    print(f"📂 Repository scan — {len(files)} Python files")
    _repo_summary(files)
    print()

    # 2. Log-driven priority (Phase 2) + Phase 16 failure-to-fix hints
    print("📡 Querying GitHub Actions for failure-driven priorities...")
    priority_files = get_log_priority_files()

    # Phase 16: merge failure→fix hints into preferred_fix_types so that fix
    # types associated with real CI failures are tried first this cycle.
    failure_fix_hints = get_failure_fix_hints()
    if failure_fix_hints and not FORCE_FIX_TYPE:
        if preferred_fix_types:
            # Prepend hints that aren't already in the list, preserving hint order
            new_prefixes = [ft for ft in failure_fix_hints if ft not in preferred_fix_types]
            preferred_fix_types = new_prefixes + preferred_fix_types
        else:
            preferred_fix_types = list(failure_fix_hints)
        print(
            "  💡 Failure→fix hints merged: "
            + " → ".join(preferred_fix_types[:3])
        )

    # Phase 16 SIL: mirror the CI environment as an external system so that
    # Niblit can establish resonance and adapt its strategy to the CI signal
    # patterns before scoring and planning fixes.
    if _SIL_AVAILABLE:
        try:
            # Derive current objective from goal_adaptation_engine when available.
            _sil_objective = "maximize_stability"
            if _PHASE3_AVAILABLE:
                try:
                    from nibblebots import goal_adaptation_engine as _gae  # noqa: PLC0415
                    _sil_objective = _gae.evaluate() or "maximize_stability"
                except Exception:  # noqa: BLE001
                    pass

            _ci_signal_data: dict = {}
            if failure_fix_hints:
                for ft in failure_fix_hints:
                    _ci_signal_data[f"ci_failure_{ft}"] = 1.0
            if priority_files:
                _ci_signal_data["ci_priority_files"] = float(len(priority_files))
            _ci_signal_data["ci_max_fixes"] = float(MAX_FIXES)
            _ci_profile = _sil.mirror_system(
                "niblit_ci",
                _ci_signal_data,
                current_objective=_sil_objective,
                authority_domains=["risk", "rollback", "exploration"],
            )
            _ci_resonance = _sil.establish_resonance(
                _ci_profile,
                current_objective=_sil_objective,
            )
            print(
                f"  🪞 Phase 16 SIL: mirrored niblit_ci → "
                f"{_ci_profile.decision_structure}"
            )
            print(
                f"  🎯 Resonance: trust={_ci_resonance.signal_weight_adj:.3f} "
                f"explore_adj={_ci_resonance.explore_rate_adj:+.4f}"
                + (" [OBJECTIVE_CONFLICT]" if _ci_resonance.objective_conflict else "")
            )
        except Exception:  # noqa: BLE001
            pass
    print()

    # 3. Find raw batch of issues to fix this cycle
    fix_type = FORCE_FIX_TYPE or None
    issues = find_batch_issues(
        files,
        fix_type=fix_type,
        max_issues=MAX_FIXES * 3,   # over-fetch; planner will gate down to MAX_FIXES
        priority_files=priority_files,
        preferred_fix_types=preferred_fix_types,  # Phase 15
    )

    if not issues:
        print("✅ No fixable issues found — the repository is already clean!")
        _set_output("changed_files", "")
        _set_output("commit_subject", "")
        return 0

    # 4. Phase 3: Semantic classification + impact scoring + planner
    if _PHASE3_AVAILABLE:
        print("🧠 Phase 3: classifying issues semantically...")
        semantic_issues = semantic_engine.classify_batch(issues, workspace=WORKSPACE)

        print("⚖️  Phase 3: scoring impact per issue...")
        impact_scores = impact_engine.score_batch(semantic_issues)

        paired = list(zip(semantic_issues, impact_scores))

        print("📋 Phase 3: building ranked evolution plan...")
        plan = evolution_planner.build_plan(paired, workspace=WORKSPACE, max_fixes=MAX_FIXES)
        evolution_planner.print_plan(plan)
        print()

        if not plan.planned_fixes:
            # Phase 16: don't exit — fall through to the bulk lane which may
            # still have low-risk cosmetic cleanup work to do.
            print("ℹ️  Planner: no fixes above gate — continuing to bulk lane.")
            ordered_issues = []
            fix_type_name = None

        # Phase 15 — swarm topology split for large batches (>3 fixes)
        # When MAX_FIXES > 3 and the plan has > 3 fixes, split into a "core"
        # worker (subsystem in {core, evaluation, learning}) and a "peripheral"
        # worker.  Each worker scores its sub-plan; they merge ordered by score.
        if len(plan.planned_fixes) > 3:
            _core_subs = {"core", "evaluation", "learning", "error_handling"}
            core_fixes = [
                pf for pf in plan.planned_fixes
                if pf.semantic_issue.subsystem in _core_subs
            ]
            peripheral_fixes = [
                pf for pf in plan.planned_fixes
                if pf.semantic_issue.subsystem not in _core_subs
            ]
            # Each worker sub-plan is sorted by net_score desc (best first)
            core_fixes.sort(key=lambda pf: -pf.impact.net_score)
            peripheral_fixes.sort(key=lambda pf: -pf.impact.net_score)
            # Interleave: core first, then peripheral (mirrors Ruflo coordinator/worker merge)
            merged = core_fixes + peripheral_fixes
            if merged:
                plan = plan._replace(planned_fixes=merged[:MAX_FIXES])
                print(
                    f"🐝 Phase 15 swarm split: {len(core_fixes)} core + "
                    f"{len(peripheral_fixes)} peripheral → "
                    f"{len(plan.planned_fixes)} merged"
                )
                print()

        # Extract the Issue objects in plan order (Phase 2 execution engine takes Issue)
        planned_fix_types = {pf.semantic_issue.file_path for pf in plan.planned_fixes}
        ordered_issues = [
            i for i in issues if i.file_path in planned_fix_types
        ]
        # Preserve planner order
        ordered_issues.sort(
            key=lambda i: next(
                pf.rank for pf in plan.planned_fixes
                if pf.semantic_issue.file_path == i.file_path
            )
        )
        fix_type_name = ordered_issues[0].fix_type if ordered_issues else None
    else:
        # Phase 2 fallback: apply issues directly
        ordered_issues = issues[:MAX_FIXES]
        fix_type_name = issues[0].fix_type
        plan = None

    # When Lane 1 has nothing and Lane 2 is not available, exit cleanly
    if not ordered_issues and (not BULK_LANE_ENABLED or FORCE_FIX_TYPE):
        print("✅ No eligible fixes found — repository is clean or all issues gated.")
        _set_output("changed_files", "")
        _set_output("commit_subject", "")
        return 0

    if ordered_issues:
        print(f"🎯 Selected fix type  : {fix_type_name}")
        print(f"   Files to fix       : {len(ordered_issues)}")
        print(f"   Total instances    : {sum(i.count for i in ordered_issues)}")
    else:
        print("ℹ️  Lane 1: no fixes selected — bulk lane will handle cleanup only")
    print()

    # 5. Apply fixes — Lane 1 (intelligent pipeline) + Lane 2 (bulk low-risk)
    lane1_fixed: List[Tuple[Path, int]] = []
    lane2_fixed: List[Tuple[Path, int, str]] = []  # (path, count, fix_type)
    written_files: List[Path] = []
    lane1_count = 0
    lane2_count = 0

    for issue in ordered_issues:
        rel = issue.file_path.relative_to(WORKSPACE)
        result = _apply_single_fix(issue)
        if result is None:
            print(f"  ⚠ Skipping {rel} — validation failed")
            continue

        new_content, count = result
        lane1_count += count
        lane1_fixed.append((issue.file_path, count))
        s = "s" if count != 1 else ""
        print(f"  ✅ {rel} ({count} instance{s})")

        if DRY_RUN:
            continue

        try:
            issue.file_path.write_text(new_content, encoding="utf-8")
            written_files.append(issue.file_path)
        except OSError as exc:
            print(f"  ⚠ Failed to write {rel}: {exc}", file=sys.stderr)

    # Phase 16 — Lane 2: bulk low-risk execution
    # trailing_whitespace / double_blank_lines / eof_newline bypass the
    # semantic+impact pipeline entirely — near-zero risk, high throughput.
    if BULK_LANE_ENABLED and not FORCE_FIX_TYPE:
        lane1_paths = {p for p, _ in lane1_fixed}
        bulk_results = find_bulk_issues(
            files=[f for f in files if f not in lane1_paths],
            max_issues=BULK_MAX_FIXES,
            priority_files=priority_files,
        )
        if bulk_results:
            _total_bulk = sum(len(v) for v in bulk_results.values())
            print(
                f"\n🚀 Phase 16 — Lane 2 ({_total_bulk} file(s) across "
                f"{len(bulk_results)} fix type(s))"
            )
            for bulk_ft, bulk_batch in bulk_results.items():
                verb = _SUBJECT_VERBS.get(bulk_ft, bulk_ft)
                print(f"   {verb}:")
                for issue in bulk_batch:
                    rel = issue.file_path.relative_to(WORKSPACE)
                    result = _apply_single_fix(issue)
                    if result is None:
                        print(f"    ⚠ Skipping {rel} — validation failed")
                        continue
                    new_content, count = result
                    lane2_count += count
                    s = "s" if count != 1 else ""
                    print(f"    ✅ {rel} ({count} instance{s})")
                    lane2_fixed.append((issue.file_path, count, bulk_ft))
                    if DRY_RUN:
                        continue
                    try:
                        issue.file_path.write_text(new_content, encoding="utf-8")
                        written_files.append(issue.file_path)
                    except OSError as exc:
                        print(f"    ⚠ Failed to write {rel}: {exc}", file=sys.stderr)

    all_fixed = lane1_fixed + [(p, c) for p, c, _ in lane2_fixed]

    if not all_fixed:
        print("\n⚠ All fixes failed validation — nothing to commit.", file=sys.stderr)
        _set_output("changed_files", "")
        _set_output("commit_subject", "")
        return 1

    # 6. Build enriched commit message (covers both lanes)
    if fix_type_name and lane1_fixed:
        subject, full_msg = build_commit_message(
            fix_type_name, lane1_fixed, lane1_count
        )
    else:
        # Only Lane 2 contributed (intelligent lane gated all fixes)
        subject, full_msg = _build_bulk_commit_message(lane2_fixed)

    # Append Phase 3 impact summary to commit body when planner was active
    if _PHASE3_AVAILABLE and plan is not None:
        impact_summary = (
            f"\nPhase 3 Impact Analysis:\n"
            f"  Expected net impact : {plan.expected_net_impact:+.3f}\n"
            f"  Avg risk level      : {plan.risk_level:.3f}\n"
            f"  Issues skipped (gate): {plan.skipped_count}"
        )
        full_msg = full_msg.replace(
            "[Niblit Evolution Agent — Phase 3]",
            impact_summary + "\n\n[Niblit Evolution Agent — Phase 3]",
        )

    # Append Lane 2 bulk section when both lanes contributed
    if lane2_fixed and fix_type_name and lane1_fixed:
        full_msg = full_msg.rstrip("\n") + "\n\n" + _build_lane2_section(lane2_fixed)
        subject = subject + f" + {len(lane2_fixed)} bulk cleanup(s)"

    if DRY_RUN:
        print("\n[DRY RUN] Commit subject:")
        print(f"  {subject}")
        print("\n[DRY RUN] Full commit message:")
        print(full_msg)
        _set_output("changed_files", "")
        _set_output("commit_subject", "")
        return 0

    # 7. Write commit message and changed-files list to temp files
    try:
        Path(COMMIT_MSG_FILE).write_text(full_msg, encoding="utf-8")
    except OSError as exc:
        print(f"  ⚠ Could not write commit message file: {exc}", file=sys.stderr)

    changed_files_str = "\n".join(
        str(p.relative_to(WORKSPACE)) for p in written_files
    )
    try:
        Path(CHANGED_FILES_FILE).write_text(changed_files_str, encoding="utf-8")
    except OSError as exc:
        print(f"  ⚠ Could not write changed files list: {exc}", file=sys.stderr)

    # 8. Set GitHub Actions step outputs
    _set_output("changed_files", changed_files_str)
    _set_output("commit_subject", subject)

    total_count = lane1_count + lane2_count
    print(f"\n✅ Evolution cycle complete")
    print(f"   Fixed   : {len(written_files)} file(s)")
    print(f"   Total   : {total_count} instance(s)")
    print(f"   Subject : {subject}")

    # 9. Phase 3: Record outcome + update impact weights
    #    NOTE: The commit SHA isn't available until after the workflow pushes,
    #    so we record a preliminary entry now; the workflow can set GITHUB_SHA
    #    as a follow-up step and re-invoke feedback_learner directly if needed.
    if _PHASE3_AVAILABLE and written_files:
        print("\n📊 Phase 3: scheduling outcome recording for post-push CI check...")
        pending = {
            "fix_types": list(
                {i.fix_type for i in ordered_issues}
                | {ft for _, _, ft in lane2_fixed}
            ),
            "fixed_files": [str(p.relative_to(WORKSPACE)) for p in written_files],
            "total_instances": total_count,
            "commit_sha": GITHUB_SHA,
        }
        pending_file = Path("/tmp/niblit_pending_outcome.json")
        try:
            pending_file.write_text(
                json.dumps(pending, indent=2), encoding="utf-8"
            )
            print(f"   Pending outcome written to {pending_file}")
        except OSError as exc:
            print(f"  ⚠ Could not write pending outcome: {exc}", file=sys.stderr)

    # Phase 16.5 SIL: record causal attribution for niblit_ci now that we know
    # the expected impact of this cycle.  This closes the resonance feedback loop
    # so trust updates use actual outcome deltas rather than correlation alone.
    if _SIL_AVAILABLE and written_files:
        try:
            _sil_objective = "maximize_stability"
            if _PHASE3_AVAILABLE:
                try:
                    from nibblebots import goal_adaptation_engine as _gae  # noqa: PLC0415
                    _sil_objective = _gae.evaluate() or "maximize_stability"
                except Exception:  # noqa: BLE001
                    pass
            # post score: shift from neutral using normalised expected_net_impact
            _net = 0.0
            if _PHASE3_AVAILABLE and plan is not None:
                _net = float(plan.expected_net_impact)
            _post_score = min(1.0, max(0.0, 0.5 + _net))
            _sil.record_resonance_attribution(
                system_id="niblit_ci",
                baseline_outcome=0.5,
                post_resonance_outcome=_post_score,
                adjustments_applied={"cycle_fixes": len(written_files)},
            )
            print(
                f"  🔗 Phase 16.5 SIL: attribution recorded for niblit_ci "
                f"(delta={_post_score - 0.5:+.4f})"
            )
        except Exception:  # noqa: BLE001
            pass

    return 0


if __name__ == "__main__":
    sys.exit(main())
