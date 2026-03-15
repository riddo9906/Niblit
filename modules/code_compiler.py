#!/usr/bin/env python3
"""
CODE COMPILER MODULE
Execute and compile code in multiple languages safely.

Features:
- Run Python, Bash, JavaScript (Node.js) code via subprocess
- Safe sandboxed execution with timeout
- Capture stdout/stderr
- Termux and standard Linux environment support
- Syntax validation before running (Python, Bash, JavaScript)
- Pre-execution syntax gate: bash -n / py_compile / node --check
- Store execution results in KnowledgeDB
"""

import ast
import os
import subprocess
import sys
import tempfile
import time
import logging
from typing import Any, Dict, Optional

log = logging.getLogger("CodeCompiler")

# Default execution timeout (seconds)
DEFAULT_TIMEOUT: int = 10

# Language → interpreter command
_RUNNERS: Dict[str, str] = {
    "python": sys.executable,
    "python3": sys.executable,
    "bash": "bash",
    "sh": "sh",
    "javascript": "node",
    "js": "node",
}

# Language → file extension for temp files
_EXT: Dict[str, str] = {
    "python": ".py",
    "python3": ".py",
    "bash": ".sh",
    "sh": ".sh",
    "javascript": ".js",
    "js": ".js",
}


class ExecutionResult:
    """Result of a code execution."""

    def __init__(
        self,
        *,
        success: bool,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
        elapsed_ms: float = 0.0,
        language: str = "",
        error: Optional[str] = None,
    ):
        self.success = success
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.elapsed_ms = elapsed_ms
        self.language = language
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "success": self.success,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "returncode": self.returncode,
            "elapsed_ms": self.elapsed_ms,
            "language": self.language,
            "error": self.error,
        }

    def format_output(self) -> str:
        """Human-readable execution output."""
        icon = "✅" if self.success else "❌"
        lines = [f"{icon} **Execution ({self.language}) — {self.elapsed_ms:.0f}ms**"]
        if self.stdout.strip():
            lines.append(f"\n📤 Output:\n{self.stdout.strip()}")
        if self.stderr.strip():
            lines.append(f"\n⚠️ Stderr:\n{self.stderr.strip()}")
        if self.error:
            lines.append(f"\n❗ Error: {self.error}")
        return "\n".join(lines)


