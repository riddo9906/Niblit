"""MutationEngine — applies random mutations to agent parameter dicts.

Usage example::

    engine = MutationEngine()
    mutated = engine.mutate({"lr": 0.01, "layers": 3}, mutation_rate=0.1)
"""

from __future__ import annotations

import logging
import random
from typing import Any, Dict, List

log = logging.getLogger("MutationEngine")


class MutationEngine:
    """Applies configurable random mutations to agent parameter dicts."""

    def __init__(self, seed: int = 42) -> None:
        self._rng = random.Random(seed)
        self._history: List[Dict[str, Any]] = []

    # ── public API ──

    def mutate(
        self, agent_params: Dict[str, Any], mutation_rate: float = 0.1
    ) -> Dict[str, Any]:
        """Return mutated copy of *agent_params*."""
        mutated = dict(agent_params)
        for key, val in agent_params.items():
            if self._rng.random() < mutation_rate:
                if isinstance(val, float):
                    mutated[key] = round(val * self._rng.uniform(0.8, 1.2), 6)
                elif isinstance(val, int):
                    mutated[key] = max(1, val + self._rng.randint(-1, 1))
                elif isinstance(val, bool):
                    mutated[key] = not val
        record = {"original": agent_params, "mutated": mutated, "rate": mutation_rate}
        self._history.append(record)
        log.debug("MutationEngine: mutated %d keys", len(agent_params))
        return mutated

    def batch_mutate(
        self, population: List[Dict[str, Any]], rate: float = 0.1
    ) -> List[Dict[str, Any]]:
        """Mutate each member of *population*."""
        return [self.mutate(p, rate) for p in population]

    def get_mutation_history(self) -> List[Dict[str, Any]]:
        """Return all past mutation records."""
        return list(self._history)
