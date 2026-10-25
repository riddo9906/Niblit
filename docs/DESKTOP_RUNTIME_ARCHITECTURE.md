# Desktop runtime connections

The integrated folder contains four repository products. Launch Core with
`Start-Niblit-Testing.cmd`; the standalone UI installer does not include them all.

| Product | Role | Desktop boundary |
| --- | --- | --- |
| Niblit Core | Governs commands, memory, cognitive processing and service ownership | Core API on loopback port 5000 and runtime WebSocket |
| niblit-ui | Presents conversations, files, commands, configuration and subsystem state | Calls Core; it does not manufacture subsystem health |
| niblit-cloud-server | Owns model discovery and inference execution | Core-owned inference proxy to loopback port 8000 |
| niblit-lean-algos | Owns trading runtime state and validation | Packaged Core HTTP client to loopback port 8100 |

Core starts the packaged runtime dependencies early, waits for deferred Core
initialization, verifies readiness, starts its API, waits for Cloud and the
required Lean runtime, then opens the desktop. Healthy existing sidecars can be
attached without pretending to own their processes. The frozen runtime resolves
components beside its executable and does not require a developer checkout.

Core's runtime manager and the UI runtime use explicit bridges to the module
event bus. These remain distinct objects; shared concepts or a window opening
are not evidence that a bridge is active. The Architecture view reports actual
bus identities, bridge flags, persistent memory, repository discovery, process
supervision, Cloud reachability and Lean readiness. Failed checks stay visible.

KnowledgeDB owns canonical knowledge. Its compatibility facade shares the same
writer when configured for the same file. SQLite stores paired conversation
exchanges. The default Runtime chat follows Core's processing and memory policy;
direct Model chat is a separate inference view and is not evidence that a fact
was promoted to canonical knowledge. See `MEMORY_STRUCTURE.md` for ownership.

Original commands are discovered from the live registry and packaged CLI source.
Only commands bound into the governed execution registry can be prepared in the
UI. Execution uses the same validation, availability and permission checks as
the model tool loop. Operator-only and unavailable entries remain discoverable
without being falsely labelled executable.

Testing starts in paper/observe mode. An operator can enable simulated orders in
Trading. Core sends intents to the separate Lean runtime; that runtime owns
validation, risk, idempotency, paper accounting and execution records. Its owned
Freqtrade worker supplies strategy signals over explicitly recorded candles.
The worker never places orders. Cloud supplies optional local AI approval before
an eligible strategy intent enters the same runtime decision pipeline.

Replay cursor/pending acknowledgements and paper account state survive restart.
Cash is reserved on entry; exit releases it and records fees and realized net
PnL. Live exchange execution is not enabled by this operator profile. The UI
submits requests through Core and displays backend outcomes; it owns no ledger.

Remote providers,
external vector stores and other optional services require their own available
configuration; their absence must not be hidden by the UI.
