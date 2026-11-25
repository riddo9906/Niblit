# Freebuff Capability & Integration Evaluation — 2026-11-21

Evaluation of Freebuff (cloud coding agent operating on this desktop workspace) as an
*additional* development assistant for NiblitAIOS. Nothing in this document authorises
Freebuff to place orders, start trading engines, or replace Niblit's cognition or
governance. No broker session, account setting, release executable or uncommitted work
was modified.

Working context: `C:\Users\Riyaad\Documents\GitHub`, Freebuff attached to the local
desktop (Windows, Python 3.14.6, pytest 9.2.0).

---

## 1. Discovery

### 1.1 Repositories and Git state (observed, not modified)

| Repository | Branch | Dirty entries | Notes |
|---|---|---|---|
| `Niblit` | `fix/exness-demo-readiness-20261118` | 78 (28 modified, 50 untracked `.pytest-*` dirs) | Head `301571f0` "Scope uncertain broker delivery by account and fix Exness profile fallback" |
| `niblit-cloud-server` | `main` | 12 (3 modified, 9 untracked: `market_advisory.py`, `mobile_gateway.py`, `mobile_ui/`, `portal_mobile_auth.py`, `sidecar_gguf.py`, smoke scripts, tests) | Head `5dfec96` "update" |

`Niblit` is a single Python package at the repo root (`__init__.py`, `pyproject.toml`,
`testpaths = ["."]`) with ~359 modules in `modules/`, ~139 test modules in `tests/`, and
~200 `test_*.py` files at the root. Releases live outside both repos at
`D:\NiblitAIOS\releases`; the active demo build is
`releases/candidates/build-20261121-r11-market-cognition-venues/niblit` (a packaged
runtime directory).

### 1.2 Subsystem map (verified by file inventory, not by launch)

