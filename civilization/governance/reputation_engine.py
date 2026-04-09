"""ReputationEngine — tracks and ranks agent reputations.

Usage example::

    rep = ReputationEngine()
    rep.record_action("agent-1", success=True, score=1.0)
    rating = rep.get_reputation("agent-1")
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List

log = logging.getLogger("ReputationEngine")

_INITIAL_REP = 0.5
_DECAY = 0.99


class ReputationEngine:
    """Maintains exponentially-smoothed reputation scores for agents."""

    def __init__(self) -> None:
        self._reputation: Dict[str, float] = defaultdict(lambda: _INITIAL_REP)
        self._action_counts: Dict[str, int] = defaultdict(int)

    # ── public API ──

    def record_action(
        self,
        agent_id: str,
        success: bool,
        score: float = 1.0,
    ) -> None:
        """Update *agent_id* reputation based on action outcome."""
        self._action_counts[agent_id] += 1
        current = self._reputation[agent_id]
        delta = score * 0.1 if success else -0.05
        self._reputation[agent_id] = max(0.0, min(1.0, current * _DECAY + delta))
        log.debug("ReputationEngine: %s rep → %.4f", agent_id, self._reputation[agent_id])

    def get_reputation(self, agent_id: str) -> float:
        """Return reputation score (0.0–1.0) for *agent_id*."""
        return round(self._reputation[agent_id], 4)

    def top_agents(self, n: int = 10) -> List[Dict[str, Any]]:
        """Return top-*n* agents by reputation."""
        sorted_agents = sorted(self._reputation.items(), key=lambda x: x[1], reverse=True)
        return [
            {"agent_id": aid, "reputation": round(rep, 4), "actions": self._action_counts[aid]}
            for aid, rep in sorted_agents[:n]
        ]

    def penalize(self, agent_id: str, amount: float = 0.1) -> None:
        """Reduce *agent_id* reputation by *amount*."""
        self._reputation[agent_id] = max(0.0, self._reputation[agent_id] - amount)
        log.warning("ReputationEngine: penalised %s by %.2f", agent_id, amount)


if __name__ == "__main__":
    print('Running reputation_engine.py')
