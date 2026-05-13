"""Governed cognition-aware Qdrant memory cluster runtime layer."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from shared.governance_contract.memory_contracts import (
    CANONICAL_MEMORY_COLLECTIONS,
    collection_blueprints,
    detect_memory_drift,
    governed_recall_allowed,
    memory_retrieval_score,
    normalize_memory_payload,
    reconstruct_memory_lineage,
    transition_memory_lifecycle,
    validate_memory_payload,
)
from shared.governance_contract.schema_v2 import ensure_schema_v2
from shared.governance_contract.validators import validate_runtime_contract

log = logging.getLogger("GovernedQdrantMemoryCluster")


class GovernedQdrantMemoryCluster:
    """Governed memory wrapper for Qdrant-backed cognition and replay."""

    def __init__(
        self,
        *,
        collection_prefix: str = "niblit",
        qdrant_url: str = "",
        qdrant_api_key: str = "",
        vector_store_factory: Callable[..., Any] | None = None,
        node_identity: str = "niblit_core",
        authority: str = "niblit_core",
    ) -> None:
        self.collection_prefix = collection_prefix
        self.qdrant_url = qdrant_url
        self.qdrant_api_key = qdrant_api_key
        self.node_identity = node_identity
        self.authority = authority
        self._lock = threading.Lock()
        self._vector_store_factory = vector_store_factory
        self._vector_stores: dict[str, Any] = {}
        self._catalog: dict[str, dict[str, Any]] = {}
        self._writes = 0
        self._recalls = 0
        self._lifecycle_runs = 0

    def _collection_name(self, memory_type: str) -> str:
        return f"{self.collection_prefix}_{memory_type}"

    def _make_vector_store(self, collection_name: str) -> Any | None:
        factory = self._vector_store_factory
        if factory is None:
            try:
                from modules.vector_store import VectorStore
            except Exception as exc:  # pragma: no cover - defensive import guard
                log.debug("VectorStore import unavailable: %s", exc)
                return None
            factory = VectorStore
        try:
            return factory(
                collection=collection_name,
                qdrant_url=self.qdrant_url,
                qdrant_api_key=self.qdrant_api_key,
            )
        except Exception as exc:
            log.debug("Vector store init failed for %s: %s", collection_name, exc)
            return None

    def _get_vector_store(self, memory_type: str) -> Any | None:
        collection_name = self._collection_name(memory_type)
        with self._lock:
            if collection_name in self._vector_stores:
                return self._vector_stores[collection_name]
            store = self._make_vector_store(collection_name)
            self._vector_stores[collection_name] = store
            return store

    def write_memory(
        self,
        text: str,
        *,
        payload: dict[str, Any] | None = None,
        memory_type: str = "semantic_memory",
    ) -> dict[str, Any]:
        """Write a normalized governed memory into the cluster catalog/backend."""
        runtime_payload = ensure_schema_v2(payload or {})
        runtime_validation = validate_runtime_contract(runtime_payload)
        validation = validate_memory_payload({**(payload or {}), "memory_type": memory_type, "text": text})
        normalized = normalize_memory_payload(
            validation["normalized"],
            text=text,
            memory_type=memory_type,
            node_identity=self.node_identity,
            authority=self.authority,
        )
        normalized["schema_v2"] = runtime_payload
        normalized["runtime_contract"] = runtime_validation["normalized"]
        normalized["lineage"] = {
            "trace_id": (normalized.get("replay_metadata") or {}).get("trace_id", ""),
            "causal_chain": list(normalized.get("causal_chain", [])),
        }
        normalized["reflection_binding"] = {
            "summary": str(normalized.get("reflection_summary") or ""),
            "memory_type": normalized["memory_type"],
        }
        normalized["federation_metadata"] = dict(normalized.get("federation_origin") or {})
        backend = "none"
        stored = False
        store = self._get_vector_store(normalized["memory_type"])
        if store is not None:
            try:
                backend = getattr(store, "backend", "vector")
                topic = normalized["routing"]["namespace"]
                result = store.add(normalized["memory_id"], normalized["content_text"] or normalized["summary"], topic=topic)
                stored = result is not False
            except Exception as exc:
                log.debug("Governed memory write degraded to catalog-only for %s: %s", normalized["memory_id"], exc)
        with self._lock:
            self._catalog[normalized["memory_id"]] = normalized
            self._writes += 1
        return {
            "valid": validation["valid"] and runtime_validation["valid"],
            "issues": validation["issues"] + runtime_validation["issues"],
            "stored": stored,
            "backend": backend,
            "memory_id": normalized["memory_id"],
            "collection": normalized["memory_type"],
        }

    def recall(
        self,
        query: str,
        *,
        top_k: int = 5,
        memory_types: list[str] | None = None,
        runtime_mode: str = "normal",
        governance_state: str = "active",
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Recall governed memories with explainable ranking and filtering."""
        requested_types = [item for item in (memory_types or list(CANONICAL_MEMORY_COLLECTIONS)) if item in CANONICAL_MEMORY_COLLECTIONS]
        query_tokens = {token for token in query.lower().split() if token}
        candidates: dict[str, float] = {}
        filters = filters or {}

        for memory_type in requested_types:
            store = self._get_vector_store(memory_type)
            if store is None:
                continue
            try:
                for hit in store.search(query, top_k=max(top_k * 2, 5)):
                    hit_id = str(hit.get("id") or "")
                    if hit_id:
                        candidates[hit_id] = max(candidates.get(hit_id, 0.0), float(hit.get("score", 0.0)))
            except Exception as exc:
                log.debug("Vector search failed for %s: %s", memory_type, exc)

        with self._lock:
            catalog_values = list(self._catalog.values())
            self._recalls += 1

        ranked: list[dict[str, Any]] = []
        for payload in catalog_values:
            if payload["memory_type"] not in requested_types:
                continue
            trace_filter = str(filters.get("trace_id", "")).strip()
            if trace_filter and str((payload.get("replay_metadata") or {}).get("trace_id", "")) != trace_filter:
                continue
            node_filter = str(filters.get("federation_node_id", "")).strip()
            if node_filter and str((payload.get("federation_origin") or {}).get("node_id", "")) != node_filter:
                continue
            if not governed_recall_allowed(payload, runtime_mode=runtime_mode, governance_state=governance_state):
                continue
            content = f"{payload.get('content_text', '')} {payload.get('summary', '')}".lower()
            lexical_overlap = 0.0
            if query_tokens:
                lexical_overlap = sum(1 for token in query_tokens if token in content) / float(len(query_tokens))
            base_score = max(candidates.get(payload["memory_id"], 0.0), lexical_overlap)
            if base_score <= 0.0 and query_tokens:
                continue
            score = memory_retrieval_score(payload, base_score=base_score, runtime_mode=runtime_mode)
            ranked.append(
                {
                    "memory_id": payload["memory_id"],
                    "collection": payload["memory_type"],
                    "score": score,
                    "payload": payload,
                    "explanation": {
                        "base_score": round(base_score, 6),
                        "coherence_score": payload["coherence_score"],
                        "reinforcement_score": payload["lifecycle"]["reinforcement_score"],
                        "runtime_mode": runtime_mode,
                        "lifecycle_state": payload["lifecycle"]["state"],
                    },
                }
            )
        ranked.sort(key=lambda item: item["score"], reverse=True)
        ts = int(time.time())
        with self._lock:
            for item in ranked[:top_k]:
                memory_id = item["memory_id"]
                if memory_id in self._catalog:
                    self._catalog[memory_id]["last_accessed_at"] = ts
        return ranked[:top_k]

    def apply_lifecycle(self, *, runtime_pressure: float = 0.0, now_ts: int | None = None) -> dict[str, Any]:
        """Run lifecycle transitions across the governed memory catalog."""
        transitions: list[dict[str, Any]] = []
        with self._lock:
            keys = list(self._catalog.keys())
        for memory_id in keys:
            with self._lock:
                payload = self._catalog.get(memory_id)
            if payload is None:
                continue
            transition = transition_memory_lifecycle(payload, runtime_pressure=runtime_pressure, now_ts=now_ts)
            transitions.append({"memory_id": memory_id, **transition})
            with self._lock:
                self._catalog[memory_id] = transition["updated"]
        self._lifecycle_runs += 1
        by_state: dict[str, int] = {}
        for transition in transitions:
            by_state[transition["state"]] = by_state.get(transition["state"], 0) + 1
        return {"count": len(transitions), "by_state": by_state, "transitions": transitions}

    def reconstruct_replay(self, trace_id: str) -> dict[str, Any]:
        """Reconstruct a replay lineage from governed memory records."""
        with self._lock:
            records = list(self._catalog.values())
        return reconstruct_memory_lineage(records, trace_id=trace_id)

    def stitch_lineage(self, memory_ids: list[str]) -> dict[str, Any]:
        """Reconstruct lineage for an explicit list of memory identifiers."""
        with self._lock:
            records = [self._catalog[memory_id] for memory_id in memory_ids if memory_id in self._catalog]
        return reconstruct_memory_lineage(records)

    def observability_snapshot(self) -> dict[str, Any]:
        """Return cluster health, drift, lifecycle, and federation observability."""
        with self._lock:
            records = list(self._catalog.values())
        by_collection: dict[str, int] = {}
        by_state: dict[str, int] = {}
        by_runtime_mode: dict[str, int] = {}
        for record in records:
            by_collection[record["memory_type"]] = by_collection.get(record["memory_type"], 0) + 1
            state = record["lifecycle"]["state"]
            by_state[state] = by_state.get(state, 0) + 1
            mode = record["runtime_mode"]
            by_runtime_mode[mode] = by_runtime_mode.get(mode, 0) + 1
        return {
            "node_identity": self.node_identity,
            "authority": self.authority,
            "collection_blueprints": collection_blueprints(self.node_identity),
            "records": len(records),
            "writes": self._writes,
            "recalls": self._recalls,
            "lifecycle_runs": self._lifecycle_runs,
            "by_collection": by_collection,
            "by_state": by_state,
            "by_runtime_mode": by_runtime_mode,
            "drift": detect_memory_drift(records),
        }


_cluster: GovernedQdrantMemoryCluster | None = None
_cluster_lock = threading.Lock()


def get_governed_qdrant_memory_cluster() -> GovernedQdrantMemoryCluster:
    """Return the process-level governed Qdrant memory cluster singleton."""
    global _cluster
    with _cluster_lock:
        if _cluster is None:
            _cluster = GovernedQdrantMemoryCluster()
    return _cluster
