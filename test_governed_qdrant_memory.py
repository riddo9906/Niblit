from __future__ import annotations

from niblit_memory.governed_qdrant_memory import GovernedQdrantMemoryCluster
from shared.governance_contract.memory_contracts import (
    collection_blueprints,
    governed_recall_allowed,
    normalize_memory_payload,
    reconstruct_memory_lineage,
    transition_memory_lifecycle,
    validate_memory_payload,
)


class _StubVectorStore:
    def __init__(self, collection: str, qdrant_url: str = "", qdrant_api_key: str = "") -> None:
        self.collection = collection
        self.backend = "memory"
        self._docs: dict[str, str] = {}

    def add(self, doc_id: str, text: str, topic: str = "") -> bool:
        self._docs[doc_id] = f"{topic} {text}".strip()
        return True

    def search(self, query: str, top_k: int = 5):
        tokens = {token for token in query.lower().split() if token}
        ranked = []
        for doc_id, text in self._docs.items():
            overlap = sum(1 for token in tokens if token in text.lower())
            if overlap:
                ranked.append({"id": doc_id, "text": text, "score": overlap / max(len(tokens), 1)})
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked[:top_k]


def test_normalize_memory_payload_defaults() -> None:
    payload = normalize_memory_payload({}, text="alpha memory", memory_type="semantic_memory")
    assert payload["memory_type"] == "semantic_memory"
    assert payload["lifecycle"]["state"] == "warm"
    assert payload["telemetry"]["runtime_mode"] == "normal"
    assert payload["replay_metadata"]["trace_id"].startswith("trace-")


def test_validate_memory_payload_flags_missing_content() -> None:
    result = validate_memory_payload({"memory_type": "semantic_memory", "text": ""})
    assert not result["valid"]
    assert "memory_content_missing" in result["issues"]


def test_governed_recall_blocks_locked_memory_without_override() -> None:
    payload = normalize_memory_payload(
        {"lifecycle": {"governance_locked": True}, "text": "governance secret"},
        memory_type="governance_memory",
    )
    assert not governed_recall_allowed(payload, governance_state="active")
    assert governed_recall_allowed(payload, governance_state="override")


def test_transition_memory_lifecycle_preserves_replay_trace() -> None:
    payload = normalize_memory_payload(
        {
            "text": "replay memory",
            "last_accessed_at": 0,
            "replay_metadata": {"trace_id": "trace-123"},
            "memory_type": "replay_memory",
        },
        memory_type="replay_memory",
    )
    transition = transition_memory_lifecycle(payload, runtime_pressure=0.95, now_ts=120 * 86400)
    assert transition["state"] == "archived"
    assert transition["action"] == "archive"


def test_reconstruct_memory_lineage_orders_records() -> None:
    first = normalize_memory_payload({"text": "first", "timestamp": 1, "replay_metadata": {"trace_id": "trace-x"}})
    second = normalize_memory_payload({"text": "second", "timestamp": 2, "replay_metadata": {"trace_id": "trace-x"}})
    lineage = reconstruct_memory_lineage([second, first], trace_id="trace-x")
    assert lineage["ordered_memory_ids"] == [first["memory_id"], second["memory_id"]]


def test_governed_cluster_write_recall_lifecycle_and_observability() -> None:
    cluster = GovernedQdrantMemoryCluster(vector_store_factory=_StubVectorStore)
    write = cluster.write_memory(
        "reflection shows coherence drift in cautious runtime",
        memory_type="reflection_memory",
        payload={
            "runtime_mode": "cautious",
            "coherence_score": 0.74,
            "advisor_lineage": ["reflection_engine"],
            "replay_metadata": {"trace_id": "trace-r1", "causal_references": ["m-1"]},
        },
    )
    assert write["stored"] is True
    results = cluster.recall("coherence drift cautious", memory_types=["reflection_memory"], governance_state="override")
    assert results
    assert results[0]["payload"]["memory_type"] == "reflection_memory"
    lifecycle = cluster.apply_lifecycle(runtime_pressure=0.5, now_ts=15 * 86400)
    assert lifecycle["count"] >= 1
    replay = cluster.reconstruct_replay("trace-r1")
    assert replay["ordered_memory_ids"] == [write["memory_id"]]
    snapshot = cluster.observability_snapshot()
    assert snapshot["records"] >= 1
    assert "reflection_memory" in snapshot["by_collection"]


def test_collection_blueprints_include_required_memory_collections() -> None:
    blueprints = collection_blueprints()
    for required in (
        "episodic_memory",
        "semantic_memory",
        "reflection_memory",
        "governance_memory",
        "runtime_memory",
        "replay_memory",
        "telemetry_memory",
        "advisor_memory",
        "federation_memory",
        "execution_memory",
    ):
        assert required in blueprints
