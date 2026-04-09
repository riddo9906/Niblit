#!/usr/bin/env python3
"""
modules/global_code_intelligence/pattern_graph_builder.py

Convert extracted information into a global knowledge graph that Niblit can
traverse for architecture discovery and code generation augmentation.

Extends the KnowledgeGraphBuilder from SEKE with a richer vocabulary of
software-engineering concepts and pre-seeded "world model" edges.

Usage::

    from modules.global_code_intelligence.pattern_graph_builder import PatternGraphBuilder
    pgb = PatternGraphBuilder()
    pgb.seed_world_model()          # load built-in software knowledge
    pgb.add_repo_knowledge(repos)   # add from EcosystemScanner output
    answer = pgb.find_architectures_for("real-time chat")
    path   = pgb.concept_path("FastAPI", "client-server")
"""

import logging
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set, Tuple

log = logging.getLogger("PatternGraphBuilder")

# Try networkx for richer queries
try:
    import networkx as nx
    _NX = True
except ImportError:
    nx = None  # type: ignore[assignment]
    _NX = False

# ── Built-in world-model seed edges ──────────────────────────────────────────
_SEED_EDGES: List[Tuple[str, str, str]] = [
    # Languages
    ("Python",     "language",        "is_a"),
    ("JavaScript", "language",        "is_a"),
    ("Rust",       "language",        "is_a"),
    ("Go",         "language",        "is_a"),
    ("Java",       "language",        "is_a"),
    # Frameworks → language
    ("FastAPI",    "Python",          "uses_language"),
    ("Django",     "Python",          "uses_language"),
    ("Flask",      "Python",          "uses_language"),
    ("PyTorch",    "Python",          "uses_language"),
    ("React",      "JavaScript",      "uses_language"),
    ("Express",    "JavaScript",      "uses_language"),
    # Frameworks → architecture
    ("FastAPI",    "REST_API",        "implements"),
    ("Django",     "MVC",             "implements"),
    ("React",      "component_model", "implements"),
    ("Kafka",      "event_driven",    "implements"),
    ("Celery",     "task_queue",      "implements"),
    # Infrastructure
    ("Docker",     "containerization","implements"),
    ("Kubernetes", "container_orchestration", "implements"),
    ("Redis",      "caching",         "implements"),
    ("PostgreSQL", "relational_database", "is_a"),
    # ML
    ("Transformer","attention_mechanism", "uses"),
    ("Transformer","neural_network",   "is_a"),
    ("ResNet",     "convolutional_network", "is_a"),
    ("PyTorch",    "neural_network",   "trains"),
    # Architecture lineages
    ("REST_API",   "client_server_architecture", "is_part_of"),
    ("MVC",        "layered_architecture",        "is_a"),
    ("event_driven","message_passing",            "uses"),
]


