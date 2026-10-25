# Phase 5R — Reality Map of Niblit Capabilities

Read-only. No code was modified this phase. Every claim below is backed by a
live probe against a real `NiblitCore` boot, or by a file:line citation.

**Probe artifacts (all read-only, all self-contained):**

| File | Purpose |
|---|---|
| `_p5r_probe.py` / `_p5r_probe.json` / `_p5r_report.txt` | Boot topology, attribute presence, governed surface, memory, trading, static scan (16,713 files) |
| `_p5r_probe2.py` / `_p5r_probe2.json` / `_p5r_probe2.txt` | BrainRouter instance state, memory store sizes, per-command governed state, **live execution of 33 read-only governed capabilities**, EventBus subscribers, subsystem stats |
| `_p5r_dump.py`, `_p5r_dump2.py` | Render the JSON evidence as readable text |

**Levels used** (L0 = worst, L7 = best):
`L0` spec only · `L1` code exists, unwired · `L2` wireable, not on the live path ·
`L3` on the live path, degrades truthfully · `L4` live and populated ·
`L5` autonomous · `L6` self-correcting · `L7` self-correcting and authority-governed.

---

## 1. Boot topology — what actually exists

```
NiblitCore.__init__                      Phase 0 (sync)  : 77–115 s
  ├─ db, memory        = KnowledgeDB     (niblit_memory, singleton)
  ├─ brain             = NiblitBrain     (niblit_brain)
  ├─ router            = NiblitRouter
  ├─ brain_router      = BrainRouter     <- SEPARATE instance from brain's
  ├─ trading_runtime_manager = None      <- niblit_lean_algos ABSENT
  └─ 104 startup components: 101 ready / 2 degraded / 1 background

deferred-init daemon thread             Phase 1         : 108–125 s
  ├─ semantic_agent, claude_engine, local_brain, github_sync ...
  ├─ lean_algo_manager = modules.lean_algo_manager.LeanAlgoManager
  ├─ kernel, hybrid_qdrant, self_monitor, security_membrane
  └─ _deferred_init_phase -> "complete"  (core.wait_for_ready() -> True)
```

`NiblitServer` runs in a `DaemonThreadPool` on port 53619.
Cloud Server port is `NIBLIT_CLOUD_SERVER_PRIMARY_PORT` (default 8000).

**Degraded / background (from `startup_report`):**

| Component | Status | Error |
|---|---|---|
| `slsa_engine` | degraded | `'SLSAGenerator' object has no attribute 'start'` |
| `local_brain_model` | degraded | `Local Qwen model files not found in cache (unknown)` |
| `module_loader` | background | Layer 5 timed out at 120 s, still loading in background |

> **Probe correction.** My first probe read attributes *before*
> `wait_for_ready()` and reported `brain` / `trading_runtime_manager` as absent.
> Phase 1 builds most modules in a deferred thread, so every deferred attribute
> reads `None` until the core is ready. Both probes now wait.

---

## 2. Capability reality map

### Capability 1 — Local model runs locally (no internet)
**Level 3 — wired, on the live path, degrades truthfully. Model weights are an environment gap.**

`modules/local_brain.py::LocalBrainGateway` is present (`core.local_brain`) and
wired into `BrainRouter.local_brain` and into `NiblitBrain.think()`
(`niblit_brain.py:2094-2101`). Live `stats()`:

```json
{"local_brain": {"profile": "local", "running": false, "healthy": false,
                 "restart_count": 0, "last_health_ts": 0.0}}
```

Startup marked `local_brain_model` **degraded**:
`Local Qwen model files not found in cache (unknown). Run: tools/install_local_qwen_model.py`.

The `think()` fallback chain is honest, not fabricated — local brain -> academic
module -> kernel v3 -> language module, finally returning the literal
`"[Local brain: Qwen not yet loaded — run 'brain status']"` (`niblit_brain.py:2129`).

**Not L4** because no model weights exist in this environment. Code: present. Assets: absent.

### Capability 2 — Cloud inference via Cloud Server :8000
**Level 3 — code wired, requires an external Cloud process that is not running.**

