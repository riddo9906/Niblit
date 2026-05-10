# niblit_tools/builtin_tools.py
"""
Built-in function-calling tools for Niblit — LangChain-inspired.

Each function is decorated with ``@tool`` so it is automatically
registered in the global :class:`ToolRegistry` and exposed through
``niblit --list-tools`` / ``niblit --tool-call``.

Tools provided
--------------
``calculator``      — Safely evaluate arithmetic expressions.
``get_datetime``    — Return the current UTC date and/or time.
``word_count``      — Count words, characters, and lines in text.
``kb_query``        — Search Niblit's knowledge base for stored facts.
``list_commands``   — List all Niblit shell commands.
``summarise_text``  — Truncate long text to a concise excerpt.
"""

from __future__ import annotations

import ast
import logging
import math
import operator
import re
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("Niblit.BuiltinTools")


# ── Safe arithmetic evaluator ─────────────────────────────────────────────────

_SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

_SAFE_NAMES = {name: getattr(math, name) for name in dir(math) if not name.startswith("_")}
_SAFE_NAMES.update({"abs": abs, "round": round, "int": int, "float": float})


def _safe_eval(expr: str) -> float:
    """Evaluate a restricted arithmetic expression.  Raises ValueError on unsafe input."""
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid expression: {exc}") from exc

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise ValueError(f"Unsupported constant type: {type(node.value)}")
        if isinstance(node, ast.Name):
            if node.id in _SAFE_NAMES:
                return _SAFE_NAMES[node.id]  # type: ignore[return-value]
            raise ValueError(f"Unknown name: {node.id!r}")
        if isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in _SAFE_OPS:
                raise ValueError(f"Unsupported operator: {op_type.__name__}")
            return _SAFE_OPS[op_type](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type not in _SAFE_OPS:
                raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
            return _SAFE_OPS[op_type](_eval(node.operand))  # type: ignore[call-arg]
        if isinstance(node, ast.Call):
            func = _eval(node.func)
            args = [_eval(a) for a in node.args]
            return func(*args)  # type: ignore[operator]
        raise ValueError(f"Unsupported AST node: {type(node).__name__}")

    return _eval(tree)


# ── Tool functions ─────────────────────────────────────────────────────────────

def calculator(expression: str) -> str:
    """Safely evaluate an arithmetic or mathematical expression.

    Supports +, -, *, /, //, %, ** and all Python ``math`` module functions
    (sin, cos, sqrt, log, etc.).  No code execution beyond pure arithmetic.

    Args:
        expression: Mathematical expression to evaluate, e.g. ``"2 ** 10"``
                    or ``"sqrt(2) * pi"``.

    Returns:
        The result as a string, or an error message.
    """
    try:
        result = _safe_eval(expression)
        # Return integer representation when the result is a whole number
        if result == int(result) and abs(result) < 1e15:
            return str(int(result))
        return str(result)
    except Exception as exc:
        return f"[calculator error] {exc}"


def get_datetime(format: str = "both") -> str:
    """Return the current UTC date and/or time.

    Args:
        format: One of ``"date"``, ``"time"``, or ``"both"`` (default).

    Returns:
        A human-readable UTC datetime string.
    """
    now = datetime.now(tz=timezone.utc)
    format = (format or "both").strip().lower()
    if format == "date":
        return now.strftime("%Y-%m-%d (UTC)")
    if format == "time":
        return now.strftime("%H:%M:%S UTC")
    return now.strftime("%Y-%m-%d %H:%M:%S UTC")


def word_count(text: str) -> str:
    """Count words, characters, and lines in the given text.

    Args:
        text: The text to analyse.

    Returns:
        A summary string, e.g. ``"Words: 42 | Characters: 213 | Lines: 5"``.
    """
    if not text:
        return "Words: 0 | Characters: 0 | Lines: 0"
    words = len(text.split())
    chars = len(text)
    lines = text.count("\n") + 1
    return f"Words: {words} | Characters: {chars} | Lines: {lines}"


def kb_query(query: str, max_results: int = 5) -> str:
    """Search Niblit's knowledge base for facts matching *query*.

    Performs a keyword search over the local KB and returns the most
    relevant stored facts.  Returns a helpful message if the KB is
    unavailable.

    Args:
        query:       Search terms to look for in the KB.
        max_results: Maximum number of results to return (default 5).

    Returns:
        Newline-separated list of matching KB entries, or a status message.
    """
    try:
        from niblit_memory import NiblitMemory
        mem = NiblitMemory()
        results = mem.search(query, top_k=max(1, int(max_results)))
        if not results:
            return f"No KB entries found for: {query!r}"
        lines = []
        for i, r in enumerate(results, 1):
            fact = r.get("fact") or r.get("content") or r.get("text") or str(r)
            lines.append(f"{i}. {fact[:200]}")
        return "\n".join(lines)
    except Exception as exc:
        return f"[kb_query] KB unavailable: {exc}"


def list_commands() -> str:
    """List all available Niblit interactive shell commands.

    Returns:
        A formatted list of command names.
    """
    try:
        from main import COMMANDS
        return "Available commands:\n" + "\n".join(f"  • {c}" for c in sorted(COMMANDS))
    except Exception:
        return "Command list unavailable — start Niblit with `python main.py` to see all commands."


def summarise_text(text: str, max_words: int = 50) -> str:
    """Return the first *max_words* words of *text* followed by '…' if truncated.

    Useful for condensing long context or document snippets before sending
    them to an LLM.

    Args:
        text:      The text to summarise.
        max_words: Maximum word count before truncation (default 50).

    Returns:
        Truncated text excerpt.
    """
    if not text:
        return ""
    words = text.split()
    max_words = max(1, int(max_words))
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + " …"


# ── Registration helper ────────────────────────────────────────────────────────

def register_all(registry: "ToolRegistry") -> None:  # type: ignore[name-defined]  # noqa: F821
    """Register all built-in tools from this module into *registry*."""
    from niblit_tools.tool_registry import _build_parameters_schema

    _TOOLS = [
        (calculator,    "calculator",    "Safely evaluate an arithmetic or math expression."),
        (get_datetime,  "get_datetime",  "Return the current UTC date and/or time."),
        (word_count,    "word_count",    "Count words, characters, and lines in text."),
        (kb_query,      "kb_query",      "Search Niblit's knowledge base for stored facts."),
        (list_commands, "list_commands", "List all available Niblit shell commands."),
        (summarise_text, "summarise_text", "Truncate long text to a concise excerpt."),
    ]

    for fn, name, description in _TOOLS:
        tool_def = {
            "type": "function",
            "name": name,
            "description": description,
            "function": {
                "name": name,
                "description": description,
                "parameters": _build_parameters_schema(fn),
            },
        }
        registry._fns[name] = fn
        registry._defs[name] = tool_def
        logger.debug("Built-in tool registered: %s", name)
