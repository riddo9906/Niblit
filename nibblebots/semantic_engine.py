#!/usr/bin/env python3
"""
nibblebots/semantic_engine.py — Phase 3 Semantic Classification Engine

Converts raw fix-type + code context into *structured meaning*: what kind of
problem exists, which subsystem it belongs to, how severe it is, and whether
this occurrence looks intentional.

The semantic layer answers:
  "What is this issue really about?"

rather than just:
  "Which pattern matched?"

SemanticIssue fields
--------------------
fix_type        : raw fix-type string from the fix catalogue
semantic_type   : high-level semantic category (error_handling_risk, etc.)
file_path       : path of the affected file
count           : number of fixable instances
subsystem       : Niblit subsystem this file belongs to (decision, trading, …)
severity        : 0.0–1.0  (how harmful is the pattern in this context?)
confidence      : 0.0–1.0  (how confident are we in the classification?)
intentional     : True if the pattern appears to be intentional/documented
context_hint    : short human-readable phrase explaining the classification
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, NamedTuple, Optional


# ---------------------------------------------------------------------------
# Semantic categories
# ---------------------------------------------------------------------------

SEMANTIC_TYPES = (
    "error_handling_risk",   # bare/silent exceptions that hide failures
    "code_style_debt",       # formatting / PEP 8 issues
    "performance_debt",      # not yet detected by static rules; placeholder
    "architectural_smell",   # structural problems (dead code, always-true, …)
    # Phase 6 log-derived semantic types
    "performance_bottleneck",  # timeout / slowness patterns in runtime logs
    "dependency_break",        # import errors / missing modules in logs
    "logic_instability",       # assertion failures / unexpected state in logs
)

# ---------------------------------------------------------------------------
# Subsystem map  — repo-relative path prefixes → subsystem name
# ---------------------------------------------------------------------------

_SUBSYSTEM_MAP: List[tuple] = [
    # Order matters: first match wins
    ("modules/decision_engine",       "decision"),
    ("modules/meta_engine",           "meta"),
    ("modules/policy_optimizer",      "policy"),
    ("modules/evaluation_engine",     "evaluation"),
    ("modules/trade_kb_learner",      "trading"),
    ("modules/autonomous_learning",   "learning"),
    ("modules/knowledge",             "knowledge"),
    ("modules/quality_feedback",      "feedback"),
    ("niblit_memory/",                "knowledge"),
    ("niblit_agents/",                "agents"),
    ("nibblebots/",                   "evolution"),
    ("modules/",                      "core"),
]

# ---------------------------------------------------------------------------
# Context-severity multipliers
#
# If the file belongs to a subsystem in this table its base severity is
# scaled by the multiplier — fixes in the decision engine or trading logic
# are more impactful (and riskier) than fixes in a test helper.
# ---------------------------------------------------------------------------

_SUBSYSTEM_SEVERITY: dict = {
    "decision":   1.4,
    "meta":       1.3,
    "policy":     1.3,
    "trading":    1.5,
    "evaluation": 1.2,
    "learning":   1.1,
    "feedback":   1.1,
    "knowledge":  1.0,
    "agents":     0.9,
    "evolution":  0.8,
    "core":       1.0,
    "other":      0.8,
}

# ---------------------------------------------------------------------------
# Base severity per fix type
# ---------------------------------------------------------------------------

_BASE_SEVERITY: dict = {
    "bare_except":         0.75,   # high risk — hides all exceptions
    "bare_except_pass":    0.55,   # moderate — silences known type
    "trailing_whitespace": 0.15,   # cosmetic
    "double_blank_lines":  0.10,   # cosmetic
    "eof_newline":         0.08,   # cosmetic
}

# ---------------------------------------------------------------------------
# Semantic type per fix type
# ---------------------------------------------------------------------------

_FIX_SEMANTIC_TYPE: dict = {
    "bare_except":         "error_handling_risk",
    "bare_except_pass":    "error_handling_risk",
    "trailing_whitespace": "code_style_debt",
    "double_blank_lines":  "code_style_debt",
    "eof_newline":         "code_style_debt",
}

# Patterns that suggest intentional suppression
_INTENTIONAL_PATTERNS = re.compile(
    r"(# ?noqa|# ?pylint.*disable|# ?type: ?ignore|intentional|deliberate)",
    re.IGNORECASE,
)

# Patterns that suggest a test helper context (reduces severity)
_TEST_FILE_RE = re.compile(r"(^|/)test_|_test\.py$|/tests/")


# ---------------------------------------------------------------------------
# SemanticIssue data structure
# ---------------------------------------------------------------------------

class SemanticIssue(NamedTuple):
    fix_type: str
    semantic_type: str
    file_path: Path
    count: int
    subsystem: str
    severity: float
    confidence: float
    intentional: bool
    context_hint: str


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify(
    fix_type: str,
    file_path: Path,
    count: int,
    workspace: Optional[Path] = None,
    content_snippet: str = "",
) -> SemanticIssue:
    """Classify a raw issue into a SemanticIssue.

    Parameters
    ----------
    fix_type        : raw fix type from the Phase 2 catalogue
    file_path       : absolute path to the file
    count           : number of instances in the file
    workspace       : repo root (used to compute a relative path for matching)
    content_snippet : a few hundred chars of file content for contextual signals
    """
    workspace = workspace or Path(".")
    try:
        rel = str(file_path.relative_to(workspace))
    except ValueError:
        rel = str(file_path)

    semantic_type = _FIX_SEMANTIC_TYPE.get(fix_type, "architectural_smell")
    subsystem = _detect_subsystem(rel)
    base_sev = _BASE_SEVERITY.get(fix_type, 0.5)
    severity = min(1.0, base_sev * _SUBSYSTEM_SEVERITY.get(subsystem, 1.0))

    # Reduce severity for test files
    if _TEST_FILE_RE.search(rel):
        severity *= 0.5

    intentional = bool(
        content_snippet and _INTENTIONAL_PATTERNS.search(content_snippet)
    )
    if intentional:
        severity *= 0.6   # soften — may be OK

    # Confidence: higher for error-handling types than style types
    if semantic_type == "error_handling_risk":
        confidence = 0.85
    elif semantic_type == "code_style_debt":
        confidence = 0.95
    else:
        confidence = 0.70

    # Penalise confidence slightly when we can't examine content
    if not content_snippet:
        confidence -= 0.05

    context_hint = _build_context_hint(fix_type, subsystem, severity, count)

    issue = SemanticIssue(
        fix_type=fix_type,
        semantic_type=semantic_type,
        file_path=file_path,
        count=count,
        subsystem=subsystem,
        severity=round(severity, 3),
        confidence=round(max(0.0, confidence), 3),
        intentional=intentional,
        context_hint=context_hint,
    )

    # Phase 8: update context_guard window so it tracks live context
    try:
        from nibblebots import context_guard as _cg  # noqa: PLC0415
        _cg.observe(fix_type, subsystem, semantic_type)
    except Exception:  # noqa: BLE001
        pass

    return issue


def classify_batch(
    issues: list,   # List[Issue]  (duck-typed to avoid circular import)
    workspace: Optional[Path] = None,
    read_content: bool = True,
) -> List[SemanticIssue]:
    """Classify a list of Phase 2 Issue namedtuples into SemanticIssues.

    Parameters
    ----------
    issues       : list of objects with .fix_type, .file_path, .count
    workspace    : repo root
    read_content : when True, reads the first 2 KB of each file for context
    """
    results: List[SemanticIssue] = []
    for issue in issues:
        snippet = ""
        if read_content:
            try:
                snippet = issue.file_path.read_text(
                    encoding="utf-8", errors="replace"
                )[:2048]
            except OSError:
                pass
        results.append(
            classify(
                fix_type=issue.fix_type,
                file_path=issue.file_path,
                count=issue.count,
                workspace=workspace,
                content_snippet=snippet,
            )
        )
    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _detect_subsystem(rel_path: str) -> str:
    for prefix, name in _SUBSYSTEM_MAP:
        if rel_path.startswith(prefix) or f"/{prefix.strip('/')}" in rel_path:
            return name
    return "other"


def _build_context_hint(
    fix_type: str,
    subsystem: str,
    severity: float,
    count: int,
) -> str:
    sev_label = "critical" if severity >= 0.8 else "moderate" if severity >= 0.4 else "low"
    type_map = {
        "bare_except":         f"untyped exception in {subsystem} ({sev_label} severity) — "
                               f"hides all failures from evaluation engine",
        "bare_except_pass":    f"silent exception swallow in {subsystem} ({sev_label} severity) — "
                               f"breaks feedback observability",
        "trailing_whitespace": f"trailing whitespace in {subsystem} — noisy diffs",
        "double_blank_lines":  f"excess blank lines in {subsystem} — PEP 8 E303",
        "eof_newline":         f"missing EOF newline in {subsystem}",
    }
    hint = type_map.get(fix_type, f"{fix_type} in {subsystem}")
    return f"{hint} [{count} instance{'s' if count != 1 else ''}]"


# ---------------------------------------------------------------------------
# Phase 6: Log-derived semantic classification
# ---------------------------------------------------------------------------

# Patterns that indicate each log-derived semantic type
_LOG_PERF_RE = re.compile(
    r"(timeout|timed.out|slow|latency|performance|memory.leak|OOM|out.of.memory)",
    re.IGNORECASE,
)
_LOG_DEP_RE = re.compile(
    r"(ImportError|ModuleNotFoundError|No module named|cannot import|"
    r"dependency.error|missing.package)",
    re.IGNORECASE,
)
_LOG_LOGIC_RE = re.compile(
    r"(AssertionError|assertion.failed|unexpected.state|invariant.violated|"
    r"logic.error|inconsistency|unexpected.value)",
    re.IGNORECASE,
)

# Minimum line frequency to surface a log-derived semantic type
_LOG_MIN_FREQ: int = 3


def classify_log_lines(
    lines: List[str],
    source_label: str = "log",
) -> List[SemanticIssue]:
    """Classify a list of log lines into SemanticIssues.

    Applies regex + frequency analysis to surface:
      * ``performance_bottleneck`` — timeout / slowness patterns
      * ``dependency_break``       — import / missing-module errors
      * ``logic_instability``      — assertion failures / unexpected state

    Only patterns that appear at least _LOG_MIN_FREQ times are surfaced to
    avoid noise from one-off events.

    Parameters
    ----------
    lines        : list of raw log line strings
    source_label : human-readable label for the log source (used in hints)

    Returns a list of SemanticIssue namedtuples (one per detected pattern type).
    """
    counts: dict = {
        "performance_bottleneck": 0,
        "dependency_break":       0,
        "logic_instability":      0,
    }
    for line in lines:
        if _LOG_PERF_RE.search(line):
            counts["performance_bottleneck"] += 1
        if _LOG_DEP_RE.search(line):
            counts["dependency_break"] += 1
        if _LOG_LOGIC_RE.search(line):
            counts["logic_instability"] += 1

    results: List[SemanticIssue] = []
    _severity_map = {
        "performance_bottleneck": 0.55,
        "dependency_break":       0.75,
        "logic_instability":      0.70,
    }
    for sem_type, count in counts.items():
        if count < _LOG_MIN_FREQ:
            continue
        sev = min(1.0, _severity_map.get(sem_type, 0.50) + 0.02 * count)
        hint = (
            f"{sem_type.replace('_', ' ')} detected in {source_label} "
            f"[{count} occurrence{'s' if count != 1 else ''}]"
        )
        results.append(SemanticIssue(
            fix_type=f"log:{sem_type}",
            semantic_type=sem_type,
            file_path=Path(source_label),
            count=count,
            subsystem="core",
            severity=round(sev, 3),
            confidence=0.75,
            intentional=False,
            context_hint=hint,
        ))
    return results


def classify_log_file(log_path: Path) -> List[SemanticIssue]:
    """Classify all lines in a log file into SemanticIssues.

    Convenience wrapper around ``classify_log_lines``.
    """
    if not log_path.exists():
        return []
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return classify_log_lines(lines, source_label=log_path.name)
