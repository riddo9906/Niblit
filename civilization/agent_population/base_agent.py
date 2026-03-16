"""BaseAgent — abstract foundation for all civilisation agents.

Usage example::

    class MyAgent(BaseAgent):
        def execute(self, task_dict):
            return {"result": "done"}
    agent = MyAgent("a1", "worker")
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

log = logging.getLogger("BaseAgent")


class BaseAgent:
    """Abstract base for civilisation agents.

    Args:
        agent_id: Unique identifier for this agent.
        role: Role label (e.g. 'researcher', 'builder').
    """

    def __init__(self, agent_id: str, role: str) -> None:
        self._agent_id = agent_id
        self._role = role
        self._memory: Dict[str, Any] = {}
        self._tasks_completed: int = 0
        self._last_task_at: Optional[float] = None

    @property
    def agent_id(self) -> str:
        """Public agent identifier."""
        return self._agent_id

    @property
    def role(self) -> str:
        """Agent role label."""
        return self._role

    # ── public API ──

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute *task*; subclasses must override."""
        raise NotImplementedError(f"{self.__class__.__name__} must implement execute()")

    def get_memory(self) -> Dict[str, Any]:
        """Return agent memory dict."""
        return dict(self._memory)

    def store_memory(self, key: str, value: Any) -> None:
        """Store *value* under *key* in agent memory."""
        self._memory[key] = value

    def get_stats(self) -> Dict[str, Any]:
        """Return task statistics."""
        return {
            "agent_id": self._agent_id,
            "role": self._role,
            "tasks_completed": self._tasks_completed,
            "last_task_at": self._last_task_at,
        }

    # ── internals ──

    def _record_task(self) -> None:
        self._tasks_completed += 1
        self._last_task_at = time.time()
