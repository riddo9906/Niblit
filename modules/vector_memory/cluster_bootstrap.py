#!/usr/bin/env python3
"""Python Governed Bootstrap Engine for the Niblit Qdrant cluster.

Mirrors the idempotent logic of ``qdrant_cluster_logic/deployment/initialize_cluster.sh``
in Python, making it callable from the Niblit runtime on startup or from tests.

Bootstrap contract:
  STEP 1: Check if collection already exists.
  STEP 2: If exists → validate schema compatibility (vector size == 384) → log "already governed".
  STEP 3: If missing → create collection with governed schema → register metadata.
  STEP 4: Never overwrite existing collections silently.
  STEP 5: HTTP 409 / "already exists" responses are treated as SUCCESS.

Idempotency guarantee:
  Running ``bootstrap_all_collections()`` any number of times has the same end-state
  as running it once.  Re-runs MUST NOT fail the system.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("Niblit.VectorMemory.ClusterBootstrap")

VECTOR_DIM = 384

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import Distance, VectorParams
    _QDRANT_AVAILABLE = True
except ImportError:  # pragma: no cover
    QdrantClient = None  # type: ignore[assignment,misc]
    Distance = None  # type: ignore[assignment,misc]
    VectorParams = None  # type: ignore[assignment,misc]
    _QDRANT_AVAILABLE = False


# ── Canonical governed collection definitions ──────────────────────────────────
# Each entry maps to one of the 10 governed memory collections.
# payload_indexes mirrors the governance blueprints in qdrant_cluster_logic/collections/*.json.

@dataclass
class CollectionSpec:
    """Governed schema specification for one Niblit memory collection."""
    name: str
    purpose: str
    payload_indexes: List[Dict[str, Any]] = field(default_factory=list)


_GOVERNED_COLLECTIONS: List[CollectionSpec] = [
    CollectionSpec(
        name="episodic_memory",
        purpose="cognition.episodic",
        payload_indexes=[
            {"field_name": "trace_id", "field_schema": "keyword"},
            {"field_name": "runtime_mode", "field_schema": "keyword"},
            {"field_name": "governance_state", "field_schema": "keyword"},
            {"field_name": "lifecycle.state", "field_schema": "keyword"},
            {"field_name": "federation_origin.node_id", "field_schema": "keyword"},
        ],
    ),
    CollectionSpec(
        name="semantic_memory",
        purpose="cognition.semantic",
        payload_indexes=[
            {"field_name": "trace_id", "field_schema": "keyword"},
            {"field_name": "runtime_mode", "field_schema": "keyword"},
            {"field_name": "governance_state", "field_schema": "keyword"},
            {"field_name": "indexing.tags", "field_schema": "keyword"},
            {"field_name": "indexing.keywords", "field_schema": "keyword"},
        ],
    ),
    CollectionSpec(
        name="reflection_memory",
        purpose="cognition.reflection",
        payload_indexes=[
            {"field_name": "trace_id", "field_schema": "keyword"},
            {"field_name": "runtime_mode", "field_schema": "keyword"},
            {"field_name": "governance_state", "field_schema": "keyword"},
            {"field_name": "advisor_lineage", "field_schema": "keyword"},
            {"field_name": "constitutional_alignment.allowed", "field_schema": "bool"},
        ],
    ),
    CollectionSpec(
        name="governance_memory",
        purpose="governance.decisions",
        payload_indexes=[
            {"field_name": "trace_id", "field_schema": "keyword"},
            {"field_name": "runtime_mode", "field_schema": "keyword"},
            {"field_name": "governance_state", "field_schema": "keyword"},
            {"field_name": "constitutional_alignment.authority", "field_schema": "keyword"},
            {"field_name": "lifecycle.governance_locked", "field_schema": "bool"},
        ],
    ),
    CollectionSpec(
        name="runtime_memory",
        purpose="runtime.snapshots",
        payload_indexes=[
            {"field_name": "trace_id", "field_schema": "keyword"},
            {"field_name": "runtime_mode", "field_schema": "keyword"},
            {
                "field_name": "telemetry.epoch_id",
                "field_schema": {"type": "integer", "lookup": False, "range": True},
            },
            {"field_name": "telemetry.source", "field_schema": "keyword"},
            {"field_name": "federation_origin.node_id", "field_schema": "keyword"},
        ],
    ),
    CollectionSpec(
        name="replay_memory",
        purpose="replay.lineage",
        payload_indexes=[
            {"field_name": "trace_id", "field_schema": "keyword"},
            {"field_name": "replay_metadata.trace_id", "field_schema": "keyword"},
            {"field_name": "replay_metadata.causal_references", "field_schema": "keyword"},
            {"field_name": "lifecycle.governance_locked", "field_schema": "bool"},
        ],
    ),
    CollectionSpec(
        name="telemetry_memory",
        purpose="telemetry.history",
        payload_indexes=[
            {"field_name": "trace_id", "field_schema": "keyword"},
            {"field_name": "runtime_mode", "field_schema": "keyword"},
            {
                "field_name": "telemetry.epoch_id",
                "field_schema": {"type": "integer", "lookup": False, "range": True},
            },
            {"field_name": "telemetry.source", "field_schema": "keyword"},
        ],
    ),
    CollectionSpec(
        name="advisor_memory",
        purpose="advisors.debate",
        payload_indexes=[
            {"field_name": "trace_id", "field_schema": "keyword"},
            {"field_name": "advisor_lineage", "field_schema": "keyword"},
            {"field_name": "runtime_mode", "field_schema": "keyword"},
            {"field_name": "governance_state", "field_schema": "keyword"},
        ],
    ),
    CollectionSpec(
        name="federation_memory",
        purpose="federation.provenance",
        payload_indexes=[
            {"field_name": "trace_id", "field_schema": "keyword"},
            {"field_name": "federation_origin.node_id", "field_schema": "keyword"},
            {"field_name": "federation_origin.role", "field_schema": "keyword"},
            {"field_name": "runtime_mode", "field_schema": "keyword"},
        ],
    ),
    CollectionSpec(
        name="execution_memory",
        purpose="reinforcement.outcomes",
        payload_indexes=[
            {"field_name": "trace_id", "field_schema": "keyword"},
            {"field_name": "runtime_mode", "field_schema": "keyword"},
            {"field_name": "governance_state", "field_schema": "keyword"},
            {"field_name": "replay_metadata.trace_id", "field_schema": "keyword"},
            {"field_name": "telemetry.source", "field_schema": "keyword"},
        ],
    ),
]


@dataclass
class BootstrapResult:
    """Result of a single collection bootstrap attempt."""
    name: str
    status: str   # "already_governed" | "created" | "error"
    message: str


class ClusterBootstrap:
    """Idempotent governed bootstrap engine for Niblit's Qdrant memory cluster.

    Usage::

        from modules.vector_memory.cluster_bootstrap import ClusterBootstrap
        results = ClusterBootstrap().bootstrap_all_collections()

    The bootstrap can be called multiple times safely.  Existing collections
    are detected and validated (not overwritten) — HTTP 409 is treated as success.
    """

    def __init__(
        self,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self._url = url if url is not None else os.getenv("QDRANT_URL", "http://localhost:6333")
        self._api_key = api_key if api_key is not None else os.getenv("QDRANT_API_KEY", "")
        self._client: Optional[Any] = None

    def _get_client(self) -> Optional[Any]:
        if not _QDRANT_AVAILABLE:
            return None
        if self._client is not None:
            return self._client
        kwargs: Dict[str, Any] = {"url": self._url, "timeout": 15}
        if self._api_key:
            kwargs["api_key"] = self._api_key
        try:
            self._client = QdrantClient(**kwargs)
            return self._client
        except Exception as exc:
            log.warning("[ClusterBootstrap] failed to connect to Qdrant: %s", exc)
            return None

    def _existing_collection_names(self, client: Any) -> set:
        try:
            return {c.name for c in client.get_collections().collections}
        except Exception as exc:
            log.warning("[ClusterBootstrap] failed to list collections: %s", exc)
            return set()

    def _validate_existing_collection(self, client: Any, name: str) -> bool:
        """Validate that an existing collection conforms to the 384-dim governance contract.

        Returns ``True`` when the contract is satisfied.  Returns ``False`` when a
        concrete dimension mismatch is detected.  When collection info cannot be
        retrieved (transient error), logs a warning and returns ``True`` to avoid
        blocking normal operations on temporary connectivity issues — but this is
        logged explicitly so operators can investigate.
        """
        try:
            info = client.get_collection(name)
            params = getattr(info, "config", None)
            params = getattr(params, "params", params)
            vectors = getattr(params, "vectors", None)
            if vectors is None and isinstance(params, dict):
                vectors = params.get("vectors")
            size = getattr(vectors, "size", None)
            if isinstance(vectors, dict) and size is None:
                size = vectors.get("size")
            if isinstance(size, int) and size != VECTOR_DIM:
                log.error(
                    "[ClusterBootstrap] GOVERNANCE VIOLATION: collection '%s' has "
                    "vector size=%d but governance contract requires %d",
                    name, size, VECTOR_DIM,
                )
                return False
            return True
        except Exception as exc:
            log.warning(
                "[ClusterBootstrap] Could not retrieve schema info for '%s' to validate "
                "the 384-dim governance contract (%s). Treating existing collection as "
                "governed (best-effort). Verify manually if this persists.",
                name, exc,
            )
            return True  # preserve governed state on transient failure; see warning above

    def _ensure_payload_indexes(self, client: Any, spec: CollectionSpec) -> None:
        """Create payload indexes idempotently — 409 = already exists = success."""
        for idx in spec.payload_indexes:
            field_name = idx.get("field_name", "")
            try:
                field_schema = idx["field_schema"]
                # qdrant-client accepts string schema names or dict configs
                client.create_payload_index(
                    collection_name=spec.name,
                    field_name=field_name,
                    field_schema=field_schema,
                )
                log.debug(
                    "[ClusterBootstrap] payload index created: %s.%s", spec.name, field_name
                )
            except Exception as exc:
                exc_str = str(exc).lower()
                if "already exist" in exc_str or "conflict" in exc_str or "409" in exc_str:
                    log.debug(
                        "[ClusterBootstrap] payload index already exists (governed): %s.%s",
                        spec.name, field_name,
                    )
                else:
                    log.warning(
                        "[ClusterBootstrap] payload index creation failed for %s.%s: %s",
                        spec.name, field_name, exc,
                    )

    def bootstrap_collection(self, spec: CollectionSpec) -> BootstrapResult:
        """Idempotently bootstrap a single governed collection.

        Returns a ``BootstrapResult`` describing the outcome.  Never raises on
        409 / "already exists" — that is considered a valid governed state.
        """
        client = self._get_client()
        if client is None:
            msg = "Qdrant unavailable — skipping bootstrap"
            log.warning("[ClusterBootstrap] %s: %s", spec.name, msg)
            return BootstrapResult(name=spec.name, status="error", message=msg)

        existing = self._existing_collection_names(client)

        # STEP 2: Already governed — validate and skip
        if spec.name in existing:
            valid = self._validate_existing_collection(client, spec.name)
            if not valid:
                msg = (
                    f"collection '{spec.name}' exists but violates the 384-dim "
                    "governance contract — manual intervention required"
                )
                log.error("[ClusterBootstrap] %s", msg)
                return BootstrapResult(name=spec.name, status="error", message=msg)
            log.info(
                "[ClusterBootstrap] GOVERNED: '%s' already governed (size=384). Skipping creation.",
                spec.name,
            )
            self._ensure_payload_indexes(client, spec)
            return BootstrapResult(
                name=spec.name,
                status="already_governed",
                message="collection already exists and is schema-compatible",
            )

        # STEP 3: Missing — create
        try:
            client.create_collection(
                collection_name=spec.name,
                vectors_config=VectorParams(size=VECTOR_DIM, distance=Distance.COSINE),
            )
            log.info("[ClusterBootstrap] CREATED: '%s'", spec.name)
            self._ensure_payload_indexes(client, spec)
            return BootstrapResult(
                name=spec.name,
                status="created",
                message=f"collection created with size={VECTOR_DIM}, distance=Cosine",
            )
        except Exception as exc:
            exc_str = str(exc).lower()
            # STEP 4: 409 / "already exists" = success (governed state)
            if "already exist" in exc_str or "conflict" in exc_str or "409" in exc_str:
                log.info(
                    "[ClusterBootstrap] GOVERNED: '%s' already exists (409). Treating as governed success.",
                    spec.name,
                )
                self._ensure_payload_indexes(client, spec)
                return BootstrapResult(
                    name=spec.name,
                    status="already_governed",
                    message="collection already exists (409 treated as governed success)",
                )
            msg = f"collection creation failed: {exc}"
            log.warning("[ClusterBootstrap] ERROR: '%s': %s", spec.name, msg)
            return BootstrapResult(name=spec.name, status="error", message=msg)

    def bootstrap_all_collections(self) -> List[BootstrapResult]:
        """Idempotently bootstrap all 10 governed memory collections.

        Safe to call at startup or in tests — existing collections are preserved
        and validated, not overwritten.

        Returns:
            List of ``BootstrapResult`` objects, one per governed collection.
        """
        results: List[BootstrapResult] = []
        for spec in _GOVERNED_COLLECTIONS:
            result = self.bootstrap_collection(spec)
            results.append(result)
        errors = [r for r in results if r.status == "error"]
        if errors:
            log.error(
                "[ClusterBootstrap] bootstrap completed with %d error(s): %s",
                len(errors),
                [r.name for r in errors],
            )
        else:
            log.info(
                "[ClusterBootstrap] governed bootstrap complete — all %d collections in valid state",
                len(results),
            )
        return results


if __name__ == "__main__":
    print('Running cluster_bootstrap.py')
