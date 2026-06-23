"""modules/meta_cognition/resource_allocator.py — ResourceAllocator (MSG Layer v1).

Allocates *compute / attention* budget strategically across Niblit's major
subsystems:

    allocation = {
        "ALE_research": 0.30,
        "ALE_evolution": 0.15,
        "LLM_training":  0.15,
        "Trading":       0.05,
        "Security":      0.10,
        "Memory":        0.10,
        "Reasoning":     0.15,
    }

The allocator re-balances after each :meth:`rebalance` call by shifting budget
toward weaker subsystems (as identified by :class:`MetaEvaluator`) and away
from already-strong ones.  The intent engine's resource_budget is honoured.

Allocation values are soft hints — no hard enforcement — but they guide the
MSG Layer logs and can be consulted by downstream components.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, Optional

log = logging.getLogger("Niblit.ResourceAllocator")

# Default allocation (must sum to ≤ 1.0)
_DEFAULT_ALLOCATION: Dict[str, float] = {
    "ALE_research":  0.30,
    "ALE_evolution": 0.15,
    "LLM_training":  0.15,
    "Trading":       0.05,
    "Security":      0.10,
    "Memory":        0.10,
    "Reasoning":     0.15,
}

_MIN_ALLOC = 0.02   # floor per bucket
_MAX_ALLOC = 0.60   # ceiling per bucket
_SHIFT_RATE = 0.03  # max shift per rebalance cycle


class ResourceAllocator:
    """Manages Niblit's resource budget across subsystems.

    All public methods are thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._allocation: Dict[str, float] = dict(_DEFAULT_ALLOCATION)
        self._rebalance_count: int = 0

    # ── Public API ────────────────────────────────────────────────────────

    def get_allocation(self) -> Dict[str, float]:
        """Return a copy of the current allocation dict."""
        with self._lock:
            return dict(self._allocation)

    def rebalance(
        self,
        meta_scores: Optional[Dict[str, float]] = None,
        intent_budget: Optional[float] = None,
        priority_bucket: Optional[str] = None,
    ) -> None:
        """Shift allocation toward weaker subsystems.

        Parameters
        ----------
        meta_scores:
            Dict of {subsystem: score ∈ [0,1]} from :class:`MetaEvaluator`.
            Lower scores → more budget shifted toward that area.
        intent_budget:
            Optional resource budget from the current active intent (0–1).
        priority_bucket:
            If given, ensure this bucket gets at least *intent_budget* of the total.
        """
        with self._lock:
            self._rebalance_count += 1

            if not meta_scores:
                return

            # Map meta-evaluator subsystem names → allocation bucket names
            _MAP = {
                "ALE":        "ALE_research",
                "Evolution":  "ALE_evolution",
                "Kernel":     "LLM_training",
                "Trading":    "Trading",
                "Security":   "Security",
                "Memory":     "Memory",
                "Reasoning":  "Reasoning",
            }

            adjustments: Dict[str, float] = {}
            for sys_name, bucket in _MAP.items():
                if sys_name not in meta_scores:
                    continue
                score = meta_scores[sys_name]
                # Weak subsystem → positive shift; strong → negative
                shift = _SHIFT_RATE * (0.5 - score)  # range: ±_SHIFT_RATE
                adjustments[bucket] = shift

            # Apply shifts
            for bucket, shift in adjustments.items():
                current = self._allocation.get(bucket, _MIN_ALLOC)
                self._allocation[bucket] = max(
                    _MIN_ALLOC, min(_MAX_ALLOC, round(current + shift, 4))
                )

            # Honour intent budget for priority bucket
            if priority_bucket and intent_budget is not None:
                cur = self._allocation.get(priority_bucket, _MIN_ALLOC)
                if cur < intent_budget:
                    self._allocation[priority_bucket] = min(_MAX_ALLOC, intent_budget)

            # Normalise so total ≤ 1.0
            total = sum(self._allocation.values())
            if total > 1.0:
                factor = 1.0 / total
                self._allocation = {
                    k: round(v * factor, 4)
                    for k, v in self._allocation.items()
                }

            log.debug(
                "[ResourceAllocator] Rebalance #%d: %s",
                self._rebalance_count,
                {k: f"{v:.0%}" for k, v in self._allocation.items()},
            )

    def set_bucket(self, bucket: str, value: float) -> None:
        """Manually set a budget allocation for *bucket*."""
        with self._lock:
            self._allocation[bucket] = max(_MIN_ALLOC, min(_MAX_ALLOC, value))

    def snapshot(self) -> Dict[str, Any]:
        """Return a serialisable snapshot."""
        with self._lock:
            return {
                "allocation": {k: round(v, 4) for k, v in self._allocation.items()},
                "rebalance_count": self._rebalance_count,
                "total": round(sum(self._allocation.values()), 4),
            }


# ── Singleton ─────────────────────────────────────────────────────────────────

_instance: Optional[ResourceAllocator] = None
_inst_lock = threading.Lock()


def get_resource_allocator() -> ResourceAllocator:
    """Return the process-wide :class:`ResourceAllocator` singleton."""
    global _instance
    if _instance is None:
        with _inst_lock:
            if _instance is None:
                _instance = ResourceAllocator()
    return _instance


if __name__ == "__main__":
    print('Running resource_allocator.py')
