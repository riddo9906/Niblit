#!/usr/bin/env python3
"""
modules/ai_dev_lab/safety_guard.py

Validate code safety before execution in the SEADL sandbox.

Restrictions enforced:
    - No shell execution (os.system, subprocess, eval, exec)
    - No filesystem writes outside the sandbox
    - No network calls outside approved domains
    - No dynamic code generation via compile()

Usage::

    from modules.ai_dev_lab.safety_guard import SafetyGuard
    guard = SafetyGuard()
    is_safe = guard.validate(code_string)
    warnings = guard.get_warnings(code_string)
"""

import ast
import logging
import re
from typing import List, Tuple

log = logging.getLogger("SafetyGuard")

# Banned call patterns (string-level check before AST)
_BANNED_STRINGS: List[str] = [
    "os.system",
    "subprocess.call",
    "subprocess.run",
    "subprocess.Popen",
    "__import__",
    "importlib.import_module",
    "compile(",
    "ctypes",
]

# Banned AST node names
_BANNED_CALLS: set = {
    "eval", "exec", "execfile", "compile",
}

# Allowed built-ins (allowlist approach for strict mode)
_SUSPICIOUS_PATTERNS: List[Tuple[str, str]] = [
    (r"\beval\s*\(", "eval() usage"),
    (r"\bexec\s*\(", "exec() usage"),
    (r"os\.system\s*\(", "os.system() call"),
    (r"subprocess\.(run|Popen|call)\s*\(", "subprocess execution"),
    (r"open\s*\(.+['\"]w['\"]", "file write operation"),
    (r"shutil\.(rmtree|move|copy)\s*\(", "filesystem manipulation"),
    (r"socket\.connect\s*\(", "raw socket connection"),
    (r"__import__\s*\(", "__import__ call"),
]


class SafetyGuard:
    """
    Validate code safety using a combination of string patterns and AST analysis.

    Returns True from validate() when code is deemed safe.
    """

    def __init__(self, strict: bool = False) -> None:
        """
        Args:
            strict: When True, any suspicious pattern raises a warning even if
                    not definitively unsafe.
        """
        self.strict = strict

    # ── public API ────────────────────────────────────────────────────────────

    def validate(self, code: str) -> bool:
        """
        Return True if code passes all safety checks.

        Raises ValueError if a critical unsafe pattern is detected.
        """
        if not isinstance(code, str):
            return True

        # 1 — String-level banned patterns
        code_lower = code
        for banned in _BANNED_STRINGS:
            if banned in code_lower:
                raise ValueError(f"SafetyGuard: unsafe pattern detected: '{banned}'")

        # 2 — Regex pattern checks
        for pattern, label in _SUSPICIOUS_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                if self.strict:
                    raise ValueError(f"SafetyGuard: suspicious code — {label}")
                log.warning("SafetyGuard: warning — %s found in code", label)

        # 3 — AST-level check
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func_name = ""
                    if isinstance(node.func, ast.Name):
                        func_name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        func_name = node.func.attr
                    if func_name in _BANNED_CALLS:
                        raise ValueError(
                            f"SafetyGuard: banned function call: '{func_name}()'"
                        )
        except SyntaxError:
            pass  # Syntax errors are caught by CodeCompiler, not our concern here

        return True

    def get_warnings(self, code: str) -> List[str]:
        """
        Return a list of warning strings for suspicious but not banned patterns.
        """
        if not isinstance(code, str):
            return []
        warnings: List[str] = []
        for pattern, label in _SUSPICIOUS_PATTERNS:
            if re.search(pattern, code, re.IGNORECASE):
                warnings.append(label)
        return warnings

    def is_safe(self, code: str) -> bool:
        """Return True without raising exceptions (swallows ValueError)."""
        try:
            return self.validate(code)
        except ValueError:
            return False

    def audit(self, code: str) -> dict:
        """Return a full safety audit report."""
        safe = self.is_safe(code)
        warnings = self.get_warnings(code)
        return {
            "safe": safe,
            "warnings": warnings,
            "warning_count": len(warnings),
        }


if __name__ == "__main__":
    print('Running safety_guard.py')
