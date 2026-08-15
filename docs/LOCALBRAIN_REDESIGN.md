# LocalBrain Redesign — Next-Generation Architecture

**Date:** 2026-07-26  
**Constraint:** Design Document Only — No Implementation  
**Purpose:** Blueprint for redesigning LocalBrain to work with the new Cloud Runtime architecture

---

## 1. Current LocalBrain

`modules/local_brain.py` (2883 lines) currently implements:

### QwenLocalBrain
- **Lazy GGUF inference** via 3 backends: HTTP (llama-server), subprocess (llama-cli), python (llama-cpp-python)
- **Model management**: load, cache, swap local models
- **Chat templating**: qwen/llama2/alpaca/raw templates
- **Server health checks**: TTL-cached llama-server probes
- **Cloud fallback**: NiblitCloudBrain HTTP client

### NiblitCloudBrain
- **HTTP client** to CloudServer endpoints
- **Fallback chain**: `/v1/chat/completions` → `/chat/completions` → `/v1/bridge/inference` → `/chat`

### BrainTrainer
- **Training data**: records exchanges, ingests research
- **Persistence**: MemoryManager + HybridQdrantManager
- **Knowledge synthesis**: injects context into prompts

### Configuration
- **20+ env vars** read at import time
- **Module-level constants** (`_MAX_NEW_TOKENS`, `_GGUF_N_CTX`, `_LLAMA_SERVER_URL`, etc.)
- **`_LocalBrainConfig`** singleton (newer pattern, not universally used)

### Key Methods
- `generate()`, `chat()`, `ask()`, `generate_with_tools()`
- `_ensure_loaded()`, `_check_server_url()`, `_check_server_url_cached()`
- `swap_local_brain()`, `set_backend_url()`

---

## 2. Proposed LocalBrain

**New role: Runtime Orchestrator**

LocalBrain becomes a lightweight coordinator that validates, launches, monitors, and recovers the CloudRuntime. It does NOT perform inference, model loading, or process management.

### Core Responsibilities

#### 1. Runtime Discovery
Locate all required components:
- `llama-server` binary path
- GGUF model files
- Cloud Server executable (`niblit-cloud.exe` or `python main.py`)
- Configuration files
- Runtime profiles (local, balanced, power, offline)

#### 2. Runtime Validation
Verify prerequisites:
- llama-server exists and is executable
- GGUF model exists and is readable
- CloudRuntime executable exists
- Configuration is valid (env vars, paths)
- Ports are available
- Dependencies are met

#### 3. Runtime Coordination
Coordinate startup sequence:
- Invoke RuntimeBootstrap
- Invoke RuntimeManager
- Launch CloudRuntime (if not running)
- Wait for READY state
- Expose status to UI

#### 4. Runtime Monitoring
Continuously monitor:
- CloudRuntime health (HTTP `/healthz`)
- llama-server availability (HTTP probe)
- Model availability (loaded/unloaded)
- API availability (response time)
- Memory usage
- Disk usage

#### 5. Runtime Status
Expose unified status to:
- UI Runtime (WebSocket/REST)
- RuntimeManager (in-process)
- Diagnostics (CLI/REST)
- Scheduler (background jobs)

#### 6. Runtime Recovery
Handle failures:
- Restart CloudRuntime on crash
- Reconnect to llama-server if dropped
- Fallback to degraded mode
- Restore from checkpoint
- Alert on unrecoverable errors

---

## 3. Responsibility Migration

| Responsibility | Current Owner | Future Owner |
|----------------|---------------|--------------|
| Runtime orchestration | LocalBrain | **LocalBrain** |
| Runtime discovery | LocalBrain | **LocalBrain** |
| Runtime validation | LocalBrain | **LocalBrain** |
| Runtime coordination | LocalBrain | **LocalBrain** |
| Runtime monitoring | LocalBrain | **LocalBrain** |
| Runtime status | LocalBrain | **LocalBrain** |
| Runtime recovery | LocalBrain | **LocalBrain** |
| Inference | LocalBrain (QwenLocalBrain) | **CloudRuntime (GGUFEngine)** |
| Model loading | LocalBrain (QwenLocalBrain) | **CloudRuntime (ModelManager)** |
| GGUF execution | LocalBrain (QwenLocalBrain) | **CloudRuntime (GGUFEngine)** |
| llama.cpp compilation | LocalBrain | **Build system / CI** |
| llama-server process mgmt | LocalBrain (subprocess backend) | **CloudRuntime** |
| Scheduler | LocalBrain (none) | **CloudRuntime** |
| WebSocket | LocalBrain (none) | **CloudRuntime** |
| API services | LocalBrain (none) | **CloudRuntime** |
| Embeddings | LocalBrain (none) | **CloudRuntime** |
| Vector database | LocalBrain (none) | **CloudRuntime** |
| Trading runtime | LocalBrain (none) | **CloudRuntime** |
| Lean runtime | LocalBrain (none) | **CloudRuntime** |
| Health subsystem | LocalBrain (TTL cache) | **CloudRuntime** |
| Cloud fallback | LocalBrain (NiblitCloudBrain) | **NiblitBrain** (orchestrates CloudRuntime) |
| Brain training | LocalBrain (BrainTrainer) | **NiblitBrain** (uses CloudRuntime) |
| Configuration | LocalBrain (env vars) | **CloudConfig + LocalBrain config** |