| Concern | Authoritative locations |
|---|---|
| Cognition / reasoning | `niblit_brain.py` (`NiblitBrain`, `BrainTrainer`), `modules/cognition_core.py`, `modules/reasoning_engine.py`, `modules/cognitive_synthesis_engine.py`, `modules/metacognition.py`, `modules/cognitive_memory_layer.py` |
| Governance | `modules/constitutional_layer.py`, `modules/human_alignment.py`, `modules/meta_governance_engine.py`, `modules/permission_manager.py` |
| Memory | `niblit_memory/` (`knowledge_store.py`, `unified_memory_engine.py`, `governed_qdrant_memory.py`, `qdrant_engine.py`), `modules/fused_memory.py`, `modules/memory_graph.py`, `modules/knowledge_db*.py`, `modules/cognitive_memory_layer.py` |
| Market analysis / cognition | `modules/adaptive_market_cognition.py` (this task's target), `modules/market_evidence.py`, `market_thesis.py`, `market_prediction.py`, `market_researcher.py`, `desktop_market_intelligence.py`, `online_market_study.py`, `market_data_providers.py` |
| Strategy | `modules/strategy_manager.py` (six-strategy consensus), `strategy_research.py`, `demo_strategy.py`, `modules/hypothesis_engine.py`, `modules/rl_trading_policy.py` |
| LLM / inference | `modules/llm_provider_manager.py` (qwen, llama3, hf, anthropic, ruflo), `modules/local_brain.py`, `modules/llama_server_manager.py`, `modules/hf_brain.py`, `modules/anthropic_adapter.py`, `modules/ruflo_adapter.py` |
| Execution | `modules/core_trading_sessions.py`, `trading_session_adapters.py`, `remote_demo_adapter.py`, `trading_desk.py`, `position_exit_policy.py`, `task_admission.py`, `freqtrade_core_claim.py`, `deploy/vps-gateway/` |
| Runtime / orchestration | `core/runtime_manager.py`, `modules/unified_runtime.py` (hosts `market_cognition = AdaptiveMarketCognitionLayer`), `aios_runtime.py`, `lifecycle_engine.py`, `modules/niblit_kernel.py` |
| Developer tooling | `agents/niblit_dev_agent/` (planning engine, architecture indexer, provider awareness), `nibblebots/` (audit, doc, test-gap, autonomous evolution agents), `tools/build_system_map.py` |

### 1.3 Integration map

- **Qdrant** — `modules/hybrid_qdrant_manager.py` (`HybridQdrantManager`, collections
  `niblit_episodic_memory` / `niblit_reflection_memory`), `niblit_memory/qdrant_engine.py`,
  `niblit_memory/governed_qdrant_memory.py` (`get_governed_qdrant_memory_cluster().recall /
  .write_memory`), plus `qdrant_cluster_logic/` (collections, payload/governance schemas).
  Optional and non-fatal at runtime: with no reachable collection the manager logs
  `insert: collection not available` and market-cognition persistence falls through to
  `log.debug`.
- **llama.cpp** — `modules/llama_server_manager.py` owns one `llama-server` subprocess:
  GGUF discovery from `NIBLIT_LLAMA_MODEL_DIRS`, `register_model`, `start/stop`,
  `switch_model` under `_MODEL_SWITCH_LOCK`, health thread. Registered as an *optional*
  Layer-2 service in `core/runtime_manager.py`; `modules/local_brain.py` consumes it via
  `NIBLIT_LLAMA_SERVER_URL` (default `http://127.0.0.1:8080`).
- **MT5** — `modules/trading_session_adapters.py` + `modules/remote_demo_adapter.py` +
  `deploy/vps-gateway/{gateway,demo_execution}.py`. Demo-scoped by construction:
  account-environment detection, pinned account binding, refusal of live/funded scope in
  `permission_manager`, quarantine of uncertain deliveries. `MetaTrader5` is an optional
  dependency (`requirements-mt5.txt`).
- **Freqtrade** — `niblit-lean-algos/freqtrade_bridge/` (bridge, risk, execution manager,
  offline worker, desktop profiles), consumed in Core via `modules/freqtrade_core_claim.py`
  and the Market Desk (port 8150 worker). `modules/freqtrade_research.py` reads research
  data. Core claims native entries through a one-time receipt; the Core never starts the
  engine from observation or activation (asserted by existing tests).
- **RuFlo** — LLM provider, not an execution path. `modules/ruflo_adapter.py` is wired into
  `llm_provider_manager` as `ruflo`, configured by `RUFLO_API_URL` / `RUFLO_API_KEY` /
  `RUFLO_MODEL` / `RUFLO_API_FORMAT` / `RUFLO_CHAT_PATH` in `config.py`, and switchable with
  `llm-provider ruflo`. Separately, `nibblebots/` adopts Ruflo *design patterns*
  (declarative agent registry, audit/doc/test-gap workers, "search before starting").

### 1.4 Existing functionality (baseline before any change)

Market cognition already implements: event→experience assembly with causal chain, risk
scoring, reflection generation, decision-quality index (DQI), governed Qdrant recall and
write-back, KnowledgeDB fact flushes, contradiction detection, retrieval bundles for prompt
enrichment, and `market intelligence …` render commands. `test_unified_runtime_architecture.py`
and `test_hypothesis_engine.py` exercise this path end to end. The r10/r11 releases are
market-cognition builds, so this area is live product surface, not a sandbox.

---

## 2. Freebuff capability test results (what actually happened)

| Capability | Result | Evidence / limits |
|---|---|---|
| Navigate a 359-module Python repo with 139 test modules | Pass | Located the market-cognition layer, its consumer in `unified_runtime.py`, and its tests in one search pass |
| Read TypeScript/Rust surfaces | **Not evaluated** | The JS/TS in this workspace is the portal/desk front end (`assets/client-portal`, `assets/trading-desk`); Rust opts are `niblit_models`/`Package.swift` stubs. No TS/Rust work was requested, so no claim is made |
| Trace dependencies across repos | Pass | Followed market cognition → Qdrant recall → provider manager → Freqtrade bridge and VPS gateway by import/reference search |
| Diagnose a defect accurately | Pass, with empirical proof | Reproduced the defect in-process before editing: `_bucket(None) -> "low"`, experience stored as `volatility_regime="low"` with no volatility payload, `_infer_volatility_from_query("explain this") -> "medium"` |
| Generate useful regression tests | Pass | 5 new tests; all 5 pass; 31 existing consumer tests still pass |
| Execute a focused coding task | Pass | 18-line production diff in one file, no interface change |
| Preserve working behaviour | Pass for the tested surfaces | `test_unified_runtime_architecture.py`, `test_hypothesis_engine.py`, `test_adaptive_retrieval_cognition.py`: 31 passed |
| Maintain context across sessions | **Not proven** | Context is per-conversation. Repository-local documentation (this file plus `tests/test_adaptive_market_cognition.py`) is the durable handoff, not agent memory |

Environment limitations encountered (not caused by the change):

- `pytest`'s default temp root `%LOCALAPPDATA%\Temp\pytest-of-Riyaad` is access-denied on
  this machine (`PermissionError: [WinError 5]`), so any `tmp_path` test errors at setup
  unless `--basetemp` is pointed inside the workspace. Consumer suites were therefore run
  with `--basetemp=.pytest-adaptive-cognition-r1` (removed afterwards).
- Many `diagnostics/` and `runtime/` test-cache directories are permission-denied to this
  process; some recursive searches report those as errors. Read access to source was never
  blocked.
- No live Qdrant collection, MT5 terminal, Freqtrade engine, RuFlo endpoint or paid model was
  contacted. No full-suite run was attempted (thousands of tests, live-service dependencies).

---

## 3. The implemented improvement

### 3.1 Current implementation (before)

`modules/adaptive_market_cognition.py`:

- `_bucket(value)` clamped any input through `_clamp(value, 0.0)`, so `None`, `""` or a
  non-numeric value became `0.0` and was reported as `"low"`.
- `observe_event()` used `_bucket(payload.get("volatility"))` for `volatility_regime`, so an
  experience with **no** volatility data was permanently recorded as a *calm* market. That
  value is written into Qdrant payloads and KnowledgeDB tags, so the false claim outlives
  the session.
- `_infer_volatility_from_query()` returned `"medium"` when the query contained no
  volatility cue, and `build_market_retrieval_bundle()` added `+0.12` similarity whenever the
  two matched. Every `"medium"` experience therefore received a free ranking bonus on
  *every* query, unrelated to what was asked.

### 3.2 Change

| File | Change |
|---|---|
| `modules/adaptive_market_cognition.py` | `_bucket` returns `"unknown"` for `None`, booleans and non-numeric input; `_infer_volatility_from_query` returns `""` when the query states no volatility cue; the `+0.12` volatility term is applied only when a cue exists and the experience's regime is known |
| `tests/test_adaptive_market_cognition.py` | New: 5 regression tests |

Expected behaviour, and what was measured:

| Scenario | Before | After |
|---|---|---|
| Experience with no `volatility`/`volatility_regime` | `"low"` (false calm) | `"unknown"` |
| `volatility=0.10 / 0.55 / 0.90` | low / medium / high | unchanged: low / medium / high |
| Query with no volatility cue, one medium-vol experience | +0.12 bonus | no bonus; equal similarity to an unknown-vol experience |
| Query "high volatility …" | no reliable discrimination | high-vol experience ranked first, `0.12` above the low-vol one |

Risk scoring, DQI, contradiction detection, reflection text, retrieval bundle shape,
event names and the public `AdaptiveMarketCognitionLayer` API are unchanged.

### 3.3 Tests and actual results

```
python -m pytest tests/test_adaptive_market_cognition.py -q
.....                                                                    [100%]   exit 0

python -m pytest test_unified_runtime_architecture.py test_hypothesis_engine.py \
                 test_adaptive_retrieval_cognition.py -q \
                 --basetemp=.pytest-adaptive-cognition-r1
...............................                                          [100%]   exit 0
```

`git status` for this work: `M modules/adaptive_market_cognition.py`,
`?? tests/test_adaptive_market_cognition.py`. Nothing else was touched.

### 3.4 Known remaining inconsistency (deliberately not changed)

`_risk_state()` still coerces a missing drawdown/exposure/concentration/uncertainty to
`0.0` via `_clamp`, so `risk_state["volatility_state"]` can read `"low"` for an experience
whose `volatility_regime` is now `"unknown"`. Fixing that means preserving `None` through
`_risk_state` → `_calculate_risk` → `risk_score` labels, which changes risk output consumed
elsewhere. It is a contained follow-up, not part of this isolated change.

---

## 4. Integration recommendation

**Operate Freebuff as an optional standalone coding assistant — select, isolated tasks,
human-reviewed diffs.**

- It should **not** become a participant in Niblit's agent orchestration at this time.
  Niblit's orchestration (`core/orchestrator.py`, `modules/unified_runtime.py`,
  `nibblebots/`) is in-process, event-driven and governed by `permission_manager` and the
  constitutional layer. Freebuff has no seat in that governance, cannot be audited by it,
  and its context does not persist. Wiring it in would create an ungoverned mutation path
  into a system whose whole design is bounded authority.
