from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MemoryNode:
    id: str
    text: str
    type: str
    collection: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryEdge:
    source_id: str
    target_id: str
    relation: str
    weight: float = 1.0
    timestamp: float = field(default_factory=time.time)


class MemoryGraph:
    """In-memory graph representation of the Qdrant-backed memory system."""

    def __init__(self) -> None:
        self.nodes: Dict[str, MemoryNode] = {}
        self.edges: List[MemoryEdge] = []

    def add_node(self, node: MemoryNode) -> None:
        existing = self.nodes.get(node.id)
        if existing is not None:
            existing.text = node.text
            existing.type = node.type
            existing.collection = node.collection
            existing.timestamp = node.timestamp
            merged = dict(existing.metadata)
            merged.update(node.metadata)
            existing.metadata = merged
            return
        self.nodes[node.id] = node

    def get_node(self, node_id: str) -> Optional[MemoryNode]:
        return self.nodes.get(node_id)

    def add_edge(self, edge: MemoryEdge) -> None:
        for existing in self.edges:
            if (
                existing.source_id == edge.source_id
                and existing.target_id == edge.target_id
                and existing.relation == edge.relation
            ):
                existing.weight = max(existing.weight, edge.weight)
                existing.timestamp = edge.timestamp
                return
        self.edges.append(edge)

    def get_edges_from(self, node_id: str) -> List[MemoryEdge]:
        return [edge for edge in self.edges if edge.source_id == node_id]

    def get_edges_to(self, node_id: str) -> List[MemoryEdge]:
        return [edge for edge in self.edges if edge.target_id == node_id]

    def edge_count(self, node_id: str) -> int:
        return len(self.get_edges_from(node_id)) + len(self.get_edges_to(node_id))

    def touch_node(self, node_id: str, *, timestamp: Optional[int] = None) -> None:
        node = self.get_node(node_id)
        if node is None:
            return
        graph_meta = dict(node.metadata.get("graph") or {})
        graph_meta["access_count"] = int(graph_meta.get("access_count", 0)) + 1
        graph_meta["last_accessed_at"] = int(timestamp or time.time())
        node.metadata["graph"] = graph_meta

    def expansion_scores(
        self,
        seed_scores: Dict[str, float],
        *,
        max_depth: int = 1,
    ) -> Dict[str, Dict[str, Any]]:
        frontier = {node_id: (max(0.0, float(score)), 0) for node_id, score in seed_scores.items() if score > 0.0}
        expanded: Dict[str, Dict[str, Any]] = {
            node_id: {"score": max(0.0, float(score)), "hops": 0, "relations": []}
            for node_id, score in seed_scores.items()
            if score > 0.0
        }
        while frontier:
            next_frontier: Dict[str, tuple[float, int]] = {}
            for node_id, (score, depth) in frontier.items():
                if depth >= max_depth:
                    continue
                for edge in self.get_edges_from(node_id):
                    propagated = score * max(0.0, float(edge.weight))
                    if propagated <= 0.0:
                        continue
                    existing = expanded.get(edge.target_id)
                    hops = depth + 1
                    if existing is None or propagated > float(existing["score"]):
                        expanded[edge.target_id] = {
                            "score": propagated,
                            "hops": hops,
                            "relations": [edge.relation],
                        }
                    elif edge.relation not in existing["relations"]:
                        existing["relations"].append(edge.relation)
                    queued = next_frontier.get(edge.target_id)
                    if queued is None or propagated > queued[0]:
                        next_frontier[edge.target_id] = (propagated, hops)
            frontier = next_frontier
        return expanded
