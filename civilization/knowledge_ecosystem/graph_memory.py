"""GraphMemory — concept graph for the knowledge ecosystem.

Usage example::

    gm = GraphMemory()
    gm.add_concept("AI", {"type": "field"})
    gm.link("ML", "AI", "subfield_of")
    related = gm.find_related("AI")
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("GraphMemory")


class GraphMemory:
    """In-memory concept graph with BFS traversal."""

    def __init__(self) -> None:
        self._concepts: Dict[str, Dict[str, Any]] = {}
        self._edges: List[Dict[str, str]] = []

    # ── public API ──

    def add_concept(self, concept_id: str, props: Dict[str, Any]) -> None:
        """Add or update *concept_id* with *props*."""
        self._concepts[concept_id] = {"concept_id": concept_id, **props}
        log.debug("GraphMemory: added concept %s", concept_id)

    def link(
        self, concept_a: str, concept_b: str, relation_type: str
    ) -> None:
        """Create directed edge concept_a → concept_b."""
        self._edges.append({"src": concept_a, "dst": concept_b, "rel": relation_type})

    def traverse(self, start: str, depth: int = 2) -> List[Dict[str, Any]]:
        """BFS from *start* up to *depth* hops; return visited concept dicts."""
        visited: List[str] = []
        frontier = [start]
        for _ in range(depth):
            next_frontier: List[str] = []
            for node in frontier:
                for edge in self._edges:
                    if edge["src"] == node and edge["dst"] not in visited:
                        visited.append(edge["dst"])
                        next_frontier.append(edge["dst"])
            frontier = next_frontier
        return [self._concepts[c] for c in visited if c in self._concepts]

    def find_related(self, concept_id: str) -> List[str]:
        """Return concept_ids directly connected to *concept_id*."""
        return [e["dst"] for e in self._edges if e["src"] == concept_id]

    def concept_count(self) -> int:
        """Return total concept count."""
        return len(self._concepts)


if __name__ == "__main__":
    print('Running graph_memory.py')
