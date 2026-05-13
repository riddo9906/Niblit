# Governed Qdrant Memory Cluster Logic

This package turns Qdrant into a governed cognitive memory cluster for the Niblit ecosystem. It aligns the cluster with Niblit's schema-v2 governance authority, Niblit-cloud-server runtime portability semantics, and niblit-lean-algos replay-compatible execution cognition.

## What this package contains

- `collections/` — governance blueprints for the ten canonical governed memory collections
- `deployment/api_payloads/` — exact JSON payloads to paste into the Qdrant Cloud create-collection UI/API
- `payload_schemas/` — canonical governed payload shapes for memory, governance, replay, and federation metadata
- `governance_schemas/` — lifecycle, routing, and governance policies
- `deployment/` — copy/paste-ready Qdrant Cloud setup, payload index, and snapshot commands

## Memory flow

1. Niblit normalizes memory payloads through `shared/governance_contract/memory_contracts.py`.
2. The governed runtime layer writes normalized memories to the matching collection namespace.
3. Retrieval applies governance locks, constitutional alignment, lifecycle state, runtime mode, and reinforcement-aware ranking.
4. Replay lineage is reconstructed from `trace_id`, `decision_lineage`, and `causal_references`.
5. Federation metadata keeps cross-node provenance explainable and replay-safe.

## Collection relationships

- `episodic_memory` captures interaction turns and runtime episodes.
- `semantic_memory` stores durable knowledge and compressed summaries.
- `reflection_memory` stores reflective critiques and adaptation proposals.
- `governance_memory` stores constitutional and governance decisions.
- `runtime_memory` stores runtime snapshots from the distributed coordinator.
- `replay_memory` stores deterministic lineage and replay-safe causal traces.
- `telemetry_memory` stores normalized telemetry and health history.
- `advisor_memory` stores debates, votes, and advisor lineage.
- `federation_memory` stores cross-node shared memory provenance.
- `execution_memory` stores execution outcomes and reinforcement anchors.

## Governance model

Governance-aware memory behavior is driven by:

- runtime mode normalization (`normal`, `cautious`, `survival`, `lockdown`)
- constitutional alignment checks
- lifecycle state transitions (`hot`, `warm`, `cold`, `archived`)
- replay lineage preservation
- governance locks for replay/governance collections
- federation origin tracing for cross-node memory movement

## Deployment order

1. Export environment variables from `deployment/env.example`.
2. Run `deployment/initialize_cluster.sh`.
3. Run `deployment/create_payload_indexes.sh`.
4. Upload or verify snapshots with `deployment/snapshot_recovery.sh`.
5. Point Niblit runtime to the cluster with `QDRANT_URL`, `QDRANT_API_KEY`, and `QDRANT_COLLECTION_PREFIX`.

## Qdrant Cloud instructions

- Open Qdrant Cloud and copy the cluster URL + API key.
- Use `deployment/api_payloads/*.json` directly in the Qdrant Cloud collection creation UI or API.
- Use `collections/*.json` as the operator-facing governance blueprint for shard strategy, retention, lifecycle, and index requirements.
- Use `curl_examples.md` if you want one-command examples before running the scripts.
- In the Qdrant Cloud UI, create the collection first, then add the listed payload indexes from the matching governance blueprint.

## Troubleshooting

- If collection creation fails, confirm the API key has write access and the URL includes the correct region host.
- If payload indexes fail, create them one by one from `curl_examples.md` to isolate the field causing the error.
- If retrieval quality drifts, inspect `governance_schemas/lifecycle_policy.json` and compare runtime pressure to stored lifecycle state.
- If federation lineage looks inconsistent, verify the `federation_origin` payload and `trace_id` normalization in the Python runtime layer.
