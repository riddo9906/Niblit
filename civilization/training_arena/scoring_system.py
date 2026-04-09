"""ScoringSystem — scores and ranks agent solutions for arena competitions.

Usage example::

    scoring = ScoringSystem()
    score = scoring.score("def add(a,b): return a+b", {"title": "Adder"})
    scoring.update_leaderboard("agent-1", score)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

log = logging.getLogger("ScoringSystem")


class ScoringSystem:
    """Evaluates solution quality and maintains a leaderboard."""

    def __init__(self) -> None:
        self._leaderboard: Dict[str, float] = {}

    # ── public API ──

    def score(self, solution: str, challenge: Dict[str, Any]) -> float:
        """Return 0.0–1.0 quality score for *solution*."""
        if not solution.strip():
            return 0.0
        base = 0.4
        if "def " in solution:
            base += 0.2
        if "return" in solution:
            base += 0.15
        if len(solution) > 20:
            base += 0.1
        difficulty = challenge.get("difficulty", "medium")
        multiplier = {"easy": 0.8, "medium": 1.0, "hard": 1.2}.get(difficulty, 1.0)
        return min(1.0, round(base * multiplier, 4))

    def rank(self, scores: List[Tuple[str, float]]) -> List[Tuple[str, int]]:
        """Return list of (agent_id, rank) sorted best-first."""
        sorted_scores = sorted(scores, key=lambda x: x[1], reverse=True)
        return [(agent_id, rank + 1) for rank, (agent_id, _) in enumerate(sorted_scores)]

    def update_leaderboard(self, agent_id: str, score: float) -> None:
        """Update *agent_id* score if *score* is higher than current."""
        current = self._leaderboard.get(agent_id, 0.0)
        self._leaderboard[agent_id] = max(current, score)
        log.debug("ScoringSystem: %s score → %.4f", agent_id, self._leaderboard[agent_id])

    def get_leaderboard(self) -> List[Dict[str, Any]]:
        """Return sorted leaderboard as list of dicts."""
        entries = sorted(self._leaderboard.items(), key=lambda x: x[1], reverse=True)
        return [{"agent_id": aid, "score": s, "rank": i + 1} for i, (aid, s) in enumerate(entries)]


if __name__ == "__main__":
    print('Running scoring_system.py')
