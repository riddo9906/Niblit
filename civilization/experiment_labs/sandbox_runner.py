"""SandboxRunner — restricted Python execution for experiment labs.

Usage example::

    runner = SandboxRunner()
    result = runner.run("x = 1 + 1\nprint(x)")
"""

from __future__ import annotations

import io
import logging
import sys
import time
from typing import Any, Dict

log = logging.getLogger("SandboxRunner")

_BANNED = [
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

_SAFE_BUILTINS: Dict[str, Any] = {
    "print": print, "range": range, "len": len,
    "int": int, "float": float, "str": str, "bool": bool,
    "list": list, "dict": dict, "set": set, "tuple": tuple,
    "abs": abs, "min": min, "max": max, "sum": sum,
    "sorted": sorted, "enumerate": enumerate, "zip": zip,
    "map": map, "filter": filter, "isinstance": isinstance,
    "round": round, "pow": pow, "__import__": None,
}


class SandboxRunner:
    """Runs code strings in a restricted exec environment."""

    # ── public API ──

    def is_safe(self, code: str) -> bool:
        """Return True if *code* passes safety checks."""
        if any(p in code for p in _BANNED):
            return False
        return _ast_is_safe(code)

    def run(self, code: str, timeout: float = 5.0) -> Dict[str, Any]:
        """Execute *code* safely; return stdout/stderr/success dict."""
        if not self.is_safe(code):
            return {"stdout": "", "stderr": "Unsafe code rejected.", "success": False, "error": "unsafe"}
        captured = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = captured
        start = time.time()
        error = ""
        success = True
        try:
            exec(code, {"__builtins__": _SAFE_BUILTINS}, {})  # noqa: S102
        except Exception as exc:
            success = False
            error = str(exc)
        finally:
            sys.stdout = old_stdout
        return {
            "stdout": captured.getvalue(),
            "stderr": "",
            "success": success,
            "error": error,
            "elapsed_s": round(time.time() - start, 4),
        }


if __name__ == "__main__":
    print('Running sandbox_runner.py')
