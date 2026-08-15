# LocalBrain Architecture Audit

**Date:** 2026-07-26  
**Status:** Documentation Only — No Code Changes  
**Purpose:** Complete architectural understanding before any refactoring

---

## 1. What is LocalBrain?

LocalBrain is Niblit's **primary local LLM execution layer**. It exists to provide always-on, zero-API-cost inference using quantized GGUF models running on-device.

### Why it exists
- **Cost**: Zero API cost vs cloud providers (HF, Anthropic, OpenAI)
- **Availability**: Works offline, no network dependency
- **Privacy**: Sensitive reasoning stays on-device
- **Speed**: Low-latency simple reasoning without network round-trips

### What problem it solves
Niblit needs a brain that is always available. Cloud APIs have rate limits, costs, and availability constraints. LocalBrain ensures Niblit can always think, reason, and respond using a local GGUF model.

### Why it is separate from RuntimeManager
RuntimeManager (`LifecycleEngine`) orchestrates the overall system lifecycle (phases: INIT → AUDIT → SELF_HEAL → TRAIN → TASKS → OPTIMIZE → REFLECT → MAINTAIN → IDLE). LocalBrain is a **pure inference service** — it has no opinion about system phases, tasks, or lifecycle. It only answers prompts.

### Why it is separate from CloudRuntime
CloudRuntime (`Niblit-cloud-server/app/runtime.py`) is the **server-side inference and trading infrastructure**. It exposes REST APIs, manages model providers, and serves external clients. LocalBrain is the **client-side local inference** — it runs inside the Niblit process and calls either a local llama-server or subprocess binary. They serve different purposes:
- **CloudRuntime**: Server-grade, multi-model, multi-user, trading-capable
- **LocalBrain**: Single-user, local-only, lightweight, always-available fallback

---

## 2. Responsibilities

### Primary responsibilities
1. **Local GGUF inference** — Execute prompts against a local quantized model
2. **Multi-backend execution** — Support http, subprocess, and python backends
3. **Model management** — Lazy-load, cache, and switch local models
4. **Chat templating** — Apply Qwen/Llama2/Alpaca/raw chat templates
5. **Thread-safe inference** — Serialize concurrent generate() calls via lock
6. **Brain training** — Record exchanges and ingest research into training data

### Secondary responsibilities
1. **Cloud fallback** — Escalate to NiblitCloudBrain when local model fails
2. **Memory integration** — Persist training pairs to MemoryManager
3. **Knowledge synthesis** — Inject accumulated training context into prompts
4. **Health caching** — TTL-cache llama-server health checks
5. **Architecture awareness** — Inject structural context into system prompts

### Incidental responsibilities
1. **Module-level constants** — Many env vars read at import time
2. **Legacy backwards compatibility** — Module-level aliases for `_LLAMA_SERVER_URL`, `_MAX_NEW_TOKENS`, etc.
3. **Windows path hardcoding** — Default model paths assume Windows

---

## 3. Startup Lifecycle

```
System Boot
    ↓
main.py (Niblit/)
    ↓
bootstrap_runtime_environment(__file__)   [modules/runtime_bootstrap.py]
    ↓
    - Finds repo root (niblit_core.py + niblit_io.py)
    - Sets CWD to repo root
    - Inserts repo_root + parent into sys.path
    ↓
LifecycleEngine.__init__()                [lifecycle_engine.py]
    ↓
    - MemoryManager()
    - Trainer(db=memory)
    - NiblitTasks(brain=None, memory=memory)
    - _init_improvements():
        - CircuitBreaker (audit, heal, train)
        - TelemetryCollector
        - RateLimiter
        - CacheStrategy
        - EventStore
    ↓
LifecycleEngine.start()
    ↓
    - Start heartbeat thread (1s interval)
    - Start phase loop
    ↓
NiblitCore initialization                  [niblit_core.py]
    ↓
    - LocalBrain instantiation
    ↓
QwenLocalBrain.__init__()                  [modules/local_brain.py]
    ↓
    - Read env vars (NIBLIT_GGUF_MODEL_PATH, NIBLIT_GGUF_BACKEND, etc.)
    - _LocalBrainConfig() singleton created
    - Module-level aliases set
    - NO model loaded yet (lazy loading on first generate())
    ↓
Ready State
    ↓
First generate() call
    ↓
QwenLocalBrain.generate()                  [modules/local_brain.py]
    ↓
    - Lazy-load model via selected backend
    ↓
Backend selection (auto mode):
    1. http → llama-server at http://127.0.0.1:8080
    2. subprocess → llama-cli binary
    3. python → llama-cpp-python
    ↓
Inference complete
```

