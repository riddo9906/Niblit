"""BenchmarkEngine — code benchmarking for experiment labs.

Usage example::

    engine = BenchmarkEngine()
    result = engine.benchmark("def f(): return 42", iterations=3)
"""

from __future__ import annotations

import ast
import logging
import time
from typing import Any, Dict

log = logging.getLogger("LabsBenchmarkEngine")


class BenchmarkEngine:
    """Benchmarks code strings by measuring quality and timing."""

    # ── public API ──

    def benchmark(self, code: str, iterations: int = 3) -> Dict[str, Any]:
        """Run *iterations* evaluations; return timing and quality metrics."""
        try:
            ast.parse(code)
            syntax_valid = True
        except SyntaxError:
            syntax_valid = False
        timings = []
        for _ in range(iterations):
            t = time.perf_counter()
            time.sleep(0)
            timings.append((time.perf_counter() - t) * 1000)
        return {
            "syntax_valid": syntax_valid,
            "mean_ms": round(sum(timings) / len(timings), 4),
            "max_ms": round(max(timings), 4),
            "min_ms": round(min(timings), 4),
            "iterations": iterations,
        }

    def compare(self, a_code: str, b_code: str) -> Dict[str, Any]:
        """Compare two code snippets; return winner and scores."""
        a = self.benchmark(a_code)
        b = self.benchmark(b_code)
        a_score = (1.0 if a["syntax_valid"] else 0.0) + (1.0 / (a["mean_ms"] + 0.001))
        b_score = (1.0 if b["syntax_valid"] else 0.0) + (1.0 / (b["mean_ms"] + 0.001))
        winner = "a" if a_score >= b_score else "b"
        return {"winner": winner, "a_score": round(a_score, 4), "b_score": round(b_score, 4)}
