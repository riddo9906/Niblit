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
    "SCHEMA_V2_REQUIRED_FIELDS",
    "anti_drift_report",
    "compatibility_metadata",
    "constitutional_verdict",
    "ensure_schema_v2",
    "federation_readiness_payload",
    "normalize_advisor_votes",
    "normalize_replay_metadata",
    "normalize_runtime_mode",
    "normalize_telemetry",
    "validate_compatibility",
    "validate_runtime_contract",
]
if __name__ == "__main__":
    print('Running __init__.py')