---

## 4. Startup Flow

### Current Flow
```
Niblit
    ↓
RuntimeBootstrap
    ↓
LifecycleEngine
    ↓
NiblitCore
    ↓
QwenLocalBrain
    ↓
Load GGUF
    ↓
Ready
```

### Proposed Flow
```
Niblit
    ↓
RuntimeBootstrap
    ↓
RuntimeManager
    ↓
LocalBrain (Orchestrator)
    ↓
    ├── Validate runtime
    │       ├── llama-server exists
    │       ├── GGUF exists
    │       ├── CloudRuntime exists
    │       └── config valid
    │
    ├── Discover resources
    │       ├── locate binaries
    │       ├── locate models
    │       └── enumerate profiles
    │
    └── Launch CloudRuntime
            ↓
        CloudRuntime
            ↓
        21 Boot Stages
            ↓
        Load GGUF
            ↓
        Launch llama-server
            ↓
        OpenAI API ready
            ↓
        READY
    ↓
LocalBrain monitors CloudRuntime
    ↓
UI connects
    ↓
Ready
```

### Detailed Transitions

1. **System Boot**
   - `main.py` starts
   - `RuntimeBootstrap.bootstrap_runtime_environment()` sets up paths

2. **RuntimeBootstrap → RuntimeManager**
   - `RuntimeManager` initializes
   - Loads `CloudConfig`
   - Discovers runtimes

3. **RuntimeManager → LocalBrain**
   - `LocalBrain` instantiated
   - Reads configuration
   - Discovers resources

4. **LocalBrain validates**
   - Checks llama-server binary exists
   - Checks GGUF model exists
   - Checks CloudRuntime executable exists
   - Validates configuration
   - Returns validation report

5. **LocalBrain launches CloudRuntime**
   - Spawns `python main.py` in `Niblit-cloud-server/`
   - Or connects to existing CloudRuntime
   - Waits for READY state

6. **CloudRuntime boots**
   - 21 stages execute
   - GGUF loaded
   - llama-server launched
   - OpenAI API ready

7. **LocalBrain monitors**
   - HTTP probes to `/healthz`
   - API availability checks
   - Resource usage monitoring

8. **UI connects**
   - WebSocket/REST to CloudRuntime
   - LocalBrain exposes status

9. **Ready**
   - All systems operational
   - LocalBrain watching for failures

---

## 5. Integration Points

### LocalBrain ↔ RuntimeBootstrap
- **Direction:** LocalBrain depends on RuntimeBootstrap
- **Protocol:** In-process Python
- **Data:** Repository root, sys.path configuration
- **When:** Startup, before LocalBrain initialization

### LocalBrain ↔ RuntimeManager
- **Direction:** Bidirectional
- **Protocol:** In-process Python
- **Data:** Runtime status, lifecycle events, configuration
- **When:** Continuous

### LocalBrain ↔ CloudRuntime
- **Direction:** LocalBrain → CloudRuntime (HTTP)
- **Protocol:** HTTP REST
- **Endpoints:**
  - `GET /healthz` — health check
  - `GET /v1/runtime/status` — detailed status
  - `GET /v1/runtime/diagnostics` — diagnostics
  - `POST /v1/runtime/model/switch` — model switching
  - `POST /v1/runtime/restart` — restart request
- **Data:** JSON requests/responses
- **When:** Continuous monitoring, on-demand control

### LocalBrain ↔ UI
- **Direction:** Bidirectional
- **Protocol:** WebSocket + REST
- **Data:** Runtime status, logs, diagnostics, commands
- **When:** UI connected