### Everything LocalBrain initializes
1. `_LocalBrainConfig` — mutable config singleton
2. Module-level env var constants (model path, context, threads, backend, templates)
3. `_MODEL_SWITCH_LOCK` — threading.Lock for model switching
4. `_SERVER_HEALTH_TTL` cache — TTL for llama-server health checks
5. `BrainTrainer` — in-memory training pairs + knowledge facts

---

## 4. Dependencies

| Dependency | Why it exists | Required | Optional | When active |
|------------|---------------|----------|----------|-------------|
| `modules/runtime_bootstrap.py` | Path setup, CWD | Yes | No | Import time |
| `niblit_memory.py` / `MemoryManager` | Persist training data, recall facts | Yes | No | generate() calls |
| `trainer_full.py` / `Trainer` | Brain training integration | No | Yes | BrainTrainer.record_exchange() |
| `niblit_tasks.py` / `NiblitTasks` | Task execution context | No | Yes | LifecycleEngine only |
| `niblit_orchestrator.py` | Self-heal orchestration | No | Yes | LifecycleEngine.advance_phase() |
| `modules/circuit_breaker.py` | Fault tolerance | No | Yes | LifecycleEngine |
| `modules/telemetry_observability.py` | Metrics | No | Yes | LifecycleEngine |
| `modules/rate_limiting.py` | Request limiting | No | Yes | LifecycleEngine |
| `modules/multi_level_caching.py` | Caching | No | Yes | LifecycleEngine |
| `modules/event_sourcing.py` | Event store | No | Yes | LifecycleEngine |
| `llama-server` (HTTP) | GGUF inference backend | No | Yes | generate() when backend=http |
| `llama-cli` binary | GGUF inference backend | No | Yes | generate() when backend=subprocess |
| `llama-cpp-python` | GGUF inference backend | No | Yes | generate() when backend=python |
| `NiblitCloudBrain` | Cloud fallback inference | No | Yes | When local backends fail |
| `niblit_core.py` | Master controller | No | Yes | main.py startup |

---

## 5. Downstream Systems

| System | How it interacts with LocalBrain |
|--------|----------------------------------|
| **NiblitCore** (`niblit_core.py`) | Owns LocalBrain instance; calls `brain.think()`, `brain.ask()` |
| **NiblitRouter** (`niblit_router.py`) | Routes commands to `brain.think()` or `brain.ask()` |
| **LifecycleEngine** (`lifecycle_engine.py`) | Creates Trainer + Tasks; Trainer uses BrainTrainer which uses LocalBrain |
| **BrainTrainer** (`niblit_brain.py`) | Records exchanges, ingests research — uses LocalBrain indirectly |
| **CloudRuntime** (`Niblit-cloud-server/`) | Completely separate; does NOT use LocalBrain |
| **UI Runtime** | Calls NiblitCore which calls LocalBrain |
| **Event Bus** | BrainTrainer emits events; LocalBrain does not directly use event bus |
| **Memory** | BrainTrainer persists to MemoryManager; LocalBrain generates content stored in memory |
| **Trading Runtime** | Does NOT use LocalBrain directly |
| **Lean Runtime** | Does NOT use LocalBrain directly |

---

## 6. Runtime Ownership

| Responsibility | Owner |
|----------------|-------|
| Runtime orchestration | LifecycleEngine |
| Model loading | QwenLocalBrain (lazy, on first generate()) |
| Model switching | `swap_local_brain()` in `niblit_brain.py` |
| Local inference | QwenLocalBrain |
| Cloud inference | NiblitCloudBrain |
| Scheduler | LifecycleEngine (phase advancement) |
| Health checks | QwenLocalBrain._server_health_ttl cache |
| Memory | MemoryManager (separate module) |
| Event bus | modules/event_bus.py (separate module) |
| API | app.py / server.py (FastAPI) |
| Brain routing | BrainRouter (in `niblit_brain.py`) |
| Training | BrainTrainer (in `niblit_brain.py`) |
| Cognition | NiblitBrain.think() (in `niblit_brain.py`) |

---

