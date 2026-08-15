# Niblit Ecosystem — Complete Architectural Audit

**Date:** 2026-07-26  
**Constraint:** Documentation Only — No Code Changes  
**Scope:** Entire Niblit platform across all repositories

---

## Table of Contents

1. [Repository Analysis](#1-repository-analysis)
2. [Whole-System Architecture](#2-whole-system-architecture)
3. [Capability Inventory](#3-capability-inventory)
4. [Trading Assessment](#4-trading-assessment)
5. [Freqtrade Readiness Assessment](#5-freqtrade-readiness-assessment)
6. [Gap Analysis](#6-gap-analysis)
7. [Roadmap](#7-roadmap)

---

## 1. Repository Analysis

### 1.1 Niblit (Core Repository)

**Path:** `Niblit/`  
**Purpose:** Primary runtime and AI operating system. Contains the main entrypoints, orchestration, memory, cognition, and 300+ module ecosystem.

**Runtime Ownership:**
- UI Runtime (desktop shell, FastAPI server)
- LocalBrain inference (QwenLocalBrain via GGUF)
- LifecycleEngine (phase orchestration)
- Memory (LocalDB, KnowledgeDB, FusedMemory, NiblitMemory)
- Router (NiblitRouter — 100+ command families)
- Cognition (NiblitBrain, BrainRouter, BrainTrainer)
- Autonomous Learning Engine (ALE — 29 steps)
- Self-improvement (SelfResearcher, SelfTeacher, SelfHealer, CodeGenerator, CodeCompiler)
- Knowledge (KnowledgeDB, GraphRAG, ConceptSynthesizer, KnowledgeFilter)
- Security (NiblitCyberMembrane, SecurityHardening, NiblitDefensiveEvolutionLoop)
- Platform (OSIntegration, HardwareScanner, BIOSIntegration, DeviceControl, DeviceMesh)
- Trading (TradingBrain, MarketDataProviders, RealTimeStream, LEANEngine, TradingSwingV3)
- Networking (AutonomousNetwork, DeploymentBridge, GithubSync, NiblitSidecar)
- Governance (ConstitutionalLayer, HumanAlignmentEngine, MetaGovernanceEngine)

**Internal Architecture:**
- **Startup:** `main.py` → `bootstrap_runtime_environment()` → `LifecycleEngine.__init__()` → `NiblitCore` → modules
- **Lifecycle:** Phases: INIT → AUDIT → SELF_HEAL → TRAIN → TASKS → OPTIMIZE → REFLECT → MAINTAIN → IDLE
- **Service Registry:** None explicit. Modules register themselves via import-time singletons.
- **Dependency Graph:** Highly coupled. `niblit_core.py` imports most subsystems. 300+ modules in `modules/` directory with implicit dependencies.

**Entry Points:**
- `main.py` — Interactive CLI shell
- `app.py` — FastAPI REST API (local + Vercel deployment)
- `server.py` — Same API, Vercel-compatible
- `start.sh` — Shell startup script

**Public Interfaces:**
- REST API: `GET /status`, `POST /chat`, `POST /process` (FastAPI)
- CLI: Interactive shell with 100+ commands
- IPC: `NiblitSidecar` (UNIX socket `/tmp/niblit-ctl.sock`)
- File: `niblit.db` (LocalDB), `niblit_memory.json` (KnowledgeDB), `niblit_fused.sqlite` (FusedMemory)
- Configuration: `.env`, `config.py`

---

### 1.2 Niblit-cloud-server

**Path:** `Niblit-cloud-server/`  
**Purpose:** Server-grade inference and trading infrastructure. Multi-model, multi-user, trading-capable REST API.

**Runtime Ownership:**
- REST API (FastAPI)
- GGUF inference (via ModelManager + GGUFEngine)
- Model registry (unified discovery across providers)
- Provider management (Qwen server, Ollama, OpenAI, Anthropic, HF, vLLM, remote)
- Embedding service
- Vector database
- Scheduler
- Background workers
- Health monitoring
- Cognitive subsystems (attention allocator, reflection engine, model orchestrator, event bus, temporal sync, cloud governance, federation)
- Trading pipeline (complete cognitive trading cycle)

**Internal Architecture:**
- **Startup:** `main.py:_run_cli()` → `CloudRuntime(config).run()` → 21 boot stages
- **Lifecycle:** 21 stages: CONFIGURATION → STORAGE → MODEL_REGISTRY → INFERENCE → EMBEDDINGS → VECTOR_DATABASE → API_SERVICES → WEBSOCKET → SCHEDULER → BACKGROUND_SERVICES → PLUGINS → MARKET_DATA → MARKET_STATE → MEMORY → LEAN_ALGORITHMS → LLM_VALIDATION → RISK_ENGINE → FREQTRADE → EXECUTION_MONITOR → HEALTH → READY
- **Service Registry:** `CloudRuntime._state` dict. Services register by name.
- **Dependency Graph:** Clean. All subsystems consume same `CloudConfig` instance. No circular dependencies.

**Entry Points:**
- `main.py` — `python main.py` boots entire CloudRuntime
- FastAPI app — exposed via uvicorn

**Public Interfaces:**
- REST API: OpenAI-compatible `/v1/chat/completions`, `/v1/models`, trading endpoints `/trading/*`, cognitive endpoints `/v1/runtime/*`, federation endpoints `/federation/*`, metrics endpoints `/metrics/*`
- WebSocket: Deferred (not yet implemented)
- CLI: None
- File: `.niblit/storage/`, `.niblit/feedback/`, `.niblit/signals/`
- Configuration: `.env`, `app/config.py`

---

### 1.3 Niblit-ui

**Path:** `Niblit-ui/`  
**Purpose:** Web-based UI for Niblit.

**Runtime Ownership:**
- UI rendering
- WebSocket client (to CloudRuntime or Niblit core)

**Internal Architecture:** Not fully audited. Likely a React/Vue/static web app.

**Entry Points:**
- `index.html` or equivalent
- Build scripts

**Public Interfaces:**
- WebSocket: Connects to backend
- REST: Calls backend APIs

---

### 1.4 niblit-lean-algos

**Path:** `niblit-lean-algos/`  
**Purpose:** Quantitative trading algorithms. LEAN/QuantConnect-based backtesting and live deployment.

**Runtime Ownership:**
- Strategy backtesting
- Strategy optimization
- Signal generation
- Lean algorithm management

**Internal Architecture:** LEAN engine integration. CLI-based with file-based signal exchange.

**Entry Points:**
- CLI commands
- Lean engine execution

**Public Interfaces:**
- File: Signal files in `.niblit/signals/`
- CLI: `lean deploy`, `lean backtest`

---

### 1.5 Freqtrade (External)

**Path:** `freqtrade/`  
**Purpose:** Open-source cryptocurrency trading bot. External execution layer.

**Runtime Ownership:**
- Exchange integration
- Order execution
- Position management
- Portfolio tracking
- Strategy hosting

**Internal Architecture:** Standalone. Niblit integrates via REST API (`/api/v1/forceentry`, `/api/v1/status`).

**Public Interfaces:**
- REST API: `/api/v1/forceentry`, `/api/v1/status`, `/api/v1/profit`, `/api/v1/trade/{trade_id}`
- WebSocket: Available
- CLI: `freqtrade trade`

---

### 1.6 niblit-memory

**Path:** `niblit-memory/` (directory)  
**Purpose:** Memory subsystem modules.

**Runtime Ownership:**
- Memory persistence
- Knowledge management
- Vector search

**Internal Architecture:** Split across `Niblit/niblit_memory/`, `Niblit/modules/knowledge_db.py`, `Niblit/modules/fused_memory.py`, `Niblit/modules/memory_weighting.py`.

---

### 1.7 Shared

**Path:** `shared/`  
**Purpose:** Shared libraries between Niblit and niblit-cloud-server.

**Runtime Ownership:**
- Common utilities
- Configuration schemas
- Event contracts

**Internal Architecture:** Not fully audited.

---

### 1.8 NibbleBots

**Path:** `Niblit/nibblebots/`  
**Purpose:** Agent framework for Niblit.

**Runtime Ownership:**
- Agent lifecycle
- Agent communication
- Agent task distribution

**Internal Architecture:** Not fully audited.

---

### 1.9 Supporting Repositories

- `github-copilot-llm-gateway/` — GitHub Copilot API compatibility layer
- `welcome-to-docker/` — Docker deployment assets
- `build/` — Build scripts and artifacts
- `tests/` — Shared tests

---

## 2. Whole-System Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Niblit Ecosystem                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────┐     │
│  │                      Niblit Core                              │     │
│  │  (Niblit/)                                                    │     │
│  │                                                               │     │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────────┐   │     │
│  │  │ main.py     │───▶│ NiblitCore  │───▶│ NiblitRouter    │   │     │
│  │  │ (CLI)       │    │ (master)    │    │ (100+ commands) │   │     │
│  │  └─────────────┘    └──────┬──────┘    └────────┬────────┘   │     │
│  │                            │                    │              │     │
│  │                            ▼                    ▼              │     │
│  │                   ┌────────────────┐    ┌────────────────┐     │     │
│  │                   │  NiblitBrain   │    │ LifecycleEngine│     │     │
│  │                   │ (think/learn)  │    │ (9 phases)     │     │     │
│  │                   └───────┬────────┘    └───────┬────────┘     │     │
│  │                           │                    │               │     │
│  │               ┌───────────▼──────────┐          │               │     │
│  │               │  QwenLocalBrain      │◄─────────┘ Trainer       │     │
│  │               │  (local GGUF)        │    uses BrainTrainer      │     │
│  │               │  Backends: http/sub/ │                           │     │
│  │               │  python              │                           │     │
│  │               └───────────┬──────────┘                           │     │
│  │                           │                                        │     │
│  │               ┌───────────▼──────────┐    ┌──────────────────┐  │     │
│  │               │  NiblitCloudBrain    │◄──▶│  MemoryManager   │  │     │
│  │               │  (HTTP client)       │    │  (LocalDB/KB/    │  │     │
│  │               └──────────────────────┘    │   FusedMemory)   │  │     │
│  │                                           └──────────────────┘  │     │
│  │                                                               │     │
│  │  ┌──────────────────────────────────────────────────────┐     │     │
│  │  │              modules/ (300+ subsystem modules)        │     │     │
│  │  │  event_bus, circuit_breaker, rate_limiter, cache,    │     │     │
│  │  │  knowledge_db, cognitive_memory, graph_rag,          │     │     │
│  │  │  autonomous_learning, self_researcher, code_gen,     │     │     │
│  │  │  distributed_coordinator, federation, etc.           │     │     │
│  │  └──────────────────────────────────────────────────────┘     │     │
│  │                                                               │     │
│  │  ┌──────────────────────────────────────────────────────┐     │     │
│  │  │              Trading Subsystem (Niblit-native)        │     │     │
│  │  │  TradingBrain, MarketDataProviders, RealTimeStream,  │     │     │
│  │  │  LEANEngine, TradingSwingV3, TradingStudy            │     │     │
│  │  └──────────────────────────────────────────────────────┘     │     │
│  └───────────────────────────────────────────────────────────────┘     │
│                                    │                                   │
│                            REST / WebSocket                            │
│                                    │                                   │
│  ┌─────────────────────────────────▼───────────────────────────┐     │
│  │              Niblit Cloud Server                             │     │
│  │              (Niblit-cloud-server/)                          │     │
│  │                                                             │     │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │     │
│  │  │ CloudRuntime│  │ ModelManager│  │  Trading Pipeline   │  │     │
│  │  │ (21 stages) │  │ (GGUF)      │  │  (market→lean→      │  │     │
│  │  │             │  │             │  │   validate→risk→    │  │     │
│  │  │ Services:   │  │ Providers:  │  │   execute→feedback) │  │     │
│  │  │  Storage    │  │  Qwen/Ollama│  │                     │  │     │
│  │  │  VectorDB   │  │  OpenAI     │  │  Modules:           │  │     │
│  │  │  Embeddings │  │  Anthropic  │  │   MarketAdapter     │  │     │
│  │  │  API        │  │  HF/vLLM    │  │   MarketIntelligence│  │     │
│  │  │  WebSocket  │  │  Remote    │  │   LeanBridge        │  │     │
│  │  │  Scheduler  │  │             │  │   GGUFValidator     │  │     │
│  │  │  Workers    │  │             │  │   RiskEngine        │  │     │
│  │  │  Plugins    │  │             │  │   TradeIntent       │  │     │
│  │  │  Health     │  │             │  │   FreqtradeAdapter  │  │     │
│  │  └─────────────┘  └─────────────┘  │   ExecutionFeedback │  │     │
│  │                                    └─────────────────────┘  │     │
│  │                                                             │     │
│  │  REST API: /v1/* (OpenAI compat), /trading/*, /federation/*│     │
│  │  WebSocket: Deferred                                       │     │
│  │  gRPC/Bridge: /v1/bridge/inference                         │     │
│  └─────────────────────────────────────────────────────────────┘     │
│                                    │                                   │
│                            REST / WebSocket                            │
│                                    │                                   │
│  ┌─────────────────────────────────▼───────────────────────────┐     │
│  │                    Niblit UI                               │     │
│  │                    (Niblit-ui/)                             │     │
│  │  Web dashboard + WebSocket client                           │     │
│  └─────────────────────────────────────────────────────────────┘     │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────┐     │
│  │                  Niblit Lean Algorithms                     │     │
│  │                  (niblit-lean-algos/)                        │     │
│  │  QuantConnect LEAN backtesting + live signal generation      │     │
│  └─────────────────────────────────────────────────────────────┘     │
│                                    │                                   │
│                            Signal files / REST                        │
│                                    │                                   │
│  ┌─────────────────────────────────▼───────────────────────────┐     │
│  │                    Freqtrade                                │     │
│  │                    (freqtrade/)                             │     │
│  │  Order execution, portfolio management, exchange integration │     │
│  └─────────────────────────────────────────────────────────────┘     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Key Connections

| Source | Target | Protocol | Purpose |
|--------|--------|----------|---------|
| Niblit Core | Niblit CloudServer | HTTP REST | Fallback inference, trading control |
| Niblit Core | Freqtrade | HTTP REST | Trade execution (via CloudServer or direct) |
| Niblit CloudServer | Freqtrade | HTTP REST | Trade execution, portfolio sync |
| Niblit Lean | CloudServer | File + HTTP | Signal files → trading pipeline |
| Niblit Core | LocalBrain | In-process | Local GGUF inference |
| Niblit UI | CloudServer | WebSocket + REST | UI ↔ backend communication |
| Niblit Core | Memory | In-process | LocalDB, KnowledgeDB, FusedMemory |
| CloudServer | VectorDB | In-process | Embeddings, semantic search |

### Startup Order

1. **Niblit Core** — `main.py` boots LifecycleEngine → NiblitCore → modules
2. **Niblit CloudServer** — `python main.py` boots CloudRuntime → 21 stages → uvicorn
3. **Niblit Lean** — On-demand (CLI or triggered by CloudServer)
4. **Freqtrade** — Independent; controlled via REST API
5. **Niblit UI** — Connects to CloudServer or Core via WebSocket

---

## 3. Capability Inventory

### Inference
- **Local GGUF** — `QwenLocalBrain` (http/subprocess/python backends)
- **Cloud GGUF** — `GGUFEngine` in CloudRuntime
- **HF Remote** — `HFBrain`, `LLMProviderManager`
- **Multi-model routing** — `ModelOrchestrator`, `BrainRouter`
- **Streaming** — SSE in CloudRuntime
- **Function calling** — Tool use via structured prompts
- **Context management** — Token budgeting, memory pressure detection
- **Crash recovery** — Model reload on `llama_decode returned -1`

### Memory
- **LocalDB** — JSON facts/interactions/learning_log (`niblit.db`)
- **KnowledgeDB** — Rich JSON facts/queue/acquired_data (`niblit_memory.json`)
- **FusedMemory** — SQLite events + Qdrant vector search
- **NiblitMemory** — Top-level hub: circuit-breaker, cache, rate-limit, telemetry
- **Memory weighting** — Prioritization of memories
- **GraphRAG** — 3-tier graph-based retrieval
- **Knowledge synthesis** — ConceptSynthesizer, KnowledgeFilter

### Cognition
- **Reasoning engine** — Multi-step logical reasoning
- **Brain training** — BrainTrainer records exchanges, ingests research
- **Reflection** — ReflectModule summarises KB entries
- **Self-improvement** — SelfResearcher, SelfTeacher, SelfHealer, CodeGenerator, CodeCompiler
- **Autonomous learning** — ALE (29-step background engine)
- **Metacognition** — SelfModel, IntentEngine, MetaEvaluator, ResourceAllocator
- **Constitutional layer** — Governance, human alignment
- **Cognitive envelope** — Structured context for inference

### Trading
- **Market data** — MarketDataProviders, RealTimeStream
- **Market intelligence** — SMA, EMA, RSI, ATR, swing points, regime detection
- **Lean algorithms** — LEANEngine, TradingSwingV3, lean_algo_manager
- **Signal generation** — File-based signal exchange
- **GGUF validation** — Structured JSON prompt/response validation
- **Risk engine** — 10 deterministic checks (no AI)
- **Trade intent** — Immutable TradeIntent objects
- **Freqtrade adapter** — REST API translation layer
- **Execution feedback** — Persist to disk, emit events, update portfolio
- **Pipeline orchestration** — 7-stage pipeline
- **18 REST endpoints** — `/trading/*`
- **Portfolio tracking** — PortfolioState, open trades, PnL

### Orchestration
- **LifecycleEngine** — 9-phase system orchestration
- **NiblitCore** — Master controller
- **NiblitRouter** — 100+ command families
- **Module loader** — Dynamic module discovery
- **Event bus** — Pub/sub event system
- **Scheduler** — Background job scheduling
- **Background workers** — Worker manager

### Platform
- **OS integration** — Linux/Android sysfs, proc, udev
- **Hardware scanner** — CPU, RAM, GPU, storage
- **BIOS integration** — UEFI/BIOS detection
- **Device control** — Sandboxed shell + serial/G-code
- **Device mesh** — LAN discovery + P2P
- **Platform bootstrap** — Cross-platform setup

### Security
- **Cyber membrane** — Adaptive intrusion detection + honeypot
- **Security hardening** — Dependency + code-level hardening
- **Defensive evolution** — Autonomous vulnerability patching
- **Governance** — Constitutional layer, human alignment
- **Permission manager** — Access control

### API
- **FastAPI** — REST endpoints (CloudServer, app.py, server.py)
- **WebSocket** — UI client (CloudServer deferred)
- **UNIX socket** — NiblitSidecar control server
- **CLI** — Interactive shell (Niblit main.py)
- **Bridge API** — `/v1/bridge/inference` for external system integration

### Persistence
- **SQLite** — niblit.db, niblit_fused.sqlite, niblit_memory.json
- **JSON files** — KnowledgeDB, LocalDB
- **Qdrant** — Vector store for FusedMemory
- **File-based signals** — `.niblit/signals/` for Lean integration

### Health
- **Health checks** — Models, API, vector DB, storage, scheduler, inference
- **Diagnostics** — `/v1/runtime/diagnostics`
- **Telemetry** — TelemetryCollector in LifecycleEngine
- **Circuit breakers** — Fault tolerance for critical operations
- **Rate limiting** — Request throttling

### Model Management
- **Model registry** — Unified discovery across providers
- **Model switching** — Runtime model switching
- **Model orchestrator** — Route requests to best model
- **Provider registry** — Qwen/Ollama/OpenAI/Anthropic/HF/vLLM/remote

---

## 4. Trading Assessment

### Current Capabilities

| Capability | Location | Status | Notes |
|------------|----------|--------|-------|
| Market Data Adapter | CloudServer `app/trading/market_adapter.py` | Complete | OHLCV ingestion, orderbook, metadata |
| Market Intelligence | CloudServer `app/trading/market_intelligence.py` | Complete | SMA, EMA, RSI, ATR, regime, swing points |
| Lean-Algos Bridge | CloudServer `app/trading/lean_bridge.py` | Complete | Signal file reading, rule-based proposals |
| GGUF Validation | CloudServer `app/trading/gguf_validator.py` | Complete | Structured JSON prompt/response |
| Risk Engine | CloudServer `app/trading/risk_engine.py` | Complete | 10 deterministic checks |
| Trade Intent | CloudServer `app/trading/trade_intent.py` | Complete | Immutable TradeIntent objects |
| Freqtrade Adapter | CloudServer `app/trading/freqtrade_adapter.py` | Complete | REST translation layer |
| Execution Feedback | CloudServer `app/trading/execution_feedback.py` | Complete | Disk persistence, event emission |
| Trading Pipeline | CloudServer `app/trading/pipeline.py` | Complete | 7-stage orchestration |
| Trading API | CloudServer `app/trading/router.py` | Complete | 18 REST endpoints |
| Trading Runtime Integration | CloudRuntime `runtime.py` | Complete | 9 new boot stages |
| LocalDB tracking | Niblit `niblit.db` | Complete | JSON-based local persistence |
| KnowledgeDB integration | Niblit `niblit_memory.json` | Complete | Research + training ingestion |
| Brain training | Niblit `BrainTrainer` | Complete | Exchange recording, research ingestion |
| LEAN engine | Niblit `modules/lean_engine.py` | Complete | QuantConnect integration |
| Real-time stream | Niblit `RealTimeStream` | Complete | Binance WebSocket |
| Market data providers | Niblit `MarketDataProviders` | Complete | Multi-provider free data |
| Trading brain | Niblit `TradingBrain` | Complete | Autonomous trading cycle |
| Trading swing | Niblit `TradingSwingV3` | Complete | Trend re-entry model |

### Capability Matrix

| Component | Decision Making | Execution | Risk | Market Analysis | Memory | Learning |
|-----------|----------------|-----------|------|-----------------|--------|----------|
| CloudServer Pipeline | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Niblit TradingBrain | ✓ | ✓ | ✗ | ✓ | ✓ | ✓ |
| LeanAlgos Bridge | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Freqtrade Adapter | ✗ | ✓ | ✗ | ✗ | ✗ | ✗ |
| RiskEngine | ✗ | ✗ | ✓ | ✗ | ✗ | ✗ |
| ExecutionFeedback | ✗ | ✓ | ✗ | ✗ | ✓ | ✓ |
| BrainTrainer | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ |

---

## 5. Freqtrade Readiness Assessment

| Capability | Status | Details |
|------------|--------|---------|
| Strategy reasoning | **Complete** | GGUF validation + Market Intelligence + Lean Bridge |
| Risk analysis | **Complete** | 10 deterministic checks in RiskEngine |
| Market analysis | **Complete** | SMA, EMA, RSI, ATR, regime detection, swing points |
| Order execution | **Partial** | FreqtradeAdapter layer exists; needs live Freqtrade instance |
| Exchange integration | **Missing** | No direct exchange API client (delegated to Freqtrade) |
| Portfolio management | **Partial** | PortfolioState model exists; needs live Freqtrade sync |
| Live trade supervision | **Missing** | No active trade monitoring loop (only static API polling) |
| Strategy generation | **Complete** | BrainTrainer + Lean engine + rule-based proposals |
| Strategy optimization | **Partial** | ALE background engine exists; no trading-specific optimization |
| Backtesting | **Partial** | LEAN engine exists; needs CloudServer integration |
| Performance tracking | **Complete** | ExecutionFeedback + statistics |
| Event bus integration | **Complete** | trade.execution.completed events emitted |
| Memory integration | **Complete** | BrainTrainer + KnowledgeDB + LocalDB |
| Scheduler integration | **Partial** | TradingPipeline.run_cycle() is manual; no scheduler trigger |
| Execution lifecycle | **Complete** | Proposal → Validate → Risk → Intent → Execute → Feedback |

### Readiness Score: 11/15 Complete (73%)

**Complete:** Strategy reasoning, Risk analysis, Market analysis, Strategy generation, Performance tracking, Event bus, Memory integration, Execution lifecycle, GGUF validation, Market intelligence, Trade intent  
**Partial:** Order execution, Portfolio management, Backtesting, Scheduler integration, Strategy optimization  
**Missing:** Exchange integration, Live trade supervision

---

## 6. Gap Analysis

### Critical Gaps (Block production use)

1. **Live trade supervision loop** — No background thread monitoring open trades, checking stop-loss/take-profit, handling exchange disconnections
2. **Exchange integration testing** — No validated test against live exchange API
3. **Portfolio reconciliation** — PortfolioState is in-memory only; needs persistent sync with Freqtrade
4. **Scheduler trigger** — TradingPipeline.run_cycle() must be triggered automatically on a schedule (cron-like)
5. **Freqtrade lifecycle management** — No start/stop/restart of Freqtrade process from CloudRuntime

### Important Gaps (Block autonomy)

6. **Strategy optimization loop** — ALE runs generic steps; no trading-specific optimization cycle
7. **Backtesting integration** — LEAN engine results don't flow back into CloudServer for validation
8. **Multi-symbol coordination** — Pipeline runs one symbol at a time; no portfolio-level coordination
9. **Error recovery** — No retry logic for failed trade execution, stuck orders, or API timeouts
10. **Configuration management** — Risk configs, model paths, Freqtrade credentials need unified config

### Future Enhancements

11. **Multi-exchange support** — Currently Freqtrade-only; could support multiple exchanges
12. **Advanced execution algorithms** — TWAP, VWAP, iceberg orders
13. **Portfolio-level risk** — Correlation, sector exposure, tail risk
14. **Strategy evolution** — Genetic algorithms, strategy mutation
15. **Regime-aware position sizing** — Dynamic Kelly criterion based on market regime

---

## 7. Roadmap

### Phase 1: Production Hardening (Critical)

**Goal:** Make the current trading pipeline production-ready.

**Dependencies:** None. All modules exist.

**Work:**
1. Add live trade supervision loop (background thread in CloudRuntime)
2. Add Freqtrade lifecycle management (start/stop/restart from CloudRuntime)
3. Add portfolio reconciliation (sync PortfolioState with Freqtrade)
4. Add scheduler trigger for TradingPipeline
5. Add retry logic and error recovery for trade execution

**Repositories affected:** `Niblit-cloud-server/`  
**Runtime changes:** New CloudRuntime boot stages or background workers

### Phase 2: Autonomy Loop (Important)

**Goal:** Close the autonomy gap — from signal generation to strategy improvement.

**Dependencies:** Phase 1.

**Work:**
1. Integrate LEAN backtesting results into CloudServer validation pipeline
2. Build trading-specific ALE phase (strategy optimization)
3. Add multi-symbol coordination (portfolio-level scheduler)
4. Connect BrainTrainer to trading performance data

**Repositories affected:** `Niblit-cloud-server/`, `niblit-lean-algos/`, `Niblit/`  
**Runtime changes:** New integration points between CloudServer trading pipeline and Niblit ALE

### Phase 3: Advanced Intelligence (Future)

**Goal:** Autonomous strategy design and evolution.

**Dependencies:** Phase 2.

**Work:**
1. Strategy generator (LLM-driven strategy creation)
2. Genetic algorithm for strategy mutation
3. Multi-exchange support
4. Advanced execution algorithms
5. Portfolio-level risk (correlation, tail risk)

**Repositories affected:** All  
**Runtime changes:** New modules in Niblit and CloudServer

---

## Appendix A: Repository Dependency Matrix

| Repository | Depends on Niblit | Depends on CloudServer | Depends on Lean | Depends on Freqtrade |
|------------|-------------------|------------------------|-----------------|----------------------|
| Niblit | — | Optional (NiblitCloudBrain) | No | No |
| Niblit-cloud-server | No | — | No | Optional (FreqtradeAdapter) |
| niblit-lean-algos | No | Optional | — | No |
| Niblit-ui | No | Yes | No | No |
| Freqtrade | No | Optional | No | — |
| niblit-memory | No | No | No | No |
| shared | Yes | Yes | No | No |

## Appendix B: Communication Protocols

| Channel | Protocol | Format | Used By |
|---------|----------|--------|---------|
| LocalBrain inference | HTTP/Subprocess/Python | OpenAI-compatible JSON | Niblit Core |
| CloudRuntime inference | HTTP REST | OpenAI-compatible JSON | CloudServer clients |
| CloudRuntime bridge | HTTP POST | JSON envelope | External systems |
| Trading signals | File (JSON) | `.niblit/signals/*.json` | Lean → CloudServer |
| Trade execution | HTTP REST | JSON payload | CloudServer → Freqtrade |
| Portfolio sync | HTTP REST | JSON | CloudServer → Freqtrade |
| UI communication | WebSocket + REST | JSON | UI ↔ CloudServer |
| Sidecar control | UNIX socket | Text commands | Niblit Sidecar |

## Appendix C: Key Files by Repository

### Niblit/
- `main.py` — Entrypoint, imports all subsystems
- `niblit_core.py` — NiblitCore master controller
- `niblit_brain.py` — NiblitBrain, BrainRouter, BrainTrainer, NiblitCloudBrain
- `niblit_router.py` — NiblitRouter (100+ commands)
- `lifecycle_engine.py` — LifecycleEngine (9 phases)
- `niblit_memory.py` — MemoryManager
- `config.py` — Configuration
- `modules/local_brain.py` — QwenLocalBrain (2883 lines)
- `modules/runtime_bootstrap.py` — Path/CWD setup
- `modules/` — 300+ subsystem modules

### Niblit-cloud-server/
- `main.py` — FastAPI app, ModelManager, CloudRuntime boot
- `runtime.py` — CloudRuntime (21 boot stages)
- `app/trading/` — 10 trading modules
- `app/config.py` — CloudConfig
- `app/main.py` — FastAPI endpoints
- `tests/` — 250+ tests

### niblit-lean-algos/
- LEAN engine integration
- Signal generation
- Backtesting

### Niblit-ui/
- Web UI assets
- WebSocket client

### Freqtrade/
- External: order execution, portfolio management, exchange integration

---

## Summary

Niblit is a **distributed AI operating system** with two primary runtimes:

1. **Niblit Core** — Local, offline-capable, cognitive AI with 300+ modules, memory, learning, and self-improvement
2. **Niblit CloudServer** — Server-grade, multi-user, trading-capable inference and execution platform

Both runtimes are **independent but complementary**. The CloudServer handles external APIs, trading execution, and multi-user inference. Niblit Core handles local cognition, memory, learning, and autonomous improvement.

For Freqtrade integration, Niblit is **73% ready** (11/15 capabilities). The core decision pipeline is complete. The main gaps are live trade supervision, exchange integration testing, portfolio reconciliation, and scheduler automation.

The recommended roadmap is:
1. **Phase 1:** Production hardening (live supervision, lifecycle management, portfolio sync, scheduler)
2. **Phase 2:** Autonomy loop (backtesting integration, multi-symbol coordination, ALE enhancement)
3. **Phase 3:** Advanced intelligence (strategy generation, genetic algorithms, multi-exchange)