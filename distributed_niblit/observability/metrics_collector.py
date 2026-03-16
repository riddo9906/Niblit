"""MetricsCollector — time-series metric collection for cluster observability.

Usage example::

    metrics = MetricsCollector()
    metrics.record("cpu_usage", 0.45, tags={"node": "n1"})
    agg = metrics.aggregate("cpu_usage")
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

log = logging.getLogger("MetricsCollector")


class MetricsCollector:
    """Records and aggregates named metrics."""

    def __init__(self) -> None:
        self._data: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    # ── public API ──

    def record(
        self,
        metric_name: str,
        value: float,
        tags: Optional[Dict[str, str]] = None,
    ) -> None:
        """Record a single *value* for *metric_name*."""
        self._data[metric_name].append({
            "value": value,
            "tags": tags or {},
            "ts": time.time(),
        })
        log.debug("MetricsCollector: %s = %s", metric_name, value)

    def get(self, metric_name: str) -> List[Dict[str, Any]]:
        """Return all recorded points for *metric_name*."""
        return list(self._data.get(metric_name, []))

    def aggregate(self, metric_name: str) -> Dict[str, Any]:
        """Return mean/max/min/count for *metric_name*."""
        points = self._data.get(metric_name, [])
        if not points:
            return {"mean": 0.0, "max": 0.0, "min": 0.0, "count": 0}
        vals = [p["value"] for p in points]
        return {
            "mean": round(sum(vals) / len(vals), 6),
            "max": max(vals),
            "min": min(vals),
            "count": len(vals),
        }

    def reset(self, metric_name: Optional[str] = None) -> None:
        """Clear data for *metric_name* or all metrics if None."""
        if metric_name is None:
            self._data.clear()
            log.info("MetricsCollector: reset all metrics")
        else:
            self._data.pop(metric_name, None)