`modules/llm_tool_loop.py:26-28`:
```python
_NIBLIT_CLOUD_PORT = int(os.environ.get("NIBLIT_CLOUD_SERVER_PRIMARY_PORT", "8000"))
_CLOUD_ROOT = f"http://127.0.0.1:{_NIBLIT_CLOUD_PORT}"
_CHAT_PATH  = "/v1/chat/completions"
```
`LlmToolLoop.chat()` targets `qwen2.5-coder-3b` by default. `BrainRouter.cloud_brain`
is a plain function (`_cloud_escalation`, `brain_router.py:214`).

Live: `cloud_runtime: {healthy: false, running: false}` — the Cloud server is not up.
`_cloud_chat` uses `urllib` and returns a structured failure rather than fabricating output.

### Capability 3 — Model routing between cloud and local
**Level 4 — live and populated. Two real defects (see section 4).**

`modules/brain_router.py::BrainRouter` with `route()`, `_choose_path()`,
`_local_first()`, `_memory_augmented()`, `_cloud_escalation()`, `_hybrid_response()`,
`set_mode()`, `stats()`. Modes `local | balanced | power | offline`
(`NIBLIT_BRAIN_MODE`, default `balanced`). Word thresholds 15/40
(`NIBLIT_ROUTER_SIMPLE_WORDS` / `..._COMPLEX_WORDS`).


### Capability 4 — Personality and memory
**Level 4 — live and populated, but thin (2 persisted keys).**

`core.personality = modules.niblit_personality.NiblitPersonality`.
Live `db.get_personality()` / `db.get_preferences()` both return:
```json
{"tone": "adaptive", "optimization_timestamp": "2026-09-29T17:13:20.761018+00:00"}
```
Persisted through `KnowledgeDB.store_preferences` / `get_personality`
(`niblit_memory/__init__.py:2650-2663`) — survives restarts (timestamp is 11 days old).

### Capability 5 — Research pipeline (search -> browse -> reason -> store -> recall)
**Level 4 — live, governed, single-flight, hard-capped. Not autonomous.**

`modules/research_orchestrator.py` (597 lines): `ResearchOrchestrator.run(topic)`
-> `plan_research` -> `assess_topic` -> `audit_evidence` -> `internal_first` ->
`ResearchRunResult` with `artifact()`. Members verified importable:
`[assess_topic, audit_evidence, internal_first, plan_research, run]`.

Registered on the **same governed loop** (`core_tool_runtime.py:902-926`):
```python
def build_governed_tool_loop(core_getter):
    loop = LlmToolLoop()
    register_research_tools(loop)          # web_search / web_fetch
    register_trading(loop, ...)
    loop.register_capability("run_research", ...)
    register_workspace_tools(loop)
    register_knowledge_tools(loop, core_getter)
    register_original_readonly_tools(loop, core_getter)
    return loop
```

Budgets are hard-capped in code and the UI can only lower them
(`core_tool_runtime.py:988-990`); `run_research_capability` is **single-flight**
via `_RESEARCH_LOCK` (`:101`). Live budgets:
`max_searches 4, max_fetches 6, max_rounds 2, followups_per_audit 2, max_llm_retries 2`.

Promotion gate (`modules/research_contracts.py::evaluate_promotion`) is reachable.
Promoted facts carry `promotion: governed` + `promotion_reason`.

**Parallel path:** `core.researcher = SelfResearcher` — a second, older research
surface that is *not* the orchestrator.

### Capability 6 — Memory / knowledge
**Level 4 — the authoritative store is real, populated, and healthy. Requires duplicate-path classification (5 classes).**

**Authority: `niblit_memory.KnowledgeDB`** — `core.db` **and** `core.memory` are
the *same* object (singleton via `__new__`, `niblit_memory/__init__.py:1727`).