class PatternGraphBuilder:
    """
    Global knowledge graph of software concepts, frameworks, and patterns.
    """

    def __init__(self) -> None:
        if _NX:
            self._g = nx.DiGraph()
        else:
            self._adj: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
            self._g = None

    # ── public API ────────────────────────────────────────────────────────────

    def seed_world_model(self) -> int:
        """Load the built-in world-model seed edges.  Returns number added."""
        for src, tgt, rel in _SEED_EDGES:
            self._add(src, tgt, rel)
        log.info("PatternGraphBuilder: seeded %d world-model edges", len(_SEED_EDGES))
        return len(_SEED_EDGES)

    def add_edge(self, source: str, target: str, relation: str = "related_to") -> None:
        self._add(source, target, relation)

    def add_repo_knowledge(self, repos: List[Dict[str, Any]]) -> int:
        """Add knowledge from EcosystemScanner records.  Returns edges added."""
        count = 0
        for repo in repos:
            name = repo.get("name", "").split("/")[-1]
            lang = repo.get("language", "")
            domain = repo.get("domain", "")
            if name and lang:
                self._add(name, lang, "uses_language")
                count += 1
            if name and domain:
                self._add(name, domain, "belongs_to_domain")
                count += 1
            for topic in repo.get("topics", []):
                self._add(name, topic, "tagged")
                count += 1
        return count

    def find_architectures_for(self, problem: str) -> List[str]:
        """
        Return architecture names relevant to the given problem description.

        Uses keyword matching against node names and their 1-hop neighbors.
        """
        keywords = set(problem.lower().replace("-", "_").split())
        arch_nodes = ["microservices", "event_driven", "actor_model", "layered",
                      "mvc", "rest_api", "cqrs", "hexagonal", "plugin", "serverless"]
        relevant: List[str] = []
        for arch in arch_nodes:
            arch_words = set(arch.lower().replace("_", " ").split())
            if arch_words & keywords:
                relevant.append(arch)
                continue
            # Check 1-hop neighbors for keyword matches
            for nbr_info in self._neighbors(arch):
                nbr = nbr_info["target"].lower().replace("_", " ")
                if set(nbr.split()) & keywords:
                    relevant.append(arch)
                    break
        return relevant or arch_nodes[:3]

    def find_frameworks_by_language(self, language: str) -> List[str]:
        """Return all framework nodes that 'use_language' the given language."""
        lang_lower = language.lower()
        result: List[str] = []
        for src, tgt, rel in self._all_edges():
            if rel == "uses_language" and tgt.lower() == lang_lower:
                result.append(src)
        return result

    def concept_path(self, source: str, target: str) -> List[str]:
        """Return shortest path between two concept nodes."""
        if _NX:
            try:
                return list(nx.shortest_path(self._g, source, target))
            except Exception:  # noqa: BLE001
                return []
        return self._bfs(source, target)

    def related_concepts(self, concept: str, depth: int = 2) -> List[str]:
        """Return concepts reachable within *depth* hops."""
        if _NX:
            try:
                reachable = nx.single_source_shortest_path_length(self._g, concept, cutoff=depth)
                return [n for n in reachable if n != concept]
            except Exception:  # noqa: BLE001
                return []
        return self._bfs_multi(concept, depth)

    def summary(self) -> Dict[str, int]:
        return {"nodes": len(self._all_nodes()), "edges": len(self._all_edges())}

    # ── internals ─────────────────────────────────────────────────────────────

    def _add(self, src: str, tgt: str, rel: str) -> None:
        if _NX:
            self._g.add_edge(src, tgt, relation=rel)
        else:
            entry = (tgt, rel)
            if entry not in self._adj[src]:
                self._adj[src].append(entry)

    def _neighbors(self, node: str) -> List[Dict[str, str]]:
        if _NX:
            return [
                {"target": t, "relation": self._g.get_edge_data(node, t).get("relation", "")}
                for t in self._g.successors(node)
            ]
        return [{"target": t, "relation": r} for t, r in self._adj.get(node, [])]

    def _all_nodes(self) -> List[str]:
        if _NX:
            return list(self._g.nodes())
        return list(self._adj.keys())

    def _all_edges(self) -> List[Tuple[str, str, str]]:
        if _NX:
            return [(u, v, d.get("relation", "")) for u, v, d in self._g.edges(data=True)]
        edges = []
        for src, targets in self._adj.items():
            for tgt, rel in targets:
                edges.append((src, tgt, rel))
        return edges

    def _bfs(self, source: str, target: str) -> List[str]:
        parents: Dict[str, Optional[str]] = {source: None}
        q: deque = deque([source])
        while q:
            node = q.popleft()
            if node == target:
                path: List[str] = []
                cur: Optional[str] = node
                while cur is not None:
                    path.append(cur)
                    cur = parents[cur]
                return list(reversed(path))
            for tgt, _ in self._adj.get(node, []):
                if tgt not in parents:
                    parents[tgt] = node
                    q.append(tgt)
        return []

    def _bfs_multi(self, start: str, depth: int) -> List[str]:
        visited: Set[str] = {start}
        q: deque = deque([(start, 0)])
        while q:
            node, dist = q.popleft()
            if dist >= depth:
                continue
            for tgt, _ in self._adj.get(node, []):
                if tgt not in visited:
                    visited.add(tgt)
                    q.append((tgt, dist + 1))
        visited.discard(start)
        return list(visited)


if __name__ == "__main__":
    print('Running pattern_graph_builder.py')
