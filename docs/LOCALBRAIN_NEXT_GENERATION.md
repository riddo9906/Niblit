# LocalBrain Next Generation — Final Architecture

**Date:** 2026-07-26  
**Constraint:** Design Document Only — No Implementation  
**Scope:** `modules/local_brain.py` and every file that directly interacts with it  
**Purpose:** Definitive blueprint for LocalBrain's role in Niblit 2.0

---

## Section 1: What Should LocalBrain Become?

**Recommendation: Runtime Gateway**

LocalBrain should become a **Runtime Gateway** — a lightweight orchestration layer whose sole purpose is to validate, launch, monitor, and recover the CloudRuntime.

### Reasoning

The term "Orchestrator" implies active coordination of multiple services. The term "Supervisor" implies passive monitoring. The term "Gateway" implies both:
- It is the **entry point** through which the rest of Niblit accesses the runtime
- It is the **gatekeeper** that validates prerequisites before allowing access
- It is the **coordinator** that launches and monitors the runtime
- It is the **recovery agent** that handles failures

This matches LocalBrain's new role perfectly:
- It is the first runtime component NiblitCore touches
- It validates the runtime before allowing inference
- It launches CloudRuntime and waits for READY
- It monitors health and recovers on failure
- It exposes unified status to UI, RuntimeManager, and diagnostics

**Why not Orchestrator?**  
Orchestrator implies managing multiple independent services with complex coordination logic. LocalBrain should not manage services — CloudRuntime does that. LocalBrain should only manage CloudRuntime itself.

**Why not Supervisor?**  
Supervisor implies passive watching. LocalBrain must actively launch and recover CloudRuntime, which is more than supervision.

**Why not Coordinator?**  
Coordinator implies mediating between peer services. LocalBrain stands between Niblit and CloudRuntime, not between peers.

**Gateway** is the precise term: one door, one responsibility, clear ownership.

---

## Section 2: Responsibilities That Remain Inside LocalBrain

These responsibilities cannot logically belong anywhere else:

### 1. Runtime Discovery
- Locate `llama-server` binary
- Locate GGUF model files
- Locate CloudRuntime executable
- Enumerate runtime profiles (local, balanced, power, offline)
- **Why here:** LocalBrain is the first Niblit component to touch the runtime. It must find the pieces before anyone else can use them.

### 2. Runtime Validation
- Verify `llama-server` exists and is executable
- Verify GGUF model exists and is readable
- Verify CloudRuntime executable exists
- Validate configuration (env vars, paths, ports)
- Check dependencies are met
- **Why here:** Validation must happen before launch. LocalBrain is the gatekeeper.

### 3. Runtime Coordination
- Invoke RuntimeBootstrap
- Invoke RuntimeManager
- Launch CloudRuntime (spawn process or connect to existing)
- Wait for READY state
- Coordinate startup sequence
- **Why here:** LocalBrain is the parent process that owns CloudRuntime's lifecycle.

### 4. Runtime Monitoring
- Probe CloudRuntime health (`/healthz`)
- Probe llama-server availability
- Monitor model availability
- Track API response times
- Monitor resource usage (memory, disk)
- **Why here:** LocalBrain is the supervisor. CloudRuntime does not monitor itself.

### 5. Runtime Status
- Expose unified status to UI (WebSocket/REST)
- Expose status to RuntimeManager (in-process)
- Expose diagnostics to CLI/REST
- Expose status to Scheduler (background jobs)
- **Why here:** LocalBrain is the single pane of glass for runtime state.

### 6. Runtime Recovery
- Restart CloudRuntime on crash (exponential backoff)
- Reconnect to llama-server if dropped
- Fallback to degraded mode
- Restore from checkpoint
- Alert on unrecoverable errors
- **Why here:** Recovery requires ownership of the runtime process. Only LocalBrain can restart CloudRuntime.

### 7. Configuration Discovery
- Read LocalBrain-specific env vars
- Discover runtime profiles
- Resolve model paths and binary paths
- **Why here:** LocalBrain-specific configuration that doesn't belong in CloudConfig.

---

