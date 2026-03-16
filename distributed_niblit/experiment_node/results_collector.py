"""ResultsCollector — aggregates and exports experiment results.

Usage example::

    collector = ResultsCollector()
    collector.record("exp-1", {"score": 0.9, "latency_ms": 120})
    agg = collector.aggregate("exp-1")
"""

from __future__ import annotations

import csv
import io
import logging
from collections import defaultdict
from typing import Any, Dict, List

log = logging.getLogger("ResultsCollector")


class ResultsCollector:
    """Collects and aggregates per-experiment result dictionaries."""

    def __init__(self) -> None:
        self._data: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    # ── public API ──

    def record(self, exp_id: str, result: Dict[str, Any]) -> None:
        """Append *result* to the record for *exp_id*."""
        self._data[exp_id].append(result)
        log.debug("ResultsCollector: recorded result for %s", exp_id)

    def get(self, exp_id: str) -> List[Dict[str, Any]]:
        """Return all results for *exp_id*."""
        return list(self._data.get(exp_id, []))

    def aggregate(self, exp_id: str) -> Dict[str, Any]:
        """Return mean/max/min/count aggregation for numeric fields in *exp_id*."""
        records = self._data.get(exp_id, [])
        if not records:
            return {"mean": 0.0, "max": 0.0, "min": 0.0, "count": 0}
        numeric_keys = [k for k, v in records[0].items() if isinstance(v, (int, float))]
        agg: Dict[str, Any] = {"count": len(records)}
        for key in numeric_keys:
            vals = [r[key] for r in records if isinstance(r.get(key), (int, float))]
            if vals:
                agg[f"{key}_mean"] = round(sum(vals) / len(vals), 4)
                agg[f"{key}_max"] = max(vals)
                agg[f"{key}_min"] = min(vals)
        if numeric_keys:
            first_key = numeric_keys[0]
            vals = [r[first_key] for r in records if isinstance(r.get(first_key), (int, float))]
            if vals:
                agg["mean"] = round(sum(vals) / len(vals), 4)
                agg["max"] = max(vals)
                agg["min"] = min(vals)
        return agg

    def export_csv(self, exp_id: str) -> str:
        """Return CSV string of all results for *exp_id*."""
        records = self._data.get(exp_id, [])
        if not records:
            return ""
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(records[0].keys()))
        writer.writeheader()
        writer.writerows(records)
        return buf.getvalue()
