"""BenchmarkEngine — evaluates and compares code quality metrics.

Usage example::

    engine = BenchmarkEngine()
    result = engine.evaluate("def add(a, b): return a + b")
    comparison = engine.compare([result1, result2])
"""

from __future__ import annotations

import ast
import logging
import time
from typing import Any, Dict, List

log = logging.getLogger("BenchmarkEngine")


def _syntax_valid(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


def _quality_score(code: str) -> float:
    """Heuristic quality score 0.0–1.0."""
    score = 0.5
    if _syntax_valid(code):
        score += 0.2
    if '"""' in code or "'''" in code:
        score += 0.1
    if "def " in code or "class " in code:
        score += 0.1
    if "try" in code:
        score += 0.05
    if "return" in code:
        score += 0.05
    return min(1.0, score)


class BenchmarkEngine:
    """Evaluates code strings and compares benchmark results."""

    # ── public API ──

    def evaluate(self, code: str) -> Dict[str, Any]:
        """Return quality metrics for *code*."""
        start = time.time()
        valid = _syntax_valid(code)
        score = _quality_score(code)
        elapsed_ms = round((time.time() - start) * 1000, 4)
        log.debug("BenchmarkEngine: evaluated code — valid=%s score=%.2f", valid, score)
        return {
            "syntax_valid": valid,
            "quality_score": score,
            "exec_time_ms": elapsed_ms,
            "lines": len(code.splitlines()),
        }

    def compare(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Compare a list of evaluate() results."""
        if not results:
            return {"best": None, "worst": None, "average": 0.0}
        scores = [r.get("quality_score", 0.0) for r in results]
        best_idx = scores.index(max(scores))
        worst_idx = scores.index(min(scores))
        return {
            "best": results[best_idx],
            "worst": results[worst_idx],
            "average": round(sum(scores) / len(scores), 4),
        }


if __name__ == "__main__":
    print('Running benchmark_engine.py')
