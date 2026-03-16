"""PopulationManager — spawns and despawns agents in the civilization.

Usage example::

    pm = PopulationManager()
    ids = pm.spawn("researcher", count=3)
    print(pm.agent_count())
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

log = logging.getLogger("PopulationManager")


class PopulationManager:
    """Manages the active agent population."""

    def __init__(self) -> None:
        self._agents: Dict[str, Dict[str, Any]] = {}

    # ── public API ──

    def spawn(self, role: str, count: int = 1) -> List[str]:
        """Create *count* agents of *role*; return their agent_ids."""
        ids = []
        for _ in range(count):
            agent_id = str(uuid.uuid4())
            self._agents[agent_id] = {
                "agent_id": agent_id,
                "role": role,
                "status": "active",
                "spawned_at": time.time(),
            }
            ids.append(agent_id)
        log.info("PopulationManager: spawned %d %s agent(s)", count, role)
        return ids

    def despawn(self, agent_id: str) -> None:
        """Remove *agent_id* from the population."""
        self._agents.pop(agent_id, None)
        log.info("PopulationManager: despawned %s", agent_id)

    def get_agents(self, role: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return agents, optionally filtered by *role*."""
        agents = list(self._agents.values())
        if role is not None:
            agents = [a for a in agents if a["role"] == role]
        return agents

    def get_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Return agent metadata or None."""
        return self._agents.get(agent_id)

    def agent_count(self) -> int:
        """Return total active agent count."""
        return len(self._agents)
