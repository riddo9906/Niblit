"""CompetitionEngine — runs multi-agent competitions on challenges.

Usage example::

    engine = CompetitionEngine()
    results = engine.run(["agent-1", "agent-2"], {"title": "Adder"})
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Tuple

log = logging.getLogger("CompetitionEngine")

_MOCK_SOLUTIONS: Dict[str, str] = {
    "researcher": "def solve(x): return x * 2",
    "builder": "class Solver:\n    def run(self): return True",
    "planner": "# Plan: analyse → implement → test\ndef plan(): pass",
    "analyst": "def analyse(data): return sum(data)/len(data)",
    "default": "def solution(): pass",
}


class CompetitionEngine:
    """Orchestrates multi-agent competitions."""

    def __init__(self) -> None:
        self._results: List[Dict[str, Any]] = []

    # ── public API ──

    def run(
        self, agents: List[Any], challenge: Dict[str, Any]
    ) -> List[Tuple[str, float]]:
        """Run all *agents* against *challenge*; return [(agent_id, score)]."""
        results: List[Tuple[str, float]] = []
        for agent in agents:
            agent_id = agent if isinstance(agent, str) else (
                agent.get("agent_id", str(agent)) if isinstance(agent, dict)
                else getattr(agent, "agent_id", getattr(agent, "_agent_id", str(agent)))
            )
            solution = _MOCK_SOLUTIONS.get(agent_id, _MOCK_SOLUTIONS["default"])
            score = self.evaluate_solution(solution, challenge)
            results.append((agent_id, score))
            log.debug("CompetitionEngine: %s score=%.4f", agent_id, score)
        self._results.append({"challenge": challenge, "results": results, "run_at": time.time()})
        return sorted(results, key=lambda x: x[1], reverse=True)

    def evaluate_solution(self, solution: str, challenge: Dict[str, Any]) -> float:
        """Score a single *solution* for *challenge*."""
        base = 0.5 if solution.strip() else 0.0
        base += 0.2 if "def " in solution else 0.0
        base += 0.1 if "return" in solution else 0.0
        return min(1.0, round(base, 4))

    def get_results(self) -> List[Dict[str, Any]]:
        """Return all past competition results."""
        return list(self._results)


if __name__ == "__main__":
    print('Running competition_engine.py')
