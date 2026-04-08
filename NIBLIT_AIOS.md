# NIBLIT-AIOS Architecture

## Canonical Name

```
NIBLIT-AIOS
Neural Integrated Baseline for Learning, Intelligence, and Tasking
Artificial Intelligence Operating System
```

---

## Acronym Breakdown

| Letter | Expansion | System Mapping |
|--------|-----------|---------------|
| **N** | Neural | `modules/hf_brain.py` (HFBrain), `modules/vector_store.py` (embedding), `modules/llm_adapter.py` |
| **I** | Integrated | Unified agents + tools + memory under a single runtime |
| **B** | Baseline | Foundational pre-OS intelligence layer — always-on, always-learning |
| **L** | Learning | `modules/autonomous_learning_engine.py` (ALE), `modules/self_teacher.py`, `modules/knowledge_comprehension.py` |
| **I** | Intelligence | `niblit_brain.py` (NiblitBrain), `modules/reasoning_engine.py`, `modules/concept_synthesizer.py` |
| **T** | Tasking | `niblit_core.py` (CommandRegistry + execution), agents, CLI workflows |
| — | — | — |
| **A** | Artificial Intelligence | The full NIBLIT reasoning + learning stack |
| **I** | Intelligence | The kernel + orchestration layer that makes decisions |
| **O** | Operating | Scheduling, resource management, I/O, persistence, control |
| **S** | System | The complete runtime environment binding all layers |

---

## Clean Architecture Stack

```
╔══════════════════════════════════════════════════════════════════╗
║                        AIOS LAYER                               ║
║  ┌──────────────────────────────────────────────────────────┐   ║
║  │  Orchestrator        niblit_orchestrator.py              │   ║
║  │  Runtime / Scheduler modules/niblit_runtime.py           │   ║
║  │  Tool Interface      modules/terminal_tools.py           │   ║
║  │                      modules/internet_manager.py         │   ║
║  │  Persistence         niblit_memory/ + niblit_sqlite_db   │   ║
║  │  Execution Control   lifecycle_engine.py                 │   ║
║  │  Kernel              modules/niblit_kernel.py            │   ║
║  └──────────────────────────────────────────────────────────┘   ║
╠══════════════════════════════════════════════════════════════════╣
║                       NIBLIT CORE                               ║
║  ┌──────────────────────────────────────────────────────────┐   ║
║  │  NiblitBrain         niblit_brain.py (reasoning/infer.)  │   ║
║  │    └─ HFBrain        modules/hf_brain.py                 │   ║
║  │    └─ LLMAdapter     modules/llm_adapter.py              │   ║
║  │    └─ ClaudeAdapter  modules/anthropic_adapter.py        │   ║
║  │                                                          │   ║
║  │  Memory System       niblit_memory/ (KnowledgeDB,        │   ║
║  │                      MemoryManager, LocalDB)             │   ║
║  │    └─ MemoryGraph    modules/memory_graph.py (SECA ARG)  │   ║
║  │    └─ VectorStore    modules/vector_store.py (MiniLM)    │   ║
║  │    └─ HybridQdrant   modules/hybrid_qdrant_manager.py    │   ║
║  │                                                          │   ║
║  │  Concept Extractor   modules/knowledge_comprehension.py  │   ║
║  │    └─ Synthesizer    modules/concept_synthesizer.py      │   ║
║  │    └─ RewardModel    modules/reward_model.py (SECA SRM)  │   ║
║  │                                                          │   ║
║  │  Trainer (ALE)       modules/autonomous_learning_engine  │   ║
║  │    └─ SelfTeacher    modules/self_teacher.py             │   ║
║  │    └─ BrainTrainer   niblit_brain.py (BrainTrainer)      │   ║
║  │    └─ LLMTraining    modules/llm_training_agent.py       │   ║
║  │                                                          │   ║
║  │  Agent System        niblit_agents/ + agents/            │   ║
║  │    └─ Router         niblit_router.py                    │   ║
║  │    └─ ChatDetector   niblit_router.py (ChatDetector)     │   ║
║  └──────────────────────────────────────────────────────────┘   ║
╠══════════════════════════════════════════════════════════════════╣
║                     INTERFACE LAYER                             ║
║  ┌──────────────────────────────────────────────────────────┐   ║
║  │  CLI Shell           main.py (run_shell loop)            │   ║
║  │  REST API            server.py / app.py (Flask)          │   ║
║  │  Mobile Client       kivy_app.py                        │   ║
║  │  Notification Bus    core/notification_queue.py          │   ║
║  └──────────────────────────────────────────────────────────┘   ║
╚══════════════════════════════════════════════════════════════════╝
```

---

## Naming Conventions

Consistent shorthand for code and documentation:

| Scope | Module / Symbol | File |
|-------|----------------|------|
| `niblit_core` | `NiblitCore` | `niblit_core.py` |
| `niblit_brain` | `NiblitBrain`, `BrainTrainer`, `hf_query` | `niblit_brain.py` |
| `niblit_router` | `NiblitRouter`, `ChatDetector` | `niblit_router.py` |
| `aios_kernel` | `NiblitKernel` | `modules/niblit_kernel.py` |
| `aios_runtime` | `AIOSRuntime`, `get_aios_runtime()` | `aios_runtime.py` |
| `niblit_runtime` | `NiblitRuntime`, `Adaptable`, `get_niblit_runtime()` | `modules/niblit_runtime.py` |
| `aios_orchestrator` | orchestration + diagnostics | `niblit_orchestrator.py` |
| `aios_scheduler` | `AIOSScheduler`, `ScheduledTask`, `get_aios_scheduler()` | `aios_scheduler.py` |
| `aios_hal` | `HAL`, `get_aios_hal()` | `aios_hal.py` |
| `aios_memory` | `KnowledgeDB`, `MemoryManager`, `LocalDB` | `niblit_memory/__init__.py` |
| `aios_persistence` | `KnowledgeStore`, SQLite | `niblit_memory/__init__.py` |

---

## Boot Sequence & Runtime Lifecycle

This is the formal boot sequence that turns NIBLIT-AIOS from architecture
into an executable system.

### Phase 0 — Pre-Boot (Environment)

```
main.py ──► Load .env (python-dotenv)
        ──► logging.basicConfig(WARNING)         # single root StreamHandler
        ──► Signal handlers: SIGINT, SIGTERM, SIGHUP → _shutdown_on_signal()
        ──► os.chdir(BASE_DIR)                   # lock working directory
```

**Module:** `main.py`  
**AIOS role:** Environment initialisation, signal wiring, working-directory lock.

---

### Phase 1 — BIOS / HAL (Hardware Abstraction)

```
modules/bios.py ──► BIOS.boot_sequence()        # basic hardware checks
modules/bios_integration.py                     # platform capability probing
modules/hardware_scanner.py                     # detect CPU / GPU / memory
modules/platform_bootstrap.py                  # platform-specific init
modules/os_integration.py                       # OS API wiring
```

**AIOS role:** Hardware Abstraction Layer — detects the execution environment
(cloud, Termux, desktop, edge device) and configures the runtime accordingly.

---

### Phase 2 — Bootloader (Core Services)

```
modules/bootloader.py ──► Bootloader.start()   # simulated boot start
niblit_core.py        ──► NiblitCore.__init__()
    ├── CommandRegistry.register_all()          # all CLI commands
    ├── StructuredLogging (correlation IDs)
    ├── RateLimiter, CircuitBreaker, Metrics
    ├── EventSourcing ledger open
    ├── PluginArchitecture.discover()           # hot-reload plugins
    └── MonitoringAlerting.start()
```

**AIOS role:** Core service bootstrap — command dispatch, fault tolerance,
observability, and event-sourcing infrastructure come online.

---

### Phase 3 — Memory System (Persistence)

```
niblit_memory/__init__.py ──► KnowledgeDB.connect()      # SQLite open
                          ──► LocalDB.connect()
                          ──► MemoryManager.init()
modules/vector_store.py   ──► load_sentence_transformer() # MiniLM embed model
modules/memory_graph.py   ──► MemoryGraph.init()          # SECA ARG
modules/hybrid_qdrant_manager.py ──► connect / create_collection()
```

**NIBLIT role:** Memory System online — vector + relational + graph storage
are all ready before any inference begins.

---

### Phase 4 — Intelligence Layer (NiblitBrain)

```
niblit_brain.py ──► NiblitBrain.__init__()
    ├── HFBrain / LLMProviderManager.wire(hf_brain, claude)
    ├── LLMChatMemory.load()                   # persistent chat history
    ├── KnowledgeComprehension.init()          # concept extractor (SECA)
    │     ├── ConceptSynthesizer
    │     └── RewardModel (SRM)
    ├── BrainTrainer.connect(KnowledgeDB)
    └── LLMTrainingAgent.init()
```

**NIBLIT role:** Reasoning and inference layer online.
`brain.think(query)` is now callable: SECA enriches the prompt via
`search_graph()`, the LLM generates a response, `reward_model.record_feedback()`
propagates quality back to the MemoryGraph.

---

### Phase 5 — Autonomous Learning Engine (ALE)

```
modules/autonomous_learning_engine.py ──► ALE.__init__()
    ├── GradedCurriculum.build_topics()        # curriculum-aligned topics
    ├── SelfTeacher.init()
    ├── SelfResearcher.init()
    ├── LLMTrainingAgent.connect()
    └── ALE._start_background_thread()         # runs when idle
```

**NIBLIT role:** Background learning loop starts.  When the system is idle,
ALE autonomously researches topics, extracts concepts, trains the brain, and
writes ledger entries — all without user interaction.

---

### Phase 6 — Agent System & Router

```
niblit_router.py ──► NiblitRouter.__init__()
    ├── ChatDetector.compile_patterns()
    ├── GapAnalyzer.init()
    ├── IntentParser.init()
    └── all route handlers registered

niblit_agents/ + agents/ ──► agent pool ready
modules/background_jobs.py ──► periodic background jobs start
core/notification_queue.py ──► NotificationQueue + log handler installed
```

