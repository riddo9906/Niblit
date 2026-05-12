# Niblit Architecture Principles (Phase Ω.8)

## Ecosystem Overview

The Niblit ecosystem consists of three repositories with distinct authority
boundaries:

| Repository | Authority Role |
|---|---|
| **riddo9906/Niblit** | Canonical Governance + Orchestration Authority |
| **riddo9906/Niblit-cloud-server** | Canonical Runtime Portability Authority |
| **riddo9906/niblit-lean-algos** | Canonical Execution Cognition Authority |

Authority boundaries are strict: no repository may redefine semantics owned
by another.

---

## Canonical Authority Boundaries

### Niblit (this repository)

Niblit owns and exports the following canonical semantics via
`shared/governance_contract/`:

- **schema-v2 contract**: field names, types, normalization rules, and required
  fields for cognitive execution envelopes.
- **governance semantics**: runtime mode meanings (`normal`, `cautious`,
  `survival`, `lockdown`), governance stability logic, constitutional laws.
- **advisor protocol semantics**: vote shapes, consensus normalization,
  direction enumeration (`BUY`, `SELL`, `HOLD`).
- **event contract semantics**: canonical event names and the closed set of
  known events (`CANONICAL_EVENTS`).
- **compatibility contract metadata**: version keys and acceptable value ranges
  for cross-repo interoperability negotiation.
- **federation readiness contract**: node advertisement payload structure and
  capability metadata format.
- **telemetry normalization**: canonical field names and clamping rules for
  runtime telemetry and replay metadata.
- **constitutional laws**: the seven constitutional laws and lightweight
  constitutional verdict logic.
- **anti-drift validation**: `anti_drift_report` and `validate_runtime_contract`
  for detecting schema drift, mode mismatches, and unknown events.

**What Niblit must NOT own:**

- runtime portability or execution profiles → cloud-server authority
- execution cognition, strategy logic, or replay trace writing → lean-algos authority
- active distributed networking → deferred beyond Ω.8

### Niblit-cloud-server

Owns and exports:

- runtime profiles and portability semantics across deployment environments
- sidecar/runtime communication protocol (UNIX socket, TCP, HTTP)
- governance-aware runtime execution and health probes
- portability diagnostics and anti-drift runtime tooling
- runtime telemetry normalization for inference/model layers

Consumes from Niblit: schema-v2, runtime modes, event constants,
compatibility metadata.

### niblit-lean-algos

Owns and exports:

- execution cognition and governed strategy execution
- replay-compatible governance decision traces
- TradeGovernanceGate and execution routing logic
- execution telemetry and realized-outcome reconciliation
- advisor vote parsing and debate/consensus logic

Consumes from Niblit: schema-v2 canonical field definitions, runtime mode
names, canonical events, advisor protocol structure, compatibility contract.

---

## Distributed Runtime Topology

```
Niblit (governance authority)
  ├── shared/governance_contract/   ← canonical contracts (read by all)
  ├── modules/distributed_runtime_coordinator.py
  ├── modules/federation_foundation.py
  ├── api/federation.py             ← /federation/status, /federation/peers
  └── app.py                        ← /niblit/runtime, /cluster/status

Niblit-cloud-server (runtime portability authority)
  ├── tools/lib/sidecar_client.py   ← consumes schema-v2 normalization
  ├── tools/runtime_profiles/       ← deployment environment profiles
  └── tools/lib/runtime_profiles.py ← profile loader

niblit-lean-algos (execution cognition authority)
  ├── freqtrade_strategies/cognitive_envelope.py  ← reads schema-v2 envelopes
  ├── freqtrade_strategies/runtime_adapter.py     ← probes /niblit/runtime
  ├── freqtrade_strategies/trade_governance.py    ← governance-gated execution
  └── freqtrade_strategies/execution_replay.py    ← replay trace writer
```

---

## Compatibility Guarantees

All subsystems negotiate compatibility through the canonical compatibility
metadata structure (`shared/governance_contract/compatibility_matrix.py`):

| Key | Value |
|---|---|
| `schema_version` | `"2.x"` |
| `event_contract_version` | `"omega-7"` |
| `governance_contract_version` | `"1.x"` |
| `advisor_protocol_version` | `"2.x"` |
| `runtime_mode_contract` | `"2026.05"` |

Compatibility rules:
- An incoming value is checked against the canonical expected value.
- An absent key is treated as compatible (backward-compatible default).
- Any non-empty value that diverges from the canonical value is a mismatch.

---

## Schema Evolution Rules

1. New fields in schema-v2 envelopes must have safe defaults and be backward
   compatible — existing normalizers must still accept envelopes without the
   new field.
2. Field names and top-level sections (`governance`, `runtime`, `temporal`,
   `resources`, `trace`, `advisors`) are stable and must not be renamed.
3. New governance modes may only be added to `GOVERNANCE_RUNTIME_MODES` if
   they do not conflict with existing mode semantics.
4. New canonical events may be added to `CANONICAL_EVENTS` if they represent
   genuinely new semantic categories; existing event names must not change.
5. Compatibility matrix version strings must be updated when a breaking
   semantic change is introduced.

---

## Runtime Mode Contract

Four canonical runtime modes govern execution across all repositories:

| Mode | Rank | Semantics |
|---|---|---|
| `normal` | 0 | Full execution authority, no special constraints |
| `cautious` | 1 | Reduced position sizing, elevated monitoring |
| `survival` | 2 | Minimal exposure, capital preservation priority |
| `lockdown` | 3 | No new execution, awaiting governance clearance |

The alias `constrained` normalizes to `cautious` for backward compatibility.

---

## Federation Philosophy

Federation in Phase Ω.8 is contract-first:

- **Readiness metadata**: each node advertises capabilities and compatibility.
- **Capability advertisements**: Niblit advertises governance/schema/event
  authority; cloud-server advertises runtime portability; lean-algos advertises
  execution cognition.
- **Compatibility negotiation**: nodes check each other's compatibility metadata
  before trusting runtime signals.
- **Sync placeholders**: actual distributed sync is deferred; stubs exist to
  ensure APIs are stable for future activation.

No active distributed networking or peer discovery is required in Ω.8.

---

## Anti-Drift Guarantees

Drift is defined as semantic divergence from the canonical contracts. The
anti-drift system detects:

1. **Runtime contract invalidity**: missing required schema-v2 fields,
   runtime/governance mode mismatch.
2. **Compatibility mismatch**: incoming metadata that diverges from canonical
   version strings.
3. **Unknown events**: events observed on the bus that are not in
   `CANONICAL_EVENTS`.

Drift risk is classified as `low` / `medium` / `high` based on the number of
active drift factors.

---

## Replay Governance Semantics

Replay-compatible governance traces must include:

- `trace_id` / `causal_trace_id`: unique causal identifier for the decision.
- `decision_lineage`: ordered list of contributing factors.
- `confidence_evolution`: sequence of confidence scores during deliberation.
- `governance_replay`: dict capturing governance mode and constitutional state
  at decision time.
- `causal_references`: identifiers of memory/model inputs that influenced
  the decision.

Niblit owns the canonical field names; lean-algos owns the trace writing logic.

