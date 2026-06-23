#!/usr/bin/env python3
"""
modules/evolution_queue.py — Niblit Evolution Queue
====================================================
A persistent priority queue for Niblit's self-evolution proposals.

Every item in the queue represents a proposed modification to Niblit
itself — whether it originates from the Nibblebot scanner, a failed
test, civilization evolution engine insights, manual input, or the
CognitiveGraphKernel's own analysis.

Items progress through a lifecycle:

    PROPOSED → TESTING → APPROVED → APPLIED
                     └→ REJECTED

The :class:`~modules.niblit_cognitive_graph_kernel.EvolutionGraphRuntime`
calls ``list_pending()`` on each cycle and routes items to the
:mod:`modules.evolve_adapter` for safe, CyberMembrane-gated application.

Persistence
-----------
Items are optionally persisted to a JSONL file so they survive restarts.
Set ``NIBLIT_EVOLUTION_QUEUE_PATH`` (default: ``evolution_queue.jsonl``).

Singleton
---------
``get_evolution_queue()`` returns the process-wide
:class:`EvolutionQueue` instance.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

log = logging.getLogger(__name__)

ItemSource = Literal[
    "NIBBLEBOT", "DIAGNOSTICS", "CIVILIZATION", "MANUAL", "TEST_FAILURE",
    "KERNEL", "EVOLUTION_ENGINE"
]
RiskClass = Literal["LOW", "MEDIUM", "HIGH"]
ItemStatus = Literal["PROPOSED", "TESTING", "APPROVED", "APPLIED", "REJECTED"]

_QUEUE_PATH = os.environ.get("NIBLIT_EVOLUTION_QUEUE_PATH", "evolution_queue.jsonl")
_MAX_QUEUE_SIZE = int(os.environ.get("NIBLIT_EVOLUTION_QUEUE_MAX", "500"))


@dataclass
class EvolutionItem:
    """A single self-evolution proposal."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: ItemSource = "MANUAL"
    target_modules: List[str] = field(default_factory=list)
    description: str = ""
    suggested_patch: Optional[str] = None
    risk_class: RiskClass = "MEDIUM"
    status: ItemStatus = "PROPOSED"
    priority: float = 1.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "EvolutionItem":
        valid_fields = {f.name for f in EvolutionItem.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        filtered = {k: v for k, v in d.items() if k in valid_fields}
        return EvolutionItem(**filtered)


class EvolutionQueue:
    """
    Thread-safe, optionally-persistent evolution proposal queue.

    Items are kept in memory (dict keyed by ID) and optionally appended
    to a JSONL file for persistence across restarts.
    """

    def __init__(self, path: str = _QUEUE_PATH, max_size: int = _MAX_QUEUE_SIZE) -> None:
        self._items: Dict[str, EvolutionItem] = {}
        self._lock = threading.Lock()
        self._path = Path(path) if path else None
        self._max_size = max_size
        self._enqueued: int = 0
        self._applied: int = 0
        self._rejected: int = 0
        self._load_from_disk()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_from_disk(self) -> None:
        """Load persisted items from JSONL (skip APPLIED/REJECTED on reload)."""
        if self._path is None or not self._path.exists():
            return
        loaded = 0
        try:
            with open(self._path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = EvolutionItem.from_dict(json.loads(line))
                        if item.status not in ("APPLIED", "REJECTED"):
                            self._items[item.id] = item
                            loaded += 1
                    except Exception:  # noqa: BLE001
                        pass
            log.debug("[EvolutionQueue] loaded %d items from %s", loaded, self._path)
        except Exception as exc:  # noqa: BLE001
            log.debug("[EvolutionQueue] could not load queue: %s", exc)

    def _append_to_disk(self, item: EvolutionItem) -> None:
        if self._path is None:
            return
        try:
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(item.to_dict()) + "\n")
        except Exception as exc:  # noqa: BLE001
            log.debug("[EvolutionQueue] disk write error: %s", exc)

    # ── Public API ────────────────────────────────────────────────────────────

    def enqueue_item(
        self,
        source: ItemSource,
        description: str,
        target_modules: Optional[List[str]] = None,
        suggested_patch: Optional[str] = None,
        risk_class: RiskClass = "MEDIUM",
        priority: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> EvolutionItem:
        """
        Create and enqueue a new evolution proposal.

        Returns the created :class:`EvolutionItem`.
        """
        item = EvolutionItem(
            source=source,
            target_modules=target_modules or [],
            description=description,
            suggested_patch=suggested_patch,
            risk_class=risk_class,
            priority=priority,
            metadata=metadata or {},
        )
        with self._lock:
            # Drop lowest-priority item if at capacity
            if len(self._items) >= self._max_size:
                proposed = [i for i in self._items.values() if i.status == "PROPOSED"]
                if proposed:
                    oldest = min(proposed, key=lambda x: x.priority)
                    del self._items[oldest.id]
            self._items[item.id] = item
            self._enqueued += 1
        self._append_to_disk(item)
        log.debug("[EvolutionQueue] enqueued %s (%s) — %s", item.id, item.source, item.description[:60])
        return item

    def list_pending(self, limit: int = 10) -> List[EvolutionItem]:
        """
        Return up to *limit* items with status PROPOSED, sorted by
        descending priority then oldest-first.
        """
        with self._lock:
            pending = [i for i in self._items.values() if i.status == "PROPOSED"]
        pending.sort(key=lambda x: (-x.priority, x.created_at))
        return pending[:limit]

    def list_all(
        self,
        status: Optional[ItemStatus] = None,
        limit: int = 50,
    ) -> List[EvolutionItem]:
        """Return all items, optionally filtered by status."""
        with self._lock:
            items = list(self._items.values())
        if status is not None:
            items = [i for i in items if i.status == status]
        items.sort(key=lambda x: (-x.priority, x.created_at))
        return items[:limit]

    def get_item(self, item_id: str) -> Optional[EvolutionItem]:
        with self._lock:
            return self._items.get(item_id)

    def update_status(
        self,
        item_id: str,
        new_status: ItemStatus,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Update the status of an item.

        Returns ``True`` if the item was found and updated.
        """
        with self._lock:
            item = self._items.get(item_id)
            if item is None:
                return False
            item.status = new_status
            item.updated_at = time.time()
            if metadata:
                item.metadata.update(metadata)
            if new_status == "APPLIED":
                self._applied += 1
            elif new_status == "REJECTED":
                self._rejected += 1
        self._append_to_disk(item)
        return True

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            by_status: Dict[str, int] = {}
            by_source: Dict[str, int] = {}
            for item in self._items.values():
                by_status[item.status] = by_status.get(item.status, 0) + 1
                by_source[item.source] = by_source.get(item.source, 0) + 1
        return {
            "total_in_memory": len(self._items),
            "enqueued_lifetime": self._enqueued,
            "applied_lifetime": self._applied,
            "rejected_lifetime": self._rejected,
            "by_status": by_status,
            "by_source": by_source,
            "queue_path": str(self._path) if self._path else None,
        }


# ── Singleton ─────────────────────────────────────────────────────────────────

_queue_instance: Optional[EvolutionQueue] = None
_queue_lock = threading.Lock()


def get_evolution_queue() -> EvolutionQueue:
    """Return the process-wide :class:`EvolutionQueue` singleton."""
    global _queue_instance
    with _queue_lock:
        if _queue_instance is None:
            _queue_instance = EvolutionQueue()
    return _queue_instance


if __name__ == "__main__":
    print('Running evolution_queue.py')