## Section 3: Responsibilities That Must Move Into CloudRuntime

These responsibilities now belong exclusively to CloudRuntime because CloudRuntime is the authoritative runtime:

### Inference
- GGUF model loading and execution
- Backend management (HTTP, subprocess, python)
- Chat templating (qwen, llama2, alpaca, raw)
- Token generation
- Stop token handling
- **Why:** CloudRuntime already owns inference via `GGUFEngine` and `ModelManager`. LocalBrain should not duplicate this.

### Model Management
- Model registry (unified discovery across providers)
- Model loading/caching/switching
- Model health checks
- Provider management (Qwen, Ollama, OpenAI, Anthropic, HF, vLLM, remote)
- **Why:** CloudRuntime already owns this via `ModelRegistry` and `ModelManager`. Duplication causes divergence.

### Scheduler
- Background job scheduling
- Queue processing
- Health heartbeat
- Metrics collection
- Model watcher
- Cache manager
- Cleanup tasks
- **Why:** CloudRuntime already owns this via its scheduler and worker manager modules.

### WebSocket
- WebSocket server
- WebSocket broadcasting
- WebSocket client management
- **Why:** CloudRuntime owns the API layer. WebSocket is part of that layer.

### API Services
- REST API endpoints
- OpenAI-compatible endpoints
- Trading endpoints
- Cognitive endpoints
- Federation endpoints
- Metrics endpoints
- **Why:** CloudRuntime already exposes all APIs. LocalBrain should not duplicate.

### Embeddings
- Embedding service
- Embedding generation
- Embedding caching
- **Why:** CloudRuntime already owns this. LocalBrain has no need for embeddings.

### Vector Database
- Qdrant integration
- Vector search
- Semantic indexing
- **Why:** CloudRuntime already owns this. LocalBrain has no need for vector DB.

### Trading Runtime
- Market data adapter
- Market intelligence
- Lean-algos bridge
- GGUF validation
- Risk engine
- Trade intent
- Freqtrade adapter
- Execution feedback
- Trading pipeline
- **Why:** CloudRuntime already owns the complete trading pipeline. LocalBrain should not duplicate.

### Lean Runtime
- LEAN engine integration
- Signal generation
- Backtesting
- Live deployment
- **Why:** CloudRuntime already owns this via `LeanBridge`. LocalBrain should not duplicate.

### Health Subsystem
- Health verification
- Degraded mode detection
- Health endpoint (`/healthz`)
- Health diagnostics
- **Why:** CloudRuntime already owns this. LocalBrain's TTL cache is insufficient compared to CloudRuntime's comprehensive health system.

### Process Management
- `llama-server` process management
- Subprocess spawning
- Process lifecycle
- **Why:** CloudRuntime already owns this. LocalBrain's subprocess backend is obsolete.

### Configuration Loading
- CloudConfig loading
- Unified configuration
- Configuration validation
- **Why:** CloudRuntime already owns this via `CloudConfig`. LocalBrain should not have its own config loading.

---

## Section 4: Responsibilities That Belong Inside NiblitBrain Instead

These responsibilities are cognitive, not orchestration. They belong in NiblitBrain:

### Cloud Fallback
- `NiblitCloudBrain` HTTP client
- Fallback chain (`/v1/chat/completions` → `/chat/completions` → `/v1/bridge/inference` → `/chat`)
- **Why:** Cloud fallback is a cognitive routing decision. NiblitBrain decides when to escalate to cloud. LocalBrain should not make cognitive decisions.

### Brain Training
- `BrainTrainer` — records exchanges, ingests research
- Training data persistence
- Knowledge synthesis
- Context injection
- **Why:** Training is a cognitive function. NiblitBrain learns and improves. LocalBrain only orchestrates runtime.

### Chat/Ask/Generate
- `generate()`, `chat()`, `ask()`, `generate_with_tools()`
- Prompt construction
- Response parsing
- **Why:** These are cognitive operations. NiblitBrain thinks and generates responses. LocalBrain only launches the runtime that enables thinking.