### LocalBrain ↔ Scheduler
- **Direction:** LocalBrain → Scheduler (via RuntimeManager)
- **Protocol:** In-process Python
- **Data:** Job schedules, triggers, status
- **When:** Continuous

### LocalBrain ↔ Memory
- **Direction:** Bidirectional
- **Protocol:** In-process Python
- **Data:** Runtime events, logs, state snapshots
- **When:** Continuous

### LocalBrain ↔ Event Bus
- **Direction:** Bidirectional
- **Protocol:** In-process pub/sub
- **Events:**
  - `runtime.started`
  - `runtime.ready`
  - `runtime.degraded`
  - `runtime.crashed`
  - `runtime.recovered`
- **When:** Continuous

### LocalBrain ↔ Trading Runtime
- **Direction:** LocalBrain → Trading Runtime (via CloudRuntime)
- **Protocol:** HTTP REST
- **Path:** LocalBrain → CloudRuntime → TradingPipeline
- **When:** On-demand

### LocalBrain ↔ Lean Runtime
- **Direction:** LocalBrain → Lean Runtime (via CloudRuntime)
- **Protocol:** HTTP REST + file signals
- **Path:** LocalBrain → CloudRuntime → LeanBridge
- **When:** On-demand

---

## 6. Benefits

### Separation of Concerns
- **CloudRuntime** owns execution: inference, model loading, scheduling, APIs, embeddings, vector DB, trading, Lean
- **LocalBrain** owns orchestration: discovery, validation, coordination, monitoring, recovery
- **NiblitBrain** owns cognition: reasoning, learning, training, knowledge

### Clear Ownership
- No duplicated inference logic
- No duplicated health checks
- No duplicated lifecycle management
- Single source of truth for each responsibility

### Lifecycle Management
- CloudRuntime has explicit 21-stage boot
- LocalBrain has explicit orchestration lifecycle
- NiblitBrain has explicit 9-phase lifecycle
- Each manages its own concerns

### Maintainability
- Smaller, focused modules
- Clear interfaces between components
- Easier testing (mock HTTP instead of subprocess)
- Easier debugging (clear ownership)

### Extensibility
- Easy to add new CloudRuntime capabilities (trading, Lean, etc.)
- LocalBrain doesn't need to change for new CloudRuntime features
- UI can consume CloudRuntime directly or via LocalBrain

### Future Multi-Model Support
- CloudRuntime already supports multiple providers (Qwen, Ollama, OpenAI, Anthropic, HF, vLLM, remote)
- LocalBrain just orchestrates, doesn't care about model specifics

### Future Distributed Runtime Support
- CloudRuntime can be on a different machine
- LocalBrain just needs HTTP endpoint
- No subprocess/process management coupling

---

## 7. File Structure

### Current
```
modules/local_brain.py (2883 lines)
    ├── QwenLocalBrain (inference)
    ├── NiblitCloudBrain (HTTP client)
    ├── BrainTrainer (training)
    ├── _LocalBrainConfig (config)
    └── Module-level constants
```

### Proposed
```
modules/
    ├── local_brain.py (orchestrator only, ~500 lines)
    │       ├── LocalBrainOrchestrator
    │       ├── validate_runtime()
    │       ├── discover_resources()
    │       ├── coordinate_runtime()
    │       ├── monitor_health()
    │       ├── runtime_status()
    │       └── runtime_recovery()
    │
    ├── local_brain_config.py (moved to shared config)
    │       └── LocalBrainConfig
    │
    └── local_brain_inference.py (DELETED — moved to CloudRuntime)
```

### Migrated to CloudRuntime
```
Niblit-cloud-server/
    ├── app/
    │   ├── runtime.py (CloudRuntime — already exists)
    │   ├── main.py (GGUFEngine, ModelManager — already exists)
    │   └── trading/ (trading pipeline — already exists)
    └── tests/ (already exists)
```

### Migrated to NiblitBrain
```
Niblit/
    ├── niblit_brain.py
    │   ├── NiblitBrain (orchestrates CloudRuntime via HTTP)
    │   ├── BrainRouter (routes to CloudRuntime)
    │   └── NiblitCloudBrain (thin HTTP client, moved from local_brain.py)
    └── modules/
        └── brain_trainer.py (BrainTrainer, moved from local_brain.py)
```

---

## 8. Communication Protocol

### LocalBrain → CloudRuntime

