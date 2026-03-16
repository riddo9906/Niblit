"""ResultAnalyzer — statistical analysis of experiment results.

Usage example::

    analyzer = ResultAnalyzer()
    stats = analyzer.analyze([{"score": 0.8}, {"score": 0.9}, {"score": 0.7}])
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List

log = logging.getLogger("ResultAnalyzer")


class ResultAnalyzer:
    """Provides statistical summaries and improvement detection."""

    # ── public API ──

    def analyze(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Return mean/std/min/max/outliers for numeric fields in *results*."""
        if not results:
            return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "outliers": []}
        score_key = next(
            (k for k in results[0] if isinstance(results[0][k], (int, float))), None
        )
        if score_key is None:
            return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "outliers": []}
        vals = [r[score_key] for r in results if isinstance(r.get(score_key), (int, float))]
        mean = sum(vals) / len(vals)
        std = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
        outliers = [v for v in vals if abs(v - mean) > 2 * std]
        return {
            "mean": round(mean, 6),
            "std": round(std, 6),
            "min": min(vals),
            "max": max(vals),
            "outliers": outliers,
        }

    def detect_improvement(
        self, baseline: Dict[str, Any], candidate: Dict[str, Any]
    ) -> bool:
        """Return True if *candidate* score exceeds *baseline* score."""
        b = baseline.get("mean", baseline.get("score", 0.0))
        c = candidate.get("mean", candidate.get("score", 0.0))
        return float(c) > float(b)

    def summarize(
        self, exp_id: str, results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Return a named summary for *exp_id*."""
        stats = self.analyze(results)
        return {"exp_id": exp_id, "result_count": len(results), **stats}
