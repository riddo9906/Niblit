# Automation Governance (Phase Ω.8)

## Governance Responsibilities

All automation workflows in the Niblit ecosystem operate as **orchestration
participants**, not independent authorities. Canonical authority resides
exclusively in `shared/governance_contract/`.

Every workflow that modifies or evaluates architecture must:

- classify its impact across four governance dimensions:
  `governance_impact`, `schema_impact`, `runtime_impact`, `federation_impact`
- emit a structured JSON output artifact using `build_workflow_output()`
- include a `drift_risk` score derived from the impact classification
- include a `confidence` score for the assessment
- avoid introducing semantics that diverge from canonical contracts

---

## Authority Hierarchy

```
shared/governance_contract/    ← canonical authority (read-only for workflows)
  ├── schema_v2.py             ← schema field definitions
  ├── runtime_modes.py         ← mode semantics
  ├── event_constants.py       ← canonical event names
  ├── compatibility_matrix.py  ← interoperability version metadata
  ├── constitutional_laws.py   ← constitutional law identifiers
  ├── telemetry_contract.py    ← telemetry/replay field definitions
  ├── federation_contract.py   ← federation readiness structure
  ├── advisor_protocol.py      ← advisor vote normalization
  └── validators.py            ← anti-drift + contract validation

nibblebots/workflow_governance_helpers.py  ← workflow output helpers
.github/workflows/niblit-cognitive-orchestrator.yml  ← orchestration hub
```

---

## Allowed Automation Scope

### Permitted actions

- diagnostics aggregation and compatibility reporting
- drift detection and governance alignment reporting
- documentation generation and schema version tracking
- low-risk tooling and environment management
- structured output artifact creation
- governance event observation and classification

### Restricted actions (require governance review)

- changing canonical schema field names or semantics
- introducing alternate runtime mode meanings or new modes
- introducing alternate event naming contracts
- modifying compatibility version strings
- bypassing constitutional/governance gates
- creating autonomous architectural mutations without human review

---

## Workflow Conventions

### Concurrency control

All non-trivial workflows must declare a `concurrency` block to prevent
overlapping runs that could create conflicting governance signals:

```yaml
concurrency:
  group: <workflow-name>-${{ github.ref }}
  cancel-in-progress: false  # use true only for non-governance workflows
```

Governance and orchestration workflows must use `cancel-in-progress: false` to
ensure governance signals are never silently dropped.

### Structured artifacts

Every governance/orchestration workflow must upload a JSON artifact containing
the `build_workflow_output()` payload, enabling downstream orchestration
workflows to aggregate governance signals.

### Timeout handling

Long-running workflows must declare `timeout-minutes` to prevent runaway
autonomous behavior:

```yaml
jobs:
  job-name:
    timeout-minutes: 30
```

### Impact classification

Use these levels consistently:

| Level | Meaning |
|---|---|
| `none` | No impact on the governed dimension |
| `low` | Observational / read-only change |
| `medium` | Configuration or tooling change with bounded effect |
| `high` | Semantic or contract change with ecosystem-wide effect |

---

## Workflow Inventory

| Workflow | Scope | Concurrency |
|---|---|---|
| `niblit-cognitive-orchestrator.yml` | Governance aggregation hub | ✅ |
| `niblit-autonomous-evolution.yml` | Auto-fix proposals | ✅ |
| `test.yml` | CI lint + test | ✅ |
| `deploy.yml` | Deployment | ✅ |
| `nibblebot-*.yml` | Research / improvement bots | varies |

---

## Anti-Drift Enforcement

The anti-drift system (`shared/governance_contract/validators.py`) detects
three categories of semantic drift:

1. **Runtime contract invalidity** — schema or mode violations in live payloads.
2. **Compatibility mismatch** — version metadata diverging from canonical.
3. **Unknown events** — event names not in `CANONICAL_EVENTS`.

Drift risk thresholds:

| Active Drift Factors | Drift Risk |
|---|---|
| 0 | `low` |
| 1 | `medium` |
| 2+ | `high` |

High-drift findings must be escalated to the governance orchestrator workflow
and must not be silently suppressed by autonomous bots.

---

## Interoperability Expectations

### Niblit → cloud-server

- Niblit exposes `/niblit/runtime`, `/cluster/status`, `/federation/status`
  as the canonical governance/runtime metadata surface.
- cloud-server `RuntimeAdapter` polls `/niblit/runtime` to derive runtime mode
  and governance context for inference execution.
- cloud-server must consume runtime mode values as defined in
  `runtime_modes.py` without redefining them.

### Niblit → lean-algos

- Niblit's `lean_algo_manager.py` publishes schema-v2 cognitive execution
  envelopes to a signal file consumed by lean-algos.
- lean-algos `cognitive_envelope.py` reads and normalizes these envelopes.
- lean-algos must use canonical field names as defined in `schema_v2.py`.
- lean-algos `TradeGovernanceGate` evaluates governance mode from the envelope;
  mode semantics are canonical and owned by Niblit.

### cloud-server → lean-algos

- cloud-server does not directly own governance semantics for lean-algos.
- Any runtime signals cloud-server relays to lean-algos must preserve Niblit's
  canonical schema and mode semantics.

---

## Replay/Governance Compatibility

Replay traces written by lean-algos must be interpretable without re-running
the original execution. Compatibility guarantees:

- `trace_id` uniquely identifies each governed decision.
- `governance_replay` captures mode, constitution pass/fail, and risk tier at
  decision time.
- Replay readers must tolerate additional fields (forward compatibility).
- Replay writers must not remove fields listed in `normalize_replay_metadata()`
  (backward compatibility).

---

## Synchronization Expectations

Autonomous workflows are orchestration participants, not independent
authorities. Rules:

1. Canonical authority resides in `shared/governance_contract/` — workflows
   read this, they do not write to it autonomously.
2. Proposals from autonomous workflows are advisory; human review is required
   before merging changes that affect canonical contracts.
3. All governance signals are aggregated by `niblit-cognitive-orchestrator.yml`;
   individual bots must not act independently on high-drift findings.
4. Schema or event contract changes require explicit governance review and a
   compatibility matrix version bump.

