"""ServiceRegistry — capability-based agent service discovery.

Usage example::

    reg = ServiceRegistry()
    reg.register("planner-svc", "agent-1", ["plan", "decompose"])
    agents = reg.find("plan")
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

log = logging.getLogger("CollabServiceRegistry")


class ServiceRegistry:
    """Maps service names and capabilities to agent IDs."""

    def __init__(self) -> None:
        self._services: Dict[str, Dict[str, Any]] = {}

    # ── public API ──

    def register(
        self, service_name: str, agent_id: str, capabilities: List[str]
    ) -> None:
        """Register *agent_id* under *service_name* with *capabilities*."""
        self._services[service_name] = {
            "agent_id": agent_id,
            "capabilities": capabilities,
        }
        log.info("CollabServiceRegistry: registered %s → %s", service_name, agent_id)

    def deregister(self, service_name: str) -> None:
        """Remove *service_name* from registry."""
        self._services.pop(service_name, None)

    def find(self, capability: str) -> List[str]:
        """Return agent_ids that support *capability*."""
        return [
            str(v["agent_id"])
            for v in self._services.values()
            if capability in v.get("capabilities", [])
        ]

    def list_all(self) -> Dict[str, Any]:
        """Return full registry dict."""
        return dict(self._services)