- It should **not** be a required dependency. Nothing in this change requires Freebuff at
  runtime, build time or test time.
- It **should** be used where it demonstrably helped here: cross-repo dependency tracing,
  defect reproduction before editing, generating focused regression tests, and writing
  handoff documentation.
- A future, deliberately-designed option: a *proposal-only* dev-agent role that submits
  diffs as artifacts for Niblit's existing dev-agent pipeline
  (`agents/niblit_dev_agent/`, `nibblebots/testgap_agent.py`) to evaluate and apply under
  the normal permission checks. That requires an explicit governance design and is out of
  scope now.

---

## 5. Limitations and risks

1. **No context continuity.** Each session starts from the repository. Mitigation: land the
   reasoning in-repo (tests + this document + commit messages), which is what was done.
2. **No live-system validation.** No MT5 terminal, Freqtrade engine, Qdrant collection, RuFlo
   endpoint or paid LLM was contacted. Changes affecting those paths must be verified by the
   acceptance procedures in `docs/NIBLIT_TESTING_GUIDE.md`, not by this report.
3. **Broad test suite is not runnable here** without live services and with the temp-dir
   permission issue; verification was intentionally scoped to the touched module and its
   consumers.
4. **Working tree is heavily dirty (78 entries).** A diff-centric agent must stage or inspect
   narrowly; bulk `git add -A`, `stash`, `clean` or `reset` would destroy in-flight work.
   None were used.
5. **Semantic changes can leak into stored memory.** Market-cognition output is persisted to
   Qdrant and KnowledgeDB; anything written before this fix may contain `"low"` values that
   were actually unknown. That historical data was not rewritten (rewriting user memory is
   outside scope).
6. **Cloud agent + local filesystem.** Commands run against this desktop; a disconnect can
   interrupt a write mid-flight. The edited files were re-inspected after the interruption
   risk window and pass their tests.

---

## 6. Handoff for the main Niblit development session

Changed:

- `modules/adaptive_market_cognition.py` — unknown volatility is no longer labelled "low",
  and volatility similarity only applies to explicit query cues.
- `tests/test_adaptive_market_cognition.py` — new regression coverage (5 tests).

Verified: 5/5 new tests pass; 31/31 existing market-cognition consumer tests pass.

Not verified: nothing live (no broker, no engine start, no Qdrant, no paid inference);
no full-suite run; historical persisted volatility labels untouched.

Suggested commits (do not commit from here):

1. `Record unknown market volatility honestly instead of as a calm regime`
2. `Cover adaptive market cognition unknown-volatility and retrieval ranking`

Optional follow-up worth a separate change: preserve `None` through `_risk_state` so
`risk_state` labels agree with `volatility_regime` about missing data.
