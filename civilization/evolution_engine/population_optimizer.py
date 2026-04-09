"""PopulationOptimizer — generational population optimization loop.

Usage example::

    optimizer = PopulationOptimizer()
    result = optimizer.optimize(population, lambda a: a.get("fitness", 0.5), generations=5)
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List

from .mutation_engine import MutationEngine
from .selection_engine import SelectionEngine

log = logging.getLogger("PopulationOptimizer")


class PopulationOptimizer:
    """Runs generational evolution to optimise agent populations."""

    def __init__(self) -> None:
        self._mutator = MutationEngine()
        self._selector = SelectionEngine()

    # ── public API ──

    def optimize(
        self,
        population: List[Dict[str, Any]],
        fitness_fn: Callable[[Dict[str, Any]], float],
        generations: int = 10,
    ) -> Dict[str, Any]:
        """Run *generations* of evolution; return best agent and history."""
        current = list(population)
        history: List[Dict[str, Any]] = []
        best = None
        best_fitness = -1.0
        for gen in range(generations):
            current = self.step(current, fitness_fn)
            scores = {a.get("agent_id", str(i)): fitness_fn(a) for i, a in enumerate(current)}
            gen_best_id = max(scores, key=lambda k: scores[k])
            gen_best_score = scores[gen_best_id]
            history.append({"generation": gen + 1, "best_fitness": gen_best_score})
            if gen_best_score > best_fitness:
                best_fitness = gen_best_score
                best = next((a for a in current if a.get("agent_id") == gen_best_id), current[0])
            log.debug("PopulationOptimizer: gen %d best=%.4f", gen + 1, gen_best_score)
        return {"best_agent": best, "best_fitness": best_fitness, "history": history}

    def step(
        self,
        population: List[Dict[str, Any]],
        fitness_fn: Callable[[Dict[str, Any]], float],
    ) -> List[Dict[str, Any]]:
        """Execute one evolution step: select + mutate."""
        scores = {a.get("agent_id", str(i)): fitness_fn(a) for i, a in enumerate(population)}
        elite = self._selector.elite_select(population, scores, n=max(1, len(population) // 2))
        offspring = self._mutator.batch_mutate(elite, rate=0.15)
        return elite + offspring


if __name__ == "__main__":
    print('Running population_optimizer.py')
