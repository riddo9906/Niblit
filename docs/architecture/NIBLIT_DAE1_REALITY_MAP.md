# Niblit DAE-1 reality map

This is an incremental discovery and implementation checkpoint on 7 November 2026.
The complete DAE-1 acceptance is pending. Historical r8/r9.1 evidence is retained separately.

## Actual roots and compatibility

The four established sibling repositories are under C:/Users/Riyaad/Documents/GitHub.
No separate NiblitAIOS checkout was established. DAE-1 extends Core in place.
All preexisting tracked and untracked changes are preserved.
See DAE1_CONFIGURATION_REFERENCES.json for exact HEADs, status and reference locations.
The original Gateway 0.1 remains in the Codex outputs directory and its original ZIP.
Version 0.2 is staged under deploy/vps-gateway. It requires distinct read and stop tokens.
A 0.1 client cannot assume the 0.2 envelope. SQLite gains additive history/checkpoint/control tables.
No live runtime configuration or running release was replaced.

## Runtime graph and ownership

Desktop Core -> existing cognitive ingress / brain / command registry / execution graph.
Core -> existing task admission -> local inference and tool execution.
Core trading -> existing demo sessions / deterministic funded evaluator.
Core trading status -> new remote observation client -> operator-verified SSH forward
-> loopback Gateway 0.2 -> explicit terminal and bound XM account.
Core status -> existing Market Desk sessions route -> remote observation panel.
Canonical memory SQLite -> ingestion outbox -> existing projection worker -> Qdrant.
Existing Docker portal and Freqtrade retain their existing compose ownership and networks.
The VPS runs Windows, MT5 and the lightweight gateway. Heavy inference remains desktop-owned.

## Process and resource evidence

Fresh privileged process inspection found no matching niblit, llama or terminal64 process.
This differs from the earlier r8 PID inventory. No process was stopped by this implementation.
Selected listeners observed only Docker-published 8080, 6333 and 6334, all loopback.
Docker reported existing portal healthy, Freqtrade running and Qdrant v1.18.0 running.
Container process status does not establish broker mode, authorization or position state.
Exact evidence is saved in the session work/dae1/runtime-baseline.json.
Open database handle ownership, current broker positions and active runtime scopes remain unverified.
The RDP client reported that the VPS was restarting and ended the interactive session.
User Windows sign-in and secure administrative access are required before remote inspection.

## Capability inventory

| Subsystem | Source evidence | Classification and limit |
| --- | --- | --- |
| Core startup | niblit_core.py:3 · NiblitCore | Implemented; current service not observed |
| Brain Router | niblit_brain.py:23 · NiblitBrain | Implemented; live inference unverified this milestone |
| Command registry | modules/command_registry.py:14 · CommandRegistry | Implemented; admission must remain authoritative |
| Execution graph | modules/execution_graph.py:17 · ExecutionGraph | Implemented with existing modifications; regression pending |
| Tool loop | modules/llm_tool_loop.py:? · LLMToolLoop | Implemented with existing modifications; no live tool execution attempted |
| Distributed contracts | modules/distributed_runtime_coordinator.py:40 · DistributedRuntimeCoordinator | Implemented; static nodes are configuration, observed refresh is separate |
| Resource monitoring | modules/runtime_resource_manager.py:135 · RuntimeResourceManager | Partial; RAM/CPU and latency available in implementation, GPU and IO coverage pending |
| Scheduler | aios_scheduler.py:14 · AIOSScheduler | Implemented with preexisting modifications; resource admission integration pending |
| Memory canonical outbox | modules/memory_laboratory/runtime.py:53 · MemoryRuntime | Implemented and called by Core; live projection acceptance pending |
| Qdrant | deploy/memory-laboratory.compose.yml:2 · qdrant | Existing v1.18.0 container observed running on loopback; API/volume recovery pending |
| Research | modules/phased_research_engine.py:402 · PhasedResearchEngine | Implemented with preexisting modifications; isolated workload migration pending |
| ALE | modules/autonomous_learning_engine.py:150 · AutonomousLearningEngine | Implemented with preexisting modifications; promotion acceptance pending |
| Strategy assessment | modules/strategy_manager.py:172 · assess_with_context | Implemented; six-strategy and replay regression scheduled |
| Trading authority | modules/core_trading_sessions.py:52 · CoreTradingSessions | Implemented; durable demo sessions and funded evaluation, no funded authority |
| Funded risk | modules/funded_risk.py:40 · evaluate | Implemented deterministic rejection; no policy grants authority |
| Desktop MT5 | modules/mt5_bridge.py:58 · MT5Bridge | Implemented; XM connectivity unverified, remote profile suppresses local status probes |
| Freqtrade | modules/trading_session_adapters.py:194 · FreqtradeSessionAdapter | Implemented; container running, engine and position state unverified |
| Gateway 0.2 | deploy/vps-gateway/gateway.py:61 · Monitor | Source candidate; history checkpoints and scoped stop; real VPS deployment pending |
| Core remote client | modules/remote_broker_gateway.py:45 · RemoteBrokerGateway | Source integration; strict identity/freshness, actual remote acceptance pending |
| Market Desk | assets/trading-desk/sessions.js:39 · refresh | Source integration for remote panel; browser runtime verification pending |
| Inference runtime | modules/local_brain.py:1 · LocalBrain | Implemented with preexisting modifications; no llama process observed |
| Build | niblit.spec:220 · Analysis | Existing packaged pipeline; DAE-1 frozen build and multirepo locking pending |

