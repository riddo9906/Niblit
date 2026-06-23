from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional


class Tool(ABC):
    """A callable capability that can be routed to by the tool dispatcher."""

    name: str = "tool"
    description: str = "Generic tool"

    @abstractmethod
    def execute(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raise NotImplementedError


class LoggerTool(Tool):
    name = "logger"
    description = "Emit a structured log entry"

    def execute(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        message = (payload or {}).get("message", "")
        return {"status": "ok", "tool": self.name, "message": message}


class FileReaderTool(Tool):
    name = "file_reader"
    description = "Read a file from disk"

    def execute(self, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        path_value = (payload or {}).get("path", "")
        if not path_value:
            return {"status": "error", "tool": self.name, "error": "missing path"}

        path = Path(path_value)
        candidates = []
        if path.is_absolute():
            candidates.append(path)
        else:
            candidates.append(Path.cwd() / path)
            for parent in [Path.cwd(), *Path.cwd().parents]:
                candidates.append(parent / path)
            for match in Path.cwd().rglob(str(path)):
                if match.is_file():
                    candidates.append(match)
                    break

        resolved = None
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                resolved = candidate
                break

        if resolved is None:
            return {"status": "error", "tool": self.name, "error": f"missing file: {path_value}"}
        return {"status": "ok", "tool": self.name, "path": str(resolved), "content": resolved.read_text(encoding="utf-8")[:200]}


class ToolRouter:
    """Registry and dispatcher for simple tools."""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register_tool(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get_registered_tools(self) -> List[str]:
        return sorted(self._tools.keys())

    def dispatch(self, name: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            return {"status": "error", "tool": name, "error": "unknown tool"}
        return tool.execute(payload)
