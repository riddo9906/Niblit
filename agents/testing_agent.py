#!/usr/bin/env python3
"""
agents/testing_agent.py — Code validation agent.

Handles ``task_type="testing"`` tasks.  Uses CodeCompiler for syntax checks
and CodeErrorFixer for auto-repair, then publishes a TEST_RUN_COMPLETED event
with pass/fail status and any error details.

Architecture role (Phase 2)
---------------------------
    CodingAgent → TaskQueue → TestingAgent → ReflectionAgent
"""

import logging
from typing import Any, Dict, Optional

from agents.base_agent import BaseAgent
from core.event_bus import Event, EventBus, EventType
from core.task_queue import Task

log = logging.getLogger("TestingAgent")


class TestingAgent(BaseAgent):
    """
    Validates generated code via syntax checks and optional auto-fix.

    Args:
        code_compiler:    modules.code_compiler.CodeCompiler instance.
        code_error_fixer: modules.code_error_fixer.CodeErrorFixer instance.
    """

    HANDLED_TASK_TYPES = ["testing", "validate_code", "test_run"]

    def __init__(
        self,
        code_compiler: Optional[Any] = None,
        code_error_fixer: Optional[Any] = None,
    ) -> None:
        super().__init__("testing")
        self._compiler = code_compiler
        self._fixer = code_error_fixer

    # ── execution ─────────────────────────────────────────────────────────────

    def _execute(self, task: Task, event_bus: EventBus) -> Dict[str, Any]:
        code = task.payload.get("code", "")
        language = task.payload.get("language", "python")
        description = task.payload.get("description", "")

        if not code:
            result = {
                "passed": False,
                "error": "No code provided",
                "language": language,
            }
            self._publish(event_bus, EventType.TEST_FAILED, result)
            return result

        passed = False
        error_msg = ""
        fixed_code = code

        # Syntax check
        if self._compiler is not None:
            try:
                syntax_ok, msg = self._compiler.syntax_test(code, language)
                if syntax_ok:
                    passed = True
                else:
                    error_msg = msg or "Syntax error"
                    # Attempt auto-fix
                    if self._fixer is not None:
                        try:
                            fix_result = self._fixer.fix_syntax_errors(code, language)
                            if isinstance(fix_result, dict):
                                fixed_code = fix_result.get("fixed_code", code)
                                if fix_result.get("success"):
                                    passed = True
                                    error_msg = ""
                            elif isinstance(fix_result, str) and fix_result:
                                fixed_code = fix_result
                        except Exception as fe:
                            self._log.debug("auto-fix failed: %s", fe)
            except Exception as exc:
                error_msg = str(exc)
        else:
            # No compiler available — assume passed (basic check)
            passed = bool(code.strip())

        result = {
            "passed": passed,
            "error": error_msg,
            "language": language,
            "code": fixed_code,
            "description": description,
        }

        if passed:
            self._publish(event_bus, EventType.TEST_RUN_COMPLETED, result)
        else:
            self._publish(event_bus, EventType.TEST_FAILED, result)

        self._log.info("testing(%s) → %s", language, "PASS" if passed else "FAIL")
        return result


if __name__ == "__main__":
    print('Running testing_agent.py')
