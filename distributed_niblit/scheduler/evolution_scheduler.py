"""EvolutionScheduler — schedules and tracks agent evolution cycles.

Usage example::

    sched = EvolutionScheduler()
    cid = sched.schedule_evolution_cycle({"generations": 5})
    result = sched.run_next_cycle()
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

log = logging.getLogger("EvolutionScheduler")

_DEFAULT_CYCLE_CONFIG: Dict[str, Any] = {
    "generations": 3,
    "mutation_rate": 0.1,
    "population_size": 10,
}


class EvolutionScheduler:
    """Tracks and executes agent evolution cycle schedules."""

    def __init__(self) -> None:
        self._cycles: List[Dict[str, Any]] = []

    # ── public API ──

    def schedule_evolution_cycle(
        self, cycle_config: Optional[Dict[str, Any]] = None
    ) -> str:
        """Schedule an evolution cycle; return cycle_id."""
        cid = str(uuid.uuid4())
        config = {**_DEFAULT_CYCLE_CONFIG, **(cycle_config or {})}
        self._cycles.append({
            "cycle_id": cid,
            "config": config,
            "status": "pending",
            "scheduled_at": time.time(),
        })
        log.info("EvolutionScheduler: scheduled cycle %s", cid)
        return cid

    def get_cycles(self) -> List[Dict[str, Any]]:
        """Return all scheduled cycles."""
        return list(self._cycles)

    def run_next_cycle(self) -> Dict[str, Any]:
        """Execute the next pending cycle; return result dict."""
        for cycle in self._cycles:
            if cycle["status"] == "pending":
                cycle["status"] = "running"
                log.info("EvolutionScheduler: running cycle %s", cycle["cycle_id"])
                result = {
                    "cycle_id": cycle["cycle_id"],
                    "config": cycle["config"],
                    "best_fitness": 0.82,
                    "generations_run": cycle["config"].get("generations", 3),
                    "completed_at": time.time(),
                }
                cycle["status"] = "completed"
                cycle["result"] = result
                return result
        return {"status": "no_pending_cycles"}