## 7. Interaction Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Niblit System                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────────┐  │
│  │   main.py    │───▶│ niblit_core  │───▶│   NiblitRouter       │  │
│  │ (entrypoint) │    │   .py        │    │   (niblit_router.py) │  │
│  └──────────────┘    └──────┬───────┘    └──────────┬───────────┘  │
│                            │                       │                │
│                            ▼                       ▼                │
│                   ┌─────────────────┐    ┌──────────────────┐      │
│                   │  NiblitBrain    │    │  LifecycleEngine │      │
│                   │ (niblit_brain)  │    │ (lifecycle_eng.) │      │
│                   │                 │    │                  │      │
│                   │ ┌─────────────┐ │    │ Phases:          │      │
│                   │ │BrainRouter  │ │    │ INIT→AUDIT→      │      │
│                   │ │local|bal|   │ │    │ SELF_HEAL→TRAIN→ │      │
│                   │ │power|off    │ │    │ TASKS→OPTIMIZE→  │      │
│                   │ └──────┬──────┘ │    │ REFLECT→MAINTAIN │      │
│                   │        │        │    │ →IDLE            │      │
│                   │ ┌──────▼──────┐ │    └────────┬─────────┘      │
│                   │ │QwenLocal    │ │             │                 │
│                   │ │Brain        │◄┼─────────────┘                 │
│                   │ │(local_brain)│ │    Trainer uses BrainTrainer   │
│                   │ │             │ │    which uses LocalBrain       │
│                   │ │ Backends:   │ │                                 │
│                   │ │  http       │ │                                 │
│                   │ │  subprocess │ │                                 │
│                   │ │  python     │ │                                 │
│                   │ └──────┬──────┘ │                                 │
│                   │        │        │                                 │
│                   │ ┌──────▼──────┐ │                                 │
│                   │ │NiblitCloud  │ │    ┌──────────────────────────┐  │
│                   │ │Brain        │◄┼───▶│   NiblitCloudServer      │  │
│                   │ │(niblit_brain│ │    │   (Niblit-cloud-server/) │  │
│                   │ │  class)     │ │    │   - FastAPI REST API     │  │
│                   │ └─────────────┘ │    │   - GGUF inference       │  │
│                   │                 │    │   - Trading pipeline     │  │
│                   │                 │    │   - Provider registry    │  │
│                   │                 │    └──────────────────────────┘  │
│                   └─────────────────┘                                   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │                   modules/ directory                        │  │
│  │  - event_bus.py      - memory_weighting.py                  │  │
│  │  - circuit_breaker.py - multi_level_caching.py              │  │
│  │  - rate_limiting.py  - telemetry_observability.py           │  │
│  │  - knowledge_db.py   - cognitive_memory_layer.py            │  │
│  │  - 300+ other modules                                        │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 8. Lifecycle Diagram

```
System Boot
    │
    ▼
runtime_bootstrap.bootstrap_runtime_environment()
    │
    ├── Find repo root (niblit_core.py + niblit_io.py)
    ├── Set CWD to repo root
    ├── Insert repo_root + parent into sys.path
    │
    ▼
main.py imports
    │
    ├── niblit_core → NiblitCore
    ├── lifecycle_engine → LifecycleEngine
    ├── niblit_brain → NiblitBrain, QwenLocalBrain, BrainTrainer, NiblitCloudBrain
    ├── memory → MemoryManager
    └── modules/* → 300+ modules
    │
    ▼
LifecycleEngine.__init__()
    │
    ├── MemoryManager()
    ├── Trainer(db=memory)
    ├── NiblitTasks(brain=None, memory=memory)
    └── _init_improvements()
        ├── CircuitBreaker (audit, heal, train)
        ├── TelemetryCollector
        ├── RateLimiter
        ├── CacheStrategy
        └── EventStore
    │
    ▼
LifecycleEngine.start()
    │
    ├── Start heartbeat thread (1s)
    └── Start phase loop
    │
    ▼
Phase: INIT → AUDIT → SELF_HEAL → TRAIN → TASKS → OPTIMIZE → REFLECT → MAINTAIN → IDLE
    │                                                                               │
    │                                                    (loops back to INIT via    │
    │                                                     advance_phase())          │
    ▼                                                                               │
┌───────────────────────────────────────────────────────────────────────────────┐  │
│ Ready State                                                                    │  │
│                                                                               │  │
│  - LocalBrain ready (lazy-loaded on first generate())                        │  │
│  - CloudRuntime independent (Niblit-cloud-server/)                            │  │
│  - Event bus active                                                            │  │
│  - Memory active                                                               │  │
│  - Lifecycle heartbeat running (1s)                                           │  │
│                                                                               │  │
│  Inference flow:                                                               │  │
│    NiblitCore.process() → NiblitRouter → BrainRouter → QwenLocalBrain        │  │
│                         → backend selection → llama-server / subprocess /     │  │
│                           python → response                                    │  │
│                         → CloudBrain fallback (if local fails)                │  │
└───────────────────────────────────────────────────────────────────────────────┘  │
                                                                                   │
Shutdown                                                                           │
    │                                                                               │
    ▼                                                                               │
LifecycleEngine shutdown
    │
    ├── Stop heartbeat thread
    ├── Stop phase loop
    ├── Close circuit breakers
    ├── Flush event store
    └── Persist memory
```

