"""SelectionEngine — fitness-based agent selection strategies.

Usage example::

    engine = SelectionEngine()
    selected = engine.elite_select(population, {"a1": 0.9, "a2": 0.5}, n=1)
"""

from __future__ import annotations

import logging
import random
from typing import Any, Dict, List

log = logging.getLogger("SelectionEngine")


class SelectionEngine:
    """Implements tournament and elite selection strategies."""

    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)

    # ── public API ──

    def select(
        self,
        population: List[Dict[str, Any]],
        fitness_scores: Dict[str, float],
        n: int = 10,
    ) -> List[Dict[str, Any]]:
        """Select top-*n* agents by fitness score."""
        return self.elite_select(population, fitness_scores, n=n)

    def tournament_select(
        self,
        population: List[Dict[str, Any]],
        fitness_scores: Dict[str, float],
        k: int = 3,
    ) -> Dict[str, Any]:
        """Select best of *k* random agents."""
        if not population:
            return {}
        contestants = self._rng.sample(population, min(k, len(population)))
        return max(contestants, key=lambda a: fitness_scores.get(a.get("agent_id", ""), 0.0))

    def elite_select(
        self,
        population: List[Dict[str, Any]],
        fitness_scores: Dict[str, float],
        n: int = 5,
    ) -> List[Dict[str, Any]]:
        """Return the top-*n* fittest agents."""
        sorted_pop = sorted(
            population,
            key=lambda a: fitness_scores.get(a.get("agent_id", ""), 0.0),
            reverse=True,
        )
        return sorted_pop[:n]


if __name__ == "__main__":
    print('Running selection_engine.py')
