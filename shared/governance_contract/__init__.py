"""Canonical governance/runtime contract authority for the Niblit ecosystem."""

from .advisor_protocol import normalize_advisor_votes
from .compatibility_matrix import compatibility_metadata, validate_compatibility
from .constitutional_laws import CONSTITUTIONAL_LAWS, constitutional_verdict
from .event_constants import (
    CANONICAL_EVENTS,
    EVENT_ATTENTION_ALLOCATED,
    EVENT_EXECUTION_ENVELOPE_PUBLISHED,
    EVENT_MARKET_EPISODE_INGESTED,
    EVENT_REFLECTION_COMPLETE,
    EVENT_RESOURCE_ADAPTED,
    EVENT_RUNTIME_MODE_CHANGED,
    EVENT_STATE_UPDATED,
    EVENT_TRADE_REFLECTION_INGESTED,
    EVENT_WORLD_MODEL_UPDATED,
)
from .federation_contract import federation_readiness_payload
from .memory_contracts import (
    CANONICAL_MEMORY_COLLECTIONS,
    MEMORY_LIFECYCLE_STATES,
    collection_blueprints,
    detect_memory_drift,
    governed_recall_allowed,
    memory_retrieval_score,
    normalize_memory_payload,
    reconstruct_memory_lineage,
    transition_memory_lifecycle,
    validate_memory_payload,
)
from .runtime_modes import GOVERNANCE_RUNTIME_MODES, normalize_runtime_mode
from .schema_v2 import SCHEMA_V2_REQUIRED_FIELDS, ensure_schema_v2
from .telemetry_contract import normalize_replay_metadata, normalize_telemetry
from .validators import anti_drift_report, validate_runtime_contract

__all__ = [
    "CANONICAL_EVENTS",
    "CONSTITUTIONAL_LAWS",
    "EVENT_ATTENTION_ALLOCATED",
    "EVENT_EXECUTION_ENVELOPE_PUBLISHED",
    "EVENT_MARKET_EPISODE_INGESTED",
    "EVENT_REFLECTION_COMPLETE",
    "EVENT_RESOURCE_ADAPTED",
    "EVENT_RUNTIME_MODE_CHANGED",
    "EVENT_STATE_UPDATED",
    "EVENT_TRADE_REFLECTION_INGESTED",
    "EVENT_WORLD_MODEL_UPDATED",
    "GOVERNANCE_RUNTIME_MODES",
    "CANONICAL_MEMORY_COLLECTIONS",
    "MEMORY_LIFECYCLE_STATES",
    "SCHEMA_V2_REQUIRED_FIELDS",
    "anti_drift_report",
    "collection_blueprints",
    "compatibility_metadata",
    "constitutional_verdict",
    "detect_memory_drift",
    "ensure_schema_v2",
    "federation_readiness_payload",
    "governed_recall_allowed",
    "memory_retrieval_score",
    "normalize_advisor_votes",
    "normalize_memory_payload",
    "normalize_replay_metadata",
    "normalize_runtime_mode",
    "normalize_telemetry",
    "reconstruct_memory_lineage",
    "transition_memory_lifecycle",
    "validate_compatibility",
    "validate_memory_payload",
    "validate_runtime_contract",
]
if __name__ == "__main__":
    print('Running __init__.py')
