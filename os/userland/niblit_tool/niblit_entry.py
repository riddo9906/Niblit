#!/usr/bin/env python3
"""
os/userland/niblit_tool/niblit_entry.py
─────────────────────────────────────────────────────────────────────────────
NiblitOS userspace entry point for the Niblit AI tool.

Called by niblit_runner (the C daemon) when a kernel request arrives.
Request parameters are delivered via environment variables:

  NIBLIT_REQUEST_ID   — numeric request ID
  NIBLIT_REQUEST_TYPE — "query" | "tool"
  NIBLIT_TOOL         — tool name (only for type=tool)
  NIBLIT_QUERY        — natural-language query or JSON arguments

The script's stdout is captured by niblit_runner and written back into
the kernel's NiblitRing response slot.  All output must be valid UTF-8.

Usage (direct):
  NIBLIT_REQUEST_TYPE=query NIBLIT_QUERY="What is 2+2?" python3 niblit_entry.py
"""

from __future__ import annotations

import json
import os
import sys
import traceback

# ── Path setup — ensure the Niblit repo root is on sys.path ──────────────────
# niblit_entry.py lives at  os/userland/niblit_tool/niblit_entry.py
# Niblit repo root is 3 levels up.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT  = os.path.abspath(os.path.join(_SCRIPT_DIR, "..", "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _handle_query(query: str) -> str:
    """Process a natural-language query through NiblitCore."""
    try:
        from niblit_core import NiblitCore  # type: ignore[import]
        core = NiblitCore()
        result = core.process(query)
        return str(result) if result else "(no response)"
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: NiblitCore unavailable — {exc}"


def _handle_tool_call(tool_name: str, args_json: str) -> str:
    """Invoke a registered Niblit tool by name with JSON arguments."""
    try:
        from niblit_tools.tool_registry import get_registry  # type: ignore[import]
        registry = get_registry()
        try:
            kwargs = json.loads(args_json) if args_json else {}
        except json.JSONDecodeError:
            kwargs = {}
        result = registry.run(tool_name, kwargs)
        return json.dumps(result, default=str)
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: tool '{tool_name}' failed — {exc}"


def main() -> None:
    request_id   = os.environ.get("NIBLIT_REQUEST_ID", "0")
    request_type = os.environ.get("NIBLIT_REQUEST_TYPE", "query").lower()
    tool_name    = os.environ.get("NIBLIT_TOOL", "")
    query        = os.environ.get("NIBLIT_QUERY", "")

    try:
        if request_type == "tool" and tool_name:
            result = _handle_tool_call(tool_name, query)
        else:
            result = _handle_query(query)
    except Exception:  # noqa: BLE001
        result = f"ERROR: unhandled exception\n{traceback.format_exc()}"

    # Coerce to str before any string-method calls.
    result = str(result) if not isinstance(result, str) else result

    # Output the result as a JSON envelope so niblit_runner can parse it.
    envelope = {
        "request_id": int(request_id),
        "status": "ok" if not result.startswith("ERROR:") else "error",
        "result": result,
    }
    print(json.dumps(envelope), end="", flush=True)


if __name__ == "__main__":
    main()
