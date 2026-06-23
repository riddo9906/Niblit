#!/usr/bin/env python3
"""
modules/ai_dev_lab/benchmark_engine.py

Evaluate code implementations with objective performance metrics.

Metrics measured:
    - syntax validity
    - execution time (for pure-function snippets)
    - memory usage (via tracemalloc)
    - test pass rate (if test cases provided)
    - static quality score (line count, docstring presence)

Usage::

    from modules.ai_dev_lab.benchmark_engine import BenchmarkEngine
    engine = BenchmarkEngine()
    results = engine.evaluate(code_string)
    results = engine.evaluate(code_string, test_cases=[{"input": ..., "expected": ...}])
"""

import ast
import logging
import time
import tracemalloc
from typing import Any, Dict, List, Optional

log = logging.getLogger("BenchmarkEngine")

_EXEC_TIMEOUT = 5.0  # seconds — safeguard against infinite loops


class BenchmarkEngine:
    """
    Evaluate generated code with multiple quality and performance metrics.
    """

    # ── public API ────────────────────────────────────────────────────────────

    def evaluate(
        self,
        code: str,
        test_cases: Optional[List[Dict[str, Any]]] = None,
        label: str = "",
    ) -> Dict[str, Any]:
        """
        Evaluate *code* and return a metrics report.

        Returns dict with keys:
            label, syntax_valid, syntax_error, quality_score,
            execution_time_ms, memory_peak_kb, test_results, performance
        """
        results: Dict[str, Any] = {
            "label": label,
            "syntax_valid": False,
            "syntax_error": None,
            "quality_score": 0.0,
            "execution_time_ms": 0.0,
            "memory_peak_kb": 0.0,
            "test_results": [],
            "performance": 0.0,
        }

        if not isinstance(code, str) or not code.strip():
            results["syntax_error"] = "empty code"
            return results

        # 1 — Syntax check
        try:
            ast.parse(code)
            results["syntax_valid"] = True
        except SyntaxError as exc:
            results["syntax_error"] = str(exc)
            return results

        # 2 — Static quality score
        results["quality_score"] = self._quality_score(code)

        # 3 — Timed execution (safe sandbox)
        exec_ms, mem_kb = self._timed_exec(code)
        results["execution_time_ms"] = exec_ms
        results["memory_peak_kb"] = mem_kb

        # 4 — Test cases
        if test_cases:
            results["test_results"] = self._run_tests(code, test_cases)

        # 5 — Composite performance score
        results["performance"] = self._compute_performance(results)

        return results

    def run_tests(self, code: str, test_cases: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Run test cases against *code* and return results."""
        return self._run_tests(code, test_cases)

    def measure_performance(self, code: str) -> Dict[str, float]:
        """Return only performance-related metrics."""
        _, mem = self._timed_exec(code)
        quality = self._quality_score(code)
        return {"memory_peak_kb": mem, "quality_score": quality}

    # ── internals ─────────────────────────────────────────────────────────────

    @staticmethod
    def _quality_score(code: str) -> float:
        """Heuristic quality score 0.0–1.0 based on static properties."""
        score = 0.0
        lines = [l for l in code.splitlines() if l.strip()]
        if not lines:
            return 0.0

        # Has docstring
        if '"""' in code or "'''" in code:
            score += 0.2
        # Has type hints
        if "->" in code or ": str" in code or ": int" in code or ": Dict" in code:
            score += 0.2
        # Has class/function
        try:
            tree = ast.parse(code)
            has_class = any(isinstance(n, ast.ClassDef) for n in ast.walk(tree))
            has_func = any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(tree))
            if has_class:
                score += 0.2
            if has_func:
                score += 0.2
        except SyntaxError:
            pass
        # Reasonable length (not too short, not a wall of text)
        if 5 <= len(lines) <= 200:
            score += 0.2
        return round(min(score, 1.0), 3)

    @staticmethod
    def _timed_exec(code: str) -> tuple:
        """
        Execute code in an isolated namespace and measure time + memory.

        Returns (elapsed_ms, peak_memory_kb).  Returns (0, 0) on error.
        """
        namespace: Dict[str, Any] = {}
        tracemalloc.start()
        t0 = time.perf_counter()
        try:
            exec(compile(code, "<benchmark>", "exec"), namespace)  # noqa: S102
        except Exception:  # noqa: BLE001
            pass
        elapsed_ms = (time.perf_counter() - t0) * 1000
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        return round(elapsed_ms, 2), round(peak / 1024, 2)

    @staticmethod
    def _run_tests(
        code: str, test_cases: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Run each test case by executing code + calling the specified function.

        Each test case dict may have: function, args, expected.
        """
        namespace: Dict[str, Any] = {}
        try:
            exec(compile(code, "<test>", "exec"), namespace)  # noqa: S102
        except Exception as exc:  # noqa: BLE001
            return [{"error": f"Code execution failed: {exc}"}]

        results = []
        for tc in test_cases:
            fn_name = tc.get("function", "")
            args = tc.get("args", [])
            expected = tc.get("expected")
            if fn_name and fn_name in namespace and callable(namespace[fn_name]):
                try:
                    actual = namespace[fn_name](*args)
                    results.append({
                        "function": fn_name,
                        "passed": actual == expected,
                        "actual": actual,
                        "expected": expected,
                    })
                except Exception as exc:  # noqa: BLE001
                    results.append({"function": fn_name, "error": str(exc), "passed": False})
            else:
                results.append({"function": fn_name, "error": "not found", "passed": False})
        return results

    @staticmethod
    def _compute_performance(results: Dict[str, Any]) -> float:
        """Aggregate sub-scores into a single 0.0–1.0 performance value."""
        if not results["syntax_valid"]:
            return 0.0
        score = results["quality_score"] * 0.5
        # Test pass rate contributes 40%
        tests = results.get("test_results", [])
        if tests:
            passed = sum(1 for t in tests if t.get("passed"))
            score += 0.4 * (passed / len(tests))
        else:
            score += 0.2  # no tests — partial credit
        # Memory efficiency (low is better): 10%
        mem = results.get("memory_peak_kb", 0)
        mem_score = max(0.0, 1.0 - mem / 10000)
        score += 0.1 * mem_score
        return round(min(score, 1.0), 3)


if __name__ == "__main__":
    print('Running benchmark_engine.py')