Live store contents:
| Metric | Value |
|---|---|
| `facts_total` | **569** |
| `events_total` | **6,413** |
| `learning_log` | 11 |
| `learning_queue` | 6 pending |
| `acquired_data` | 50 entries |
| `relationship_summary` | **1,000 edges / 96 entities** (`related_to` 895, `semantic_link` 105) |
| `knowledge_health` | avg_confidence **0.985**, freshness **1.0**, coverage **0.991**, verdict **`strong`** |

Methods available: `add_fact`, `list_facts`, `search`, `recall`, `smart_recall`,
`query_vector`, `reinforce`, `decay_stale_confidence`, `consolidate_facts`,
`get_relationships`, `relationship_summary`, `store_research`, `get_acquired_data`,
`queue_learning`, `store_preferences`, `knowledge_health`, ... (35+).

**Vector store is genuinely available:** `core.fused_memory.vector_backend == "faiss"`.

**Tier curriculum is wired but empty:** `TieredKnowledgeSystem` is bound to the DB
(`tiered_db_bound: true`) yet all four tiers report `topics_covered: 0`,
`confidence: 0.0`, `current_tier: "Foundation"`.

**Five overlapping memory classes in one package** (duplicate classification required):

| Class | Line | Role | Used by |
|---|---|---|---|
| `KnowledgeDB` | 1717 | **Authoritative** facts/events/relationships | `core.db`, `core.memory` |
| `FusedMemory` | 182 | sqlite events+knowledge+graph+vector (faiss) | `core.fused_memory` |
| `KnowledgeStore` | 3039 | sqlite search-results + qdrant embed | research path |
| `NiblitMemory` | 3223 | autosave/dump loops, records | legacy |
| `LocalDB` | 740 | JSON-backed simple store | legacy |

### Capability 7 — Workspace tools (list/search/read)
**Level 4 — live, registered, validated.**

`register_workspace_tools(loop)` (`core_tool_runtime.py:278`) registers
`workspace_list` / `workspace_search` / `workspace_read` / `workspace_write` /
`workspace_edit` / `run_tests`.

Policy (`modules/workspace_tools.py`): **23** allowed extensions, **14** secret
patterns, `max_read_chars 24000`, `max_write_bytes 200000`,
`max_search_results 30`, `test_timeout 600 s`.

Live invocation: `workspace_list` -> `success` in **832 ms**, real directory
entries (`.build`, `.continue`, ...).

