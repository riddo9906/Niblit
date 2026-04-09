"""TaskRouter — maps task types to appropriate node types and IDs.

Usage example::

    router = TaskRouter(node_registry)
    router.register_route_rule("research", "agent_node")
    node_id = router.route({"type": "research", "payload": {}})
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

log = logging.getLogger("TaskRouter")


class TaskRouter:
    """Routes tasks to nodes based on registered rules."""

    def __init__(self, node_registry: Any = None) -> None:
        self._registry = node_registry
        self._rules: Dict[str, str] = {}

    # ── public API ──

    def register_route_rule(self, task_type: str, node_type: str) -> None:
        """Map *task_type* → *node_type*."""
        self._rules[task_type] = node_type
        log.debug("TaskRouter: rule %s → %s", task_type, node_type)

    def route(self, task: Dict[str, Any]) -> str:
        """Return node_id for *task*, or empty string if no match."""
        task_type = task.get("type", "")
        node_type = self._rules.get(task_type)
        if node_type is None:
            log.warning("TaskRouter: no rule for task type %s", task_type)
            return ""
        if self._registry is not None:
            try:
                nodes = self._registry.list_nodes(node_type=node_type)
                active = [n for n in nodes if n.get("status") == "active"]
                if active:
                    return str(active[0]["node_id"])
            except Exception as exc:
                log.warning("TaskRouter: registry error — %s", exc)
        return f"virtual_{node_type}"

    def get_route(self, task_type: str) -> str:
        """Return the node_type mapped to *task_type* or empty string."""
        return self._rules.get(task_type, "")


if __name__ == "__main__":
    print('Running task_router.py')
