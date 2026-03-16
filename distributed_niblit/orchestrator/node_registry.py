"""NodeRegistry — tracks agent nodes across the distributed cluster.

Usage example::

    reg = NodeRegistry()
    reg.register_node("n1", "agent_node", {"research": True})
    print(reg.list_nodes())
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("NodeRegistry")


class NodeRegistry:
    """Maintains state for all nodes in the cluster."""

    def __init__(self) -> None:
        self._nodes: Dict[str, Dict[str, Any]] = {}

    # ── public API ──

    def register_node(
        self, node_id: str, node_type: str, capabilities: Dict[str, Any]
    ) -> None:
        """Register a node with its type and capabilities."""
        self._nodes[node_id] = {
            "node_id": node_id,
            "node_type": node_type,
            "capabilities": capabilities,
            "status": "active",
            "registered_at": time.time(),
        }
        log.info("NodeRegistry: registered %s (%s)", node_id, node_type)

    def deregister_node(self, node_id: str) -> None:
        """Remove node from registry."""
        self._nodes.pop(node_id, None)
        log.info("NodeRegistry: deregistered %s", node_id)

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Return node info or None."""
        return self._nodes.get(node_id)

    def list_nodes(self, node_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return all nodes, optionally filtered by *node_type*."""
        nodes = list(self._nodes.values())
        if node_type is not None:
            nodes = [n for n in nodes if n["node_type"] == node_type]
        return nodes

    def update_status(self, node_id: str, status: str) -> None:
        """Update status field for *node_id*."""
        if node_id in self._nodes:
            self._nodes[node_id]["status"] = status
            log.debug("NodeRegistry: %s status → %s", node_id, status)
        else:
            log.warning("NodeRegistry: update_status — unknown node %s", node_id)
