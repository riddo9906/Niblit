"""NodeRegistry — tracks infrastructure nodes across clusters.

Usage example::

    reg = NodeRegistry()
    reg.register("node-1", "agent_node", "cluster-1", caps=["research"])
    nodes = reg.list_by_type("agent_node")
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("InfraNodeRegistry")


class NodeRegistry:
    """Registry of infrastructure nodes with type and capability metadata."""

    def __init__(self) -> None:
        self._nodes: Dict[str, Dict[str, Any]] = {}

    # ── public API ──

    def register(
        self,
        node_id: str,
        node_type: str,
        cluster_id: str,
        caps: Optional[List[str]] = None,
    ) -> None:
        """Register *node_id* in *cluster_id*."""
        self._nodes[node_id] = {
            "node_id": node_id,
            "node_type": node_type,
            "cluster_id": cluster_id,
            "capabilities": caps or [],
            "registered_at": time.time(),
        }
        log.info("InfraNodeRegistry: registered %s (%s)", node_id, node_type)

    def deregister(self, node_id: str) -> None:
        """Remove *node_id*."""
        self._nodes.pop(node_id, None)

    def get(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Return node dict or None."""
        return self._nodes.get(node_id)

    def list_by_type(self, node_type: str) -> List[Dict[str, Any]]:
        """Return all nodes of *node_type*."""
        return [n for n in self._nodes.values() if n["node_type"] == node_type]

    def node_count(self) -> int:
        """Return total registered node count."""
        return len(self._nodes)
