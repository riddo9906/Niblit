#!/usr/bin/env python3
"""
modules/knowledge_engine/knowledge_graph_builder.py

Build a knowledge graph of relationships between software concepts.

Uses the built-in ``collections`` module for a lightweight adjacency list
implementation.  When ``networkx`` is installed it is used instead for richer
graph operations (shortest paths, centrality, etc.).

Nodes represent concepts: framework, pattern, language, algorithm, library.
Edges represent relationships: uses, implements, is_part_of, extends.

Example::

    FastAPI → Python        (language)
    FastAPI → REST API      (implements)
    REST API → client-server architecture  (is_part_of)

Usage::

    from modules.knowledge_engine.knowledge_graph_builder import KnowledgeGraphBuilder
    kg = KnowledgeGraphBuilder()
    kg.add_edge("FastAPI", "Python", relation="uses_language")
    kg.add_edge("FastAPI", "REST", relation="implements")
    neighbors = kg.neighbors("FastAPI")
    path = kg.path("FastAPI", "client-server")
"""

import logging
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("KnowledgeGraphBuilder")

# Try to import networkx for richer graph operations
try:
    import networkx as nx
    _NX_AVAILABLE = True
except ImportError:
    nx = None  # type: ignore[assignment]
    _NX_AVAILABLE = False


class KnowledgeGraphBuilder:
    """
    Build and query a directed knowledge graph of software concepts.

    When networkx is available, the graph is backed by ``nx.DiGraph``.
    Otherwise a plain adjacency-list dict is used.
    """

    def __init__(self) -> None:
        if _NX_AVAILABLE:
            self._graph = nx.DiGraph()
        else:
            # adjacency: node → list of (target, relation)
            self._adj: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
            self._graph = None

    # ── public API ────────────────────────────────────────────────────────────

    def add_edge(
        self,
        source: str,
        target: str,
        relation: str = "related_to",
    ) -> None:
        """Add a directed edge from *source* to *target*."""
        if _NX_AVAILABLE:
            self._graph.add_edge(source, target, relation=relation)
        else:
            entry = (target, relation)
            if entry not in self._adj[source]:
                self._adj[source].append(entry)
        log.debug("KG: %s -[%s]→ %s", source, relation, target)

    def add_edges_bulk(self, edges: List[Tuple[str, str, str]]) -> None:
        """
        Add multiple edges at once.

        Each entry is (source, target, relation).
        """
        for source, target, relation in edges:
            self.add_edge(source, target, relation)

    def neighbors(self, node: str) -> List[Dict[str, str]]:
        """Return list of dicts {target, relation} reachable from *node*."""
        if _NX_AVAILABLE:
            result = []
            for target in self._graph.successors(node):
                data = self._graph.get_edge_data(node, target) or {}
                result.append({"target": target, "relation": data.get("relation", "")})
            return result
        return [{"target": t, "relation": r} for t, r in self._adj.get(node, [])]

    def path(self, source: str, target: str) -> List[str]:
        """Return the shortest path from *source* to *target* (node names)."""
        if _NX_AVAILABLE:
            try:
                return list(nx.shortest_path(self._graph, source, target))
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                return []
        return self._bfs_path(source, target)

    def all_nodes(self) -> List[str]:
        if _NX_AVAILABLE:
            return list(self._graph.nodes())
        return list(self._adj.keys())

    def all_edges(self) -> List[Tuple[str, str, str]]:
        if _NX_AVAILABLE:
            return [(u, v, d.get("relation", "")) for u, v, d in self._graph.edges(data=True)]
        result = []
        for src, targets in self._adj.items():
            for tgt, rel in targets:
                result.append((src, tgt, rel))
        return result

    def related_concepts(self, node: str, depth: int = 2) -> List[str]:
        """Return concepts reachable within *depth* hops from *node*."""
        if _NX_AVAILABLE:
            try:
                return [
                    n for n, d in nx.single_source_shortest_path_length(
                        self._graph, node, cutoff=depth
                    ).items() if n != node
                ]
            except nx.NodeNotFound:
                return []
        # BFS fallback
        visited: set = set()
        queue: deque = deque([(node, 0)])
        while queue:
            current, dist = queue.popleft()
            if dist >= depth or current in visited:
                visited.add(current)
                continue
            visited.add(current)
            for tgt, _ in self._adj.get(current, []):
                if tgt not in visited:
                    queue.append((tgt, dist + 1))
        visited.discard(node)
        return list(visited)

    def load_from_parse_results(
        self, parse_results: List[Dict[str, Any]]
    ) -> int:
        """
        Auto-populate graph from CodeParser results.

        Adds edges like: file → function, file → class, file → import.
        Returns number of edges added.
        """
        count = 0
        for result in parse_results:
            src = result.get("path", "unknown")
            for func in result.get("functions", []):
                self.add_edge(src, func["name"], relation="defines_function")
                count += 1
            for cls in result.get("classes", []):
                self.add_edge(src, cls["name"], relation="defines_class")
                count += 1
            for imp in result.get("imports", []):
                self.add_edge(src, imp, relation="imports")
                count += 1
        return count

    def summary(self) -> Dict[str, int]:
        return {
            "nodes": len(self.all_nodes()),
            "edges": len(self.all_edges()),
            "networkx": _NX_AVAILABLE,
        }

    # ── internals ─────────────────────────────────────────────────────────────

    def _bfs_path(self, source: str, target: str) -> List[str]:
        if source not in self._adj and target not in self._adj:
            return []
        parents: Dict[str, Optional[str]] = {source: None}
        queue: deque = deque([source])
        while queue:
            node = queue.popleft()
            if node == target:
                path = []
                current: Optional[str] = node
                while current is not None:
                    path.append(current)
                    current = parents[current]
                return list(reversed(path))
            for tgt, _ in self._adj.get(node, []):
                if tgt not in parents:
                    parents[tgt] = node
                    queue.append(tgt)
        return []