### Capability 8 — Governed tool execution
**Level 4 for the governed loop. A second, ungoverned dispatch surface exists and is reachable from `core.process()` (see section 4, defect #12).**

**The governed authority** — `modules/llm_tool_loop.py::LlmToolLoop`:
- one dispatch table `_tool_map`; one validator `_validate_call` (schema)
- `MAX_IDENTICAL_TOOL_CALLS = 2` — the model is stripped of tools and must answer
  from observations it already has (`llm_tool_loop.py:30-34`)
- `MAX_TOOL_CALLS_PER_TURN = 5` (`niblit_tool_executor.py:53`)
- `_DESTRUCTIVE_COMMANDS = {"shutdown","exit","quit"}` need `confirm_mode`
- `prevalidate()` / `invoke()` — **one validator, three entry points** (LLM loop,
  Command tab, direct invoke); *there is no second command executor*

`server.py:1206` -> `get_governed_tool_loop(lambda: core)`; the Command tab's
`POST /api/commands/execute` -> `execute_governed_command` -> the identical chain.

Live: **44 governed capabilities**, `EXECUTABLE 40 / REQUIRES_AUTHORIZATION 3 /
UNAVAILABLE 1`. Schema rejection verified live three times:
`recall` -> `invalid arguments for recall: missing ['query']`;
`workspace_read` -> `missing ['path']`; `workspace_search` -> `missing ['query']`.

### Capability 9 — Workspace file read
**Level 4.** `workspace_read` requires `path`, returns real file content through
the same renderer the UI file tab uses, capped at 24,000 chars, read-only
(`core_tool_runtime.py:195-212`). Properly rejects missing arguments.

### Capability 10 — Workspace write / edit with authorization
**Level 4 — gated and verified live.**

`workspace_write` / `workspace_edit` / `run_tests` are the **only three** actions
requiring authorization (`COMMAND_PERMISSION_ACTIONS`, `core_tool_runtime.py:961-965`).
Live `PermissionManager` (`ask`/`check`/`save`, file-backed):
```
check:command.workspace_write = false
check:command.workspace_edit  = false
check:command.run_tests       = false
```
-> all three report `REQUIRES_AUTHORIZATION`. Writes take an automatic backup of
any replaced file and refuse secret patterns.

### Capability 11 — Trading observation (read-only)
**Level 3 — the capability is live and truthful; the authority it observes is absent from this environment.**

`modules/trading_read_tools.py` is the complete read-only surface:
`read_runtime_status`, `execute_trading_runtime_status`, `register(loop, runtime_getter)`.
It reads *properties only* — `_state_attr` explicitly `continue`s over callables
(`trading_read_tools.py:75-76`) so nothing can be invoked through it.

Live invocation through the governed path:
```json
{"available": false, "reason": "trading_runtime_not_initialized",
 "execution_tools_exposed": false}
```
This is the correct, non-fabricated answer. The command's availability gate is
`bool(getattr(core, "trading_runtime_manager", None))`
(`core_tool_runtime.py:997-998`) -> the command is listed but state `UNAVAILABLE`.

**Root cause of the missing authority:** the module `niblit_lean_algos` does not
exist in this environment.
```
niblit_lean_algos            ModuleNotFoundError
niblit_lean_algos.manager    ModuleNotFoundError
```
Phase-0 trading init therefore fails on **every boot** (logged ERROR), and
`core.trading_runtime_manager` stays `None`. Copies of the bridge exist only in
build artifacts: `dist/_staged/lean-algos/niblit_bridge/freqtrade_adapter.py`,
`dist/niblit/_internal/lean-algos/...`.

**18 of 20 trading modules import cleanly.** All present and importable:
`trading_decision_engine`, `...freqtrade_adapter`, `...niblit_decision_engine`,
`lean_algo_manager`, `lean_deploy_engine`, `lean_engine`, `market_data_providers`,
`trading_adapter`, `trading_brain`, `trading_study`, `rl_trading_policy`,
`adaptive_market_cognition`, `governed_live_cognition`, `trade_kb_learner`,
`execution_graph`, `market_researcher`, `live_updater`, `trading_read_tools`.

**Replacement surface:** `core.lean_algo_manager = modules.lean_algo_manager.LeanAlgoManager`
provides the *shape* of the authority (`state`, `backend`, `trading_mode`,
`execution_enabled` properties; `start`/`stop`; `deploy_all`;
`start_live(project_id, brokerage="PaperBrokerage")`) and is documented as a
compatibility surface, explicitly "NOT touched or elevated" by the read-only
tools (`trading_read_tools.py:11-12`).

### Capability 12 — Trading execution
**Level 7 — enforced by absence + audit + forbidden-name guard. Execution is not possible at all in this environment.**

`FORBIDDEN_EXECUTION_NAMES` (13) — verified **none** present in the governed loop
(`forbidden_present_in_loop: []`):
`place_order, cancel_order, close_position, open_position, execute_strategy,
change_leverage, allocate_capital, start_live_trading, modify_live_strategy,
bypass_risk, disable_risk, send_freqtrade_command, run_lean_backtest_execution`.

Phase 5G already proved all **19** `TRADING` risk-class commands are non-`llm_safe`
and none are `GOVERNED_EXECUTABLE`.

`modules/trading_decision_engine/freqtrade_adapter.py` (121 lines) is a **pure signal
translator** — `to_freqtrade_signal()` maps `TradingDecision -> {enter_long,
enter_short, exit_long, exit_short, confidence, reason, metadata}`. It holds no
connection to Freqtrade and places no orders.

### Capability 13 — Freqtrade / Lean integration
**Level 3 — integration code present; the authoritative package is absent.**

- `modules/lean_deploy_engine.py` — QuantConnect REST. Live status:
  `Credentials set`, `Active monitors: 0`, templates
  `['ema_crossover','crypto_ema','forex_ema','index_cfd','multi_asset']`
- `modules/lean_engine.py`, `modules/lean_algo_manager.py` — present
- `modules/trading_decision_engine/freqtrade_adapter.py` — signal shaping only
- Packaged bridge exists **only** in `dist/_staged/lean-algos/` and
  `dist/niblit/_internal/lean-algos/`, not as an importable package
- `.github/workflows/nibblebot-ai-trading.yml` — CI for the trading bot

### Capability 14 — Market data
**Level 4 — all five providers report available.**

`modules/market_data_providers.py` (751 lines) · `MarketDataProviders` on `core`.
Live `status()`:
```
yfinance     available
ccxt         available
twelvedata   available
oanda        available
alpaca       available
```
Configured in `modules/market_data_providers.py:499-531`. I did **not** fetch live
quotes (network + read-only scope), so *provider availability* is proven and
*data flow* is unverified.

### Capability 15 — Runtime self-observation
**Level 4 — real, working, with one broken default tool and one pathological latency.**

Present on `core`: `SelfMonitor`, `TemporalCoherenceLayer` (`_tcl`, epoch 0 /
uptime 136 s / REALTIME + FAST clocks), `StructuralAwareness`.

`modules/event_bus.py::NiblitEventBus` — `publish/subscribe/subscribe_all/
unsubscribe/last_event/observability_report/stats`, `delivery_mode="async"`,
in-process only. Live: **12 event types, 759 emissions**.

Governed read-only self-observation commands executed live:

| Command | Result | Duration |
|---|---|---|
| `status` | success | 242 ms |
| `health` | success | 0.1 ms |
| `metrics` | success | 0.0 ms |
| `coherence` | success | 0.1 ms |
| `unified_runtime_status` | success | 973 ms |
| `runtime_capabilities` | success | **139,769 ms** |
| `runtime_status` | **`[niblit_exec: core not available — start Niblit first]`** | 0.0 ms |

### Capability 16 — Self-assessment and truthfulness
**Level 4 — live and populated.**

`core.kernel = modules.niblit_kernel.NiblitKernel` with `detailed_report()`,
`health_check()`, `inspect_module`, `inspect_dependencies`,
`self_analysis`, `analyze_contracts`, `analyze_all_contracts`.

Governed `sa_*` commands all executed live: `sa_dashboard` (101 ms),
`sa_structure` (0.1 ms), `sa_modules` (**5,558 ms**), `sa_resources` (104 ms),
`sa_threads` (0.2 ms), `sa_loops` (0.0 ms).

Supporting: `SecurityMembrane` live stats `{rate_limit: "60/60s",
max_payload_kb: 256, blocked_ips: 0}`, `KnowledgeDigest`, `KnowledgeFilter`.

### Capability 17 — Self-modification
**Level 4 — wired, with a real learning queue and log.**

Present: `SelfImplementer`, `SelfTeacher`, `ImprovementIntegrator`,
`AutonomousLearningEngine`, `CodeGenerator`, `CodeCompiler`, `ReflectModule`,
`Metacognition`, `ReasoningEngine`, `SoftwareStudier`.

Live `KnowledgeDB` learning state: **6 pending** topics (`get_learning_queue`),
**11** completed (`get_learning_log`), plus `mark_learning_done`, `store_learning`,
`mark_training_step`, `autonomous_learn`, `self_research`, `self_teach`, `reflect`.

`DeploymentBridge` live: `ALE cycles: 23, Facts: 48`.

Governed read path: `ale_status`, `ale_processes` — both `read_only: true`,
`side_effect_level: NONE`.

### Capability 18 — Multi-step planning, self-correction, execution graphs
**Level 4 — real step graphs and a real repetition guard.**

- `modules/deliberative_planner.py` — planner step vocabulary includes
  `"call_tool"` with `value/risk = 0.75/0.25` (`:71,85`), forced to front of pool (`:267`)
- `modules/execution_graph.py::ExecutionGraph.run()` — sequential steps
  `retrieve_memory -> call_tools -> validate_risk -> generate_response -> reflect`
  (`:246`, `_step_call_tools` at `:305`); emits `execution.complete`
- `LlmToolLoop`: `max_loop_calls=15`, `MAX_IDENTICAL_TOOL_CALLS=2` — **the
  repetition guard is real self-correction**: a stuck model loses its tool surface
  and must answer from what it has
- `Metacognition`, `ReflectModule` on `core`

---

## 3. Duplicate paths — authoritative vs legacy vs duplicate

| Layer | **Authoritative** | Parallel / legacy / duplicate | Verdict |
|---|---|---|---|
| Knowledge store | `KnowledgeDB` (`core.db` = `core.memory`) | `LocalDB`, `NiblitMemory`, `KnowledgeStore`, `FusedMemory` | **5 classes in one package** |
| Vector store | `FusedMemory` (faiss) | `KnowledgeStore` (qdrant) + `HybridQdrantManager` | parallel backends |
| Tool execution | `LlmToolLoop._tool_map` + `_validate_call` | `niblit_tools.tool_registry.ToolRegistry` | **ungoverned second surface** |
| Brain routing | `get_brain_router()` singleton | `core.brain_router` **!=** `core.brain.brain_router` | **2 live instances** |
| Trading authority | `niblit_lean_algos.TradingRuntimeManager` (**absent**) | `modules.lean_algo_manager.LeanAlgoManager` | authority missing |
| Conversation history | `LLMChatMemory` (70 msgs, 35/35) | `KnowledgeDB` interactions (**0**) | 2 conversation stores |
| Research | `ResearchOrchestrator` (governed `run_research`) | `core.researcher = SelfResearcher` | parallel research paths |
| Runtime ownership | `NiblitCore` | `core/runtime_manager.py` (a *second* `NiblitCore`-owning RuntimeManager) | 2 runtime managers |
| Chat input path | `server.py` -> governed loop | `core.process()` -> `cognitive_ingress` -> `ExecutionGraph` | 2 input paths |

---

## 4. Pre-existing defects found (all reproduce in a clean boot)

These are **not** caused by any change I made; I changed no code this phase.

| # | Defect | Evidence |
|---|---|---|
| 1 | `runtime_status` governed capability always returns `"[niblit_exec: core not available — start Niblit first]"` even with a live core | live probe2. Root cause: `NiblitToolExecutor._get_core()` (`niblit_tool_executor.py:100-108`) falls back to `niblit_core._active_core` and `NiblitRouter._instance` — **neither symbol exists** in those modules; `build_governed_tool_loop` (`core_tool_runtime.py:904`) constructs `LlmToolLoop()` with no executor/core |
| 2 | Two distinct `BrainRouter` instances | live probe2 `same_singleton: false`; both `niblit_core.py:9390` and `niblit_brain.py:1499` call `reset_brain_router()` |
| 3 | `BrainRouter.stats()` raises | live probe2: `AttributeError: 'LocalBrainGateway' object has no attribute 'is_available'` |
| 4 | `LeanAlgoManager.stats()` raises | live probe2: `AttributeError: 'NoneType' object has no attribute 'get'` |
| 5 | `runtime_capabilities` takes ~139.8 s | live probe2: `139769.4 ms` |
| 6 | Phase-0 trading init fails on every boot | `niblit_lean_algos` missing -> logged ERROR each boot; `core.trading_runtime_manager = None` |
| 7 | `slsa_engine` degraded | `'SLSAGenerator' object has no attribute 'start'` |
| 8 | `KnowledgeDB` atomic replace fails every save | `[WinError 5] Access is denied: 'tmp...' -> 'niblit_memory.json'`, falls back to direct write |
| 9 | 8 event types emitted with **0** subscribers | `capability.available`, `capability.unavailable`, `command.registered`, `execution_envelope.published`, `live.ingestion.failed`, `live.ingestion.started`, `runtime.system.started`, `workspace.inspection.started` |
| 10 | Tier curriculum never advances | all 4 tiers `topics_covered: 0`, `confidence: 0.0` |
| 11 | `LocalBrainGateway` never starts | `running: false, healthy: false` (model weights absent) |
| 12 | **Ungoverned tool dispatch reachable from the main chat path** | `core.process()` LAYER 12 -> `_dispatch_cognitive_ingress` (`niblit_core.py:11600`) -> `unified_runtime.run_cognitive_cycle` -> `CognitiveIngress.ingest` -> `cognitive_router.route` -> `ExecutionGraph.run` (`cognitive_ingress.py:93`) -> `_step_call_tools` (`execution_graph.py:305`) -> `niblit_tools.tool_registry.run(name, {})`. Dispatch is a **text-substring heuristic** (`if name.lower() in text.lower()`) with no schema validation, no risk class, no permission check. `_dispatch_cognitive_ingress` **short-circuits** `process()` and returns before SDAL/`brain.think()` |

**Defect #12 is the only finding that weakens a governance claim.** The
`LlmToolLoop` single-executor guarantee holds for the Command tab and the LLM tool
loop. `NiblitBrain.call_tool` / `get_tools` (`niblit_brain.py:1543,1567`) are
consumed **only by tests** (`test_niblit_serpex.py:471,476`) — but the same
ungoverned `tool_registry` is reachable in production through
`ExecutionGraph._step_call_tools`.

---

## 5. Environment gaps (not defects)

| Missing asset | Consequence |
|---|---|
| `niblit_lean_algos` package | `TradingRuntimeManager` never constructs; only staged in `dist/_staged/` |
| Local Qwen model weights | `local_brain_model` degraded; run `tools/install_local_qwen_model.py` |
| Cloud Server :8000 process | `LlmToolLoop.chat()` and `BrainRouter._cloud_escalation` cannot complete |
| `niblit_core._active_core` / `NiblitRouter._instance` symbols | executor fallback chain is dead (defect #1) |

---

## 6. Deferred to a later phase (own fix phases)

1. **Governance hardening** — close the `ExecutionGraph` -> `tool_registry` bypass;
   either route it through `LlmToolLoop` or delete it. Also repair `runtime_status` (#1, #12).
2. **Latency** — `runtime_capabilities` 139 s; `sa_modules` 5.6 s.
3. **Memory consolidation** — reduce 5 memory classes to one authority + one vector path.
4. **Router identity** — one `BrainRouter` instance; fix `stats()`.
5. **EventBus follow-through** — subscribe consumers for the 8 orphaned event types.
6. **Tier curriculum** — make `TieredKnowledgeSystem` actually advance.

---

## 7. Evidence quality

- Both probes boot a **real** `NiblitCore`, wait for `wait_for_ready()`, and
  read live objects. No mocks, no stubs, no invented output.
- The 33 read-only capability invocations went through the **actual governed
  path** (`LlmToolLoop.invoke` -> `_validate_call` -> `_tool_map`). Mutating
  capabilities (`workspace_write`, `workspace_edit`, `run_tests`,
  `run_research`, `web_search`, `web_fetch`) and all 13 forbidden trading names
  were **never dispatched**.
- Static scan: **16,713 `.py` files** walked (excluding tests/reports/venv) for the
  import-and-call graph.
- Classification honesty: capabilities 1, 2, 11, 13 are **not** Level 4+ because
  required external assets are absent, and I say so rather than upgrading them.





Wiring on the live path:
- `niblit_core.py:9411` `self.brain_router = get_brain_router(...)`
- `niblit_brain.py:1534` `self.brain_router = get_brain_router(...)`
- `niblit_brain.py:2188` `self.brain_router.route(prompt, context)` inside `think()`
- `niblit_core.py:11612-11614` SDAL `llm_fn` prefers `brain_router.route`

Live state: `mode = "balanced"`.

> **Correction to my earlier hypothesis.** I initially believed `brain_router`
> was unwired (it is absent from `NiblitBrain`'s *class* attributes). It is an
> **instance** attribute created in `NiblitBrain.__init__`
> (`niblit_brain.py:1496-1539`). It is on the live path.