```json
// Health check
GET /healthz
Response: {"status": "ok"}

// Detailed status
GET /v1/runtime/status
Response: {
  "runtime": "niblit_cognitive_cloud_runtime",
  "version": "0.9.0",
  "models": [...],
  "default_model": {...},
  "context_runtime": {...}
}

// Diagnostics
GET /v1/runtime/diagnostics
Response: {
  "runtime_health": 1.0,
  "inference_pressure": {...},
  "attention_pressure": {...},
  "context_runtime": {...},
  ...
}

// Inference (via NiblitBrain or direct)
POST /v1/chat/completions
Request: {
  "model": "qwen",
  "messages": [{"role": "user", "content": "Hello"}],
  "max_tokens": 256
}
Response: {
  "id": "chatcmpl-...",
  "choices": [{"message": {"content": "Hi!"}}]
}
```

### LocalBrain → NiblitBrain

```python
# In-process Python calls
brain.think(prompt)  #returns str
brain.ask(prompt)    # returns str
brain.chat(messages) # returns str
```

---

## 9. Migration Path

### Phase 1: Extract Orchestrator (No CloudRuntime changes)
1. Create `LocalBrainOrchestrator` class in `local_brain.py`
2. Move inference code to `_local_brain_inference.py` (temporary)
3. Keep everything working

### Phase 2: CloudRuntime Independence
1. Ensure CloudRuntime can run standalone
2. Add health endpoints
3. Add status endpoints
4. Test without LocalBrain

### Phase 3: LocalBrain Orchestrator
1. Implement `validate_runtime()`
2. Implement `discover_resources()`
3. Implement `coordinate_runtime()`
4. Implement `monitor_health()`
5. Implement `runtime_status()`
6. Implement `runtime_recovery()`

### Phase 4: Migration
1. Move BrainTrainer to NiblitBrain
2. Move NiblitCloudBrain to NiblitBrain
3. Remove inference code from LocalBrain
4. Update callers

### Phase 5: Cleanup
1. Delete `_local_brain_inference.py`
2. Remove module-level constants
3. Remove backwards-compatible aliases
4. Update documentation

---

## 10. Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Circular dependency LocalBrain ↔ CloudRuntime | Medium | High | LocalBrain only calls CloudRuntime HTTP, never imports |
| Subprocess management lost | Medium | Medium | CloudRuntime owns process management |
| Training data loss | Low | Medium | BrainTrainer moves to NiblitBrain with same interface |
| UI breakage | Medium | Low | UI calls CloudRuntime directly or via LocalBrain |
| Performance regression | Low | Low | HTTP overhead minimal vs local inference |
| Configuration drift | Medium | Medium | Unified CloudConfig |

---

## 11. Open Questions

1. **Should LocalBrain still exist?** Or should NiblitCore directly manage CloudRuntime?
   - **Recommendation:** Keep LocalBrain as a thin orchestrator for backward compatibility and clear separation.

2. **Should NiblitCloudBrain move to NiblitBrain or CloudRuntime?**
   - **Recommendation:** Move to NiblitBrain (thin HTTP client).

3. **Should BrainTrainer move to NiblitBrain or stay in LocalBrain?**
   - **Recommendation:** Move to NiblitBrain (training is cognitive, not orchestration).

4. **Should LocalBrain expose a REST API?**
   - **Recommendation:** Yes, for UI and diagnostics. Small FastAPI app or extend CloudRuntime.

5. **Should CloudRuntime be a separate process?**
   - **Recommendation:** Yes, for isolation and independent lifecycle.

6. **How does LocalBrain handle CloudRuntime crashes?**
   - **Recommendation:** Exponential backoff restart with circuit breaker.

---

## Summary

The proposed redesign transforms LocalBrain from a **monolithic inference engine** into a **lightweight runtime orchestrator**. CloudRuntime becomes the authoritative runtime for inference, model management, scheduling, APIs, embeddings, vector DB, trading, and Lean execution. LocalBrain validates, launches, monitors, and recovers CloudRuntime. NiblitBrain handles cognition, reasoning, and training.

This architecture:
- Eliminates duplication between LocalBrain and CloudRuntime
- Provides clear ownership and separation of concerns
- Enables independent evolution of each component
- Supports future distributed deployments
- Maintains backward compatibility through orchestration layer

**Next Steps:**
1. Review this design with stakeholders
2. Implement Phase 1 (extract orchestrator)
3. Implement Phase 2 (CloudRuntime independence)
4. Implement Phase 3 (LocalBrain orchestrator)
5. Implement Phase 4 (migration)
6. Implement Phase 5 (cleanup)