"""Governed cognition-aware Qdrant memory cluster runtime layer."""

from __future__ import annotations

import logging
import hashlib
import threading
import time
from collections.abc import Callable
from math import exp
from typing import Any

from modules.memory.graph.memory_graph import MemoryGraph
from modules.memory.router.graph_router import GraphMemoryRouter
from modules.memory.router.memory_router import MemoryRouterCore, RoutedMemory
from shared.governance_contract.memory_contracts import (
    CANONICAL_MEMORY_COLLECTIONS,
    collection_blueprints,
    detect_memory_drift,
    governed_recall_allowed,
    memory_retrieval_score,
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
        self._vector_id_lookup: dict[str, str] = {}
        self._writes = 0
        self._recalls = 0
        self._lifecycle_runs = 0
        self._graph = MemoryGraph()
        self._router_core = MemoryRouterCore(node_identity=node_identity, authority=authority)
        self._graph_router = GraphMemoryRouter(self._router_core, self._graph, write_callback=self._write_routed_memory)

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
        meta = dict(payload or {})
        meta["memory_type"] = memory_type
        meta["schema_v2"] = runtime_payload
        meta["runtime_contract"] = runtime_validation["normalized"]
        node = self._graph_router.insert(text, meta)
        normalized = dict(node.metadata)
        write_status = dict(normalized.pop("_graph_write", {}))
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
        graph_meta = dict(normalized.get("graph") or {})
        graph_meta["edge_count"] = self._graph.edge_count(normalized["memory_id"])
        normalized["graph"] = graph_meta
        backend = str(write_status.get("backend", "none"))
        stored = bool(write_status.get("stored", False))
        graph_node = self._graph.get_node(normalized["memory_id"])
        if graph_node is not None:
            graph_node.metadata = dict(normalized)
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
        lexical_candidates: dict[str, float] = {}
        filters = filters or {}

        for memory_type in requested_types:
            store = self._get_vector_store(memory_type)
            if store is None:
                continue
            try:
                for hit in store.search(query, top_k=max(top_k * 2, 5)):
                    hit_id = str(hit.get("id") or "")
                    hit_id = self._vector_id_lookup.get(hit_id, hit_id)
                    if hit_id:
                        candidates[hit_id] = max(candidates.get(hit_id, 0.0), float(hit.get("score", 0.0)))
            except Exception as exc:
                log.debug("Vector search failed for %s: %s", memory_type, exc)

        with self._lock:
            catalog_values = list(self._catalog.values())
            self._recalls += 1

        eligible_records: list[dict[str, Any]] = []
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
            if lexical_overlap > 0.0:
                lexical_candidates[payload["memory_id"]] = lexical_overlap
            eligible_records.append(payload)

        seed_scores = dict(lexical_candidates)
        for memory_id, score in candidates.items():
            seed_scores[memory_id] = max(seed_scores.get(memory_id, 0.0), score)
        expanded = self._graph.expansion_scores(seed_scores, max_depth=2) if seed_scores else {}
        candidate_ids = set(seed_scores) | set(expanded)
        now = time.time()

        ranked: list[dict[str, Any]] = []
        for payload in eligible_records:
            memory_id = payload["memory_id"]
            if candidate_ids and memory_id not in candidate_ids:
                continue
            lexical_overlap = lexical_candidates.get(memory_id, 0.0)
            base_score = max(candidates.get(memory_id, 0.0), lexical_overlap)
            graph_context = expanded.get(memory_id, {})
            graph_score = float(graph_context.get("score", 0.0))
            if base_score <= 0.0 and graph_score <= 0.0 and query_tokens:
                continue
            governed_score = memory_retrieval_score(payload, base_score=max(base_score, graph_score), runtime_mode=runtime_mode)
            temporal_score = self._temporal_score(payload, now_ts=now)
            access_score = self._access_score(payload)
            causal_score = self._causal_score(memory_id)
            edge_count = self._graph.edge_count(memory_id)
            isolation_decay = 0.88 if edge_count == 0 and graph_score <= 0.0 else 1.0
            score = (
                governed_score * 0.55
                + graph_score * 0.20
                + temporal_score * 0.10
                + access_score * 0.10
                + causal_score * 0.05
            ) * isolation_decay
            ranked.append(
                {
                    "memory_id": payload["memory_id"],
                    "collection": payload["memory_type"],
                    "score": round(max(0.0, min(1.0, score)), 6),
                    "payload": payload,
                    "explanation": {
                        "base_score": round(base_score, 6),
                        "graph_score": round(graph_score, 6),
                        "temporal_score": round(temporal_score, 6),
                        "access_score": round(access_score, 6),
                        "causal_score": round(causal_score, 6),
                        "coherence_score": payload["coherence_score"],
                        "reinforcement_score": payload["lifecycle"]["reinforcement_score"],
                        "runtime_mode": runtime_mode,
                        "lifecycle_state": payload["lifecycle"]["state"],
                        "edge_count": edge_count,
                        "graph_hops": int(graph_context.get("hops", 0)),
                        "graph_relations": list(graph_context.get("relations", [])),
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
                    graph_meta = dict(self._catalog[memory_id].get("graph") or {})
                    graph_meta["access_count"] = int(graph_meta.get("access_count", 0)) + 1
                    graph_meta["last_accessed_at"] = ts
                    graph_meta["edge_count"] = self._graph.edge_count(memory_id)
                    self._catalog[memory_id]["graph"] = graph_meta
        for item in ranked[:top_k]:
            self._graph.touch_node(item["memory_id"], timestamp=ts)
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
            "graph": {
                "nodes": len(self._graph.nodes),
                "edges": len(self._graph.edges),
                "causal_edges": sum(1 for edge in self._graph.edges if edge.relation in {"causes", "fixed_by", "leads_to"}),
            },
            "drift": detect_memory_drift(records),
            "compression_candidates": self.compression_candidates(records=records),
        }

    def _write_routed_memory(self, routed: RoutedMemory, text: str) -> dict[str, Any]:
        backend = "none"
        stored = False
        store = self._get_vector_store(routed.collection)
        if store is not None:
            try:
                backend = getattr(store, "backend", "vector")
                topic = routed.payload["routing"]["namespace"]
                result = store.add(routed.id, routed.payload["content_text"] or routed.payload["summary"] or text, topic=topic)
                stored = result is not False
                if backend == "qdrant":
                    point_id = str(int(hashlib.md5(routed.id.encode("utf-8")).hexdigest(), 16) % (2**63))
                    self._vector_id_lookup[point_id] = routed.id
            except Exception as exc:
                log.debug("Governed memory write degraded to catalog-only for %s: %s", routed.id, exc)
        return {"backend": backend, "stored": stored}

    @staticmethod
    def _temporal_score(payload: dict[str, Any], *, now_ts: float) -> float:
        touch_ts = float(payload.get("last_accessed_at") or payload.get("last_updated_at") or payload.get("created_at") or now_ts)
        age_seconds = max(0.0, now_ts - touch_ts)
        return max(0.0, min(1.0, exp(-age_seconds / 604800.0)))

    @staticmethod
    def _access_score(payload: dict[str, Any]) -> float:
        graph_meta = dict(payload.get("graph") or {})
        access_count = int(graph_meta.get("access_count", 0) or 0)
        if access_count <= 0:
            return 0.0
        return min(1.0, access_count / 5.0)

    def _causal_score(self, memory_id: str) -> float:
        relations = [
            edge.relation
            for edge in self._graph.get_edges_from(memory_id) + self._graph.get_edges_to(memory_id)
        ]
        if not relations:
            return 0.0
        causal = sum(1 for relation in relations if relation in {"causes", "fixed_by", "leads_to", "derived_from"})
        if causal <= 0:
            return 0.1
        return min(1.0, 0.35 + (0.15 * causal))

    def compression_candidates(self, *, records: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Return governed semantic compression candidates without deleting memory."""
        with self._lock:
            catalog_records = list(records if records is not None else self._catalog.values())
        clusters: dict[str, list[str]] = {}
        stale: list[str] = []
        preserve: list[str] = []
        now = int(time.time())
        for record in catalog_records:
            summary = str(record.get("summary") or record.get("content_text") or "").lower()
            tokens = sorted({token for token in summary.split() if len(token) > 3})[:4]
            cluster_key = "|".join(tokens) or record.get("memory_type", "memory")
            clusters.setdefault(cluster_key, []).append(str(record.get("memory_id")))
            importance = float(record.get("importance_score", 0.0) or 0.0)
            last_accessed = int(record.get("last_accessed_at") or record.get("created_at") or now)
            if (now - last_accessed) > 86400 and importance < 0.45:
                stale.append(str(record.get("memory_id")))
            if importance >= 0.75 or str((record.get("replay_metadata") or {}).get("trace_id", "")).strip():
                preserve.append(str(record.get("memory_id")))
        semantic_clusters = [
            {"cluster": key, "memory_ids": ids[:8], "count": len(ids)}
            for key, ids in clusters.items()
            if len(ids) > 1
        ]
        return {
            "semantic_clusters": semantic_clusters[:12],
            "duplicate_collapse": [item for item in semantic_clusters if item["count"] > 2][:8],
            "stale_candidates": stale[:12],
            "preserve_high_value": preserve[:12],
            "auto_delete": False,
            "governance_required": True,
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


if __name__ == "__main__":
    print('Running governed_qdrant_memory.py')
