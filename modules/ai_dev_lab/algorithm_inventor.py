#!/usr/bin/env python3
"""
modules/ai_dev_lab/algorithm_inventor.py

Generate new algorithms by combining known algorithmic patterns.

Input:
    - knowledge graph (optional)
    - algorithm library (built-in catalogue)
    - problem definition

Example outputs:
    - hybrid attention search algorithm
    - neural symbolic planner
    - adaptive gradient routing

Usage::

    from modules.ai_dev_lab.algorithm_inventor import AlgorithmInventor
    inventor = AlgorithmInventor()
    algo = inventor.invent("improve memory search performance")
    combined = inventor.combine(["binary_search", "attention"])
"""

import logging
import random
from typing import Any, Dict, List, Optional

log = logging.getLogger("AlgorithmInventor")

# ── Built-in algorithm library ────────────────────────────────────────────────
_ALGORITHMS: Dict[str, Dict[str, Any]] = {
    "binary_search":    {"type": "search",    "complexity": "O(log n)", "pattern": "divide_conquer"},
    "bfs":              {"type": "graph",     "complexity": "O(V+E)",   "pattern": "breadth_first"},
    "dfs":              {"type": "graph",     "complexity": "O(V+E)",   "pattern": "depth_first"},
    "attention":        {"type": "neural",    "complexity": "O(n²d)",   "pattern": "weighted_sum"},
    "gradient_descent": {"type": "optimise",  "complexity": "O(n·k)",   "pattern": "iterative_improvement"},
    "dynamic_programming": {"type": "optimise", "complexity": "O(n²)", "pattern": "memoisation"},
    "beam_search":      {"type": "search",    "complexity": "O(b^d)",   "pattern": "heuristic_search"},
    "a_star":           {"type": "search",    "complexity": "O(E log V)","pattern": "informed_search"},
    "kmeans":           {"type": "cluster",   "complexity": "O(n·k·i)", "pattern": "centroid_clustering"},
    "pagerank":         {"type": "graph",     "complexity": "O(V+E)",   "pattern": "eigenvector"},
    "lru_cache":        {"type": "cache",     "complexity": "O(1)",     "pattern": "eviction_policy"},
    "consistent_hash":  {"type": "distribute","complexity": "O(log n)", "pattern": "ring_hash"},
    "raft_consensus":   {"type": "distribute","complexity": "O(n log n)","pattern": "leader_election"},
    "bloom_filter":     {"type": "probab",    "complexity": "O(k)",     "pattern": "approximate_member"},
    "kd_tree":          {"type": "search",    "complexity": "O(log n)", "pattern": "spatial_index"},
}

# ── Combination heuristics ────────────────────────────────────────────────────
_HYBRID_TEMPLATES: List[str] = [
    "Hybrid {a}+{b}: apply {a} for initial {domain} estimation, then refine with {b}",
    "Adaptive {a}: use {b} to dynamically tune {a} parameters for {domain}",
    "Neural-symbolic {domain}: {a} for pattern recognition combined with {b} for logical inference",
    "{a}-guided {b}: replace random initialisation in {b} with {a}-derived priors for {domain}",
    "Cascaded {a}→{b}: first-pass {a} filter reduces search space before {b} for {domain}",
]


class AlgorithmInventor:
    """
    Invent and combine algorithms for SEADL experiments.
    """

    def __init__(
        self,
        graph: Optional[Any] = None,
        seed: Optional[int] = None,
    ) -> None:
        self._graph = graph
        self._rng = random.Random(seed)

    # ── public API ────────────────────────────────────────────────────────────

    def invent(self, problem: str) -> Dict[str, Any]:
        """
        Generate a new algorithm tailored to the given problem.

        Returns dict with keys:
            name, description, components, complexity, novelty_score
        """
        related = self._retrieve_related_algorithms(problem)
        return self.combine(related, problem=problem)

    def combine(
        self,
        algorithm_names: List[str],
        problem: str = "",
    ) -> Dict[str, Any]:
        """
        Combine two or more algorithms into a novel hybrid.

        Returns dict with keys:
            name, description, components, complexity, novelty_score
        """
        valid = [a for a in algorithm_names if a in _ALGORITHMS]
        if len(valid) < 2:
            # Fallback: pick two random algorithms
            valid = self._rng.sample(list(_ALGORITHMS.keys()), min(2, len(_ALGORITHMS)))

        a, b = valid[0], valid[1]
        domain = self._extract_domain(problem) if problem else "general"
        template = self._rng.choice(_HYBRID_TEMPLATES)
        description = template.format(a=a, b=b, domain=domain)

        # Estimate combined complexity (heuristic: pick the worse one)
        def _order(name: str) -> int:
            c = _ALGORITHMS.get(name, {}).get("complexity", "O(n)")
            if "n²" in c or "n^2" in c:
                return 3
            if "log" in c:
                return 1
            return 2

        complexity_label = (
            _ALGORITHMS[a]["complexity"]
            if _order(a) >= _order(b)
            else _ALGORITHMS[b]["complexity"]
        )

        novelty = round(self._rng.uniform(0.4, 0.95), 3)

        return {
            "name": f"hybrid_{a}_{b}",
            "description": description,
            "components": valid,
            "complexity": complexity_label,
            "novelty_score": novelty,
            "problem": problem,
        }

    def list_algorithms(self) -> List[str]:
        """Return all available algorithm names."""
        return sorted(_ALGORITHMS.keys())

    def get_algorithm(self, name: str) -> Optional[Dict[str, Any]]:
        """Return metadata for a named algorithm."""
        return dict(_ALGORITHMS[name]) if name in _ALGORITHMS else None

    def algorithms_by_type(self, algo_type: str) -> List[str]:
        """Return algorithms of a given type (search, neural, graph, etc.)."""
        return [k for k, v in _ALGORITHMS.items() if v.get("type") == algo_type]

    # ── internals ─────────────────────────────────────────────────────────────

    def _retrieve_related_algorithms(self, problem: str) -> List[str]:
        """Select algorithms relevant to the problem description."""
        problem_lower = problem.lower()
        related: List[str] = []

        type_keywords = {
            "search":    ["search", "find", "lookup", "retrieval"],
            "graph":     ["graph", "network", "path", "traverse"],
            "neural":    ["neural", "learn", "train", "predict", "attention"],
            "optimise":  ["optimise", "optimize", "improve", "tune"],
            "cluster":   ["cluster", "group", "segment"],
            "cache":     ["cache", "memory", "store"],
            "distribute":["distribute", "scale", "parallel", "consensus"],
        }

        for algo_type, keywords in type_keywords.items():
            if any(kw in problem_lower for kw in keywords):
                related.extend(self.algorithms_by_type(algo_type))

        if not related:
            related = self._rng.sample(list(_ALGORITHMS.keys()), 3)

        return related[:4]

    @staticmethod
    def _extract_domain(problem: str) -> str:
        """Extract a short domain label from the problem description."""
        keywords = [
            "search", "memory", "planning", "generation", "classification",
            "retrieval", "scheduling", "optimisation", "clustering",
        ]
        lower = problem.lower()
        for kw in keywords:
            if kw in lower:
                return kw
        return "computation"