**AIOS role:** I/O and scheduling layer.  The router classifies every incoming
message and dispatches it to the correct subsystem.  Background jobs push
output to the notification queue — never interrupting the user's input.

---

### Phase 7 — Interface Layer (Ready)

```
main.py ──► run_shell()   # CLI: blocking input() loop
         OR
server.py ──► Flask app.run()   # REST API: blocking serve loop
         OR
kivy_app.py ──► App().run()     # Mobile: Kivy event loop
```

**AIOS role:** Execution control handed to the interface. NIBLIT-AIOS is
fully operational.

---

### Continuous Runtime Loop

```
┌─────────────────────────────────────────────────────────────┐
│  AIOS Runtime Loop (steady state)                           │
│                                                             │
│  [Interface] ──► user_input / API_request                   │
│       │                                                     │
│       ▼                                                     │
│  [Router]    ──► classify → command | chat | query | gap   │
│       │                                                     │
│       ▼                                                     │
│  [NiblitBrain] ──► SECA enrich → LLM infer → respond      │
│       │                  │                                  │
│       │            reward_model.record_feedback()           │
│       │                                                     │
│       ▼                                                     │
│  [Memory]    ──► store interaction / learning / concept     │
│       │                                                     │
│       ▼                                                     │
│  [Notifications] ──► print background queue (after Enter)  │
│                                                             │
│  [ALE Thread — when idle]                                   │
│    research → extract → train → ledger → sleep             │
│                                                             │
│  [Lifecycle Engine — heartbeat]                             │
│    health checks → circuit breakers → metrics → alerts     │
└─────────────────────────────────────────────────────────────┘
```

---

### Shutdown Sequence

```
Signal (SIGINT / SIGTERM / SIGHUP)
    ──► _shutdown_on_signal()
          ├── NiblitCore.shutdown()
          │     ├── ALE.stop()               # flush learning queue
          │     ├── EventSourcing.close()    # flush audit ledger
          │     └── PluginArchitecture.unload_all()
          ├── NiblitBrain.flush_cache()
          ├── KnowledgeDB.close()
          └── sys.exit(0)
```

---

## AIOS Responsibilities Summary

| Responsibility | Component | File |
|---------------|-----------|------|
| Process scheduling | `LifecycleEngine` | `lifecycle_engine.py` |
| Agent orchestration | `NiblitCore` + `NiblitOrchestrator` | `niblit_core.py`, `niblit_orchestrator.py` |
| Model selection | `LLMProviderManager` | `modules/llm_provider_manager.py` |
| Memory management | `MemoryManager`, `KnowledgeDB` | `niblit_memory/__init__.py` |
| I/O layer (APIs) | Flask (`server.py`), Kivy (`kivy_app.py`) | — |
| I/O layer (sensors) | `modules/internet_manager.py` | — |
| Persistence | SQLite + Qdrant + JSON state files | — |
| Execution control | `CommandRegistry`, `NiblitRouter` | `niblit_core.py`, `niblit_router.py` |
| Autonomy bounds | `RateLimiter`, `CircuitBreaker` | `modules/rate_limiting.py`, `modules/circuit_breaker.py` |
| Self-improvement | `ALE`, `SelfTeacher`, `SECA` | `modules/autonomous_learning_engine.py` |
| Health monitoring | `NiblitKernel`, `MonitoringAlerting` | `modules/niblit_kernel.py` |
| Deployment health | Nibblebot Deployment Bot | `nibblebots/deployment_bot.py` |
| Knowledge growth | Nibblebot Research Bot | `nibblebots/research_bot.py` |

---

## Implemented Architecture Components

The following components from the AIOS proposal have been implemented:

1. ✅ **`aios_runtime.py`** — `AIOSRuntime.boot()` owns the Phase 0→7 boot
   sequence with per-phase timing, hook registration, and singleton access via
   `get_aios_runtime()`.

2. ✅ **`aios_scheduler.py`** — `AIOSScheduler` wraps `LifecycleEngine` and
   adds a priority heap queue (`ScheduledTask`), phase advancement, task
   submit/cancel, and singleton access via `get_aios_scheduler()`.

3. ✅ **`aios_hal.py`** — `HAL` consolidates `bios.py`, `bios_integration.py`,
   `hardware_scanner.py`, and `platform_bootstrap.py` behind a unified
   `HAL.probe()` → `HALProfile` API.  Singleton via `get_aios_hal()`.

4. ✅ **`Adaptable` Protocol** (`modules/niblit_runtime.py`) — `@runtime_checkable
   class Adaptable(Protocol)` defines the `aios_component_name`,
   `aios_declared_level`, and `on_adaptation_challenge()` contract for
   first-class AIOS citizens.

5. ✅ **Boot telemetry** — `AIOSRuntime._emit_telemetry()` emits a structured
   `aios.boot.complete` event at Phase 7 with per-phase timing, total boot
   duration, and `boot_id` to the `aios.runtime` logger (DEBUG) and the
   notification queue.

