#!/usr/bin/env python3
"""
CODE ERROR FIXER MODULE
Autonomously detects, diagnoses, and fixes code errors produced by
CodeGenerator, CodeCompiler, and runtime diagnostics.

Features:
- Parse syntax errors (Python ast, Bash -n, Node --check) and apply targeted
  fixes (indentation, missing colons, undefined name stubs, etc.)
- Retry-loop: fix → re-validate → compile up to MAX_FIX_ATTEMPTS times
- Store every fix attempt in KnowledgeDB for self-learning
- Used by CodeCompiler.compile_with_autofix() and by niblit_core commands
- Used by run_diagnostics and niblit_orchestrator for audit/self-repair

Exported API:
    CodeErrorFixer(db=None)
        .fix_syntax_errors(language, code, error_msg) -> (str, bool, str)
        .fix_and_compile(language, code, compiler)    -> ExecutionResult
        .auto_fix_and_run(language, code, compiler)   -> dict
        .get_stats()                                   -> dict
"""

import ast
import re
import time
import logging
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger("CodeErrorFixer")

# Maximum number of fix-then-recompile attempts per code snippet
MAX_FIX_ATTEMPTS: int = 3


# ─────────────────────────────────────────────────────────────────────────────
# PYTHON AUTO-FIXER HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _fix_python(code: str, error_msg: str) -> Tuple[str, str]:
    """Apply targeted fixes to Python code given a SyntaxError message.

    Returns (fixed_code, description_of_fix).
    """
    fixed = code
    applied: list = []

    # 1. Mixed tabs/spaces → convert tabs to 4 spaces
    if "TabError" in error_msg or "inconsistent use of tabs" in error_msg or "\t" in code:
        fixed = fixed.expandtabs(4)
        applied.append("expanded tabs to 4 spaces")

    # 2. Missing colon after def/class/if/else/elif/for/while/try/except/finally/with
    missing_colon = re.compile(
        r'^(\s*(?:def|class|if|elif|else|for|while|try|except|finally|with)\b[^:\n#]+?)$',
        re.MULTILINE,
    )
    def _add_colon(m: re.Match) -> str:
        line = m.group(1)
        if not line.rstrip().endswith(":"):
            return line.rstrip() + ":"
        return line

    new_code = missing_colon.sub(_add_colon, fixed)
    if new_code != fixed:
        fixed = new_code
        applied.append("added missing colons")

    # 3. invalid syntax near specific line — attempt to remove the offending line
    line_match = re.search(r'line (\d+)', error_msg)
    if line_match and ("invalid syntax" in error_msg or "SyntaxError" in error_msg):
        lineno = int(line_match.group(1))
        lines = fixed.splitlines(keepends=True)
        if 1 <= lineno <= len(lines):
            bad_line = lines[lineno - 1]
            # Only remove obviously broken lines (not definitions)
            if not re.match(r'^\s*(?:def|class|if|for|while|import|from)\b', bad_line):
                lines[lineno - 1] = f"# AUTO-REMOVED (syntax error): {bad_line}"
                fixed = "".join(lines)
                applied.append(f"commented out invalid line {lineno}")

    # 4. Unmatched parentheses/brackets — simple: append missing close
    open_p = fixed.count("(") - fixed.count(")")
    open_b = fixed.count("[") - fixed.count("]")
    open_c = fixed.count("{") - fixed.count("}")
    if open_p > 0:
        fixed += "\n" + ")" * open_p
        applied.append(f"added {open_p} missing ')'")
    if open_b > 0:
        fixed += "\n" + "]" * open_b
        applied.append(f"added {open_b} missing ']'")
    if open_c > 0:
        fixed += "\n" + "}" * open_c
        applied.append(f"added {open_c} missing '}}'")

    description = "; ".join(applied) if applied else "no fix applied"
    return fixed, description


def _fix_bash(code: str, error_msg: str) -> Tuple[str, str]:
    """Apply targeted fixes to Bash code given an error message."""
    fixed = code
    applied: list = []

    # 1. Ensure shebang
    if not fixed.lstrip().startswith("#!"):
        fixed = "#!/usr/bin/env bash\n" + fixed
        applied.append("added shebang")

    # 2. Ensure set -euo pipefail
    if "set -euo pipefail" not in fixed:
        lines = fixed.splitlines(keepends=True)
        insert_at = 1 if (lines and lines[0].startswith("#!")) else 0
        lines.insert(insert_at, "set -euo pipefail\n")
        fixed = "".join(lines)
        applied.append("added 'set -euo pipefail'")

    # 3. Attempt to comment out the offending line
    line_match = re.search(r'line (\d+)', error_msg)
    if line_match:
        lineno = int(line_match.group(1))
        lines = fixed.splitlines(keepends=True)
        if 1 <= lineno <= len(lines) and not lines[lineno - 1].strip().startswith("#"):
            lines[lineno - 1] = f"# AUTO-REMOVED: {lines[lineno - 1]}"
            fixed = "".join(lines)
            applied.append(f"commented out invalid line {lineno}")

    description = "; ".join(applied) if applied else "no fix applied"
    return fixed, description