### Cognitive Routing
- `BrainRouter` — local vs balanced vs power vs offline
- Model selection for cognitive tasks
- **Why:** Routing cognitive requests is a brain function, not a runtime function.

---

## Section 5: Definitive Ownership Table

| Responsibility | Owner | Rationale |
|----------------|-------|-----------|
| Runtime discovery | **LocalBrain** | First touchpoint; must find components |
| Runtime validation | **LocalBrain** | Gatekeeper; validates before launch |
| Runtime coordination | **LocalBrain** | Owns CloudRuntime lifecycle |
| Runtime monitoring | **LocalBrain** | Supervisor of CloudRuntime |
| Runtime status | **LocalBrain** | Single pane of glass |
| Runtime recovery | **LocalBrain** | Only component that can restart CloudRuntime |
| Configuration discovery | **LocalBrain** | LocalBrain-specific config |
| Inference | **CloudRuntime** | Authoritative inference runtime |
| Model loading | **CloudRuntime** | ModelManager owns models |
| GGUF execution | **CloudRuntime** | GGUFEngine owns execution |
| llama.cpp compilation | **Build system** | Not a runtime concern |
| llama-server process mgmt | **CloudRuntime** | Owns llama-server lifecycle |
| Scheduler | **CloudRuntime** | Background services |
| WebSocket | **CloudRuntime** | API layer |
| API services | **CloudRuntime** | REST endpoints |
| Embeddings | **CloudRuntime** | Embedding service |
| Vector database | **CloudRuntime** | Qdrant integration |
| Trading runtime | **CloudRuntime** | Trading pipeline |
| Lean runtime | **CloudRuntime** | Lean integration |
| Health subsystem | **CloudRuntime** | Health verification |
| Cloud fallback | **NiblitBrain** | Cognitive routing decision |
| Brain training | **NiblitBrain** | Cognitive learning |
| Chat/Ask/Generate | **NiblitBrain** | Cognitive operations |
| Cognitive routing | **NiblitBrain** | BrainRouter |
| Memory | **NiblitCore** | Shared subsystem |
| Event bus | **NiblitCore** | Shared subsystem |
| Runtime lifecycle | **CloudRuntime** | 21 boot stages |
| Reasoning | **NiblitBrain** | Cognitive function |
| Cognition | **NiblitBrain** | Brain.think() |
| Learning | **NiblitBrain** | ALE + BrainTrainer |
| Routing | **NiblitRouter** | Command routing |
| Monitoring | **LocalBrain** | Runtime monitoring |
| Diagnostics | **CloudRuntime** | `/v1/runtime/diagnostics` |
| Runtime validation | **LocalBrain** | Pre-flight checks |
| Runtime discovery | **LocalBrain** | Find components |
| Runtime recovery | **LocalBrain** | Restart/reconnect |
| Cloud server launching | **LocalBrain** | Spawn CloudRuntime process |
| llama-server launching | **CloudRuntime** | Owns llama-server |
| GGUF loading | **CloudRuntime** | ModelManager loads models |

---

