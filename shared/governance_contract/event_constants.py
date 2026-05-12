"""Canonical event semantics shared across core/cloud/lean repos."""

EVENT_EXECUTION_ENVELOPE_PUBLISHED = "execution_envelope.published"
EVENT_TRADE_REFLECTION_INGESTED = "trade_reflection.ingested"
EVENT_MARKET_EPISODE_INGESTED = "market_episode.ingested"
EVENT_RUNTIME_MODE_CHANGED = "runtime_mode.changed"
EVENT_ATTENTION_ALLOCATED = "attention.allocated"
EVENT_RESOURCE_ADAPTED = "resource.adapted"
EVENT_WORLD_MODEL_UPDATED = "world_model.updated"
EVENT_REFLECTION_COMPLETE = "reflection.complete"
EVENT_STATE_UPDATED = "state.updated"

CANONICAL_EVENTS = {
    EVENT_EXECUTION_ENVELOPE_PUBLISHED,
    EVENT_TRADE_REFLECTION_INGESTED,
    EVENT_MARKET_EPISODE_INGESTED,
    EVENT_RUNTIME_MODE_CHANGED,
    EVENT_ATTENTION_ALLOCATED,
    EVENT_RESOURCE_ADAPTED,
    EVENT_WORLD_MODEL_UPDATED,
    EVENT_REFLECTION_COMPLETE,
    EVENT_STATE_UPDATED,
}


if __name__ == "__main__":
    print('Running event_constants.py')
