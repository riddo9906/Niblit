"""WorkloadBalancer — distributes tasks across available nodes.

Usage example::

    balancer = WorkloadBalancer()
    balancer.report_load("node-1", 0.3)
    balancer.report_load("node-2", 0.7)
    chosen = balancer.get_least_loaded()
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("WorkloadBalancer")


class WorkloadBalancer:
    """Balances tasks across nodes using configurable strategies."""

    def __init__(self) -> None:
        self._loads: Dict[str, float] = {}
        self._rr_index: int = 0

    # ── public API ──

    def select_node(
        self, available_nodes: List[Any], strategy: str = "round_robin"
    ) -> str:
        """Select a node from *available_nodes* using *strategy*."""
        if not available_nodes:
            log.warning("WorkloadBalancer: no available nodes")
            return ""
        node_ids = [
            n["node_id"] if isinstance(n, dict) else str(n)
            for n in available_nodes
        ]
        if strategy == "least_loaded":
            return self._least_loaded_from(node_ids)
        # default: round_robin
        chosen = node_ids[self._rr_index % len(node_ids)]
        self._rr_index += 1
        log.debug("WorkloadBalancer: round_robin selected %s", chosen)
        return chosen

    def report_load(self, node_id: str, load_pct: float) -> None:
        """Record current load percentage (0.0–1.0) for *node_id*."""
        self._loads[node_id] = max(0.0, min(1.0, load_pct))
        log.debug("WorkloadBalancer: %s load=%.2f", node_id, self._loads[node_id])

    def get_least_loaded(self) -> Optional[str]:
        """Return node_id with lowest reported load, or None if empty."""
        if not self._loads:
            return None
        return min(self._loads, key=lambda k: self._loads[k])

    # ── internals ──

    def _least_loaded_from(self, node_ids: List[str]) -> str:
        known = {n: self._loads.get(n, 0.0) for n in node_ids}
        return min(known, key=lambda k: known[k])
