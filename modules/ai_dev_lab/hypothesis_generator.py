#!/usr/bin/env python3
"""
modules/ai_dev_lab/hypothesis_generator.py

Generate research hypotheses automatically from the knowledge graph,
performance gaps, and emerging technology signals.

Example hypotheses:
    "Graph neural networks could improve dependency resolution"
    "Actor architectures may improve autonomous agent coordination"
    "Hybrid symbolic + neural reasoning could improve planning accuracy"

Usage::

    from modules.ai_dev_lab.hypothesis_generator import HypothesisGenerator
    gen = HypothesisGenerator()
    hypothesis = gen.generate()
    hypotheses = gen.generate_batch(5)
"""

import logging
import random
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("HypothesisGenerator")

# ── Seed hypothesis templates ─────────────────────────────────────────────────
# Each template has placeholders for {tech_a} and {tech_b}.
_TEMPLATES: List[str] = [
    "{tech_a} could improve {domain} by applying {tech_b} patterns",
    "Combining {tech_a} with {tech_b} may enhance {domain} performance",
    "Replacing {domain} components with {tech_a} could reduce latency",
    "{tech_b} architecture may improve scalability of {domain} subsystems",
    "Hybrid {tech_a}+{tech_b} approach could optimise {domain} accuracy",
    "Applying {tech_a} design patterns to {domain} may improve maintainability",
    "{tech_a} could enable autonomous {domain} optimisation",
    "Using {tech_b} for {domain} state management could reduce complexity",
]

_TECHNOLOGIES: List[str] = [
    "graph neural network", "actor model", "transformer", "attention mechanism",
    "vector database", "knowledge graph", "reinforcement learning",
    "symbolic reasoning", "event-driven architecture", "CQRS", "FAISS",
    "embedding pipeline", "dependency injection", "plugin architecture",
]

_DOMAINS: List[str] = [
    "code generation", "autonomous planning", "memory management",
    "knowledge retrieval", "task scheduling", "error correction",
    "dependency resolution", "architecture analysis", "pattern recognition",
    "self-evolution", "benchmark evaluation",
]


class HypothesisGenerator:
    """
    Generate research hypotheses from knowledge graph patterns and templates.

    Args:
        graph:  Optional PatternGraphBuilder — used to find emerging patterns.
        seed:   Random seed for reproducibility.
    """

    def __init__(
        self,
        graph: Optional[Any] = None,
        seed: Optional[int] = None,
    ) -> None:
        self._graph = graph
        self._rng = random.Random(seed)

    # ── public API ────────────────────────────────────────────────────────────

    def generate(self, domain_hint: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate a single research hypothesis.

        Returns dict with keys: hypothesis, tech_a, tech_b, domain, timestamp.
        """
        tech_a = self._rng.choice(_TECHNOLOGIES)
        tech_b = self._rng.choice([t for t in _TECHNOLOGIES if t != tech_a])
        domain = domain_hint or self._rng.choice(_DOMAINS)
        template = self._rng.choice(_TEMPLATES)

        text = template.format(tech_a=tech_a, tech_b=tech_b, domain=domain)

        # Enrich with graph-related concepts if available
        if self._graph is not None:
            try:
                related = self._graph.related_concepts(tech_a, depth=1)
                if related:
                    extra = self._rng.choice(related)
                    text += f" (leveraging {extra})"
            except Exception:  # noqa: BLE001
                pass

        return {
            "hypothesis": text,
            "tech_a": tech_a,
            "tech_b": tech_b,
            "domain": domain,
            "timestamp": time.time(),
        }

    def generate_batch(
        self, n: int = 5, domain_hint: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Generate *n* distinct hypotheses."""
        seen: set = set()
        results: List[Dict[str, Any]] = []
        attempts = 0
        while len(results) < n and attempts < n * 4:
            h = self.generate(domain_hint=domain_hint)
            if h["hypothesis"] not in seen:
                seen.add(h["hypothesis"])
                results.append(h)
            attempts += 1
        return results

    def generate_from_weakness(self, weakness_description: str) -> Dict[str, Any]:
        """
        Generate a targeted hypothesis from a detected system weakness.

        The weakness description is used to select a relevant domain.
        """
        desc_lower = weakness_description.lower()
        domain = "code generation"  # default
        for d in _DOMAINS:
            if any(word in desc_lower for word in d.split()):
                domain = d
                break
        return self.generate(domain_hint=domain)