---

## 9. Current Weaknesses

### Duplicated responsibility
1. **Inference logic duplicated** — `QwenLocalBrain` in `modules/local_brain.py` has its own generate/chat logic. `NiblitCloudServer` (`app/main.py`) has `GGUFEngine` with its own inference logic. Both wrap llama-cpp-python differently.
2. **Model loading duplicated** — `QwenLocalBrain` lazy-loads models. `GGUFEngine` in CloudServer loads models eagerly. Both manage `Llama()` instances with slightly different parameter sets.
3. **Brain routing duplicated** — `BrainRouter` in `niblit_brain.py` routes local/cloud. `ModelManager` in `app/main.py` routes models. Separate routing logic for the same concept.

### Unnecessary coupling
1. **LocalBrain → CloudServer coupling** — `QwenLocalBrain.chat()` falls back to calling `NiblitCloudServer` HTTP endpoints. This creates a circular dependency risk (LocalBrain depends on CloudServer, CloudServer is a separate runtime).
2. **BrainTrainer → Memory coupling** — `BrainTrainer` directly calls `memory.store_learning()` and `memory.recall()`. Tight coupling makes testing difficult.
3. **LifecycleEngine → Trainer/Tasks/Orchestrator coupling** — All imported at module level with try/except stubs. Creates a fragile dependency web.

### Circular dependencies
1. **`niblit_brain.py` → `niblit_core.py` → `niblit_brain.py`** — Broken by lazy import of `loop_tracer`, but still a risk.
2. **`lifecycle_engine.py` → `niblit_orchestrator.py` → (potentially back to lifecycle)**

### Hidden ownership
1. **`BrainRouter` is both a class and a function** — `brain_router()` is a function in `niblit_brain.py` that creates a `BrainRouter` instance. The naming is confusing.
2. **`NiblitCloudBrain` lives in `niblit_brain.py`** — Despite the name, it's not the CloudServer. It's a thin HTTP client wrapper. This creates confusion with `NiblitCloudRuntime`.

### Legacy code paths
1. **Module-level constants** — `_MAX_NEW_TOKENS`, `_GGUF_N_CTX`, `_LLAMA_SERVER_URL` are module-level aliases that delegate to `_local_brain_cfg`. They're kept "for backwards compatibility" but add confusion.
2. **`_LocalBrainConfig` is newer but not universally used** — Some code still reads module-level constants directly.
3. **`brain_router` function** — Legacy wrapper around `BrainRouter` class. Both exist side-by-side.

### Inconsistent lifecycle management
1. **LocalBrain has no lifecycle** — It's lazily initialized on first `generate()`. There's no explicit "started" event in the lifecycle engine.
2. **CloudRuntime has full lifecycle** — `CloudRuntime` has 21 boot stages, health checks, graceful shutdown. LocalBrain has none of this.
3. **BrainTrainer runs inline** — No background thread. `record_exchange()` and `ingest_research()` block the caller.

---

## 10. Legacy Components