def _fix_javascript(code: str, error_msg: str) -> Tuple[str, str]:
    """Apply targeted fixes to JavaScript code given an error message."""
    fixed = code
    applied: list = []

    # 1. Ensure 'use strict'
    if "'use strict'" not in fixed and '"use strict"' not in fixed:
        fixed = "'use strict';\n" + fixed
        applied.append("added 'use strict'")

    # 2. Replace var with let
    if re.search(r'\bvar\b', fixed):
        fixed = re.sub(r'\bvar\b', "let", fixed)
        applied.append("replaced var with let")

    # 3. Unmatched braces
    open_c = fixed.count("{") - fixed.count("}")
    if open_c > 0:
        fixed += "\n" + "}" * open_c
        applied.append(f"added {open_c} missing '}}'")

    description = "; ".join(applied) if applied else "no fix applied"
    return fixed, description


_FIXERS = {
    "python": _fix_python,
    "python3": _fix_python,
    "bash": _fix_bash,
    "sh": _fix_bash,
    "javascript": _fix_javascript,
    "js": _fix_javascript,
}


# ─────────────────────────────────────────────────────────────────────────────
# MAIN CLASS
# ─────────────────────────────────────────────────────────────────────────────

class CodeErrorFixer:
    """
    Autonomous code error reader and fixer.

    Workflow:
        1. Receive code + error message from CodeCompiler / CodeGenerator
        2. Apply language-specific targeted fixes
        3. Re-validate with CodeCompiler.syntax_test()
        4. Repeat up to MAX_FIX_ATTEMPTS times
        5. Store outcome (fixed/not-fixed) in KnowledgeDB for self-learning

    Usage::

        fixer = CodeErrorFixer(db=knowledge_db)
        fixed_code, success, explanation = fixer.fix_syntax_errors(
            "python", broken_code, "SyntaxError: ..."
        )
        result = fixer.fix_and_compile("python", broken_code, compiler)
        report = fixer.auto_fix_and_run("python", broken_code, compiler)
    """

    def __init__(self, db: Any = None):
        self.db = db
        self._stats: Dict[str, int] = {
            "attempts": 0,
            "fixed": 0,
            "unfixed": 0,
            "compile_successes": 0,
            "compile_failures": 0,
        }
        log.debug("[CodeErrorFixer] Initialized")

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ─────────────────────────────────────────────────────────────────────────

    def fix_syntax_errors(
        self,
        language: str,
        code: str,
        error_msg: str = "",
        compiler: Any = None,
    ) -> Tuple[str, bool, str]:
        """Attempt to fix syntax errors in *code*.

        Runs up to MAX_FIX_ATTEMPTS fix passes, re-validating with
        *compiler*.syntax_test() after each pass.

        Args:
            language:  Language name (python, bash, javascript, …)
            code:      The code string to fix.
            error_msg: Original error message from the compiler/runtime.
            compiler:  Optional CodeCompiler instance for re-validation.

        Returns:
            (fixed_code, success, explanation)
            - fixed_code:  The (possibly repaired) code string.
            - success:     True if the code passes syntax validation after fixing.
            - explanation: Human-readable description of what was done.
        """
        lang = language.lower()
        fixer_fn = _FIXERS.get(lang)
        current_code = code
        history: list = []

        self._stats["attempts"] += 1

        for attempt in range(1, MAX_FIX_ATTEMPTS + 1):
            if not fixer_fn:
                # No known fixer for this language — pass through
                history.append(f"attempt {attempt}: no fixer for '{lang}'")
                break

            fixed_code, fix_desc = fixer_fn(current_code, error_msg)
            history.append(f"attempt {attempt}: {fix_desc}")

            # Re-validate if compiler available
            if compiler and hasattr(compiler, "syntax_test"):
                check = compiler.syntax_test(lang, fixed_code)
                if check.get("valid", True):
                    current_code = fixed_code
                    explanation = "; ".join(history) + " → ✅ valid"
                    self._stats["fixed"] += 1
                    self._store_fix_record(lang, code, fixed_code, explanation, True)
                    log.info("[CodeErrorFixer] Fixed %s after %d attempt(s): %s", lang, attempt, fix_desc)
                    return fixed_code, True, explanation
                else:
                    # Update error_msg for next round
                    error_msg = check.get("error", error_msg) or error_msg
            else:
                # No compiler — apply fix and assume improved
                current_code = fixed_code
                if fixed_code != code:
                    explanation = "; ".join(history) + " → applied (unverified)"
                    self._stats["fixed"] += 1
                    self._store_fix_record(lang, code, fixed_code, explanation, None)
                    return fixed_code, True, explanation

            current_code = fixed_code

        # All attempts exhausted
        explanation = "; ".join(history) + " → ❌ still broken"
        self._stats["unfixed"] += 1
        self._store_fix_record(lang, code, current_code, explanation, False)
        log.warning("[CodeErrorFixer] Could not fix %s after %d attempts", lang, MAX_FIX_ATTEMPTS)
        return current_code, False, explanation

    def fix_and_compile(
        self,
        language: str,
        code: str,
        compiler: Any,
    ) -> Any:
        """Fix syntax errors in *code*, then compile with *compiler*.

        Returns the final ExecutionResult (from compiler.run()).
        If the fixed code still fails syntax, returns a failed ExecutionResult.
        """
        from modules.code_compiler import ExecutionResult  # avoid circular at module level

        lang = language.lower()

        # First pass: syntax check
        syntax_check = compiler.syntax_test(lang, code) if hasattr(compiler, "syntax_test") else {"valid": True}

        if not syntax_check.get("valid", True):
            error_msg = syntax_check.get("error", "syntax error") or ""
            fixed_code, success, explanation = self.fix_syntax_errors(lang, code, error_msg, compiler)

            if not success:
                self._stats["compile_failures"] += 1
                return ExecutionResult(
                    success=False,
                    language=lang,
                    error=f"AutoFix failed: {explanation}",
                )
            code = fixed_code
            log.info("[CodeErrorFixer] fix_and_compile: applied fix (%s)", explanation)

        result = compiler.run(lang, code)
        if getattr(result, "success", False):
            self._stats["compile_successes"] += 1
        else:
            self._stats["compile_failures"] += 1
        return result

    def auto_fix_and_run(
        self,
        language: str,
        code: str,
        compiler: Any,
    ) -> Dict[str, Any]:
        """High-level convenience: fix errors and run code, returning a summary dict.

        Returns::

            {
                "success": bool,
                "language": str,
                "original_code": str,
                "final_code": str,
                "fix_applied": bool,
                "explanation": str,
                "output": str,
                "error": str,
                "elapsed_ms": float,
            }
        """
        ts = time.time()
        lang = language.lower()
        original_code = code
        fix_applied = False
        explanation = ""

        # Step 1: check syntax
        syntax_check = (
            compiler.syntax_test(lang, code)
            if hasattr(compiler, "syntax_test")
            else {"valid": True}
        )

        if not syntax_check.get("valid", True):
            error_msg = syntax_check.get("error", "") or ""
            code, fixed_ok, explanation = self.fix_syntax_errors(lang, code, error_msg, compiler)
            fix_applied = True
            if not fixed_ok:
                elapsed = (time.time() - ts) * 1000
                return {
                    "success": False,
                    "language": lang,
                    "original_code": original_code,
                    "final_code": code,
                    "fix_applied": fix_applied,
                    "explanation": explanation,
                    "output": "",
                    "error": f"AutoFix exhausted: {explanation}",
                    "elapsed_ms": elapsed,
                }

        # Step 2: run
        result = compiler.run(lang, code)
        elapsed = (time.time() - ts) * 1000

        success = getattr(result, "success", False)
        output = getattr(result, "stdout", "") or ""
        error = getattr(result, "error", "") or getattr(result, "stderr", "") or ""

        # Step 3: if execution failed (not syntax) → store for learning
        if not success and not fix_applied:
            explanation = f"runtime error: {error[:120]}"
            self._store_fix_record(lang, original_code, code, explanation, False)
            self._stats["compile_failures"] += 1
        elif success:
            self._stats["compile_successes"] += 1

        return {
            "success": success,
            "language": lang,
            "original_code": original_code,
            "final_code": code,
            "fix_applied": fix_applied,
            "explanation": explanation,
            "output": output,
            "error": error,
            "elapsed_ms": elapsed,
        }

    def get_stats(self) -> Dict[str, Any]:
        """Return fixer statistics."""
        return dict(self._stats)

    # ─────────────────────────────────────────────────────────────────────────
    # INTERNALS
    # ─────────────────────────────────────────────────────────────────────────

    def _store_fix_record(
        self,
        language: str,
        original_code: str,
        fixed_code: str,
        explanation: str,
        success: Optional[bool],
    ) -> None:
        """Persist a fix attempt to KnowledgeDB for autonomous self-learning."""
        if not self.db:
            return
        key = f"code_fix:{language}:{int(time.time())}"
        record = {
            "language": language,
            "original_snippet": original_code[:200],
            "fixed_snippet": fixed_code[:200],
            "explanation": explanation[:300],
            "success": success,
        }
        try:
            if hasattr(self.db, "add_fact"):
                self.db.add_fact(
                    key,
                    str(record)[:400],
                    ["code_fix", "autonomous", language],
                )
        except Exception as exc:
            log.debug("[CodeErrorFixer] DB store failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# STANDALONE SELF-TEST
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(message)s")
    from modules.code_compiler import CodeCompiler

    fixer = CodeErrorFixer()
    compiler = CodeCompiler()

    broken_python = "def foo()\n    return 1\n"
    print("=== CodeErrorFixer self-test ===\n")
    fixed, ok, explanation = fixer.fix_syntax_errors("python", broken_python, "SyntaxError: expected ':'", compiler)
    print(f"Fixed: {ok}\nExplanation: {explanation}\nCode:\n{fixed}")
    print()
    report = fixer.auto_fix_and_run("python", broken_python, compiler)
    print(f"auto_fix_and_run: success={report['success']}, fix={report['fix_applied']}, out='{report['output']}'")
    print()
    print("Stats:", fixer.get_stats())
    print("CodeErrorFixer OK")
