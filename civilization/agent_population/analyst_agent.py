"""AnalystAgent — civilisation agent specialised for benchmark analysis.

Usage example::

    agent = AnalystAgent("an1", "analyst")
    result = agent.execute({"experiment": {"data": [0.8, 0.9, 0.85]}})
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

from .base_agent import BaseAgent

log = logging.getLogger("AnalystAgent")


class AnalystAgent(BaseAgent):
    """Runs benchmarks and compares experiment results."""

    # ── public API ──

    def execute(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Execute analysis task; return analysis/score/recommendations dict."""
        experiment = task.get("experiment", {})
        benchmark = self.run_benchmark(experiment)
        recommendations = [
            "Increase training iterations by 20%.",
            "Add regularisation to reduce overfitting.",
        ]
        result = {
            "analysis": benchmark,
            "score": benchmark.get("mean_score", 0.5),
            "recommendations": recommendations,
            "analysed_at": time.time(),
        }
        self._record_task()
        log.info("AnalystAgent %s: analysis score=%.2f", self._agent_id, result["score"])
        return result

    def run_benchmark(self, experiment: Dict[str, Any]) -> Dict[str, Any]:
        """Run benchmark on *experiment* data."""
        data = experiment.get("data", [0.75])
        scores = [float(x) for x in data]
        return {
            "mean_score": round(sum(scores) / len(scores), 4),
            "max_score": max(scores),
            "min_score": min(scores),
            "sample_count": len(scores),
        }

    def compare_results(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compare multiple benchmark results."""
        if not results:
            return {"winner": None, "comparison": []}
        scores = [r.get("mean_score", r.get("score", 0.0)) for r in results]
        best_idx = scores.index(max(scores))
        return {"winner": results[best_idx], "all_scores": scores}
