# niblit_tools/tool_registry.py
"""
Tool Registry — LangChain-inspired function-calling layer for Niblit.

Provides a lightweight decorator and registry so any Python function can be
exposed as a callable "tool" that a language model (or the router) can invoke
by name with structured arguments.

Usage::

    from niblit_tools.tool_registry import tool, get_registry

    @tool(description="Add two numbers and return the sum.")
    def add(a: int, b: int) -> int:
        return a + b

    registry = get_registry()
    result   = registry.run("add", {"a": 3, "b": 4})   # → 7
    schema   = registry.get_schema("add")               # → OpenAI-style dict
    all_defs = registry.list_tools()                    # → [{"name": ..., ...}]

The tool definition format is compatible with the OpenAI / GPT tool-calling
API so it can be passed directly to ``NiblitBrain.get_tools()``.
"""

from __future__ import annotations

import inspect
import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("Niblit.ToolRegistry")

# ── Python → JSON-schema type mapping ────────────────────────────────────────
_PY_TYPE_MAP: Dict[type, str] = {
    str:   "string",
    int:   "integer",
    float: "number",
    bool:  "boolean",
    list:  "array",
    dict:  "object",
}


def _py_type_to_json(annotation: Any) -> str:
    """Return a JSON Schema type string for a Python annotation."""
    return _PY_TYPE_MAP.get(annotation, "string")


def _build_parameters_schema(fn: Callable) -> Dict[str, Any]:
    """Introspect *fn* and build an OpenAI-style ``parameters`` dict."""
    sig = inspect.signature(fn)
    hints = {}
    try:
        import typing
        hints = typing.get_type_hints(fn)
    except Exception:
        pass

    properties: Dict[str, Any] = {}
    required: List[str] = []

    for name, param in sig.parameters.items():
        annotation = hints.get(name, str)
        json_type = _py_type_to_json(annotation)
        properties[name] = {"type": json_type, "description": f"Parameter '{name}'"}

        if param.default is inspect.Parameter.empty:
            required.append(name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
    }


# ─────────────────────────────────────────────────────────────────────────────
# ToolRegistry
# ─────────────────────────────────────────────────────────────────────────────

class ToolRegistry:
    """Registry of callable tools that can be invoked by name.

    Each tool is stored as:
    - ``_fns``  : ``{name: callable}``
    - ``_defs`` : ``{name: OpenAI-style tool dict}``
    """

    def __init__(self) -> None:
        self._fns:  Dict[str, Callable] = {}
        self._defs: Dict[str, Dict[str, Any]] = {}

    # ── Registration ──────────────────────────────────────────────────────────

    def register(
        self,
        fn: Callable,
        *,
        name: Optional[str] = None,
        description: str = "",
    ) -> Callable:
        """Register *fn* as a tool and return it unchanged.

        Args:
            fn:          The callable to register.
            name:        Tool name override (default: ``fn.__name__``).
            description: Human-readable description for the LLM.
        """
        tool_name = name or fn.__name__
        tool_def: Dict[str, Any] = {
            "name": tool_name,
            "description": description or (inspect.getdoc(fn) or ""),
            "parameters": _build_parameters_schema(fn),
        }
        self._fns[tool_name]  = fn
        self._defs[tool_name] = tool_def
        logger.debug("Tool registered: %s", tool_name)
        return fn

    # ── Introspection ─────────────────────────────────────────────────────────

    def list_tools(self) -> List[Dict[str, Any]]:
        """Return all registered tool definitions (OpenAI format)."""
        return list(self._defs.values())

    def get_schema(self, name: str) -> Optional[Dict[str, Any]]:
        """Return the OpenAI-style definition for *name*, or ``None``."""
        return self._defs.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._fns

    # ── Execution ─────────────────────────────────────────────────────────────

    def run(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        """Call tool *name* with *arguments* and return its result.

        Args:
            name:      Registered tool name.
            arguments: Keyword arguments dict (may be ``None``).

        Returns:
            Whatever the tool function returns.

        Raises:
            KeyError:  If *name* is not registered.
            TypeError: If the arguments don't match the function signature.
        """
        if name not in self._fns:
            raise KeyError(f"Unknown tool: {name!r}")
        fn = self._fns[name]
        kwargs = arguments or {}
        logger.debug("Running tool %r with args %s", name, kwargs)
        return fn(**kwargs)


# ── Module-level singleton ───────────────────────────────────────────────────

_registry: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    """Return the module-level :class:`ToolRegistry` singleton."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _register_builtin_tools(_registry)
    return _registry


# ── @tool decorator ──────────────────────────────────────────────────────────

def tool(
    fn: Optional[Callable] = None,
    *,
    name: Optional[str] = None,
    description: str = "",
) -> Any:
    """Decorator that registers a function as a Niblit tool.

    Can be used with or without arguments::

        @tool
        def my_fn(x: int) -> int: ...

        @tool(description="My description")
        def my_fn(x: int) -> int: ...
    """
    registry = get_registry()

    def _decorator(f: Callable) -> Callable:
        registry.register(f, name=name, description=description)
        return f

    if fn is not None:
        # Called as ``@tool`` (no parentheses)
        return _decorator(fn)
    # Called as ``@tool(...)`` — return the actual decorator
    return _decorator


# ── Built-in tool registrations ──────────────────────────────────────────────

def _register_builtin_tools(registry: ToolRegistry) -> None:
    """Register the Niblit built-in tools into *registry*."""
    try:
        from niblit_tools.serpex_api import niblit_serpex_search, NIBLIT_SERPEX_TOOL
        registry._fns[NIBLIT_SERPEX_TOOL["name"]] = niblit_serpex_search
        registry._defs[NIBLIT_SERPEX_TOOL["name"]] = NIBLIT_SERPEX_TOOL
        logger.debug("Built-in tool registered: niblit_serpex_search")
    except Exception as exc:
        logger.debug("Could not register niblit_serpex_search: %s", exc)


if __name__ == "__main__":
    reg = get_registry()
    print("Registered tools:", [t["name"] for t in reg.list_tools()])