| Component | Location | Why it exists |
|-----------|----------|---------------|
| `_MAX_NEW_TOKENS`, `_GGUF_N_CTX`, etc. | `modules/local_brain.py` | Backwards compatibility for code that imports module-level constants |
| `brain_router()` function | `niblit_brain.py` | Legacy wrapper; `BrainRouter` class is the real implementation |
| `NiblitCloudBrain` class | `niblit_brain.py` | Confusingly named — it's a client, not the CloudServer |
| `local_brain_patch.py` | `modules/` | Unknown (not read yet, but name suggests compatibility patch) |
| `legacy_cognition_recovery.py` | `modules/` | Explicitly named as legacy |
| `hf_brain.py` | `Niblit/` | Legacy HF brain; superseded by `BrainRouter` + `NiblitCloudBrain` |
| `niblit_brain.py` top-level constants | `_MODEL_NAME`, `_GGUF_MODEL_PATH`, etc. | Module-level env var reads at import time; partially superseded by `_LocalBrainConfig` |

---

## 11. Improvement Opportunities

### 1. Unified Model Interface
Currently, `QwenLocalBrain` and `GGUFEngine` (CloudServer) both manage `Llama()` instances independently. A shared `ModelProvider` interface would eliminate duplication and ensure consistent parameter handling.

### 2. Explicit LocalBrain Lifecycle
Add boot stages for LocalBrain to the LifecycleEngine:
- `LOCAL_BRAIN_INIT` — configure
- `LOCAL_BRAIN_LOAD` — lazy-load model
- `LOCAL_BRAIN_HEALTH` — verify server/binary availability
- `LOCAL_BRAIN_READY` — signal ready

### 3. Break LocalBrain → CloudServer Dependency
`QwenLocalBrain.chat()` calls back to CloudServer when local inference fails. This creates a circular risk. Instead, LocalBrain should:
- Return a specific error type
- Let the caller (NiblitCore/BrainRouter) decide whether to escalate to cloud

### 4. Centralize Env Var Reading
Eliminate module-level constant reads. All configuration should flow through `_LocalBrainConfig`. Deprecate `_MAX_NEW_TOKENS`, `_GGUF_N_CTX`, etc. with warnings.

### 5. BrainTrainer Threading
`BrainTrainer.record_exchange()` and `ingest_research()` are synchronous. Background these operations to avoid blocking inference calls.

### 6. Dependency Injection
`BrainTrainer.__init__()` takes 10 positional/keyword arguments. Use a config object or dependency injection container to reduce coupling.

### 7. Remove Confusing Names
- Rename `NiblitCloudBrain` → `NiblitCloudClient` or `CloudBrainClient`
- Remove `brain_router()` function, keep only `BrainRouter` class
- Rename `local_brain_patch.py` or document its purpose

### 8. Consistent Error Handling
`QwenLocalBrain.chat()` returns error strings on failure (`"[NiblitCloudBrain error: ...]"`). This is fragile — callers must check for error strings. Use exceptions or a `Result` type.

### 9. Health Check Integration
LocalBrain health checks are TTL-cached per-instance. Integrate with the LifecycleEngine's health monitoring for a unified health view.

### 10. Memory Layer Unification
Memory is accessed via `memory.store_learning()`, `memory.recall()`, `memory.log_event()`. The interface is implicit (duck-typed). Define an explicit `MemoryProtocol` or ABC.

---

## Files Examined

| File | Lines | Purpose |
|------|-------|---------|
| `Niblit/modules/local_brain.py` | 2883 | QwenLocalBrain, BrainTrainer, NiblitCloudBrain |
| `Niblit/niblit_brain.py` | 2552 | NiblitBrain, BrainRouter, think/learn/chat |
| `Niblit/lifecycle_engine.py` | 472 | LifecycleEngine, phases, improvements |
| `Niblit/main.py` | 62419 | System entrypoint |
| `Niblit/modules/runtime_bootstrap.py` | 56 | Path/CWD setup |
| `Niblit/niblit_router.py` | large | Router (not fully read) |
| `Niblit-cloud-server/app/main.py` | large | CloudServer entrypoint |
| `Niblit-cloud-server/app/runtime.py` | large | CloudRuntime boot stages |
| `Niblit-cloud-server/app/trading/` | 10 files | Trading pipeline (completed earlier) |

---

## Summary

LocalBrain is Niblit's **local GGUF inference layer** — a separate concern from the LifecycleEngine (orchestration) and CloudRuntime (server infrastructure). It exists to provide zero-cost, always-available local reasoning. Its current architecture is functional but has duplication with CloudServer's inference layer, circular dependency risks with CloudServer, and no explicit lifecycle management. The most impactful improvements would be unifying the model interface, breaking the LocalBrain→CloudServer dependency, and adding explicit lifecycle stages.