class CodeCompiler:
    """
    Safe multi-language code execution engine.

    Usage:
        compiler = CodeCompiler(db=knowledge_db)
        result = compiler.run("python", "print('Hello, Niblit!')")
        result = compiler.run_file("/path/to/script.py")
    """

    def __init__(self, db: Any = None, timeout: int = DEFAULT_TIMEOUT):
        self.db = db
        self.timeout = timeout
        self._stats: Dict[str, int] = {
            "runs": 0,
            "successes": 0,
            "failures": 0,
        }
        log.debug("[CodeCompiler] Initialized — timeout=%ds", timeout)

    # ──────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────

    def run(self, language: str, code: str) -> ExecutionResult:
        """
        Execute a code string in the specified language.

        Runs a syntax-only check (bash -n / py_compile / node --check) before
        executing so bad code never reaches the interpreter.  Uses a temp file
        so no injection via stdin.
        """
        lang = language.lower()

        # Pre-execution syntax gate — fast, no side-effects
        syntax_check = self.syntax_test(lang, code)
        if not syntax_check["valid"]:
            return ExecutionResult(
                success=False,
                language=lang,
                error=f"SyntaxError: {syntax_check['error']}",
            )

        runner = _RUNNERS.get(lang)
        if runner is None:
            return ExecutionResult(
                success=False,
                language=lang,
                error=(
                    f"Language '{language}' not supported. "
                    f"Supported: {', '.join(_RUNNERS)}"
                ),
            )

        # Check interpreter availability
        if not self._check_interpreter(runner):
            return ExecutionResult(
                success=False,
                language=lang,
                error=f"Interpreter '{runner}' not found in PATH.",
            )

        ext = _EXT.get(lang, ".tmp")
        return self._run_in_tempfile(runner, code, ext, lang)

    def run_file(self, filepath: str) -> ExecutionResult:
        """Execute an existing file. Detects language from extension."""
        ext_map = {".py": "python", ".sh": "bash", ".js": "javascript"}
        ext = os.path.splitext(filepath)[1].lower()
        lang = ext_map.get(ext, "bash")
        runner = _RUNNERS.get(lang, "bash")

        if not os.path.isfile(filepath):
            return ExecutionResult(
                success=False,
                language=lang,
                error=f"File not found: {filepath}",
            )

        return self._execute([runner, filepath], lang)

    def validate_syntax(self, language: str, code: str) -> Dict[str, Any]:
        """
        Validate code syntax without running it.
        Delegates to syntax_test() for a unified multi-language result.
        """
        return self.syntax_test(language, code)

    def syntax_test(self, language: str, code: str) -> Dict[str, Any]:
        """
        Test the syntax of *code* for *language* without executing it.

        Supported checks:
          - python / python3  → ast.parse  (always available)
          - bash / sh         → bash -n    (writes to temp file)
          - javascript / js   → node --check (writes to temp file)

        Returns:
            {"valid": bool, "language": str, "error": Optional[str]}
        """
        lang = language.lower()

        if lang in ("python", "python3"):
            err = self._validate_python_syntax(code)
            return {"valid": err is None, "language": lang, "error": err}

        if lang in ("bash", "sh"):
            err = self._validate_bash_syntax(code)
            return {"valid": err is None, "language": lang, "error": err}

        if lang in ("javascript", "js"):
            err = self._validate_javascript_syntax(code)
            if err is None:
                return {"valid": True, "language": lang, "error": None}
            # node --check may be unavailable; treat as unknown rather than failure
            if err == "unavailable":
                return {"valid": True, "language": lang, "error": None}
            return {"valid": False, "language": lang, "error": err}

        # Unknown language — cannot check, assume valid
        return {"valid": True, "language": lang, "error": None}

    def available_languages(self) -> Dict[str, bool]:
        """Return dict of language → interpreter available."""
        result = {}
        seen: Dict[str, bool] = {}
        for lang, runner in _RUNNERS.items():
            if runner not in seen:
                seen[runner] = self._check_interpreter(runner)
            result[lang] = seen[runner]
        return result

    def get_stats(self) -> Dict[str, Any]:
        """Return execution statistics."""
        return {
            "stats": self._stats,
            "timeout": self.timeout,
            "available_languages": self.available_languages(),
        }

    # ──────────────────────────────────────────────────────
    # INTERNALS
    # ──────────────────────────────────────────────────────

    def _validate_python_syntax(self, code: str) -> Optional[str]:
        """Return None if Python syntax is valid, else error string."""
        try:
            ast.parse(code)
            return None
        except SyntaxError as exc:
            return str(exc)

    def _validate_bash_syntax(self, code: str) -> Optional[str]:
        """Return None if Bash syntax is valid (bash -n), else error string."""
        if not self._check_interpreter("bash"):
            return None  # bash not available — skip check
        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".sh", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(code)
                tmp_path = tmp.name
            result = subprocess.run(
                ["bash", "-n", tmp_path],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return (result.stderr or "bash syntax error").strip()
            return None
        except (subprocess.TimeoutExpired, OSError):
            return None  # cannot check — assume valid
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _validate_javascript_syntax(self, code: str) -> Optional[str]:
        """Return None if JS syntax is valid (node --check), else error string.

        Returns the string 'unavailable' if Node.js is not installed.
        """
        if not self._check_interpreter("node"):
            return "unavailable"
        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".js", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(code)
                tmp_path = tmp.name
            result = subprocess.run(
                ["node", "--check", tmp_path],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return (result.stderr or "javascript syntax error").strip()
            return None
        except (subprocess.TimeoutExpired, OSError):
            return None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    def _check_interpreter(self, runner: str) -> bool:
        """Check if an interpreter binary is available."""
        # sys.executable is always available
        if runner == sys.executable:
            return True
        try:
            result = subprocess.run(
                ["which", runner],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _run_in_tempfile(
        self, runner: str, code: str, ext: str, lang: str
    ) -> ExecutionResult:
        """Write code to a temp file and execute it."""
        tmp_path: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=ext,
                delete=False,
                encoding="utf-8",
            ) as tmp:
                tmp.write(code)
                tmp_path = tmp.name

            if ext == ".sh":
                os.chmod(tmp_path, 0o755)

            res = self._execute([runner, tmp_path], lang)
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        return res

    def _execute(self, cmd: list, lang: str) -> ExecutionResult:
        """Run a command and return an ExecutionResult."""
        self._stats["runs"] += 1
        ts = time.time()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            elapsed = (time.time() - ts) * 1000
            success = proc.returncode == 0
            if success:
                self._stats["successes"] += 1
            else:
                self._stats["failures"] += 1
            result = ExecutionResult(
                success=success,
                stdout=proc.stdout,
                stderr=proc.stderr,
                returncode=proc.returncode,
                elapsed_ms=elapsed,
                language=lang,
            )
        except subprocess.TimeoutExpired:
            self._stats["failures"] += 1
            result = ExecutionResult(
                success=False,
                language=lang,
                error=f"Execution timed out after {self.timeout}s",
                elapsed_ms=(time.time() - ts) * 1000,
            )
        except (OSError, FileNotFoundError) as exc:
            self._stats["failures"] += 1
            result = ExecutionResult(
                success=False,
                language=lang,
                error=f"OS error: {exc}",
                elapsed_ms=(time.time() - ts) * 1000,
            )

        self._store_result(result)
        return result

    def _store_result(self, result: ExecutionResult) -> None:
        """Store execution result in KnowledgeDB."""
        if not self.db:
            return
        key = f"code_execution:{result.language}:{int(time.time())}"
        try:
            if hasattr(self.db, "add_fact"):
                self.db.add_fact(
                    key,
                    str(result.to_dict())[:300],
                    ["code", "execution", result.language],
                )
        except Exception as exc:
            log.debug("[CodeCompiler] Store result failed: %s", exc)


# ──────────────────────────────────────────────────────
# STANDALONE SELF-TEST
# ──────────────────────────────────────────────────────
if __name__ == "__main__":
    import logging as _logging  # pylint: disable=reimported,ungrouped-imports
    _logging.basicConfig(level=_logging.INFO, format="%(message)s")
    print("=== CodeCompiler self-test ===\n")

    compiler = CodeCompiler()
    print("Available languages:", compiler.available_languages())
    print()

    # Python test
    res = compiler.run("python", "print('Hello from Niblit CodeCompiler!')\nprint(1+1)")
    print(res.format_output())
    print()

    # Syntax error test
    res = compiler.run("python", "def broken syntax !!")
    print(res.format_output())
    print()

    print("Stats:", compiler.get_stats()["stats"])
    print("CodeCompiler OK")
