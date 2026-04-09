"""ChallengeGenerator — produces coding challenges for arena competitions.

Usage example::

    gen = ChallengeGenerator()
    challenge = gen.generate(difficulty="hard")
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional

log = logging.getLogger("ChallengeGenerator")

_CHALLENGES: List[Dict[str, Any]] = [
    {
        "id": "c001",
        "title": "Fibonacci Optimiser",
        "description": "Implement an O(log n) Fibonacci function.",
        "difficulty": "medium",
        "constraints": ["No recursion", "Must handle n up to 10^6"],
    },
    {
        "id": "c002",
        "title": "Graph Shortest Path",
        "description": "Find the shortest path in a weighted directed graph.",
        "difficulty": "hard",
        "constraints": ["Dijkstra algorithm", "Handle disconnected graphs"],
    },
    {
        "id": "c003",
        "title": "Hello World",
        "description": "Print 'Hello, World!' to stdout.",
        "difficulty": "easy",
        "constraints": ["Single function", "No imports"],
    },
]


class ChallengeGenerator:
    """Generates and stores coding challenges."""

    def __init__(self) -> None:
        self._challenges: Dict[str, Dict[str, Any]] = {c["id"]: c for c in _CHALLENGES}

    # ── public API ──

    def generate(self, difficulty: str = "medium") -> Dict[str, Any]:
        """Return a challenge matching *difficulty* (or create a generic one)."""
        matches = [c for c in self._challenges.values() if c.get("difficulty") == difficulty]
        if matches:
            return dict(matches[0])
        challenge_id = str(uuid.uuid4())[:8]
        new_challenge: Dict[str, Any] = {
            "id": challenge_id,
            "title": f"Challenge {challenge_id}",
            "description": f"Solve a {difficulty} algorithmic problem.",
            "difficulty": difficulty,
            "constraints": ["Pure Python", "Must pass unit tests"],
        }
        self._challenges[challenge_id] = new_challenge
        log.info("ChallengeGenerator: generated %s challenge %s", difficulty, challenge_id)
        return dict(new_challenge)

    def list_challenges(self) -> List[Dict[str, Any]]:
        """Return all available challenges."""
        return list(self._challenges.values())

    def get_challenge(self, challenge_id: str) -> Optional[Dict[str, Any]]:
        """Return challenge by *challenge_id* or None."""
        return self._challenges.get(challenge_id)


if __name__ == "__main__":
    print('Running challenge_generator.py')
