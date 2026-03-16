#!/usr/bin/env python3
"""
modules/ai_dev_lab/discovery_engine.py

Detect performance breakthroughs in SEADL experiment results.

Process::

    monitor experiments
          ↓
    detect performance improvements above threshold
          ↓
    record discoveries
          ↓
    trigger publication / evolution

Usage::

    from modules.ai_dev_lab.discovery_engine import DiscoveryEngine
    engine = DiscoveryEngine(threshold=0.7)
    discovery = engine.detect(benchmark_results)
    if discovery:
        print("Breakthrough:", discovery)
"""

import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("DiscoveryEngine")

_DEFAULT_THRESHOLD = 0.7
_IMPROVEMENT_DELTA = 0.1  # minimum improvement over baseline to count


class DiscoveryEngine:
    """
    Monitor experiment results and flag performance breakthroughs.
    """

    def __init__(self, threshold: float = _DEFAULT_THRESHOLD) -> None:
        self.threshold = threshold
        self._baseline: float = 0.0
        self._discoveries: List[Dict[str, Any]] = []

    # ── public API ────────────────────────────────────────────────────────────

    def detect(
        self, results: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Check whether *results* represent a breakthrough or threshold event.

        Returns a discovery dict or None.

        Detection logic:
            - "breakthrough": performance significantly exceeds a previously
              established baseline (baseline > 0, improvement >= delta).
            - "threshold_exceeded": performance meets or exceeds the fixed
              threshold (covers cases where baseline is still 0).
        """
        perf = float(results.get("performance", 0.0))

        # Breakthrough: meaningful improvement over a known non-zero baseline
        if self._baseline > 0 and perf > self._baseline + _IMPROVEMENT_DELTA:
            discovery = {
                "type": "breakthrough",
                "performance": perf,
                "improvement": round(perf - self._baseline, 3),
                "baseline": self._baseline,
                "results": results,
                "timestamp": time.time(),
            }
            self._discoveries.append(discovery)
            old_baseline = self._baseline
            self._baseline = perf
            log.info(
                "DiscoveryEngine: breakthrough — perf=%.3f (was %.3f)",
                perf, old_baseline,
            )
            return discovery

        # Threshold crossed
        if perf >= self.threshold:
            discovery = {
                "type": "threshold_exceeded",
                "performance": perf,
                "threshold": self.threshold,
                "results": results,
                "timestamp": time.time(),
            }
            self._discoveries.append(discovery)
            # Also update baseline when threshold is first hit
            if perf > self._baseline:
                self._baseline = perf
            log.info("DiscoveryEngine: threshold exceeded — perf=%.3f", perf)
            return discovery

        return None

    def detect_batch(
        self, result_list: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Run detect() over a list of results.  Returns all discoveries found."""
        discoveries = []
        for r in result_list:
            d = self.detect(r)
            if d:
                discoveries.append(d)
        return discoveries

    def set_baseline(self, score: float) -> None:
        """Manually set the performance baseline."""
        self._baseline = score

    def all_discoveries(self) -> List[Dict[str, Any]]:
        return list(self._discoveries)

    def stats(self) -> Dict[str, Any]:
        return {
            "discoveries": len(self._discoveries),
            "baseline": self._baseline,
            "threshold": self.threshold,
        }
