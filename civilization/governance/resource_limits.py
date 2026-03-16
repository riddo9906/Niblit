"""ResourceLimits — enforces resource quotas for civilisation agents.

Usage example::

    limits = ResourceLimits()
    limits.set_limit("memory_mb", 512)
    ok = limits.check("memory_mb", 256)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, List

log = logging.getLogger("ResourceLimits")


class ResourceLimits:
    """Tracks and enforces resource quotas."""

    def __init__(self) -> None:
        self._limits: Dict[str, float] = {}
        self._usage: Dict[str, List[float]] = defaultdict(list)

    # ── public API ──

    def set_limit(self, resource_type: str, max_value: float) -> None:
        """Set maximum allowed *max_value* for *resource_type*."""
        self._limits[resource_type] = max_value
        log.info("ResourceLimits: %s limit → %.2f", resource_type, max_value)

    def check(self, resource_type: str, requested: float) -> bool:
        """Return True if *requested* is within the limit for *resource_type*."""
        limit = self._limits.get(resource_type)
        if limit is None:
            return True
        return requested <= limit

    def get_limits(self) -> Dict[str, Any]:
        """Return all configured limits."""
        return dict(self._limits)

    def record_usage(self, resource_type: str, used: float) -> None:
        """Record actual resource usage."""
        self._usage[resource_type].append(used)
        log.debug("ResourceLimits: %s used=%.2f", resource_type, used)
