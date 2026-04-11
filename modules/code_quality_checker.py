#!/usr/bin/env python3
"""
modules/code_quality_checker.py — CodeQL-style static analysis for Niblit-generated code.

Performs lightweight static analysis on Python, Bash, and JavaScript code that
Niblit generates or compiles, flagging security issues, bad practices, and style
problems without requiring any external dependencies (stdlib + optional ast).

Checks performed
----------------
Python  : syntax validity, hardcoded secrets, SQL injection, bare except, eval/exec,
          os.system, excessive prints, missing docstrings, long lines
Bash    : missing shebang, missing set -e, unquoted variables, destructive rm, chmod 777
JS      : missing 'use strict', eval usage, var declarations, stray console.log

Scoring
-------
Start at 100; deduct 20 per error, 5 per warning, 1 per info (floor 0).
``passed`` is True when there are zero "error"-severity issues.

Singleton via get_code_quality_checker().
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from typing import List, Optional

log = logging.getLogger("Niblit.CodeQualityChecker")

try:
    import ast as _ast
    _AST_AVAILABLE = True
except ImportError:  # pragma: no cover
    _AST_AVAILABLE = False

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CodeIssue:
    """A single static-analysis finding."""
    severity: str   # "error" | "warning" | "info"
    rule: str
    message: str
    line: int = 0   # 0 = unknown


@dataclass
class CodeQualityResult:
    """Aggregated result returned by CodeQualityChecker.check()."""
    passed: bool
    issues: List[CodeIssue]
    score: int          # 0-100
    summary: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SECRET_RE = re.compile(
    r'(?i)(password|passwd|secret|api[_-]?key|token|auth[_-]?key)\s*=\s*["\'](?!.*\{)[^"\']{4,}["\']'
)
_SQL_FMT_RE = re.compile(
    r'(?i)(execute|cursor\.execute|db\.execute)\s*\(\s*["\'].*%[sd].*["\'].*%'
    r'|(execute|cursor\.execute|db\.execute)\s*\(\s*f["\'].*SELECT|INSERT|UPDATE|DELETE'
)
_EVAL_RE = re.compile(r'\beval\s*\(')
_EXEC_RE = re.compile(r'\bexec\s*\(')
_OSSYSTEM_RE = re.compile(r'\bos\.system\s*\(')
_PRINT_RE = re.compile(r'^\s*print\s*\(', re.MULTILINE)

_SHEBANG_RE = re.compile(r'^#!')
_SETE_RE = re.compile(r'set\s+-[a-z]*e[a-z]*')
_UNQUOTED_VAR_RE = re.compile(r'(?<!["\'\$])\$([A-Za-z_][A-Za-z0-9_]*)(?!["\'\}])')
_DESTRUCTIVE_RM_RE = re.compile(r'\brm\s+(-\w*\s+)*-\w*r\w*\s+(-\w+\s+)*/\s*\*?$', re.MULTILINE)
_CHMOD777_RE = re.compile(r'\bchmod\s+777\b')

_USE_STRICT_RE = re.compile(r'["\']use strict["\']')
_JS_EVAL_RE = re.compile(r'\beval\s*\(')
_VAR_DECL_RE = re.compile(r'\bvar\s+[a-zA-Z_$]')
_CONSOLE_LOG_RE = re.compile(r'\bconsole\.log\s*\(')


# ---------------------------------------------------------------------------
# Main checker
# ---------------------------------------------------------------------------

class CodeQualityChecker:
    """Performs CodeQL-style static analysis on Python, Bash, and JS code."""

    def check(self, language: str, code: str) -> CodeQualityResult:
        """Analyse *code* written in *language* and return a :class:`CodeQualityResult`.

        Args:
            language: One of ``"python"``, ``"bash"``, ``"javascript"`` (case-insensitive).
            code:     Source code string to analyse.
        """
        lang = language.lower().strip()
        if lang in ("python", "py"):
            issues = self._check_python(code)
        elif lang in ("bash", "sh", "shell"):
            issues = self._check_bash(code)
        elif lang in ("javascript", "js"):
            issues = self._check_javascript(code)
        else:
            issues = [CodeIssue("info", "unknown-language",
                                f"No checks implemented for language '{language}'")]

        score = self._compute_score(issues)
        passed = not any(i.severity == "error" for i in issues)
        error_c = sum(1 for i in issues if i.severity == "error")
        warn_c  = sum(1 for i in issues if i.severity == "warning")
        info_c  = sum(1 for i in issues if i.severity == "info")
        summary = (
            f"{lang} analysis: {len(issues)} issue(s) — "
            f"{error_c} error(s), {warn_c} warning(s), {info_c} info — score {score}/100"
        )
        log.debug(summary)
        return CodeQualityResult(passed=passed, issues=issues, score=score, summary=summary)

    # ------------------------------------------------------------------
    # Python
    # ------------------------------------------------------------------

    def _check_python(self, code: str) -> List[CodeIssue]:
        issues: List[CodeIssue] = []
        lines = code.splitlines()

        # Syntax check
        if _AST_AVAILABLE:
            try:
                tree = _ast.parse(code)
                issues.extend(self._python_ast_checks(tree, lines))
            except SyntaxError as exc:
                issues.append(CodeIssue("error", "syntax-error",
                                        f"Syntax error: {exc.msg}", exc.lineno or 0))
                # Skip further AST checks if code won't parse
                issues.extend(self._python_regex_checks(code, lines))
                return issues
        else:
            log.warning("ast module unavailable; skipping Python AST checks")

        issues.extend(self._python_regex_checks(code, lines))
        return issues

    def _python_ast_checks(self, tree: "_ast.AST", lines: List[str]) -> List[CodeIssue]:
        issues: List[CodeIssue] = []
        has_def_or_class = False

        for node in _ast.walk(tree):
            # Bare except
            if isinstance(node, _ast.ExceptHandler) and node.type is None:
                issues.append(CodeIssue("warning", "bare-except",
                                        "Bare 'except:' catches all exceptions including SystemExit/KeyboardInterrupt.",
                                        getattr(node, "lineno", 0)))

            # eval / exec usage
            if isinstance(node, _ast.Call):
                func = node.func
                name = ""
                if isinstance(func, _ast.Name):
                    name = func.id
                elif isinstance(func, _ast.Attribute):
                    name = func.attr
                if name == "eval":
                    issues.append(CodeIssue("warning", "eval-usage",
                                            "Use of eval() is a security risk.",
                                            getattr(node, "lineno", 0)))
                if name == "exec":
                    issues.append(CodeIssue("warning", "exec-usage",
                                            "Use of exec() is a security risk.",
                                            getattr(node, "lineno", 0)))

            # os.system
            if isinstance(node, _ast.Call):
                func = node.func
                if (isinstance(func, _ast.Attribute) and func.attr == "system"
                        and isinstance(func.value, _ast.Name) and func.value.id == "os"):
                    issues.append(CodeIssue("warning", "os-system",
                                            "Prefer subprocess over os.system() for shell commands.",
                                            getattr(node, "lineno", 0)))

            # Missing docstrings
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                if not node.name.startswith("_"):
                    has_def_or_class = True
                    if not (_ast.get_docstring(node)):
                        issues.append(CodeIssue("info", "missing-docstring",
                                                f"Public function '{node.name}' has no docstring.",
                                                getattr(node, "lineno", 0)))
            if isinstance(node, _ast.ClassDef):
                if not node.name.startswith("_"):
                    has_def_or_class = True
                    if not (_ast.get_docstring(node)):
                        issues.append(CodeIssue("info", "missing-docstring",
                                                f"Public class '{node.name}' has no docstring.",
                                                getattr(node, "lineno", 0)))

        # Excessive prints in non-script code
        print_matches = _PRINT_RE.findall("\n".join(
            l for l in (getattr(tree, "body", []) and lines) or lines
        ))
        if has_def_or_class and len(print_matches) > 5:
            issues.append(CodeIssue("info", "excessive-prints",
                                    f"Found {len(print_matches)} print() calls in non-script code; "
                                    "consider using logging instead."))
        return issues

    def _python_regex_checks(self, code: str, lines: List[str]) -> List[CodeIssue]:
        issues: List[CodeIssue] = []

        # Hardcoded secrets
        for m in _SECRET_RE.finditer(code):
            lineno = code[:m.start()].count("\n") + 1
            issues.append(CodeIssue("error", "hardcoded-secret",
                                    f"Possible hardcoded secret near '{m.group(0)[:40]}'.",
                                    lineno))

        # SQL injection
        for m in _SQL_FMT_RE.finditer(code):
            lineno = code[:m.start()].count("\n") + 1
            issues.append(CodeIssue("error", "sql-injection",
                                    "Possible SQL injection: avoid formatting user data into queries.",
                                    lineno))

        # Long lines
        for idx, line in enumerate(lines, start=1):
            if len(line) > 120:
                issues.append(CodeIssue("info", "long-line",
                                        f"Line {idx} is {len(line)} characters (limit 120).", idx))
        return issues

    # ------------------------------------------------------------------
    # Bash
    # ------------------------------------------------------------------

    def _check_bash(self, code: str) -> List[CodeIssue]:
        issues: List[CodeIssue] = []
        lines = code.splitlines()

        if not lines or not _SHEBANG_RE.match(lines[0]):
            issues.append(CodeIssue("error", "missing-shebang",
                                    "Bash script is missing a shebang line (e.g. #!/usr/bin/env bash)."))

        if not _SETE_RE.search(code):
            issues.append(CodeIssue("warning", "missing-set-e",
                                    "Consider adding 'set -euo pipefail' at the top of the script."))

        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for m in _UNQUOTED_VAR_RE.finditer(line):
                issues.append(CodeIssue("warning", "unquoted-variable",
                                        f"Variable ${m.group(1)} may need quoting: \"${m.group(1)}\".",
                                        idx))
            if _CHMOD777_RE.search(line):
                issues.append(CodeIssue("warning", "chmod-777",
                                        "chmod 777 grants world-writable permissions; use a stricter mode.",
                                        idx))

        for m in _DESTRUCTIVE_RM_RE.finditer(code):
            lineno = code[:m.start()].count("\n") + 1
            issues.append(CodeIssue("error", "destructive-rm",
                                    "Potentially destructive 'rm -rf /' or 'rm -rf /*' detected.",
                                    lineno))
        return issues

    # ------------------------------------------------------------------
    # JavaScript
    # ------------------------------------------------------------------

    def _check_javascript(self, code: str) -> List[CodeIssue]:
        issues: List[CodeIssue] = []
        lines = code.splitlines()
        is_test = any(kw in code for kw in ("describe(", "it(", "test(", "expect(", "jest", "mocha"))

        if not _USE_STRICT_RE.search(code):
            issues.append(CodeIssue("warning", "missing-use-strict",
                                    "Add 'use strict'; at the top of the file or module."))

        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue

            if _JS_EVAL_RE.search(line):
                issues.append(CodeIssue("error", "eval-usage",
                                        "eval() is a security risk; avoid dynamic code execution.", idx))

            if _VAR_DECL_RE.search(line):
                issues.append(CodeIssue("info", "var-declaration",
                                        "Prefer 'const' or 'let' over 'var'.", idx))

            if not is_test and _CONSOLE_LOG_RE.search(line):
                issues.append(CodeIssue("info", "console-log",
                                        "Remove or replace console.log() before production.", idx))
        return issues

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_score(issues: List[CodeIssue]) -> int:
        score = 100
        for issue in issues:
            if issue.severity == "error":
                score -= 20
            elif issue.severity == "warning":
                score -= 5
            elif issue.severity == "info":
                score -= 1
        return max(0, score)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_checker_instance: Optional[CodeQualityChecker] = None
_checker_lock = threading.Lock()


def get_code_quality_checker() -> CodeQualityChecker:
    """Return the shared :class:`CodeQualityChecker` instance (thread-safe)."""
    global _checker_instance
    if _checker_instance is None:
        with _checker_lock:
            if _checker_instance is None:
                _checker_instance = CodeQualityChecker()
                log.info("CodeQualityChecker initialised.")
    return _checker_instance


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    checker = get_code_quality_checker()

    _PY_BAD = """\
import os
password = "hunter2"
os.system("ls")
try:
    pass
except:
    pass

def helper():
    eval("1+1")
"""

    _BASH_BAD = """\
set -e
echo $HOME
chmod 777 /etc/secret
"""

    _JS_BAD = """\
var x = 1;
eval('alert(1)');
console.log('debug');
"""

    for lang, snippet in [("python", _PY_BAD), ("bash", _BASH_BAD), ("javascript", _JS_BAD)]:
        result = checker.check(lang, snippet)
        print(f"\n{'='*60}")
        print(result.summary)
        for issue in result.issues:
            print(f"  [{issue.severity.upper():7}] {issue.rule} (line {issue.line}): {issue.message}")
        print(f"  passed={result.passed}")
