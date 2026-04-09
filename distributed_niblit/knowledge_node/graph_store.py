"""GraphStore — lightweight in-memory knowledge graph.

Usage example::

    g = GraphStore()
    g.add_node("AI", {"type": "field"})
    g.add_node("ML", {"type": "subfield"})
    g.add_edge("ML", "AI", "subfield_of")
    neighbors = g.get_neighbors("ML")
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("GraphStore")


class GraphStore:
    """Adjacency-list knowledge graph with node properties."""

    def __init__(self) -> None:
        self._nodes: Dict[str, Dict[str, Any]] = {}
        self._edges: List[Dict[str, Any]] = []

    # ── public API ──

    def add_node(self, node_id: str, props: Dict[str, Any]) -> None:
        """Add or update *node_id* with *props*."""
        self._nodes[node_id] = {"node_id": node_id, **props}
        log.debug("GraphStore: added node %s", node_id)

    def add_edge(
        self,
        src: str,
        dst: str,
        rel_type: str,
        props: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add directed edge *src* → *dst* with *rel_type*."""
        self._edges.append({
            "src": src,
            "dst": dst,
            "rel_type": rel_type,
            "props": props or {},
        })

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """Return node dict or None."""
        return self._nodes.get(node_id)

    def get_neighbors(self, node_id: str) -> List[Dict[str, Any]]:
        """Return list of {node_id, rel_type} dicts reachable from *node_id*."""
        results = []
        for edge in self._edges:
            if edge["src"] == node_id:
                neighbor = self._nodes.get(edge["dst"], {"node_id": edge["dst"]})
                results.append({**neighbor, "rel_type": edge["rel_type"]})
        return results

    def query(self, pattern: str) -> List[Dict[str, Any]]:
        """Simple pattern match — return nodes whose node_id contains *pattern*."""
        return [n for nid, n in self._nodes.items() if pattern.lower() in nid.lower()]

    def node_count(self) -> int:
        """Return total node count."""
        return len(self._nodes)


if __name__ == "__main__":
    print('Running graph_store.py')
