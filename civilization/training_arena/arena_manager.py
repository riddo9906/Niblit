"""ArenaManager — manages multiple training arenas for agent competitions.

Usage example::

    manager = ArenaManager()
    manager.create_arena("arena-1")
    results = manager.run_challenge("arena-1", ["agent-1"], {"title": "Test"})
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from .competition_engine import CompetitionEngine
from .scoring_system import ScoringSystem

log = logging.getLogger("ArenaManager")


class ArenaManager:
    """Creates arenas and orchestrates agent challenges."""

    def __init__(self) -> None:
        self._arenas: Dict[str, Dict[str, Any]] = {}
        self._scoring = ScoringSystem()
        self._engine = CompetitionEngine()

    # ── public API ──

    def create_arena(
        self, arena_id: str, config: Optional[Dict[str, Any]] = None
    ) -> None:
        """Create or overwrite *arena_id* with *config*."""
        self._arenas[arena_id] = {"arena_id": arena_id, "config": config or {}, "leaderboard": []}
        log.info("ArenaManager: created arena %s", arena_id)

    def list_arenas(self) -> List[str]:
        """Return names of all arenas."""
        return list(self._arenas.keys())

    def run_challenge(
        self,
        arena_id: str,
        agents: List[Any],
        challenge: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run *challenge* with *agents* in *arena_id*."""
        if arena_id not in self._arenas:
            self.create_arena(arena_id)
        raw_results = self._engine.run(agents, challenge)
        for agent_id, score in raw_results:
            self._scoring.update_leaderboard(agent_id, score)
        return {"arena_id": arena_id, "challenge": challenge, "results": raw_results}

    def get_leaderboard(self, arena_id: str) -> List[Dict[str, Any]]:
        """Return global leaderboard (shared across all arenas)."""
        return self._scoring.get_leaderboard()
