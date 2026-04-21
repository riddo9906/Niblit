"""
kernel/memory_manager.py — Memory allocation tracking and budgeting.

Provides a lightweight accounting layer so kernel subsystems and
NiblitCore modules can reserve, release, and inspect memory budgets
without relying on OS-level memory limits.

Actual physical memory consumption is reported via :mod:`psutil` when
available; budgets are enforced at the logical/allocation level.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

log = logging.getLogger("NiblitOSKernel.MemoryManager")

__all__ = ["MemoryAllocation", "MemoryManager"]

try:
    import psutil as _psutil  # type: ignore[import]
    _PSUTIL_AVAILABLE = True
except ImportError:
    _psutil = None  # type: ignore[assignment]
    _PSUTIL_AVAILABLE = False


@dataclass
class MemoryAllocation:
    """Represents a single logical memory reservation."""

    owner: str
    bytes_reserved: int
    allocated_at: float = field(default_factory=time.time)
    released: bool = False
    released_at: float | None = None


class MemoryManager:
    """
    Logical memory budget tracker.

    Subsystems call ``reserve(owner, bytes)`` to declare their intended
    memory footprint and ``release(owner)`` when done.  The manager never
    enforces limits at the OS level; it is purely an accounting layer that
    surfaces pressure metrics.

    Parameters
    ----------
    total_budget_bytes:
        Soft ceiling for total reservations.  Defaults to 512 MiB.
        Set to 0 to disable budget enforcement.
    """

    DEFAULT_BUDGET = 512 * 1024 * 1024  # 512 MiB

    def __init__(self, total_budget_bytes: int = DEFAULT_BUDGET) -> None:
        self._budget = total_budget_bytes
        self._allocations: dict[str, MemoryAllocation] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------ reserve ---
    def reserve(self, owner: str, bytes_requested: int) -> bool:
        """
        Reserve *bytes_requested* bytes for *owner*.

        Returns True on success, False if the budget would be exceeded.
        If *owner* already has an allocation it is updated in-place.
        """
        with self._lock:
            current_used = sum(
                a.bytes_reserved for a in self._allocations.values() if not a.released
            )
            existing = self._allocations.get(owner)
            existing_bytes = existing.bytes_reserved if existing and not existing.released else 0
            projected = current_used - existing_bytes + bytes_requested
            if self._budget > 0 and projected > self._budget:
                log.warning(
                    "[MM] Reserve denied for %s: %d bytes requested, budget would reach %d/%d",
                    owner, bytes_requested, projected, self._budget,
                )
                return False
            self._allocations[owner] = MemoryAllocation(
                owner=owner, bytes_reserved=bytes_requested
            )
            log.debug("[MM] Reserved %d bytes for %s (total %d/%d)",
                      bytes_requested, owner, projected, self._budget)
            return True

    # ------------------------------------------------------------ release ---
    def release(self, owner: str) -> None:
        """Release the allocation held by *owner*."""
        with self._lock:
            alloc = self._allocations.get(owner)
            if alloc and not alloc.released:
                alloc.released = True
                alloc.released_at = time.time()
                log.debug("[MM] Released allocation for %s (%d bytes)", owner, alloc.bytes_reserved)

    # ---------------------------------------------------------- usage_info --
    def usage_info(self) -> dict:
        """Return current logical and (if psutil available) physical usage."""
        with self._lock:
            active = {k: v for k, v in self._allocations.items() if not v.released}
            logical_used = sum(a.bytes_reserved for a in active.values())

        info: dict = {
            "budget_bytes": self._budget,
            "logical_used_bytes": logical_used,
            "logical_free_bytes": max(0, self._budget - logical_used),
            "allocations": {
                k: {"bytes": v.bytes_reserved, "allocated_at": v.allocated_at}
                for k, v in active.items()
            },
        }

        if _PSUTIL_AVAILABLE:
            try:
                vm = _psutil.virtual_memory()
                info["physical"] = {
                    "total_bytes": vm.total,
                    "available_bytes": vm.available,
                    "used_bytes": vm.used,
                    "percent": vm.percent,
                }
            except Exception:
                pass

        return info

    def status(self) -> dict:
        return self.usage_info()

    def shutdown(self) -> None:
        """Release all active allocations."""
        with self._lock:
            for alloc in self._allocations.values():
                if not alloc.released:
                    alloc.released = True
                    alloc.released_at = time.time()
        log.debug("[MM] All allocations released on shutdown.")


if __name__ == "__main__":
    print('Running memory_manager.py')
