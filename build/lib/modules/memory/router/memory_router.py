from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Dict

from shared.governance_contract.memory_contracts import normalize_memory_payload


@dataclass
class RoutedMemory:
    id: str
    collection: str
    payload: Dict[str, Any]


class MemoryRouterCore:
    """Route memory payloads into canonical governed collections."""

    _TYPE_TO_COLLECTION = {
        "memory": "semantic_memory",
        "research": "semantic_memory",
        "reflection": "reflection_memory",
        "code": "execution_memory",
        "event": "episodic_memory",
    }

    def __init__(self, *, node_identity: str = "niblit_core", authority: str = "niblit_core") -> None:
        self.node_identity = node_identity
        self.authority = authority

    def route(self, text: str, meta: Dict[str, Any] | None = None) -> RoutedMemory:
        payload = copy.deepcopy(meta or {})
        requested_type = str(
            payload.get("memory_type")
            or self._TYPE_TO_COLLECTION.get(str(payload.get("type", "memory")).strip().lower(), "semantic_memory")
        )
        normalized = normalize_memory_payload(
            payload,
            text=text,
            memory_type=requested_type,
            node_identity=self.node_identity,
            authority=self.authority,
            runtime_mode=payload.get("runtime_mode"),
            governance_state=payload.get("governance_state"),
        )
        for key in (
            "schema_v2",
            "runtime_contract",
            "lineage",
            "reflection_binding",
            "federation_metadata",
            "graph",
            "market_context",
        ):
            if key in payload:
                normalized[key] = copy.deepcopy(payload[key])
        normalized["graph"] = dict(normalized.get("graph") or {})
        normalized["graph"]["access_count"] = int(normalized["graph"].get("access_count", 0) or 0)
        return RoutedMemory(
            id=str(normalized["memory_id"]),
            collection=str(normalized["memory_type"]),
            payload=normalized,
        )
