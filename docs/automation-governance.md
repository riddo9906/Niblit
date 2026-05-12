# Automation Governance (Phase Ω.8)

## Governance Responsibilities

Automation workflows must:

- classify architecture/governance/schema/runtime/federation impact
- emit structured outputs for orchestration
- include drift risk scoring
- avoid semantic drift from canonical contracts

## Allowed Automation Scope

Allowed:

- diagnostics aggregation
- low-risk tooling/docs changes
- compatibility reporting
- drift detection

Restricted:

- changing canonical schema semantics without governance review
- introducing alternate runtime mode meanings
- introducing alternate event naming contracts
- bypassing constitutional/governance gates

## Workflow Conventions

- use workflow concurrency controls to avoid overlapping bots
- produce structured JSON artifact outputs
- include confidence and impact classification in outputs
- route high-risk changes through governance review

## Synchronization Expectations

Autonomous workflows are orchestration participants, not independent authorities.
Canonical authority resides in shared governance contracts under:

- `shared/governance_contract/`