## Section 6: Final Architecture Design

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        Niblit System                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐     │
│  │ main.py     │───▶│ Runtime     │───▶│ LocalBrain (Gateway)    │     │
│  │ (entrypoint)│    │ Bootstrap   │    │                         │     │
│  └─────────────┘    └─────────────┘    │ ┌─────────────────────┐ │     │
│                            │            │ │ Runtime Discovery   │ │     │
│                            ▼            │ │ Runtime Validation  │ │     │
│                     ┌─────────────┐     │ │ Runtime Coordination│ │     │
│                     │ Runtime     │     │ │ Runtime Monitoring  │ │     │
│                     │ Manager     │◄────┼─┤ Runtime Status      │ │     │
│                     └─────────────┘     │ │ Runtime Recovery    │ │     │
│                                         │ └─────────────────────┘ │     │
│  ┌─────────────┐                        └──────────┬──────────────┘     │
│  │ NiblitCore  │◄─────────────────────────────────┘                     │
│  └──────┬──────┘                                                         │
│         │                                                                 │
│         ▼                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐     │
│  │ NiblitBrain │    │ Niblit      │    │ NiblitRouter            │     │
│  │ (cognition) │    │ Memory      │    │ (100+ commands)         │     │
│  └──────┬──────┘    └─────────────┘    └──────────┬──────────────┘     │
│         │                                           │                     │
│         │    ┌─────────────┐                       │                     │
│         └───▶│ CloudBrain  │◄──────────────────────┘                     │
│              │ (HTTP client)│   routes to CloudRuntime                    │
│              └─────────────┘                                              │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTP REST
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      Niblit Cloud Server                                 │
│                   (Niblit-cloud-server/)                                 │
│                                                                         │
│  ┌─────────────┐                                                         │
│  │ CloudRuntime│ 21 Boot Stages                                          │
│  │             │ ├── Configuration                                        │
│  │             │ ├── Storage                                              │
│  │             │ ├── Model Registry                                       │
│  │             │ ├── Inference                                            │
│  │             │ ├── Embeddings                                           │
│  │             │ ├── Vector Database                                      │
│  │             │ ├── API Services                                         │
│  │             │ ├── WebSocket                                            │
│  │             │ ├── Scheduler                                            │
│  │             │ ├── Background Services                                  │
│  │             │ ├── Plugins                                             │
│  │             │ ├── Market Data                                          │
│  │             │ ├── Market State                                         │
│  │             │ ├── Memory                                               │
│  │             │ ├── Lean Algorithms                                      │
│  │             │ ├── LLM Validation                                       │
│  │             │ ├── Risk Engine                                          │
│  │             │ ├── Freqtrade                                            │
│  │             │ ├── Execution Monitor                                    │
│  │             │ ├── Health                                               │
│  │             │ └── READY                                               │
│  └─────────────┘                                                         │
│         │                                                                 │
│         ▼                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐          │
│  │ GGUFEngine  │  │ ModelManager│  │ Trading Pipeline         │          │
│  │ (inference) │  │ (models)    │  │ (market→lean→validate→   │          │
│  └──────┬──────┘  └─────────────┘  │  risk→execute→feedback)  │          │
│         │                            └─────────────────────────┘          │
│         ▼                                                                 │
│  ┌─────────────┐                                                         │
│  │ llama-server│◄── launched by CloudRuntime                             │
│  │ (HTTP)      │                                                         │
│  └──────┬──────┘                                                         │
│         │                                                                 │
│         ▼                                                                 │
│  ┌─────────────┐                                                         │
│  │ GGUF Model  │◄── loaded by llama-server                                │
│  │ (.gguf)     │                                                         │
│  └─────────────┘                                                         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ HTTP REST / WebSocket
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          Niblit UI                                       │
│                       (Niblit-ui/)                                       │
│  Web dashboard + WebSocket client                                       │
└─────────────────────────────────────────────────────────────────────────┘
```

### Integration Details

#### NiblitCore → LocalBrain
- **Protocol:** In-process Python
- **Calls:** `local_brain.validate()`, `local_brain.launch()`, `local_brain.status()`, `local_brain.recover()`
- **When:** Startup, on-demand, continuous

#### LocalBrain → RuntimeBootstrap
- **Protocol:** In-process Python
- **Calls:** `bootstrap_runtime_environment()`
- **When:** Before LocalBrain initialization

#### LocalBrain → RuntimeManager
- **Protocol:** In-process Python
- **Calls:** `runtime_manager.register()`, `runtime_manager.get_status()`
- **When:** Continuous

#### LocalBrain → CloudRuntime
- **Protocol:** HTTP REST
- **Endpoints:**
  - `GET /healthz` — health check
  - `GET /v1/runtime/status` — detailed status
  - `GET /v1/runtime/diagnostics` — diagnostics
  - `POST /v1/runtime/model/switch` — model switching
  - `POST /v1/runtime/restart` — restart request
- **When:** Continuous monitoring, on-demand control

#### LocalBrain → UI
- **Protocol:** WebSocket + REST
- **Data:** Runtime status, logs, diagnostics, commands
- **When:** UI connected

#### LocalBrain → Scheduler
- **Protocol:** In-process Python (via RuntimeManager)
- **Data:** Job schedules, triggers, status
- **When:** Continuous

#### LocalBrain → Memory
- **Protocol:** In-process Python
- **Data:** Runtime events, logs, state snapshots
- **When:** Continuous

#### LocalBrain → EventBus
- **Protocol:** In-process pub/sub
- **Events:**
  - `runtime.started`
  - `runtime.ready`
  - `runtime.degraded`
  - `runtime.crashed`
  - `runtime.recovered`
- **When:** Continuous

#### NiblitBrain → CloudRuntime
- **Protocol:** HTTP REST
- **Endpoints:**
  - `POST /v1/chat/completions` — inference
  - `POST /v1/bridge/inference` — bridge inference
  - `GET /v1/models` — model listing
- **When:** On-demand inference

#### CloudRuntime → llama-server
- **Protocol:** HTTP REST
- **Endpoints:**
  - `POST /v1/chat/completions` — inference
  - `GET /health` — health check
- **When:** Continuous (if HTTP backend active)

#### CloudRuntime → GGUF
- **Protocol:** Native (llama.cpp library)
- **Calls:** `Llama()` instance, `create_chat_completion()`
- **When:** Inference requests

---

## Section 7: Communication Protocol

### Recommendation: HTTP REST + In-Process Python

LocalBrain should communicate with CloudRuntime using **HTTP REST** for the following reasons:

#### Why HTTP REST?

1. **Process isolation** — CloudRuntime runs as a separate process. HTTP is the natural boundary.
2. **Language agnostic** — If CloudRuntime is ever rewritten in a different language, HTTP still works.
3. **Standard tooling** — curl, Postman, load balancers, proxies, monitoring tools all work with HTTP.
4. **Stateless** — Each request is independent. No shared state corruption.
5. **Testable** — Easy to mock HTTP in tests.
6. **Observable** — HTTP traffic is easy to log, trace, and monitor.
7. **Scalable** — Can add load balancers, replicas, or move CloudRuntime to a different machine.

#### Why not IPC?

1. **Tight coupling** — IPC requires same machine, same language runtime.
2. **Debugging difficulty** — Harder to trace and debug than HTTP.
3. **Tooling** — Fewer standard tools for IPC debugging.
4. **Future distributed** — If CloudRuntime moves to a different machine, IPC breaks.

#### Why not Events?

1. **Request-response pattern** — LocalBrain needs request-response (launch, wait for READY, get status). Events are fire-and-forget.
2. **Complexity** — Would need correlation IDs, timeouts, retries built on top of events.
3. **Overkill** — Events are great for async notifications, but LocalBrain needs synchronous coordination.

#### Why not Shared Runtime?

1. **Defeats the purpose** — CloudRuntime was designed to be independent. Shared runtime re-couples them.
2. **Testing difficulty** — Harder to test in isolation.
3. **Lifecycle coupling** — If CloudRuntime crashes, LocalBrain crashes. We want resilience.

### Why In-Process Python for NiblitCore ↔ LocalBrain?

1. **No overhead** — Same process, direct function calls.
2. **Type safety** — Python type hints work.
3. **Exception handling** — Natural exception propagation.
4. **Performance** — Zero serialization overhead.

### Protocol Summary

| Channel | Protocol | Format | Rationale |
|---------|----------|--------|-----------|
| LocalBrain ↔ CloudRuntime | HTTP REST | JSON | Process isolation, standard tooling, testable, observable |
| LocalBrain ↔ NiblitCore | In-process Python | Native | Same process, zero overhead |
| LocalBrain ↔ RuntimeManager | In-process Python | Native | Same process, zero overhead |
| LocalBrain ↔ UI | WebSocket + REST | JSON | UI needs both push and pull |
| LocalBrain ↔ EventBus | In-process pub/sub | Native | Same process, low latency |

---

## Section 8: Final Recommendation

### What LocalBrain Should Be for Niblit 2.0

**LocalBrain is a Runtime Gateway.**

It is the single entry point through which Niblit accesses its runtime infrastructure. It validates, launches, monitors, and recovers the CloudRuntime. It does not execute inference, load models, manage processes, or make cognitive decisions.

### What LocalBrain Is Not

- **Not an inference engine** — CloudRuntime handles inference
- **Not a model loader** — CloudRuntime loads models
- **Not a process manager** — CloudRuntime manages llama-server
- **Not a cognitive brain** — NiblitBrain handles cognition
- **Not a training system** — NiblitBrain handles training
- **Not an API server** — CloudRuntime exposes APIs

### What LocalBrain Owns

- **Runtime Discovery** — Find components
- **Runtime Validation** — Verify prerequisites
- **Runtime Coordination** — Launch and sequence
- **Runtime Monitoring** — Watch health
- **Runtime Status** — Expose unified view
- **Runtime Recovery** — Restart and reconnect

### File Structure

```
modules/
    └── local_brain.py (~500 lines)
            └── LocalBrainGateway
                ├── discover()
                ├── validate()
                ├── launch()
                ├── monitor()
                ├── status()
                └── recover()
