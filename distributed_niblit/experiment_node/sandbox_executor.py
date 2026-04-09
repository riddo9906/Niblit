"""SandboxExecutor — restricted Python exec environment for safe code runs.

Uses a limited builtins dict to prevent access to file I/O, network, and
other dangerous operations. No Docker or containers required.

Usage example::

    sandbox = SandboxExecutor()
    result = sandbox.run("x = 2 + 2\nprint(x)")
"""

from __future__ import annotations

import io
import logging
import sys
import time
from typing import Any, Dict

log = logging.getLogger("SandboxExecutor")

_SAFE_BUILTINS: Dict[str, Any] = {
    "print": print,
    "range": range,
    "len": len,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
    "sorted": sorted,
    "enumerate": enumerate,
    "zip": zip,
    "map": map,
    "filter": filter,
    "isinstance": isinstance,
    "type": type,
    "repr": repr,
    "round": round,
    "pow": pow,
    "divmod": divmod,
    "hasattr": hasattr,
    "getattr": getattr,
    "__import__": None,
}

_BANNED_PATTERNS = [
    "__import__", "open(", "exec(", "eval(", "compile(",
    "os.", "sys.", "subprocess", "socket", "importlib",
]

_BANNED_AST_CALLS = {"__import__", "exec", "eval", "compile", "open"}
_BANNED_AST_ATTRS = {"__class__", "__subclasses__", "__bases__", "__globals__"}


def _ast_is_safe(code: str) -> bool:
    """Return True if *code* AST contains no dangerous call/attribute nodes."""
    import ast as _ast
    try:
        tree = _ast.parse(code)
    except SyntaxError:
        return True  # syntax errors handled separately
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Call):
            func = node.func
            name = None
            if isinstance(func, _ast.Name):
                name = func.id
            elif isinstance(func, _ast.Attribute):
                name = func.attr
            if name in _BANNED_AST_CALLS:
                return False
        if isinstance(node, _ast.Attribute) and node.attr in _BANNED_AST_ATTRS:
            return False
    return True


class SandboxExecutor:
    """Executes Python code strings in a restricted environment."""

    # ── public API ──

    def validate_code(self, code: str) -> bool:
        """Return True if *code* contains no obviously unsafe patterns."""
        for pattern in _BANNED_PATTERNS:
            if pattern in code:
                log.warning("SandboxExecutor: banned pattern %r in code", pattern)
                return False
        if not _ast_is_safe(code):
            log.warning("SandboxExecutor: dangerous AST node detected")
            return False
        return True

    def run(self, code: str, timeout: float = 5.0) -> Dict[str, Any]:
        """Execute *code* safely and return stdout/stderr/success dict."""
        if not self.validate_code(code):
            return {"stdout": "", "stderr": "Code failed safety check.", "success": False, "error": "unsafe_code"}
        captured_out = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured_out
        start = time.time()
        error_msg = ""
        success = True
        try:
            local_ns: Dict[str, Any] = {}
            exec(code, {"__builtins__": _SAFE_BUILTINS}, local_ns)  # noqa: S102
        except Exception as exc:
            success = False
            error_msg = str(exc)
            log.warning("SandboxExecutor: exec error — %s", exc)
        finally:
            sys.stdout = old_stdout
        elapsed = time.time() - start
        if elapsed > timeout:
            success = False
            error_msg = f"Execution exceeded timeout of {timeout}s"
        return {
            "stdout": captured_out.getvalue(),
            "stderr": "",
            "success": success,
            "error": error_msg,
            "elapsed_s": round(elapsed, 4),
        }


if __name__ == "__main__":
    print('Running sandbox_executor.py')
