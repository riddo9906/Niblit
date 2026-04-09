"""SafetyPolicies — code safety enforcement for civilisation governance.

Usage example::

    policies = SafetyPolicies()
    is_safe = policies.check("def add(a, b): return a + b")
    violations = policies.get_violations("import os; os.system('rm -rf /')")
"""

from __future__ import annotations

import logging
import re
from typing import Dict, List

log = logging.getLogger("SafetyPolicies")

_BUILT_IN_POLICIES: Dict[str, str] = {
    "no_system_calls": r"os\.system|subprocess\.",
    "no_file_write": r"open\s*\(.*['\"]w['\"]",
    "no_dynamic_import": r"__import__|importlib\.import_module",
    "no_exec_eval": r"\bexec\s*\(|\beval\s*\(",
    "no_network": r"socket\.|urllib\.|requests\.",
}


class SafetyPolicies:
    """Enforces configurable safety policies on code strings."""

    def __init__(self) -> None:
        self._policies: Dict[str, str] = dict(_BUILT_IN_POLICIES)

    # ── public API ──

    def check(self, code: str) -> bool:
        """Return True if *code* passes all active policies."""
        return len(self.get_violations(code)) == 0

    def get_violations(self, code: str) -> List[str]:
        """Return list of policy names violated by *code*."""
        violations: List[str] = []
        for name, pattern in self._policies.items():
            try:
                if re.search(pattern, code):
                    violations.append(name)
            except re.error:
                log.warning("SafetyPolicies: invalid pattern for %s", name)
        return violations

    def add_policy(self, name: str, pattern: str) -> None:
        """Register a new policy with regex *pattern*."""
        self._policies[name] = pattern
        log.info("SafetyPolicies: added policy %s", name)

    def list_policies(self) -> List[str]:
        """Return names of all active policies."""
        return list(self._policies.keys())


if __name__ == "__main__":
    print('Running safety_policies.py')