```

### Configuration

```
LocalBrain-specific env vars:
    NIBLIT_CLOUD_RUNTIME_PATH     Path to CloudRuntime executable
    NIBLIT_RUNTIME_PROFILE        Runtime profile (local/balanced/power/offline)
    NIBLIT_RUNTIME_HEALTH_TTL     Health check TTL (default: 10s)
    NIBLIT_RUNTIME_RESTART_MAX    Max restart attempts (default: 5)
    NIBLIT_RUNTIME_BACKOFF_INIT   Initial backoff (default: 1s)
    NIBLIT_RUNTIME_BACKOFF_MAX    Max backoff (default: 60s)
```

### Lifecycle

```
LocalBrain Gateway Lifecycle:
    1. discover() — find all components
    2. validate() — verify prerequisites
    3. launch() — start CloudRuntime
    4. monitor() — continuous health checks
    5. recover() — on failure
    6. shutdown() — graceful stop
```

### Benefits for Niblit 2.0

1. **Clear separation** — LocalBrain orchestrates, CloudRuntime executes, NiblitBrain cognates
2. **No duplication** — Inference logic lives in one place (CloudRuntime)
3. **Independent evolution** — CloudRuntime can evolve without LocalBrain changes
4. **Testability** — LocalBrain tests mock CloudRuntime HTTP
5. **Resilience** — LocalBrain can restart crashed CloudRuntime
6. **Observability** — HTTP makes monitoring trivial
7. **Distribution** — CloudRuntime can be on a different machine
8. **Backward compatibility** — Existing NiblitCore code calls LocalBrain, which now calls CloudRuntime

### What Changes

| Component | Change |
|-----------|--------|
| `modules/local_brain.py` | Reduced from 2883 lines to ~500 lines. Removes QwenLocalBrain, NiblitCloudBrain, BrainTrainer. Adds LocalBrainGateway. |
| `NiblitCore` | Minor updates to call new LocalBrainGateway API |
| `CloudRuntime` | No changes — already complete |
| `NiblitBrain` | Moves NiblitCloudBrain and BrainTrainer from local_brain.py |
| `niblit_brain.py` | Adds HTTP client for CloudRuntime |

### What Does Not Change

| Component | Change |
|-----------|--------|
| CloudRuntime | No changes — already authoritative |
| Trading pipeline | No changes — already in CloudRuntime |
| Model management | No changes — already in CloudRuntime |
| Inference engine | No changes — already in CloudRuntime |
| Scheduler | No changes — already in CloudRuntime |
| Health system | No changes — already in CloudRuntime |

### Final Statement

**LocalBrain for Niblit 2.0 is a Runtime Gateway.**

It is the thin, lightweight layer between Niblit and CloudRuntime. It validates, launches, monitors, and recovers. It does not execute, load, or decide. It orchestrates exactly one thing: the CloudRuntime.

This design:
- Respects the new CloudRuntime architecture
- Eliminates all duplication
- Provides clear ownership
- Enables resilience and recovery
- Supports future distribution
- Maintains backward compatibility

**This is the blueprint for LocalBrain redesign.**