"""ServiceRegistry — lightweight service discovery for distributed Niblit.

Tracks service endpoints and provides health-check stubs.

Usage example::

    reg = ServiceRegistry()
    reg.register("planner", {"host": "localhost", "port": 8081})
    ep = reg.lookup("planner")
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("ServiceRegistry")


class ServiceRegistry:
    """In-process service registry.

    Args:
        ttl: Time-to-live for each registration in seconds (0 = forever).
    """

    def __init__(self, ttl: float = 0) -> None:
        self._ttl = ttl
        self._services: Dict[str, Dict[str, Any]] = {}

    # ── public API ──

    def register(self, service_name: str, endpoint: Dict[str, Any]) -> None:
        """Register *service_name* with its *endpoint* metadata."""
        self._services[service_name] = {
            "endpoint": endpoint,
            "registered_at": time.time(),
            "healthy": True,
        }
        log.info("ServiceRegistry: registered %s", service_name)

    def deregister(self, service_name: str) -> None:
        """Remove *service_name* from the registry."""
        self._services.pop(service_name, None)
        log.info("ServiceRegistry: deregistered %s", service_name)

    def lookup(self, service_name: str) -> Optional[Dict[str, Any]]:
        """Return endpoint dict for *service_name* or None if absent."""
        entry = self._services.get(service_name)
        if entry is None:
            return None
        if self._ttl > 0 and time.time() - entry["registered_at"] > self._ttl:
            log.warning("ServiceRegistry: entry for %s has expired", service_name)
            return None
        return entry["endpoint"]

    def list_services(self) -> List[str]:
        """Return names of all registered services."""
        return list(self._services.keys())

    def health_check(self, service_name: str) -> bool:
        """Return health status of *service_name* (simulated)."""
        entry = self._services.get(service_name)
        if entry is None:
            return False
        return bool(entry.get("healthy", False))
