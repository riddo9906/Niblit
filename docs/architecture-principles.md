# Niblit Architecture Principles (Phase Ω.8)

## Canonical Authority Boundaries

Niblit is the canonical authority for:

- schema-v2 contract semantics
- governance semantics and runtime mode meaning
- advisor protocol semantics
- event contract semantics
- compatibility contract metadata

Cloud/runtime and execution repos consume these semantics and must not redefine them.

## Distributed Runtime Topology

- **Niblit (core authority)**: governance, constitutional reasoning, orchestration, memory, anti-drift validation.
- **Niblit-cloud-server (runtime node)**: inference/runtime execution and cloud diagnostics consuming canonical contracts.
- **niblit-lean-algos (execution node)**: governed market execution and replay telemetry consuming canonical contracts.

## Compatibility Guarantees

All subsystems align to canonical metadata keys:

- `schema_version`
- `event_contract_version`
- `governance_contract_version`
- `advisor_protocol_version`
- `runtime_mode_contract`

## Federation Philosophy

Federation is contract-first in this phase:

- readiness metadata
- capability advertisements
- compatibility checks
- sync placeholders

No active distributed networking is required in Ω.8.
