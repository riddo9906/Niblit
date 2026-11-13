# Capability modernization — 2026-11-12

This work extends the existing runtime. Registration, authorization, initialized dependencies, active work and demonstrated results are separate states. The current inventory contains 414 operator entries: 382 executable, 17 protected trading families and 15 unavailable (external/CLI/dependency constraints). Executable metadata is not proof that every command's side effect has passed runtime acceptance.

| Layer | Existing authority | Implemented advancement | Acceptance / next work |
|---|---|---|---|
| Infrastructure | Core, Brain Router, RuntimeManager, command registry | Lifecycle receipts and actual start/stop postconditions; Core-owned authenticated local learning transport reuses canonical memory | One real local ALE cycle completed; Lean unavailable at startup remains degraded, not hidden |
| Perception | MT5Bridge and broker/session adapters | Explicit desktop account/terminal binding, bounded account-scoped candle cache, independent observation while VPS unavailable | Exness demo 486129611 / Exness-MT5Trial10 verified; execution routing is unchanged |
| Recognition | Existing MT5 native context and six-rule indicators | Versioned closed-candle patterns, confirmed swings, structure and SMA/EMA/RSI/ATR/Bollinger evidence | M5/H1/H4 slice verified; full formations, standard indicator parity and calendar-aware timeframes pending |
| Cognition | CognitiveIngress / ExecutionGraph | Same snapshot IDs through deterministic Core analysis and existing scoped outbox | Actual six-vote analysis + memory queue receipt; projection/retrieval quality is a separate gate |
| Strategy | Six existing demo_strategy rules / strategy_manager | Shared immutable evidence attached as advisory context without extra votes | Existing vote/consensus rules unchanged; no thresholds or risk permissions promoted |
| Governance | PermissionManager, funded risk, sessions and breakers | Learning start consumes one bounded task; stop reports unfinished ownership; failed activation cannot be called success | Funded mutations remain disabled; broad live-trading families stay protected |
| Continuous observation | Existing position intelligence/reconciliation | Desktop observation does not depend on VPS; cached data retains receipt/freshness state | Desktop demo execution selection, MQL5 buffer publishing and sustained outage tests remain pending |
| Learning | ALE, SelfTeacher, BrainTrainer, canonical MemoryRuntime | Exact local-only task, one model call, source observation, citation review and unverified episodic receipt | Real result was knowledge_gap, not verified knowledge; weight training and automatic promotion remain off |
| Optimization | Existing research/replay and release workflow | Versioned candidate, manifest, resource-limited portal image/Compose, backup/restore helpers | Data-quality expansion, calibration, cost-aware walk-forward and no-trade outcome evaluation are queued |

## Priorities for older and newer capabilities

1. Resolve actual dependencies and broken lifecycle wiring before adding parallel modules. Keep status handlers read-only; start handlers must prove owned work and stop handlers must retain uncertain ownership.
2. Modernize the old desktop-versus-remote presentation into explicit capability selection. Do not silently fail over execution or grant another account a scope. Preserve the existing demo controller and broker-confirmed reconciliation.
3. Make the fast operational path deterministic and observable. The sampled real readback took 6–15 seconds under concurrent startup/backups; optimize acquisition/persistence/UI rendering before claiming low latency. LLM interpretation stays off the mandatory decision path.
4. Add measured calibration, drift detection, walk-forward evaluation and counterfactual abstention outcomes to the existing journal. Unknown fees remain unknown; pattern shape is not a probability or profitability claim.
5. Reuse canonical SQLite/outbox and existing Qdrant partitions. Never turn projection readiness into ingestion permission or label a generated answer a broker fact.
6. Containerize only suitable existing services after backup and boundary acceptance. Keep native MT5/MQL5, Tauri and Vulkan inference. No Kubernetes deployment or new execution authority is authorized by the artifacts alone.

Detailed plans and acceptance evidence are retained in the task outputs. Remaining capability work must update this map with actual tests and runtime receipts rather than blanket “all layers ready” statements.
