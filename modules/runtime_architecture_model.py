#!/usr/bin/env python3
"""Live runtime architecture graph updated from canonical cognitive events."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

log = logging.getLogger("Niblit.RuntimeArchitectureModel")


class RuntimeArchitectureModel:
    """Small additive graph of runtime components and their interactions."""

    def __init__(self, persistence_manager: Any | None = None) -> None:
        self._lock = threading.RLock()
        self._persistence_manager = persistence_manager
        self._nodes: dict[str, dict[str, Any]] = {}
        self._edges: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._last_updated_at = 0.0

    def observe_event(self, event: dict[str, Any], *, lineage_channel: str = "") -> None:
        payload = dict(event.get("payload", {}) or {})
        source = str(event.get("source") or payload.get("source_module") or "unknown")
        event_type = str(event.get("type") or "runtime.event")
        category = str(payload.get("event_category") or "runtime")
        trace_id = str(payload.get("trace_id") or "")
        target = str(payload.get("selected_module") or payload.get("provider") or payload.get("target_module") or category)
        with self._lock:
            self._nodes.setdefault(source, {"node": source, "role": "source", "updated_at": time.time()})
            self._nodes.setdefault(target, {"node": target, "role": "target", "updated_at": time.time()})
            key = (source, target, event_type)
            edge = self._edges.get(key, {"source": source, "target": target, "event_type": event_type, "count": 0})
            edge["count"] = int(edge.get("count", 0)) + 1
            edge["category"] = category
            edge["trace_id"] = trace_id
            if lineage_channel:
                edge["lineage_channel"] = lineage_channel
            edge["updated_at"] = time.time()
            self._edges[key] = edge
            self._last_updated_at = time.time()
        self._persist()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "nodes": list(self._nodes.values()),
                "edges": list(self._edges.values()),
                "summary": {
                    "node_count": len(self._nodes),
                    "edge_count": len(self._edges),
                    "last_updated_at": self._last_updated_at,
                },
            }

    def _persist(self) -> None:
        if self._persistence_manager is None or not hasattr(self._persistence_manager, "write_json_file"):
            return
        try:
            root = getattr(self._persistence_manager, "root_dir", "")
            path = f"{root}/runtime_architecture_model.json" if root else "runtime_architecture_model.json"
            self._persistence_manager.write_json_file(path, self.status())
        except Exception as exc:
            log.debug("Failed persisting architecture model: %s", exc)