## Configuration map

DAE1_CONFIGURATION_REFERENCES.json records every assignment in the four root .env.example
templates with duplicate assignment line numbers and source literal reference locations.
The scan excludes diagnostics, tests and generated output. A literal occurrence is a
reference candidate, not proof of an effective runtime consumer. Empty lists flag keys
requiring manual review for dead, dynamic or external use. Values and private dotenv files
are excluded. Full dynamic consumer tracing and redacted effective-source reporting remain pending.
The new NIBLIT_VPS_GATEWAY_PROFILE points to one explicit JSON profile. It does not activate
observation until authenticated remote data passes account, schema, authority and age checks.

## Security and data boundaries

Remote Core access is GET-only and uses the observation token. The persistent stop requires
a distinct control token, UUID and a timestamp within 60 seconds. Duplicate UUIDs are rejected
in the same SQLite transaction as the stop. The gateway binds only 127.0.0.1.
SSH host-key verification remains an operator/deployment prerequisite; Core cannot prove
tunnel provenance by seeing a loopback port. No funded broker mutation implementation exists.
Selecting the remote profile blocks local MT5 session observation and proposal activation.
Broker history is account-bound, uses broker ticket IDs and idempotent payload fingerprints.
A checkpoint advances only with the inventory/history transaction. Reads overlap five minutes.
Initial history coverage is the preceding 24 hours. This is not a full account history backfill.
Late broker corrections older than the overlap require an explicit backfill.
Unknown commission schedules and subtype remain null.

## Integration gaps and risk register

Remote Windows hardening, Python/MT5 installation, XM login, SSH/tunnel validation, real
broker history and VPS restart testing remain blocked on remote access.
Client-side HTTP doubles establish transport behavior only. They do not establish XM health.
Full source inventory classification, Docker migrations, inference optimization, resource
scheduling integration, continuous improvement promotion and reproducible multirepo builds
remain pending. Existing resource and memory implementations should be extended after those
boundaries are verified. No new parallel memory authority or execution engine was introduced.

## Rollback

Preserve subsequent changes. Review hashes before restoring only this milestone's modifications
from work/dae1/preimages. Remove the explicit remote profile selection to restore prior local
demo configuration only after inspecting outstanding local sessions. Preserve gateway databases
and emergency latches. Revert application code independently of additive journal data.
No automatic production cutover or live broker recovery was performed.

## Tested checkpoint update

The source scheduler now has a bounded queue, reserved interactive slots, bounded retired history,
cancellation checks and optional RAM admission through the existing resource manager. Runtime RAM
admission defaults off. This does not complete GPU, IO, latency or distributed placement admission.
Qdrant candidate Compose was validated, and its readiness command returned HTTP 200 against the
existing container. Its named volume is niblit_memory_qdrant. No container was recreated.
Remote RDP TCP connectivity was verified. SSH was unreachable and RDP graphics capture timed out.
The Windows server interior and XM account remain unverified.
The configuration reference scan now includes 280 Core keys after the two new controls.
Source configuration fields, gateway histories and test manifests remain partial DAE-1 deliverables.
