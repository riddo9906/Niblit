# NIBLIT-AIOS: Neural Integrated Baseline for Learning, Intelligence, and Tasking
## Artificial Intelligence Operating System

Licensed under the MIT License. See [LICENSE](LICENSE) and [NOTICE](NOTICE) for details.

Niblit is a **self-improving, autonomous AI operating system** that learns,
researches, codes, reflects, and fine-tunes itself — running 24/7 on any device,
including your Android phone via Termux.

---

## Table of Contents

- [What is Niblit?](#what-is-niblit)
- [What Can Niblit Do?](#what-can-niblit-do)
- [Running Niblit in Termux (proot-Ubuntu)](#running-niblit-in-termux-proot-ubuntu)
- [Running Niblit in a Simulated Environment in Termux](#running-niblit-in-a-simulated-environment-in-termux)
- [🆕 NiblitOS — Niblit IS the Operating System](#niblitos--niblit-is-the-operating-system)
- [🆕 Running Qwen Locally on Termux](#running-qwen-locally-on-termux)
- [🆕 Two-Session Setup: Niblit in proot + Qwen in Termux](#two-session-setup-niblit-in-proot--qwen-in-termux)
- [🆕 Niblit Sidecar Control Terminal](#-niblit-sidecar-control-terminal)
- [Architecture: The LLM Engineer's Pipeline](#architecture-the-llm-engineers-pipeline)
- [Architecture: The Trading AI Engineer's Pipeline](#architecture-the-trading-ai-engineers-pipeline)
- [Quick Start](#quick-start)
- [What YOU Need To Do](#what-you-need-to-do)
- [APIs and Accounts Required](#apis-and-accounts-required)
- [Environment Variables Reference](#environment-variables-reference)
- [Autonomous Learning Engine (ALE) — 32-Step Cycle](#autonomous-learning-engine-ale--32-step-cycle)
- [Copilot Code Engine](#copilot-code-engine)
- [Nibblebot Research Bots](#nibblebot-research-bots)
- [Fine-Tuning Your Own Local Model](#fine-tuning-your-own-local-model)
- [Live Trading Configuration](#live-trading-configuration)
- [🆕 Niblit Cyber Membrane](#-niblit-cyber-membrane)
- [🆕 Defensive Evolution Loop](#-defensive-evolution-loop)
- [🆕 Cognitive Kernel v3](#-cognitive-kernel-v3)
- [🆕 Sync Engine (LCSP v1)](#-sync-engine-lcsp-v1)
- [🆕 Memory Weighting & Decay System (MWDS v2)](#-memory-weighting--decay-system-mwds-v2)
- [🆕 Cognition Core](#-cognition-core)
- [🆕 Goal Engine](#-goal-engine)
- [🆕 Position Sizer (Kelly Criterion)](#-position-sizer-kelly-criterion)
- [🆕 Domain Tokenizer Trainer](#-domain-tokenizer-trainer)
- [🆕 Phased Research Engine](#-phased-research-engine)
- [🆕 Cognitive Graph Kernel v1.0](#-cognitive-graph-kernel-v10)
- [🆕 Autonomous Evolution Engine (Phases 2–9.5)](#-autonomous-evolution-engine-phases-295)
- [🆕 Unified Cognitive Runtime PR Update (May 2026)](#-unified-cognitive-runtime-pr-update-may-2026)
- [🆕 C++ NiblitOS Kernel Progress (May 2026)](#-c-niblitos-kernel-progress-may-2026)
- [Project Structure](#project-structure)
- [Running Tests](#running-tests)
- [Troubleshooting](#troubleshooting)

---

## What is Niblit?

Niblit started as a Python AI assistant and has evolved into a full **AI
Operating System (AIOS)** that runs a continuous 32-step autonomous learning
cycle (ALE), builds its own knowledge graph, generates and compiles code, and
improves itself — without needing a cloud GPU.

```
Research → Learn → Reflect → Generate Code → Quality-Check →
Compile → Reason → Fine-Tune → Evaluate → Heal → Repeat
```

Key design choices:
- **No cloud required.** Niblit runs entirely on your device.  External LLMs
  (HuggingFace Inference, Anthropic Claude) are optional upgrades.
- **Multi-source knowledge.** Every fact Niblit stores comes from Wikipedia,
  DuckDuckGo, SerpAPI, GitHub code search, its own generated code, and
  internal reflections.
- **Self-correcting code.** Generated code is never saved unless it passes
  CodeQL-style static analysis and syntax checks — automatically.
- **Civilisation of agents.** 5 specialised AI agent roles (researcher,
  coder, teacher, critic, explorer) collaborate inside Niblit's own
  civilisation simulator (STACA).

---

## What Can Niblit Do?

### 🧠 Autonomous Learning
- Runs a 32-step **Autonomous Learning Engine (ALE)** cycle in the background
- Researches topics via DuckDuckGo, SerpAPI, Wikipedia, and GitHub
- Builds a persistent **Knowledge Graph (Graph-RAG)** across 3 tiers
- Reflects on what it has learned and generates new research directions
- Fills knowledge gaps automatically when you ask questions it cannot answer

### 💬 Conversational AI
- Full **chat interface** with LLM history (HuggingFace / Anthropic)
- KB-aware responses: answers from its own knowledge first, LLM second
- Works offline with pre-trained local models via `LOCAL_MODEL_PATH`
- Remembers facts between sessions via `niblit_memory`
- Chat completions via `ChatCompletions` engine (GraphRAG + LLM)

### 🔧 Copilot-Style Code Engine
- `/api/code` endpoint: Copilot-style code generation from natural language
- Generates Python, JavaScript, Bash, Rust, Go, C/C++, TypeScript, SQL, …
- **CodeQL-style quality checks**: security rules, bare-except, eval/exec,
  hardcoded secrets, SQL injection, unquoted shell variables, `chmod 777`
- **Error fixer**: `fix_until_clean()` loops fix → validate → quality-check
  until the code is error-free, blocking saves of broken code
- **Project context awareness**: loads existing codebase files to guide LLM
- Compiles and runs generated code via `CodeCompiler` with sandboxed execution

### 📈 Live Trading AI
- RSI, MACD, EMA-20, ATR-14, volatility indicators
- PPO, DQN, and Transformer RL policies (`NIBLIT_RL_ENABLED=1`)
- Binance and Alpaca exchange connectors
- 7-dimensional state vector for continuous learning

### 🌐 REST API (FastAPI)
- `/api/code` — Copilot code generation with quality gate
- `/chat` — Conversational interface
- `/api/knowledge` — KB lookup
- `/api/status` — System health
- `/api/hf-ask` — Direct LLM query
- `/api/slsa-status` — SLSA artifact status
- Full command catalog via `/api/commands`

### 🔬 Self-Improvement
- `EvolveEngine`: generates new Python modules to extend Niblit itself
- `SelfImprovementOrchestrator`: research → code → deploy cycle
- `CivilizationController (STACA)`: 5-agent society that evolves strategies
- `SLSAGenerator`: builds structured semantic artifacts from live data
- `CognitionCore`: unifies ReasoningEngine + GoalEngine + MemoryGraph
- `GoalEngine`: goal-directed learning — fills the gaps Niblit identifies in itself

### 🔐 Security & Self-Defence
- **Cyber Membrane** (8 layers): InputGuard, OutputGuard, TrackerSensor, StealthDetector, AdaptiveFirewall, SessionWarden, IntegrityMonitor
- **DefensiveEvolutionLoop**: self-attacking immunity loop — Niblit attacks itself in a sandbox to find weaknesses before real attackers do
- **Dynamic rule injection**: bypass discoveries automatically add detection patterns at runtime

### 🗃️ SLSA (Structured Live Sense Artifacts)
- Wikipedia REST API + PhasedResearchEngine + InternetManager pipeline
- Extracts: definition, structure, function, origin, evolution, context
- Stores complete semantic artifacts in KB with `slsa:` prefix
- Partial artifacts stored and updated on subsequent cycles

---


## Governed Qdrant Memory Cluster

Niblit now includes a governed cognition-aware Qdrant memory layer and a deployable `qdrant_cluster_logic/` blueprint package. The runtime normalizes memory payloads through `shared/governance_contract/memory_contracts.py`, routes them through `niblit_memory/governed_qdrant_memory.py`, and preserves replay lineage, federation provenance, lifecycle state, and governance-aware retrieval semantics across semantic, episodic, reflection, governance, runtime, replay, telemetry, advisor, federation, and execution memory collections.

## Unified System Wiring (Python AIOS + C++ NiblitOS)

Niblit now operates as one coordinated system instead of loosely-coupled loops:

1. **Runtime cognition** (`niblit_core.py`, `niblit_brain.py`) handles turn execution.
2. **Evaluation + reinforcement** (`modules/evaluation_engine.py`, `modules/quality_feedback.py`) produce quality signals.
3. **Turn-quality arbitration** (`niblit_core._arbitrate_turn_quality`) resolves conflicting quality sources into one runtime authority.
4. **Adaptive layer** (`modules/adaptive_learning.py`) consumes resolved quality without duplicate reinforcement writes (`propagate_quality=False`).
5. **Long-term learning** (`niblit_learning.py`) evolves interaction preferences using a bounded recency window.
6. **Governance + evolution** (`nibblebots/*`) applies policy constraints and autonomous adaptation.
7. **Health/observability** (`_refresh_unified_feedback_status`, `system_health_monitor`) exposes loop quality + arbitration diagnostics.

This architecture prioritizes coherence, causality, and bounded adaptation under scale.

### Current bottleneck controls

- **Feedback conflict guardrails:** high disagreement between evaluation and reinforcement does not get naively averaged.
- **Bounded learning aggregation:** `NIBLIT_LEARNING_EVOLVE_WINDOW` and `NIBLIT_LEARNING_SCAN_MULTIPLIER` avoid unbounded per-turn aggregation growth.
- **Single-turn quality authority:** adaptive satisfaction mapping consumes resolved turn-quality, reducing drift between subsystems.

### NiblitOS (C++) integration path

For OS-level execution, the C++ kernel and Python stack connect through the Niblit IPC ring:

`kernel/syscall + niblit_iface` ⇄ `os/userland/niblit_tool/niblit_runner.c` ⇄ `niblit_entry.py` ⇄ `NiblitCore`.

Useful host-side bridge targets:

```bash
make niblit-runner
make niblit-runner-run
```

These complement:

```bash
make boot-kernel
make boot-kernel-iso
make run-os
```

---

## 🆕 Unified Cognitive Runtime PR Update (May 2026)

This PR unifies runtime layers into a single runtime authority while keeping the
`niblit_dashboard.py` + `server.py` Cognitive Runtime Shell architecture as the
canonical Niblit operating environment.

### Core runtime unification delivered

- Added `modules/unified_runtime.py` with:
  - `NiblitUnifiedRuntime` (composition root)
  - `RuntimeState` (persistent state authority)
  - `RuntimeEventBus` (normalized event feed + replay cursor model)
  - `ProviderRuntimeManager` (provider registry, scoring, health/fallback routing)
  - `RuntimeTelemetryManager` (unified telemetry snapshots)
  - `DeploymentRuntimeManager` (runtime environment detection/topology)
  - `CommandRuntime` (runtime-native command dispatch)
- Introduced canonical runtime stream envelope:
  - `stream_format = "niblit.runtime.stream.v1"`

### Runtime API + stream surfaces (server + app parity)

Added in both `server.py` and `app.py`:

- `GET /api/runtime/state`
- `GET /api/runtime/events`
- `WS /ws/runtime`

Also integrated runtime state into existing status surfaces:

- `/api/status` now includes runtime mode/provider/deployment/event counters
- `/api/bg_status` now includes runtime mode/provider slices
- boot path initializes unified runtime snapshots

### Provider/runtime command routing changes

- Chat/runtime command path now dispatches through `CommandRuntime` (with
  compatibility fallback to existing core handling).
- Added runtime-native command support:
  - `runtime status`
  - `runtime provider <name>`
  - `runtime infer <prompt>`
- Preserved existing `llm-provider` command behavior and compatibility.

### Shell/UI runtime integration without replacing architecture

- Preserved existing shell design system, panel model, and command philosophy.
- Added runtime websocket client in dashboard JS to hydrate telemetry/status
  from unified runtime stream frames.
- Kept existing polling paths for graceful compatibility fallback.

### Security + maintainability hardening included in follow-up commit

- Hardened dashboard script JSON injection in `server.py`:
  - escapes `</`, `<`, `>` when embedding JSON payloads in script context.
- Replaced runtime magic numbers with constants in `modules/unified_runtime.py`.
- Consolidated runtime command prefixes into constants.
- Added `max_tokens`-aware Router V2 call path when supported by signature.

### Tests added/updated for this PR

- Added `test_unified_runtime_architecture.py`
  - runtime managers
  - normalized events/frames
  - server runtime endpoints + websocket behavior
- Added `test_app_unified_runtime.py`
  - app runtime endpoint + websocket parity
- Confirmed compatibility with existing runtime-shell tests:
  - `test_server.py`
  - `test_niblit_runtime_ui.py`

### Additional PR file updates now explicitly documented

Alongside runtime-focused code, this PR also included state/log snapshot updates:

- `niblit_state.json`
- `niblit_memory.json.snapshot`
- `nibblebots/context_guard_log.jsonl`
- `nibblebots/impact_weights.json`

---

## 🆕 C++ NiblitOS Kernel Progress (May 2026)

Current status: **advanced prototype / early real kernel stage**, not yet
production-grade general-purpose OS.

### What is already strong

- Real multiboot kernel and boot path (`os/kernel/kernel.cpp`).
- Core low-level subsystems present:
  - GDT/IDT/IRQ/PIT
  - paging + physical memory allocator + heap
  - process scheduler and task model
  - VFS + ProcFS
  - device/driver surfaces (keyboard, ATA, PCI, ACPI, DMA, net)
- Kernel shell command surface and observability paths exist.
- AI-specific syscall/IPC pathway is implemented in kernel space:
  - `niblit_query`, `niblit_tool`, IPC ring mapping, epoch sync, KB read/write.
- End-to-end bridge model defined:
  - kernel ring ↔ userspace runner ↔ Python `NiblitCore`.

### Practical maturity assessment

- **Boot/infrastructure maturity:** medium-high (for hobby/research OS stage).
- **Kernel reliability/safety maturity:** medium-low (needs stronger isolation/fault hardening).
- **Userspace/process model maturity:** medium-low (fork/wait are still stubs).
- **Security model maturity:** low-medium (requires privilege/isolation expansion).
- **Production readiness:** not yet (still a research/experimental OS runtime).

### Highest-impact improvements recommended next

1. **Process model completion**
   - replace `fork`/`waitpid` stubs with real semantics (or explicitly remove
     stubs and expose supported process APIs only).
2. **Memory safety + isolation hardening**
   - strengthen user/kernel separation, syscall pointer validation, guard pages,
     and robust fault handling paths.
3. **Scheduler and preemption robustness**
   - starvation/fairness instrumentation, priority policy, lock/IRQ-safe paths.
4. **Driver/runtime fault containment**
   - improve per-driver failure handling so a faulty device path cannot cascade.
5. **IPC ring formalization**
   - ABI versioning, strict bounds/contracts, replay/error semantics, and fuzz tests.
6. **Filesystem durability strategy**
   - define persistence guarantees, crash consistency, and recovery policy.
7. **Networking hardening**
   - expand protocol correctness testing and defensive parsing.
8. **Toolchain/test automation**
   - add deterministic kernel regression harnesses (boot assertions, syscall tests,
     IPC contract tests, stress tests).
9. **Security model for AI syscalls**
   - capability/ACL gating for AI-oriented syscalls and KB mutation operations.
10. **Performance telemetry loop**
   - expose stable kernel metrics contract consumed by runtime telemetry manager.

---

## Running Niblit in Termux (proot-Ubuntu)

The recommended way to run Niblit on Android is inside a **proot-distro
Ubuntu** environment inside Termux.  This gives you a full Ubuntu 22.04
userland with Python 3.11 and all system libraries — no root needed.

### 1. Install Termux and proot-distro

Install **Termux** from [F-Droid](https://f-droid.org/packages/com.termux/)
(do **not** use the Play Store version — it is outdated).

```bash
# Update Termux packages
pkg update && pkg upgrade -y

# Install proot-distro
pkg install proot-distro -y

# Install Ubuntu 22.04
proot-distro install ubuntu
```

### 2. Enter Ubuntu and install dependencies

```bash
# Log into Ubuntu as a normal user
proot-distro login ubuntu --user user

# Inside Ubuntu:
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv git curl build-essential \
               libssl-dev libffi-dev python3-dev

# Optional: install Node.js for JavaScript compilation support
apt install -y nodejs npm
```

### 3. Clone Niblit and install Python packages

```bash
# Clone the repository
git clone https://github.com/riddo9906/Niblit.git ~/NiblitAIOS
cd ~/NiblitAIOS/Niblit-Modules/Niblit-apk/Niblit

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install Niblit dependencies
pip install --upgrade pip
pip install -r requirements.txt

# Optional: sentence-transformers for vector search (requires ~400 MB)
pip install sentence-transformers

# Optional: HuggingFace inference for local LLM
pip install transformers torch --index-url https://download.pytorch.org/whl/cpu
```

### 4. Set up environment variables

```bash
cp .env.example .env
nano .env
```

Minimum recommended settings for Termux:

```dotenv
# HuggingFace token (free tier — get at https://huggingface.co/settings/tokens)
HF_TOKEN=hf_your_token_here

# Disable features that require a GPU or heavy RAM (optional on low-RAM devices)
NIBLIT_AUTONOMOUS_ENGINE=true
NIBLIT_RL_ENABLED=0
NIBLIT_SKIP_INIT_WAIT=0

# Path to your Niblit installation (update if different)
NIBLIT_DEPLOY_PATH=/root/NiblitAIOS/Niblit-Modules/Niblit-apk/Niblit
```

### 5. Start Niblit

```bash
# Activate the virtual environment if not already active
source .venv/bin/activate

# Start Niblit interactive CLI
python main.py

# Or start the REST API server (port 8000)
uvicorn api.index:app --host 0.0.0.0 --port 8000
```

### 6. Keep Niblit running with a persistent login alias

Add to `~/.bashrc` inside Ubuntu:

```bash
alias niblit='cd ~/NiblitAIOS/Niblit-Modules/Niblit-apk/Niblit && source .venv/bin/activate && python main.py'
alias niblit-api='cd ~/NiblitAIOS/Niblit-Modules/Niblit-apk/Niblit && source .venv/bin/activate && uvicorn api.index:app --host 0.0.0.0 --port 8000'
```

Then open a new Termux session and run:

```bash
proot-distro login ubuntu --user user
niblit
```

---

## Running Niblit in a Simulated Environment in Termux

If you want to test Niblit without modifying your main Ubuntu proot-distro
environment — or run multiple isolated Niblit instances — you can use a
**simulated sandbox environment** inside Termux.

### Option A: Native Termux (no proot)

For a lightweight setup with no Ubuntu layer:

```bash
# Install Python directly in Termux
pkg install python git -y
pip install --upgrade pip

# Clone and run
git clone https://github.com/riddo9906/Niblit.git ~/niblit-dev
cd ~/niblit-dev/Niblit-Modules/Niblit-apk/Niblit
pip install -r requirements.txt

# Run with a test/dev config (uses SQLite in /tmp, no deploy writes)
NIBLIT_ENV=testing NIBLIT_SKIP_INIT_WAIT=1 python main.py
```

### Option B: Isolated proot instance (recommended for simulation)

This creates a second, isolated Ubuntu environment just for testing:

```bash
# Back in Termux (not inside proot)
proot-distro install ubuntu --override-alias niblit-sim

# Enter the simulation environment
proot-distro login niblit-sim

# Install Python + Niblit exactly as in the main setup
apt update && apt install -y python3 python3-pip python3-venv git
git clone https://github.com/riddo9906/Niblit.git ~/niblit-sim
cd ~/niblit-sim/Niblit-Modules/Niblit-apk/Niblit
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Inside the simulation environment, set `NIBLIT_ENV=testing` to use in-memory
databases and avoid touching production KB files:

```bash
# Run Niblit in testing mode (in-memory DB, no file writes)
NIBLIT_ENV=testing python main.py
```

### Option C: Docker-style lightweight container via `proot`

If you want an even more isolated simulation without installing proot-distro:

```bash
# In Termux — download and extract a minimal Alpine Linux rootfs
mkdir -p ~/niblit-alpine/rootfs
cd ~/niblit-alpine
curl -L https://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/aarch64/alpine-minirootfs-3.19.1-aarch64.tar.gz | tar xz -C rootfs/

# Enter the Alpine environment
proot --rootfs=rootfs/ -0 -w /root /bin/sh

# Inside Alpine:
apk add python3 py3-pip git
pip install --upgrade pip
# ... clone and install Niblit as above
```

### Environment variables for simulated mode

| Variable | Value | Effect |
|---|---|---|
| `NIBLIT_ENV` | `testing` | In-memory SQLite DB, no disk writes |
| `NIBLIT_SKIP_INIT_WAIT` | `1` | Skip deferred init wait, start immediately |
| `NIBLIT_AUTONOMOUS_ENGINE` | `false` | Disable background ALE cycle |
| `NIBLIT_ALE_INTER_PHASE_SLEEP` | `1` | Speed up ALE phase gaps (default 5s) |
| `NIBLIT_EVOLVE_INTER_PHASE_SLEEP` | `1` | Speed up EvolveEngine (default 5s) |
| `HF_TOKEN` | _(optional)_ | Leave unset to run fully offline |

---

## NiblitOS — Niblit IS the Operating System

NiblitOS is not just an AI agent running on Linux — it is a real, bootable
**x86 operating system** where Niblit itself is the init process (PID 1
equivalent).  The C++ kernel lives in `os/` and boots via GRUB2 /
Multiboot2.

```
BIOS/UEFI → GRUB2 → NiblitOS C++ kernel → niblit-daemon (PID 1) → NiblitCore AI
```

### Why this is different

| Typical AI agent | NiblitOS |
|---|---|
| Runs *on* an OS that can kill it | *Is* the OS — controls scheduling |
| Subject to cgroup resource limits | Sees real RAM/CPU from physical hardware |
| Needs systemd / docker to restart | Boot = Niblit comes up automatically |
| LLM is a subprocess started by the OS | LLM is just a device (`/dev/llm0`) Niblit opens |
| Sandboxed filesystem access | Owns VFS, can spawn or kill any process |

### The full stack

```
Layer  Component           Description
────── ─────────────────── ──────────────────────────────────────────
  C++  NiblitOS kernel      21 subsystems: VGA, GDT, IDT, IRQ, Memory,
                            Paging, Heap, RTC, PIT, Scheduler, VFS,
                            ProcFS, Keyboard, DMA, ACPI, PCI, ATA,
                            E1000 Net, MSG IPC, Syscalls, NiblitIface
  C++  niblit-daemon        Kernel task (PID 1). Polls IPC ring, manages
                            /proc refresh, /var/niblit/kb/
   C   niblit_runner.c      Userland bridge: kernel ring ↔ Python socket
  Py   niblit_entry.py      Python entry: --daemon mode (UNIX socket)
  Py   NiblitCore           Full AI stack: QwenLocalBrain, BrainRouter,
                            ALE 32-step cycle, KnowledgeDB, QwenMemoryAdapter
```

### Niblit-specific syscalls (unique to NiblitOS)

```c
int  SYS_NIBLIT_SPAWN_REASONER = 205  // spawn Python reasoning daemon
int  SYS_NIBLIT_KB_WRITE       = 206  // write KB fact from userspace
int  SYS_NIBLIT_KB_READ        = 207  // read  KB fact from userspace
int  SYS_NIBLIT_RESOURCE_INFO  = 208  // get real RAM/CPU/uptime metrics
int  SYS_NIBLIT_MMAP_RING      = 209  // map IPC ring to userspace addr
```

### /proc filesystem

After boot, `/proc` exposes live kernel data:

```bash
# From the NiblitOS shell (connect via: qemu -serial stdio)
niblit-os> cat /proc/version
NiblitOS v3.0 (C++ kernel + Niblit AI tool layer)
niblit-os> cat /proc/niblit
daemon_status:  active
uptime_ms:      12345
kb_path:        /var/niblit/kb/
niblit-os> procinfo           # refresh all /proc entries and dump
niblit-os> kbwrite my_key my value here
niblit-os> kbread  my_key
```

### Build and boot in QEMU

```bash
# Requires: nasm, i686-elf-g++, grub-mkrescue, qemu-system-i386
cd os
make iso        # builds niblit-os.iso
make run        # boots in QEMU, serial output on stdout

# Connect the shell:
# QEMU output appears on terminal (via -serial stdio)
# Type: help   → full command list
```

See [`os/README.md`](os/README.md) for the full build guide, boot sequence
diagram, and roadmap.

---

## Running Qwen Locally on Termux

Qwen acts as Niblit's **local brain, memory manager, coach, and trainer**
via `modules/local_brain.py` (QwenLocalBrain).  You do **not** need a GPU
or cloud account — the 0.5B GGUF model runs on 512 MB RAM.

### Session 1 — Build llama.cpp (in normal Termux)

```bash
# Install build dependencies
pkg update && pkg install -y clang cmake git

# Clone and build llama.cpp
git clone https://github.com/ggml-org/llama.cpp ~/llama.cpp
cd ~/llama.cpp
mkdir -p build && cd build
cmake .. -DLLAMA_NATIVE=OFF -DLLAMA_BUILD_TESTS=OFF
cmake --build . -j1              # takes 10–30 min on Android
# Binary: ~/llama.cpp/build/bin/llama-cli
```

### Download the Qwen GGUF model

```bash
# Create models directory
mkdir -p ~/models

# Option A — huggingface-cli (requires pip install huggingface-hub)
pip install huggingface-hub
huggingface-cli download \
    Qwen/Qwen2.5-0.5B-Instruct-GGUF \
    qwen2.5-0.5b-instruct-q4_k_m.gguf \
    --local-dir ~/models

# Option B — direct wget (get URL from https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF)
wget -O ~/models/qwen2.5-0.5b-instruct-q4_k_m.gguf \
    "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"
```

### Start the llama-server (HTTP backend — recommended)

Running a server lets Niblit call Qwen without reloading the model for
every request, dramatically reducing latency.

```bash
# Session 1 (normal Termux — keep this open)
~/llama.cpp/build/bin/llama-server \
    -m ~/models/qwen2.5-0.5b-instruct-q4_k_m.gguf \
    --host 127.0.0.1 --port 8080 \
    -c 4096 --threads 4
# Server listens on http://127.0.0.1:8080
```

### Configure Niblit to use the server

In your `.env` (inside proot-Ubuntu, next section):

```dotenv
# Use http backend pointing to the Termux-side llama-server
NIBLIT_GGUF_BACKEND=http
NIBLIT_LLAMA_SERVER_URL=http://127.0.0.1:8080
NIBLIT_LOCAL_MODEL=~/models/qwen2.5-0.5b-instruct-q4_k_m.gguf
```

### Alternative: subprocess backend (no server)

```dotenv
NIBLIT_GGUF_BACKEND=subprocess
NIBLIT_LLAMA_BINARY=~/llama.cpp/build/bin/llama-cli
NIBLIT_GGUF_MODEL_PATH=~/models/qwen2.5-0.5b-instruct-q4_k_m.gguf
```

### Verify Qwen is working

```bash
# Quick smoke test (in proot or normal Termux)
python tools/install_local_qwen_model.py     # verify only
python tools/install_local_qwen_model.py --setup   # show full instructions

# From Niblit CLI once running:
qwen status
qwen ask "What are my current KB gaps?"
qwen audit-kb dry           # dry-run KB quality audit
qwen coach                  # get Niblit improvement recommendations
```

---

## Two-Session Setup: Niblit in proot + Qwen in Termux

The recommended production setup on Android uses **two Termux sessions**
so Qwen's model stays loaded in RAM while Niblit runs in proot-Ubuntu.

```
┌─────────────────────────────────────────────┐
│  Termux Session 1 (normal Termux)           │
│  llama-server --host 127.0.0.1 --port 8080  │
│  (Qwen 0.5B loaded, waiting for requests)   │
└─────────────────────────────────────────────┘
             ↕  HTTP  127.0.0.1:8080
┌─────────────────────────────────────────────┐
│  Termux Session 2 (proot-Ubuntu)            │
│  python main.py   (Niblit AI + ALE cycle)   │
│  NIBLIT_GGUF_BACKEND=http                   │
│  NIBLIT_LLAMA_SERVER_URL=http://127.0.0.1:8080│
└─────────────────────────────────────────────┘
```

### Step-by-step

**Session 1 — Start Qwen server (normal Termux):**

```bash
# Open a new Termux session (swipe right from left edge → New Session)
# This stays running in the background

~/llama.cpp/build/bin/llama-server \
    -m ~/models/qwen2.5-0.5b-instruct-q4_k_m.gguf \
    --host 127.0.0.1 --port 8080 \
    -c 4096 --threads 4 --n-predict 512

# You will see: "llama server listening at http://127.0.0.1:8080"
# Leave this session running.
```

**Session 2 — Run Niblit in proot-Ubuntu:**

```bash
# Open a second Termux session
proot-distro login ubuntu --user user

# Inside Ubuntu:
cd ~/NiblitAIOS/Niblit-Modules/Niblit-apk/Niblit  # or your clone path
source .venv/bin/activate

# Point Niblit at the Termux-side llama-server
export NIBLIT_GGUF_BACKEND=http
export NIBLIT_LLAMA_SERVER_URL=http://127.0.0.1:8080

# Start Niblit
python main.py
```

**Or add to `.env` permanently inside Ubuntu:**

```dotenv
NIBLIT_GGUF_BACKEND=http
NIBLIT_LLAMA_SERVER_URL=http://127.0.0.1:8080
NIBLIT_LOCAL_MODEL=~/models/qwen2.5-0.5b-instruct-q4_k_m.gguf
```

### Termux wake-lock (keep sessions alive)

```bash
# In any Termux session — prevents Android from killing the process
termux-wake-lock

# Or add to ~/.bashrc:
echo "termux-wake-lock" >> ~/.bashrc
```

### Aliases for quick startup

Add to `~/.bashrc` in **normal Termux** (Session 1):

```bash
alias qwen-server='~/llama.cpp/build/bin/llama-server \
    -m ~/models/qwen2.5-0.5b-instruct-q4_k_m.gguf \
    --host 127.0.0.1 --port 8080 -c 4096 --threads 4'
```

Add to `~/.bashrc` in **proot-Ubuntu** (Session 2):

```bash
alias niblit='cd ~/NiblitAIOS/Niblit-Modules/Niblit-apk/Niblit && \
    source .venv/bin/activate && \
    NIBLIT_GGUF_BACKEND=http \
    NIBLIT_LLAMA_SERVER_URL=http://127.0.0.1:8080 \
    python main.py'
```

Then simply:
```bash
# Session 1:  qwen-server
# Session 2 (proot):  proot-distro login ubuntu -- bash -lc niblit
```

### Memory + performance tips

| Setting | Effect |
|---------|--------|
| `--threads 4` | Use 4 CPU threads (A07 has 8 cores, but 4 is stable) |
| `-c 2048` | Smaller context if RAM is tight (< 3 GB free) |
| `NIBLIT_LOCAL_MAX_NEW=256` | Limit Qwen reply length for faster KB audits |
| `NIBLIT_GGUF_N_CTX=2048` | Match context window to server `-c` value |
| `NIBLIT_ALE_INTER_PHASE_SLEEP=2` | Slow ALE a little to free CPU for Qwen |

---

## 🆕 Niblit Sidecar Control Terminal

**Files:** `modules/niblit_sidecar.py` + `tools/niblit_ctl.py`

When the Qwen model loads in Termux (Session 1), its startup output floods
the terminal.  Even after loading, you may want to send Niblit commands from
a **different terminal window** without switching proot sessions.

The **Niblit Sidecar** is a UNIX socket server that starts inside the main
Niblit process (`python main.py`) right at boot — *before* Phase-1 init
completes.  Any terminal can connect and send commands at any time, even
while the model is loading.

### How it works

```
Session 1 (normal Termux)          Session 2 (proot-Ubuntu)
────────────────────────────────   ─────────────────────────
llama-server                        python main.py
[model loading output]               │
                                     │ Sidecar starts listening on
                                     │ /tmp/niblit-ctl.sock
                                     │ (accepts commands immediately)
                                     │ Phase-1 init running in background
                                     │ [model loads in Session 1]
                                     ▼
Session 3 (any new Termux tab)
────────────────────────────────
python tools/niblit_ctl.py
  ⏳ Niblit still initialising... (queued)
  [sends any Niblit command]
  [gets result when init finishes]
```

### Usage

```bash
# Check if Niblit sidecar is running
python tools/niblit_ctl.py --ping

# Open interactive control terminal (full command access)
python tools/niblit_ctl.py

# Wait for init to finish, then open shell
python tools/niblit_ctl.py --wait

# One-shot command (great for scripts)
python tools/niblit_ctl.py -c "brain status"
python tools/niblit_ctl.py -c "recall python"
python tools/niblit_ctl.py -c "qwen status"
python tools/niblit_ctl.py -c "autonomous-learn status"

# JSON output (for scripts / piping)
python tools/niblit_ctl.py -c "status" --json

# Use a custom socket path (if NIBLIT_CTL_SOCKET is set)
python tools/niblit_ctl.py --socket /tmp/my-niblit.sock
```

### Inside the control terminal

All Niblit commands work exactly as in the main shell:

```
Niblit-ctl > brain status
Niblit-ctl > recall python
Niblit-ctl > toggle-llm status
Niblit-ctl > autonomous-learn start
Niblit-ctl > qwen ask What are my knowledge gaps?
Niblit-ctl > help
Niblit-ctl > sidecar status        ← check socket health from main shell
Niblit-ctl > !status               ← check from niblit_ctl
Niblit-ctl > !ping                 ← quick alive check
Niblit-ctl > exit                  ← closes control terminal; Niblit keeps running
```

### Environment variable

| Variable | Default | Effect |
|----------|---------|--------|
| `NIBLIT_CTL_SOCKET` | `/tmp/niblit-ctl.sock` | Path to the UNIX domain socket |

### Three-terminal setup (complete flow)

```bash
# Session 1 — normal Termux:
~/llama.cpp/build/bin/llama-server \
    -m ~/models/qwen2.5-0.5b-instruct-q4_k_m.gguf \
    --host 127.0.0.1 --port 8080

# Session 2 — proot-Ubuntu:
proot-distro login ubuntu
cd ~/Niblit && source .venv/bin/activate
NIBLIT_GGUF_BACKEND=http NIBLIT_LLAMA_SERVER_URL=http://127.0.0.1:8080 python main.py
# → Model loads in Session 1, Niblit init runs here
# → Sidecar socket: 🔌 /tmp/niblit-ctl.sock

# Session 3 — any new Termux tab (while model still loading):
python tools/niblit_ctl.py --wait
# → Waits for init, then opens interactive shell
# → Full Niblit access: brain status, recall, qwen ask, etc.
```

---

## Copilot Code Engine

Niblit includes a Copilot-style code generation system accessible via both
the CLI and the REST API.

### REST API

```bash
# Generate a Python function from a natural-language prompt
curl -X POST http://localhost:8000/api/code \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Create a function that fetches JSON from a URL with error handling",
    "language": "python"
  }'
```

Response:
```json
{
  "code": "#!/usr/bin/env python3\n...",
  "language": "python",
  "success": true,
  "source": "template",
  "quality": {
    "passed": true,
    "score": 98,
    "issues": [],
    "summary": "python analysis: 0 errors, 0 warnings"
  },
  "structure_issues": [],
  "error": null,
  "ts": 1234567890
}
```

The response returns HTTP 422 (not 200) when the quality gate blocks
error-level issues, so callers can distinguish "generated but needs fixing"
from "ready to use".

### CLI

```
Niblit > generate python module name:my_module docstring:Handles HTTP requests
Niblit > generate-copilot python fetch JSON from a URL
Niblit > code-quality check python my_file.py
Niblit > fix-until-clean python my_broken.py
```

### Quality Check Rules

| Severity | Rule | What it catches |
|---|---|---|
| 🔴 error | `syntax-error` | Code that does not parse |
| 🔴 error | `hardcoded-secret` | `password = "..."`, `api_key = "..."` |
| 🔴 error | `sql-injection` | f-string / % formatting into SQL |
| 🔴 error | `eval-usage` (JS) | `eval()` in JavaScript |
| 🔴 error | `destructive-rm` | `rm -rf /` or `rm -rf /*` in Bash |
| 🟡 warning | `bare-except` | `except:` without exception type |
| 🟡 warning | `eval-usage` (Py) | `eval()` or `exec()` in Python |
| 🟡 warning | `os-system` | `os.system()` — prefer `subprocess` |
| 🟡 warning | `missing-shebang` | Bash script without `#!/usr/bin/env bash` |
| 🟡 warning | `unquoted-variable` | `$VAR` instead of `"$VAR"` in Bash |
| 🟡 warning | `chmod-777` | World-writable permissions |
| 🟡 warning | `missing-use-strict` | JavaScript without `'use strict'` |
| 🔵 info | `missing-docstring` | Public function/class without docstring |
| 🔵 info | `long-line` | Lines over 120 characters |
| 🔵 info | `var-declaration` | `var` instead of `const`/`let` in JS |

---


## Architecture: The LLM Engineer's Pipeline

The way the best LLMs are built (GPT, Llama, Mistral, Qwen, Phi) follows
a structured four-stage pipeline.  Niblit implements all four stages:

### Stage 1 — Data Curation

Real LLM engineers:
- Collect trillions of tokens from CommonCrawl, books, code, and scientific papers
- Deduplicate aggressively (MinHash, exact dedup)
- Filter by quality (perplexity filtering, classifier-based filtering)
- Format into prompt/completion pairs for SFT

**How Niblit does it:**
- ALE runs 32 steps every cycle, accumulating KB facts from GitHub, web search,
  Wikipedia, StackOverflow, Qdrant vector store, and its own reflections
- `LLMArchitectEngine.run_curation()` extracts `(prompt, completion)` SFT pairs
  and `(prompt, chosen, rejected)` DPO preference pairs from the KB
- Writes `niblit_sft_dataset.jsonl` and `niblit_dpo_dataset.jsonl` continuously

### Stage 2 — Supervised Fine-Tuning (SFT)

Real LLM engineers:
- Train on instruction-following datasets (Alpaca, FLAN, ShareGPT, UltraChat)
- Use LoRA/QLoRA on consumer hardware for parameter-efficient fine-tuning
- `trl.SFTTrainer` + `peft.LoraConfig` are the standard tools

**How Niblit does it:**
- `LLMArchitectEngine.run_sft()` detects whether `LOCAL_MODEL_PATH` is set
- If yes + `trl`/`peft` installed: runs LoRA SFT on the curated JSONL dataset
- If no: feeds records into `BrainTrainer` for in-context learning (no GPU needed)
- Activates automatically at ALE Step 32 every 10th cycle

### Stage 3 — RLHF / Preference Optimisation (DPO)

Real LLM engineers:
- Train a Reward Model on human preference labels
- Run PPO against the reward model (RLHF — used by InstructGPT, Claude)
- Or use Direct Preference Optimisation (DPO — simpler, no reward model needed)
- DPO is now preferred: Llama-2 Chat, Zephyr, Qwen-Chat all use it

**How Niblit does it:**
- `SECA reward_model.py` scores every KB fact as it is stored
- High-scoring facts → "chosen" examples; low-scoring → "rejected"
- `LLMArchitectEngine.run_dpo()` uses these scores to build preference pairs
- When `trl` is installed: runs `trl.DPOTrainer` on the preference JSONL
- Without `trl`: reinforces high-quality facts through BrainTrainer

### Stage 4 — Evaluation

Real LLM engineers:
- Run `lm-eval-harness` on MMLU, HellaSwag, GSM8K, HumanEval
- Track perplexity on a held-out validation set
- Compare win-rate between new and old model checkpoints

**How Niblit does it:**
- `LLMArchitectEngine.run_eval()` runs QA pairs from `LLMTrainingAgent`
- Computes keyword-overlap hit-rate + SECA reward-model scores
- Stores results as `ale_llm_eval:<ts>` KB facts for tracking over time
- Writes `niblit_eval_log.jsonl` for external analysis

---

## Architecture: The Trading AI Engineer's Pipeline

The most successful live trading AI systems (Numerai, WorldQuant, Two Sigma,
DeepMind AlphaFold-style pattern recognition) follow a structured methodology:

### Layer 1 — Reinforcement Learning for Execution

Real trading AI engineers use:
- **PPO** (Proximal Policy Optimisation) for continuous action spaces
- **DQN** (Deep Q-Network) for discrete buy/sell/hold decisions
- **A3C** / **SAC** for sample-efficient live training
- Custom **Gym trading environments** that replay historical data

**Niblit's implementation:**
- `modules/rl_trading_policy.py` implements PPO, DQN, and Transformer RL
- `TradingBrain.decide_action()` uses the RL policy when `NIBLIT_RL_ENABLED=1`
- `TradingStudy.log_trade()` propagates ±1 rewards back to the policy

### Layer 2 — Transformer Market Models for Signals

Real quant shops use:
- **Temporal Fusion Transformer** (multi-horizon probabilistic forecasts)
- **PatchTST** (patch-based transformer for time series)
- **lag-llama** / **Chronos** (LLM-based time-series foundation models)

**Niblit's current state + upgrade path:**
- Currently: 7D state vector [close, volume, RSI, MACD, EMA, ATR, volatility]
- Next step: wire `pytorch-forecasting` TFT as a second-opinion signal
  (set `TRADING_TFT_ENABLED=1` after installing `pytorch-forecasting`)

### Layer 3 — Signal Engineering

Real quant engineers spend 70% of their time on features:
- Traditional: RSI, MACD, Bollinger Bands, ATR, VWAP
- Alternative: order flow imbalance, limit order book depth, news sentiment
- Cross-asset: correlation matrices, beta, sector momentum

**Niblit's current state:** 5 indicators computed in `compute_indicators()`
(RSI, MACD, EMA-20, ATR-14, volatility). Extend by adding features to
`TradingBrain.build_state_vector()`.

### Layer 4 — Risk Management & Portfolio Optimisation

Real trading AI engineers never go to market without:
- **Kelly Criterion** position sizing (or fractional Kelly for safety)
- **Max drawdown circuit breakers** (e.g. pause if portfolio drops 15%)
- **Sharpe ratio** tracking to compare strategies
- **Mean-variance optimisation** for multi-asset portfolios

**Niblit's upgrade path:**
Set `TRADING_KELLY_ENABLED=1` and install `PyPortfolioOpt` to activate
Kelly-based position sizing. Set `TRADING_MAX_DRAWDOWN_PCT=15.0` for the
circuit breaker.

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/riddo9906/Niblit.git
cd Niblit

# 2. Virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Core dependencies
pip install -r requirements.txt

# 4. Configure
cp .env.example .env
# → Edit .env and add your HF_TOKEN (minimum requirement)

# 5. Run
python main.py
```

To activate local LLM fine-tuning (ALE Step 32):
```bash
pip install trl peft bitsandbytes accelerate datasets transformers
# Then set LOCAL_MODEL_PATH=Qwen/Qwen2.5-0.5B-Instruct in .env
```

Pre-install local Qwen model files (recommended on Termux if runtime download crashes):
```bash
python tools/install_local_qwen_model.py
```

---

## What YOU Need To Do

This section explains everything you need to set up on your end to unlock
each capability. Work through these in order — each level builds on the last.

### Level 1 — Minimum (runs today, no extra accounts)

| Action | Where |
|--------|-------|
| Create a HuggingFace account | https://huggingface.co |
| Generate a **Read** access token | https://huggingface.co/settings/tokens |
| Set `HF_TOKEN=your_token` in `.env` | `.env` |
| Run `python main.py` | Terminal |

This gives you: AI chat, research, knowledge storage, vector memory, ALE
steps 1-31, self-healing, autonomous learning every cycle.

### Level 2 — Better Research (free)

| Action | Where |
|--------|-------|
| Create a GitHub account | https://github.com |
| Generate a **Fine-grained PAT** with `repo` + `issues` scope | https://github.com/settings/tokens |
| Set `GITHUB_TOKEN=your_token` in `.env` | `.env` |
| Enable Nibblebot workflows in GitHub Actions | Repository → Actions → Enable |

This unlocks: Nibblebot research bots (research, trading, LLM-engineer),
GitHub code search in ALE, autonomous GitHub push, civilisation agents.

### Level 3 — Vector Memory (free tier available)

| Action | Where |
|--------|-------|
| Create a Qdrant Cloud account | https://cloud.qdrant.io |
| Create a free cluster (1 GB) | Qdrant dashboard |
| Copy the **Cluster URL** and **API key** | Qdrant dashboard |
| Set `QDRANT_URL=` and `QDRANT_API_KEY=` in `.env` | `.env` |

This unlocks: persistent semantic search, RAG pipeline, long-term memory
across restarts, SECA multi-hop knowledge graph.

### Level 4 — Local LLM Fine-Tuning (requires ≥8 GB RAM / GPU optional)

| Action | Where |
|--------|-------|
| Install training dependencies | `pip install trl peft bitsandbytes accelerate datasets transformers` |
| Pick a base model (see suggestions below) | HuggingFace Hub |
| Set `LOCAL_MODEL_PATH=model-id` in `.env` | `.env` |
| Restart Niblit | Terminal |

**Recommended base models by hardware:**

| Hardware | Model | Size |
|----------|-------|------|
| CPU only / 4 GB RAM | `Qwen/Qwen2.5-0.5B-Instruct` | 0.5B |
| 8 GB RAM / no GPU | `microsoft/phi-2` | 2.7B |
| 8 GB VRAM GPU | `mistralai/Mistral-7B-Instruct-v0.3` | 7B |
| 24 GB VRAM GPU | `meta-llama/Meta-Llama-3-8B-Instruct` | 8B |

ALE Step 32 (LLMArchitectCycle) automatically runs LoRA fine-tuning every
10th autonomous cycle using Niblit's own KB as training data.

### Level 5 — Live Trading (paper trading first — free)

| Action | Where |
|--------|-------|
| Create a **paper trading** Alpaca account | https://alpaca.markets |
| Copy **API Key** and **Secret** | Alpaca dashboard |
| Set `ALPACA_API_KEY=` + `ALPACA_API_SECRET=` in `.env` | `.env` |
| Set `ALPACA_PAPER=true` in `.env` | `.env` |
| Set `NIBLIT_RL_ENABLED=1` in `.env` | `.env` |

**Only switch to live trading after:**
- Running paper trading for at least 30 days
- Verifying a positive Sharpe ratio ≥ 1.0
- Setting `TRADING_MAX_DRAWDOWN_PCT=15.0` as a circuit breaker

### Level 6 — Experiment Tracking (recommended for fine-tuning)

| Action | Where |
|--------|-------|
| Create a WandB account (free) | https://wandb.ai |
| Run `wandb login` in terminal | Terminal |
| Set `WANDB_API_KEY=your_key` in `.env` | `.env` |
| Set `WANDB_PROJECT=niblit-llm` in `.env` | `.env` |
| Install: `pip install wandb` | Terminal |

This tracks every LoRA fine-tune run with loss curves, eval scores, and
hyperparameter comparisons so you can see Niblit improving over time.

---

## APIs and Accounts Required

| Service | Free Tier | What It Unlocks | Sign Up |
|---------|-----------|-----------------|---------|
| **HuggingFace** | ✅ Yes | LLM inference (required) | https://huggingface.co |
| **GitHub** | ✅ Yes | Code search, Nibblebots, Git push | https://github.com |
| **Qdrant Cloud** | ✅ Yes (1 GB) | Vector memory, RAG, SECA | https://cloud.qdrant.io |
| **Alpaca** | ✅ Paper free | Paper/live trading | https://alpaca.markets |
| **WandB** | ✅ Yes | Training experiment tracking | https://wandb.ai |
| **Together AI** | ✅ $25 credit | Higher-quality LLM training data | https://api.together.xyz |
| **Groq** | ✅ 30 req/min | Fast inference for training pairs | https://console.groq.com |
| **Anthropic** | ❌ Paid | Claude as fallback LLM | https://console.anthropic.com |
| **Serpex** | ✅ Free tier | Web search in ALE | https://serpex.dev |
| **Binance** | ✅ Free | Crypto market data + trading | https://binance.com/en/register |
| **Twelve Data** | ✅ 800 req/day | Stocks, ETFs, forex, crypto | https://twelvedata.com |
| **OANDA** | ✅ Practice | Forex CFDs paper trading | https://www.oanda.com/forex-trading |

---

## Environment Variables Reference

See `.env.example` for the complete list. The most important variables:

### Minimum Required
```env
HF_TOKEN=hf_xxxxxxxxxxxx          # HuggingFace API token (inference)
```

### Recommended for Full Functionality
```env
GITHUB_TOKEN=ghp_xxxxxxxxxxxx     # GitHub PAT (code search + Nibblebots)
QDRANT_URL=https://xxx.qdrant.io  # Qdrant Cloud cluster URL
QDRANT_API_KEY=xxxxxxxxxxxx       # Qdrant API key
ANTHROPIC_API_KEY=sk-ant-xxx      # Claude fallback LLM
SERPEX_API_KEY=xxx                # Web search in ALE
```

### For Local Fine-Tuning (ALE Step 32)
```env
LOCAL_MODEL_PATH=Qwen/Qwen2.5-0.5B-Instruct
LORA_R=8
LORA_ALPHA=16
SFT_EPOCHS=1
SFT_BATCH_SIZE=2
WANDB_API_KEY=xxx
```

### For Trading AI
```env
NIBLIT_RL_ENABLED=1
BINANCE_API_KEY=xxx
BINANCE_API_SECRET=xxx
ALPACA_API_KEY=xxx
ALPACA_API_SECRET=xxx
ALPACA_PAPER=true
TRADING_KELLY_ENABLED=0           # Set to 1 after testing
TRADING_MAX_DRAWDOWN_PCT=15.0
```

---

## Autonomous Learning Engine (ALE) — 32-Step Cycle

The ALE runs continuously in the background, executing 32 steps per cycle:

| Step | Name | What It Does |
|------|------|--------------|
| 1 | UnifiedResearch | All backends, one topic, 60s ingest wait |
| 2 | Ideas | SelfIdeaImplementation generates upgrade ideas |
| 3 | Learning | SelfTeacher internalises research results |
| 4 | Implementation | SelfImplementer executes enqueued plans |
| 5 | Reflection | ReflectModule summarises + stores to KB |
| 6 | SLSA | SLSA knowledge artifact generation |
| 7 | Evolve | EvolveEngine self-evolves Niblit's code |
| 8 | CodeResearch | Searchcode + GitHub + researcher |
| 9 | CodeGeneration | Generate compilable code from research |
| 10 | CodeCompilation | Compile and execute generated code |
| 11 | CodeReflection | Study compiled output (30s wait) |
| 12 | SoftwareStudy | Analyse code patterns via internet |
| 13 | CommandAwareness | Catalogue all commands into KB |
| 14 | CommandExecution | Exercise safe diagnostic commands |
| 15 | TopicSeeding | Derive + enqueue new research topics |
| 16 | Reasoning | Build knowledge graph, chain, infer |
| 17 | Metacognition | Evaluate self-knowledge, find gaps |
| 18 | ImprovementCycle | 10-module improvement (every 3 cycles) |
| 19 | SelfScan | Read own source files into KB |
| 20 | GitHubPush | Push generated files (every 5 cycles) |
| 21 | BinaryStudy | Seed KB with firmware/kernel topics |
| 22 | BuildsUpdate | Index builds/ directory |
| 23 | EvolveDeploy | Hot-reload evolved improvements |
| 24 | BrainTraining | Fine-tune brain on research data |
| 25 | CognitiveEnhancement | Research language/reasoning quality |
| 26 | GitHubCodeDiscovery | Pattern discovery + refactoring hints |
| 27 | SearchcodeDiscovery | Searchcode.com code-pattern index |
| 28 | ScrapyResearch | DuckDuckGo direct scraping |
| 29 | BuildsIntegration | Run builds scripts + NLP enrichment |
| 30 | SelfImproveAgents | Dispatch to Phase-2 agent architecture |
| 31 | SelfMaintenance | SelfHealer + memory pruning (every 5) |
| **32** | **LLMArchitectCycle** | **Curate → SFT → DPO → Eval (every 10)** |

---

## Nibblebot Research Bots

Nibblebot bots run on a schedule via GitHub Actions and write research
findings as GitHub Issues.  They feed directly into Niblit's KB via
`SelfImprovementOrchestrator.ingest_research_findings()`.

| Bot | Schedule | Studies |
|-----|----------|---------|
| `research_bot.py` | Friday 09:00 UTC | LLM frameworks, RAG, agent architectures, LLM pre-training/SFT/DPO/eval |
| `ai_trading_bot.py` | Saturday 08:00 UTC | RL trading, TFT market models, signal engineering, risk management |
| `improvement_bot.py` | Monday 07:00 UTC | General software improvement patterns |
| `llm_engineer_bot.py` | **Thursday 10:00 UTC** | **LLM build pipeline, training infra, fine-tuning, evaluation** (NEW) |
| `aios_research_bot.py` | Wednesday 08:00 UTC | AI-OS and agentic workflow patterns |
| `aios_architecture_bot.py` | Tuesday 09:00 UTC | AIOS architecture patterns |

### Enabling Nibblebots

1. Fork or clone this repository to your own GitHub account.
2. Go to **Settings → Actions → General** and enable workflows.
3. Add your `GITHUB_TOKEN` to **Settings → Secrets → Actions** (it's
   automatically available as `secrets.GITHUB_TOKEN` in workflows).
4. Trigger a manual run: **Actions → [Bot Name] → Run workflow**.

---

## Fine-Tuning Your Own Local Model

Once `LOCAL_MODEL_PATH` is set, ALE Step 32 runs automatically every 10
cycles. You can also trigger it manually:

```python
# From the Niblit CLI
niblit llm-architect run

# Check status
niblit llm-architect status

# Review the eval log
niblit llm-architect eval
```

### The Training Loop (What Happens Automatically)

```
Cycle 10:  LLMArchitectCycle runs
  ├── Curation: extract 200 (prompt, completion) pairs from KB
  ├── SFT: LoRA fine-tune on curated pairs (if LOCAL_MODEL_PATH set)
  ├── DPO: preference-optimise using SECA reward_model scores
  └── Eval: measure hit-rate + reward-score on 20 held-out QA pairs

Cycle 20:  LLMArchitectCycle runs again (with more KB data)
  └── ... improving with each cycle
```

### How to Monitor Fine-Tuning Progress

```bash
# Watch training loss in WandB
wandb login
# Open https://wandb.ai/your-org/niblit-llm after the first run

# Check the eval log directly
tail -f niblit_eval_log.jsonl | python -c "import sys,json; [print(json.loads(l)) for l in sys.stdin]"

# Query the KB for eval history
niblit recall ale_llm_eval
```

---

## Live Trading Configuration

### Start with Paper Trading (always)

```bash
# 1. Sign up for Alpaca paper trading
#    https://alpaca.markets → create free account → Paper Trading

# 2. Configure in .env
ALPACA_API_KEY=your_paper_key
ALPACA_API_SECRET=your_paper_secret
ALPACA_PAPER=true
NIBLIT_RL_ENABLED=1
TRADING_SYMBOL=AAPL          # or BTC/USD
TRADING_INTERVAL=1m
TRADING_CYCLE_SECS=60

# 3. Run
python main.py
```

### Evaluate Before Going Live

Run paper trading for at least 30 days. Then check:

```python
# Query trading performance from KB
niblit recall trading_performance
niblit recall ale_rl_policy

# Check Sharpe ratio (requires quantstats)
pip install quantstats
# metrics are logged to KB as trade_log:<ts> facts
```

Only switch `ALPACA_PAPER=false` after you see a Sharpe ratio ≥ 1.0 over
30+ days of paper trading.

### Adding Crypto (Binance)

```bash
# In .env:
BINANCE_API_KEY=your_key
BINANCE_API_SECRET=your_secret
TRADING_SYMBOL=BTCUSDT
CCXT_EXCHANGE=binance
```

---

## 🆕 Niblit Cyber Membrane

**File:** `modules/niblit_cyber_membrane.py`

The Cyber Membrane is a **multi-layer, real-time security architecture** that
wraps every input and output flowing through Niblit.  It operates as a
transparent defensive shell — all 8 layers run on every request with no
configuration required.

```
Input → [InputGuard] → [StealthDetector] → [SessionWarden]
      → [TrackerSensor] → [IntegrityMonitor] → [AdaptiveFirewall]
      → [OutputGuard] → Response
```

### The 7 Membrane Layers

| Layer | Class | What It Does |
|-------|-------|--------------|
| 1 | `InputGuard` | Deep injection scanning: SQLi, SSTI, LDAP, path-traversal, shell, prompt-injection. Homoglyph normalisation. Dynamic rule injection at runtime. |
| 2 | `OutputGuard` | Scrubs outbound text: OpenAI/Anthropic/HF keys, AWS creds, GitHub PATs, PEM certificates, Termux paths, password/token literals. |
| 3 | `TrackerSensor` | Scans environment for suspicious processes, network listeners, and environment variable leakage. |
| 4 | `StealthDetector` | Detects low-and-slow scans, behavioural drift, slow-brute patterns, and timing-oracle attacks. |
| 5 | `AdaptiveFirewall` | Self-tuning threat model with per-client block/escalation logic. Learns from every event. |
| 6 | `SessionWarden` | Per-session entropy + command-divergence tracking. Flags session-hijacking and bot scripting. |
| 7 | `IntegrityMonitor` | SHA-256 baseline of all `.py` modules. Flags tampered files on every 5-minute check. |

### CLI Commands

```
cyber status          — live stats: active blocks, threat frequency, session health
cyber scan <text>     — test a payload against the membrane
cyber threats         — show recent high-severity threat log
cyber integrity       — show file integrity check results
```

### Environment Variables

| Variable | Default | Effect |
|----------|---------|--------|
| `NIBLIT_BLOCK_SECS` | `300` | Initial block duration (seconds) |
| `NIBLIT_THREAT_MEMORY` | `500` | Max threat events stored |
| `NIBLIT_SLOW_WINDOW` | `600` | Slow-scan detection window (seconds) |
| `NIBLIT_SLOW_MIN_REQ` | `20` | Min requests to flag slow-brute |
| `NIBLIT_SESSION_DIVERGE` | `0.75` | Session-divergence threshold |

---

## 🆕 Defensive Evolution Loop

**File:** `modules/niblit_defensive_evolution_loop.py`

The Defensive Evolution Loop transforms Niblit from a **reactive** security
system into a **preemptively evolving** one.  It sits above the Cyber Membrane
as a purely optional, additive layer — nothing in the existing membrane is
changed.

```
Detect (existing membrane)
  ↓
AttackGenome capture — structured metadata from every severity≥0.75 threat
  ↓
SandboxReplayer — fresh isolated membrane, production never touched
  ↓
AttackMutationEngine — 4 strategies: obfuscate_syntax, time_shift,
                        layer_bypass, combine_vectors
  ↓
Self-attack loop — stress-test sandbox with all mutated variants
  ↓  (bypass found)
InputGuard.add_pattern() + AdaptiveFirewall.learn() + KnowledgeDB log
  ↓
Loop back after 60 s (background daemon thread)
```

This upgrades Niblit's security posture from:

> **Before:** Detect → Block → Log

to:

> **After:** Detect → Block → Learn → Simulate → Self-Attack → Evolve → Reinforce

### AttackGenome

Every detected threat is captured as a structured genome object:

```python
AttackGenome = {
    "type": "sqli | prompt_injection | shell | ssti | path_traversal | …",
    "entry_vector": "...",          # reconstructed attack payload
    "payload_signature": "...",     # SHA-256 fingerprint (16 hex chars)
    "timing_pattern": "normal | slow | burst | timing_oracle",
    "target_layer": "InputGuard | StealthDetector | …",
    "success_probability": float,   # 0 = caught, 1 = likely bypass
    "detected_by": ["InputGuard"],
    "severity_score": float,
    "generation": int,              # mutation depth (0 = real capture)
}
```

### Mutation Strategies

| Strategy | What It Does |
|----------|-------------|
| `obfuscate_syntax` | Type-specific encoding tricks: SQL comment injection, Unicode homoglyphs for prompt attacks, shell quoting bypasses, percent-encoded traversals |
| `time_shift` | Rotates timing metadata: normal → slow → burst → timing_oracle |
| `layer_bypass` | Re-routes payload to target a different detection layer |
| `combine_vectors` | Merges two genomes into a multi-vector hybrid attack |

### Safety Governor

| Constant | Default | Env Variable |
|----------|---------|--------------|
| `MAX_MUTATION_DEPTH` | `5` | `NIBLIT_MAX_MUTATION_DEPTH` |
| `MAX_SANDBOX_ITERATIONS` | `20` | `NIBLIT_MAX_SANDBOX_ITER` |
| `MAX_CPU_EVO_LOAD` | `0.65` | `NIBLIT_MAX_CPU_EVO_LOAD` |
| `CYCLE_INTERVAL_SECS` | `60` | `NIBLIT_EVO_CYCLE_INTERVAL` |

Evolution is automatically paused when the 1-minute CPU load average exceeds
`MAX_CPU_EVO_LOAD` — safe to run continuously on Termux/Pydroid.

### CLI Commands

```
evolution status      — cycles, bypasses found, queue depth, CPU load
evolution bypasses    — last 20 bypass discoveries with genome lineage
evolution cycle       — trigger one full evolution cycle immediately
evolution start       — (re)start the background daemon thread
evolution stop        — gracefully stop the background thread
```

---

## 🆕 Cognitive Kernel v3

**File:** `modules/niblit_kernel_v3.py`

Niblit Cognitive Kernel v3 is the **unified reasoning bus** that fuses all
previous kernel versions (v1, v2) with a structured communication bus and
a reward-shaped learning loop.

### Components

| Component | Role |
|-----------|------|
| `KernelCommunicationBus` | Pub/sub message routing between agents |
| `RewardEngine` | Scores every kernel output; reinforces high-quality reasoning |
| `KernelScheduler` | Priority-aware task queue with per-agent load-balancing |
| **5 Stateless Agents** | Research · Coder · Critic · Teacher · Explorer |

### 7-Step Processing Pipeline

```
1. Receive input message
2. Route to relevant agents via KCB
3. Parallel agent processing (Research + Coder + Critic + …)
4. Critic synthesis: select best agent response
5. RewardEngine scoring
6. Memory storage (STM → WorkingMemory → MemoryGraph)
7. Emit kernel output
```

Wired into `niblit_brain.think()` as a pre-think step every conversation cycle.
Singleton via `get_niblit_kernel_v3()`.

---

## 🆕 Sync Engine (LCSP v1)

**File:** `modules/sync_engine.py`

The Sync Engine implements the **Local ↔ Cloud Sync Protocol (LCSP v1)**,
enabling Niblit to run across multiple devices (phone + desktop + server)
and keep all knowledge, training data, and evolution state in sync.

### Architecture

```
SyncQueue (JSONL on disk)
    ↓
ChangeDetector (SHA-256 per artifact)
    ↓
ConflictResolver (timestamp → weight → merge)
    ↓
RESTTransport (urllib — no extra dependencies)
    ↓
Remote endpoint / second Niblit instance
```

### Synced Artifact Types

All major Niblit subsystems emit sync artifacts:

| Source | Artifact Key |
|--------|-------------|
| ALE phased research | `ale_research` |
| ALE cognition cycle | `ale_cognition_cycle` |
| GoalEngine.generate_goals | `goal_engine_cycle` |
| TradingBrain decisions | `trading_decision` |
| ChatCompletions turns | `chat_turn` |
| GraphRAG facts (tier 1) | `graph_rag_tier1` |
| GraphRAG stats (tier 2) | `graph_rag_tier2` |

### Environment Variables

```env
NIBLIT_SYNC_MODE=push            # push | pull | bidirectional
NIBLIT_SYNC_INTERVAL=30          # seconds between sync cycles
NIBLIT_SYNC_ENDPOINT=https://…   # remote Niblit instance URL
NIBLIT_SYNC_API_TOKEN=…          # bearer token for remote auth
NIBLIT_SYNC_QUEUE_PATH=…         # JSONL queue file path
NIBLIT_DEVICE_ID=my-phone        # unique identifier for this node
```

---

## 🆕 Memory Weighting & Decay System (MWDS v2)

**File:** `modules/memory_weighting.py`

MWDS v2 replaces simple KB storage with a **biologically-inspired adaptive
memory lifecycle** where facts decay, get reinforced, tier-promoted, and
eventually pruned — just like human long-term memory.

### Memory Tiers

| Tier | Condition | Storage |
|------|-----------|---------|
| `hot` | weight ≥ 0.8 | In-memory working set |
| `warm` | 0.5 ≤ weight < 0.8 | Normal KB access |
| `cold` | 0.2 ≤ weight < 0.5 | Compressed (zlib), slower access |
| `dead` | weight < 0.2 | Pruned on next maintenance cycle |

### Weight Formula

```
weight = decay × usage × success_ratio × recency_boost × graph_factor
```

- **decay**: exponential time-based decay (configurable half-life)
- **usage**: how often a fact has been retrieved
- **success_ratio**: how often it contributed to correct answers
- **recency_boost**: temporary +boost on recent access
- **graph_factor**: MemoryGraph connectivity score

`KernelMemory.store/retrieve/decay/reinforce` all delegate to `MemoryStore`.
Singleton via `get_memory_store()`.

---

## 🆕 Cognition Core

**File:** `modules/cognition_core.py`

`CognitionCore` is the architectural glue that unifies three previously
separate systems — `ReasoningEngine`, `GoalEngine`, and `MemoryGraph` — into
a single, coherent cognition loop.

### Pipeline

```
think(topic)
  → Chain-of-Thought reasoning (ReasoningEngine)
  → Belief synthesis (contradictions + confidence)
  → MemoryGraph expansion (associated concepts)
  → Response generation

cycle() → ALE integration
  → run_maintenance() → decay + prune + compress_cold
  → feed fresh beliefs into cross-cycle context
```

`MemoryGraph` upgrades included: `apply_decay()`, `reinforce()`,
`prune_low_score()`, `stats()`.  Singleton via `get_cognition_core()`.

---

## 🆕 Goal Engine

**File:** `modules/goal_engine.py`

The Goal Engine gives Niblit **goal-directed cognition** — instead of random
topic selection, every ALE cycle begins with a prioritised list of goals
derived from analysing Niblit's own knowledge gaps.

### Goal Sources

| Source | What It Detects |
|--------|----------------|
| Metacognition gaps | Topics where self-confidence is below threshold |
| Reasoning contradictions | Mutually exclusive KB facts |
| Low-confidence KB facts | Facts with reward-model score < 0.4 |
| Sparse domain coverage | Knowledge domains with < 5 facts |
| Capability gaps | Commands the router can handle but has never exercised |

Generated `Goal` objects are fed into
`ALE._cross_cycle_context["goal_objectives"]` so every research step pursues
what Niblit most needs to learn.  Singleton via `get_goal_engine()`.

---

## 🆕 Position Sizer (Kelly Criterion)

**File:** `modules/position_sizer.py`

The `PositionSizer` adds professional-grade risk management to Niblit's
trading AI using the **Kelly Criterion** with a max-drawdown circuit breaker.

### Features

- **Kelly Criterion** — mathematically optimal bet size given win-rate and odds
- **Fractional Kelly** — configurable fraction (default 0.5×) for safety
- **Max-drawdown circuit breaker** — pauses trading when portfolio drawdown
  exceeds threshold

### Configuration

```env
NIBLIT_KELLY_FRACTION=0.5         # Fractional Kelly multiplier (0.0–1.0)
NIBLIT_MAX_POSITION_FRAC=0.25     # Max single-position size (% of portfolio)
NIBLIT_MAX_DRAWDOWN_PCT=15.0      # Circuit breaker: pause at 15% drawdown
```

Wired into `TradingBrain` via the `position_sizer` parameter.
Singleton via `get_position_sizer()`.

---

## 🆕 Domain Tokenizer Trainer

**File:** `modules/tokenizer_trainer.py`

The `TokenizerTrainer` trains a **domain-specific BPE tokenizer** on Niblit's
own Knowledge Base corpus — dramatically improving token efficiency for
AI, trading, and code-focused text compared to general-purpose tokenizers.

### How It Works

```
KB corpus extraction
    ↓
SentencePiece BPE training (preferred)
    ↓   (or word-frequency JSON fallback when SentencePiece unavailable)
Domain vocabulary saved to NIBLIT_TOKENIZER_DIR
    ↓
Used by LLMArchitectEngine for all tokenisation
```

### Configuration

```env
NIBLIT_TOKENIZER_DIR=./tokenizer       # Where to save the trained vocab
NIBLIT_TOKENIZER_VOCAB_SIZE=8000       # BPE vocabulary size
NIBLIT_TOKENIZER_MODEL_TYPE=bpe        # bpe | unigram | char | word
```

Singleton via `get_tokenizer_trainer()`.

---

## 🆕 Phased Research Engine

**File:** `modules/phased_research_engine.py`

The `PhasedResearchEngine` replaces Niblit's single-shot research calls with a
**3-phase structured pipeline** that progressively deepens understanding of any
topic.

### 3-Phase Pipeline

| Phase | Timeout | What It Does |
|-------|---------|--------------|
| **Phase 1** | 300 s | Broad discovery: DuckDuckGo + Wikipedia surface scan. Extracts key entities, definitions, and sub-topics. |
| **Phase 2** | 300 s | Deep dive: GitHub code search + SerpAPI. Extracts implementation patterns, code examples, and technical facts. |
| **Phase 3** | 300 s | Synthesis: cross-reference facts, detect contradictions, build SLSA-compatible structured artifact. |

Used by: `SLSAGenerator`, `ALE Step 1 (UnifiedResearch)`, `Cognitive Kernel v3`.

---

## 🆕 Cognitive Graph Kernel v1.0

**File:** `modules/niblit_cognitive_graph_kernel.py`

The Cognitive Graph Kernel v1.0 is a **unified runtime substrate** that
collapses Niblit's four previously separate subsystems — Cyber Membrane, Graph
Knowledge, Memory, and Defensive Evolution — into a single event-driven graph
operating system.

### Architecture

```
┌──────────────────────────────────────────────────────────┐
│                  CognitiveGraphKernel                    │
│              (Graph Event Runtime v1.0)                  │
└────────────────────────┬─────────────────────────────────┘
                         │
     ┌───────────────────┼───────────────────┐
     │                   │                   │
Memory Graph        Membrane Graph      Evolution Graph
(knowledge state)   (security state)    (self-mod system)
     │                   │                   │
     └──────────┬────────┴──────────┬────────┘
                │                   │
     EventBus (Causal DAG Runtime)
                │
    Everything = Event + Node + Edge
```

### Core Design Principle

> **Everything is an event.**

Instead of calling functions directly, running background polling threads, or
procedural mutation loops, every interaction becomes a typed event:

```
Event(type, payload, source, timestamp, energy, priority)
```

All mutations are graph rewriting operations, triggered exclusively by event
propagation — zero direct cross-module calls at runtime.

### Five Components

| Component | Class | Role |
|-----------|-------|------|
| **EventBus** | `EventBus` | Priority min-heap queue + typed subscriptions. Dispatches up to 200 events per `tick()`. Drops lowest-priority events when queue is full. |
| **CognitiveGraph** | `CognitiveGraph` | In-process knowledge graph: typed nodes + weighted directed edges. Integrates with `KnowledgeDB` to persist high-weight nodes. Auto-prunes oldest nodes when limit exceeded. |
| **MemoryLayer** | `MemoryLayer` | Unified weighted, decaying key-value store. Delegates hot/warm storage to MWDS v2 `MemoryStore` when available. Applies exponential decay on every 100th tick. |
| **MembraneGraph** | `MembraneGraph` | Event-filtering security layer. Dynamic rule injection at runtime: patterns are injected on every bypass discovery. Bridges to `CyberMembrane` `InputGuard` + `AdaptiveFirewall`. |
| **EvolutionGraphRuntime** | `EvolutionGraphRuntime` | Converts `DefensiveEvolutionLoop`'s procedural mutation engine into event-driven graph rewriting. Bridges to real DEL bypass discoveries. |

### How DefensiveEvolutionLoop becomes Event Graph

**Before (procedural):**
```
thread → drain queue → replay sandbox → mutate → inject firewall rules
```

**After (event-driven):**
```
Event: security.threat
        ↓ (MembraneGraph blocks)
Event: evolve.attack
        ↓ (EvolutionGraphRuntime.handle_evolve_event)
Event: graph.update  →  new mutation_node in CognitiveGraph
        ↓
MembraneGraph.reinforce()  →  CyberMembrane.InputGuard.add_pattern()
        ↓
Event: security.pattern_learned  (observability)
```

### Deterministic Tick Cycle

```python
kernel.tick()
  1. bus.dispatch(limit=200)    # process queued events in priority order
  2. memory.decay()             # every 100 ticks
  3. system.prune event emitted # reclaim dead memory entries
```

No background polling threads required — the kernel can be driven
synchronously, or started with `kernel.start()` for an auto-background tick.

### Event Types

| Event Type | Source | Handler |
|------------|--------|---------|
| `memory.write` | Any module | Write key/value into MemoryLayer |
| `memory.read` | Any module | Read with optional callback |
| `graph.update` | Evolution / API | Add/update a Node in CognitiveGraph |
| `graph.edge` | API | Add a directed edge between nodes |
| `security.threat` | API / Membrane | Filter → emit `evolve.attack` if blocked |
| `evolve.attack` | MembraneGraph / Evolution | Mutate → graph node + pattern reinforce |
| `evolve.result` | Evolution | Observability for bypass discoveries |
| `security.pattern_learned` | Evolution | Notifies that a new pattern was injected |
| `system.tick` | Kernel | Observability marker every N ticks |
| `system.prune` | Kernel | Triggers memory decay and graph pruning |

### CLI Commands

```
cgk status               — full kernel status: event bus, graph, memory, membrane, evolution
cgk graph                — knowledge graph stats (nodes, edges, types, mutations)
cgk events               — event bus stats (queue depth, dispatched, dropped)
cgk memory               — memory layer stats
cgk membrane             — security membrane stats + last 20 threat events
cgk evolution            — evolution runtime stats (cycles, mutations, DEL bridge)
cgk tick [N]             — run N deterministic tick cycles (default 1)
cgk start                — start background tick + evolution loops
cgk stop                 — stop background loops
```

### Environment Variables

| Variable | Default | Effect |
|----------|---------|--------|
| `NIBLIT_CGK_TICK_INTERVAL` | `0.5` | Seconds between background ticks (set 0 to disable) |
| `NIBLIT_CGK_DECAY_FACTOR` | `0.995` | Memory weight decay factor per tick cycle |
| `NIBLIT_CGK_MAX_QUEUE` | `2000` | Max events in priority queue before dropping |
| `NIBLIT_CGK_EVO_INTERVAL` | `10` | Seconds between evolution sweep cycles |
| `NIBLIT_CGK_MAX_GRAPH_NODES` | `5000` | Prune oldest nodes when exceeded |

### Unified System Representation

| System | Representation in CGK |
|--------|----------------------|
| Memory | Weighted + decaying graph nodes |
| Knowledge | Graph traversal + edge weights |
| Reasoning | Event propagation through node types |
| Security | Filtering function on event stream |
| Evolution | Self-rewriting graph mutations |
| All interactions | Events through EventBus (zero direct calls) |

Singleton via `get_cognitive_graph_kernel()`. Wired into `niblit_core._init_optional_services`
as `self.cognitive_graph_kernel`; auto-started on init with `CyberMembrane` bridge.

---

## 🆕 Autonomous Evolution Engine (Phases 2–9.5)

Niblit continuously improves its own Python codebase through a multi-phase
**Autonomous Evolution Engine** that runs on a scheduled GitHub Actions
workflow (`niblit-autonomous-evolution.yml`).  Each phase added a new layer
of intelligence on top of the previous one.

---

### Phase 2 — Batch Fix Agent

**File:** `nibblebots/autonomous_evolution_agent.py`

- Scans all Python files for code quality issues
- Batches up to `MAX_FIXES` (default 5) files of the same fix type per run
- Fix catalogue: `bare_except`, `bare_except_pass`, `trailing_whitespace`,
  `double_blank_lines`, `eof_newline`
- Enriched commit messages include Category / Reason / Impact
- Uses GitHub API log scan (`get_log_priority_files()`) to prioritise files
  that appeared in recent CI failures
- Temp files `/tmp/niblit_{commit_msg,changed_files}.txt` bridge
  agent ↔ workflow

---

### Phase 3 — Semantic Impact Engine

**Files:** `nibblebots/semantic_engine.py`, `nibblebots/impact_engine.py`,
`nibblebots/evolution_planner.py`, `nibblebots/feedback_learner.py`

- `SemanticEngine.classify()` maps each issue to a `SemanticIssue`
  (subsystem / severity / confidence)
- `ImpactEngine.score()` assigns expected_gain / risk / net_score using
  learnable weights stored in `impact_weights.json`
- `EvolutionPlanner.build_plan()` gates fixes: confidence ≥ 0.60,
  net_score ≥ 0.05; protects `decision_engine`, `meta_engine`, trading
- `FeedbackLearner.record_outcome()` records CI outcomes to
  `outcome_journal.jsonl` and calls `impact_engine.update_weights()`

---

### Phase 4–6 — Observation, Rollback & Domain Awareness

**New files:**
`nibblebots/observation_collector.py`,
`nibblebots/rollback_guard.py`,
`nibblebots/domain_registry.py`,
`nibblebots/dependency_analyzer.py`,
`nibblebots/system_health_monitor.py`,
`nibblebots/learning_loop_bridge.py`

| Component | What it does |
|-----------|-------------|
| `ObservationCollector` | Unified sensing layer across CI, health, and code |
| `RollbackGuard` | Auto-reverts commits when ≥ 2 consecutive regressions; writes `/tmp/niblit_revert_cmd.txt` |
| `ImpactEngine` (regression) | Fits a Pearson regression model from the outcome journal (`fit_regression_from_journal`, min 20 samples) |
| `DomainRegistry` | Classifies files into `code / workflow_config / dependency_pins`; caps cross-domain fixes at 8 |
| `DependencyAnalyzer` | Builds AST import graph; flags high fan-out files (≥ 10 imports) for extra risk |
| `SystemHealthMonitor` | Captures `SystemHealthSnapshot` + delta every cycle |
| `LearningLoopBridge` | Publishes `EVENT_EVOLUTION_OUTCOME` on EventBus → MetaEngine |

Also added: `semantic_engine` log-derived classification
(`classify_log_lines` / `classify_log_file`).

---

### Phase 7 — Strategic Planning & Anomaly Detection

**New files:**
`nibblebots/anomaly_detector.py`,
`nibblebots/confidence_decay.py`,
`nibblebots/delayed_outcome_tracker.py`,
`nibblebots/strategic_planner.py`

| Component | What it does |
|-----------|-------------|
| `AnomalyDetector` | EWMA + IQR control chart; detects pattern drift; exposes `is_system_safe()` |
| `ConfidenceDecay` | Exponential half-life decay on `impact_weights` (half-life = 14 days); `mark_validated` / `apply_decay` / `get_staleness_report` |
| `DelayedOutcomeTracker` | Tracks outcomes at H1 / H5 / H20 horizon checkpoints; `get_corrected_entries` feeds delayed regression |
| `StrategicPlanner` | Do-nothing gate (`MIN_GAIN = 0.03`), ε-greedy exploration (`EXPLORATION_RATE = 0.20`), goal derivation: `maximize_stability / minimize_regression / improve_learning` |

`EvolutionPlanner.build_plan()` now accepts a `strategic_decision` parameter;
`FeedbackLearner` calls all four components on every `record_outcome()`.

---

### Phase 8 — Real-World Value & Causal Tracking

**New files:**
`nibblebots/objective_engine.py`,
`nibblebots/reality_bridge.py`,
`nibblebots/value_engine.py`,
`nibblebots/causality_tracker.py`,
`nibblebots/goal_adaptation_engine.py`

| Component | What it does |
|-----------|-------------|
| `ObjectiveEngine` | Top-authority goal layer (`ObjectiveProfile`); `score_outcome / score_delta / update_goal`; persists to `objective_state.json` |
| `RealityBridge` | Aggregates CI journal + trade KB + health log into a snapshot; `pull_snapshot / get_cached_snapshot / inject_snapshot` |
| `ValueEngine` | `ValueAssessment` (delta / confidence / passes_gate); confidence-weighted evaluation; hard gate `MIN_REAL_WORLD_GAIN = 0.02`; history in `value_history.jsonl` |
| `CausalityTracker` | Pearson r + mean_value_delta + consistency per fix_type; `record / get_correlations / get_fix_type_trust`; `CAUSALITY_WINDOW = 30` |
| `GoalAdaptationEngine` | Hysteresis-gated goal switching (stability ↔ profitability ↔ learning); `evaluate / force_goal`; log in `goal_adaptation_log.jsonl` |

Upgraded wiring: `StrategicPlanner.decide()` gains `reality_snapshot` param +
objective_engine gate; `EvolutionPlanner.build_plan()` gains `value_engine` gate;
`FeedbackLearner` calls `_evaluate_real_world_value()` every cycle.

---

### Phase 8.5 — Signal Integrity & Intent Anchoring

**New files:**
`nibblebots/signal_integrity_engine.py`,
`nibblebots/intent_anchor_engine.py`

| Component | What it does |
|-----------|-------------|
| `SignalIntegrityEngine` | Assesses CI / trading / runtime / snapshot reliability; returns `SignalConfidence`; gates on `SIE_MIN_CONFIDENCE_GATE = 0.50` |
| `IntentAnchorEngine` | Persistent intent anchor with drift detection; `set_anchor / score_alignment / update / check_drift / status`; `INTENT_DRIFT_THRESHOLD = 0.40`, penalty `0.25`; state in `intent_anchor_state.json` |

Upgraded wiring: `RealityBridge.pull_snapshot()` merges `SignalConfidence`
fields; `ValueEngine.evaluate()` uses confidence-weighted delta with hard gate;
`CausalityTracker.record()` gains `signal_confidence` parameter;
`GoalAdaptationEngine` forces `stability` when `avg_confidence < 0.5`;
`EvolutionPlanner` halves the plan on intent drift.

---

### Phase 9 — Temporal Consistency (Stability Controller)

**New file:** `nibblebots/stability_controller.py`

Adds controlled temporal consistency to prevent the system thrashing between
modes faster than it can learn from either.

| Mechanism | What it does |
|-----------|-------------|
| **Mode locking** | Once a mode is entered, it cannot be exited until `MODE_MIN_DURATION = 5` cycles have elapsed |
| **Asymmetric hysteresis** | Enter stability: confidence < 0.45; Exit stability: confidence > 0.65 — creates a dead zone that prevents flip-flopping |
| **Safety override** | Low-confidence always forces stability regardless of mode lock |
| **Switch penalty** | Recent switches accumulate a penalty; suppresses further switches when penalty ≥ 0.15 with negative momentum |

Upgraded wiring: `StrategicPlanner.decide()` calls
`stability_controller.resolve_mode()`; `GoalAdaptationEngine` tracks
`last_goal + cycles_in_goal`; `FeedbackLearner._evaluate_real_world_value()`
calls `stability_controller.record_cycle()`.  Added `EVENT_MODE_LOCKED` on
EventBus.

---

### Phase 9.5 — Context-Aware Mode Memory (Situational Intelligence)

**File:** `nibblebots/stability_controller.py` (extended)

Solves the **"context-blind stability bias"** failure mode: without this
upgrade, stability mode that performs well during noisy CI biases the system
toward stability even when conditions improve, causing under-exploration.

#### Three new capabilities

**1. Contextual cycle recording**

Every `record_cycle()` call now stores conditions alongside the outcome:

```python
{
    "mode": mode,
    "outcome": outcome_score,
    "confidence": avg_confidence,
    "intent_alignment": intent_score,
    "signal_reliability": signal_confidence,
}
```

**2. Mode effectiveness scoring per condition** (`get_mode_score`)

```python
# Returns avg outcome for this mode only among records with similar conditions
score = stability_controller.get_mode_score("explore", confidence=0.8, signal_conf=0.75)
```

Looks up the last `CONTEXT_MEMORY_MAX = 200` records, filters to those where
both `confidence` and `signal_reliability` are within `CONTEXT_SIMILARITY_BAND = 0.1`,
and returns the mean outcome.  Returns `0.0` when no similar history exists.

**3. Contextual exploration bias in `resolve_mode()`**

```python
exploration_score = get_mode_score("explore", confidence, signal_conf)
stability_score   = get_mode_score("stability", confidence, signal_conf)

if exploration_score > stability_score + EXPLORATION_BIAS_THRESHOLD:  # default 0.05
    favour_exploration = True  # override the stability gate
```

This changes the system from:
> *"Stability worked recently → keep using it"*

to:
> *"Stability works under these conditions, not always"*

**4. Switch penalty cap** (`SWITCH_PENALTY_MAX = 0.25`)

The penalty is now hard-capped at 0.25 (was 0.50), preventing permanent
"stuck mode" where the system can never switch regardless of conditions.

#### New constants (overridable via env vars)

| Variable | Default | Effect |
|----------|---------|--------|
| `SC_SWITCH_PENALTY_MAX` | `0.25` | Hard cap on switch penalty |
| `SC_CTX_MEMORY_MAX` | `200` | Max contextual cycle records |
| `SC_CTX_BAND` | `0.1` | Similarity tolerance for condition matching |
| `SC_EXPLORE_BIAS` | `0.05` | Margin exploration must beat stability to trigger bias |

#### Evolution of intelligence layers

| Layer | Capability |
|-------|-----------|
| Phase 3 | Fix things |
| Phase 7 | Learn impact |
| Phase 8 | Align with goals |
| Phase 9 | Stabilise behaviour |
| **Phase 9.5** | **Understand context of success** |
| **Phase 10–19** | **Governed learning authority — signal arbitration, resonance, causality** |
| **Phase 20** | **Temporal Coherence — synchronised multi-timescale adaptation** |

---

## 🆕 Phase 20 — Temporal Coherence Layer

Phase 20 solves the *cross-timescale instability* problem: adaptive subsystems
that operate at different speeds (kernel IPC → per-turn learning → governance)
can desynchronise, causing fast loops to reinforce stale information from slow
loops.

### New module: `modules/temporal_coherence.py`

| Class | Role |
|---|---|
| `AdaptationClock` | Per-tier cadence gate — `should_adapt("MEDIUM")` fires at most once per 60 s |
| `EpochManager` | Monotonic epoch counter; stamps every arbitration decision with `_epoch` |
| `SynchronizationBarrier` | Cross-tier staleness guard — fast tier skips adaptation if slow tier is stale |
| `TemporalCoherenceLayer` | Unified facade used by `niblit_core`, `niblit_learning`, nibblebots |

### Adaptation tier hierarchy

```
REALTIME   →  0 s — kernel IPC ring signals
FAST       →  0 s — per-turn quality scoring (always fires)
MEDIUM     → 60 s — NiblitLearning.evolve()   ← bounded by cadence gate
STRATEGY   →  5 m — CSE rule derivation
GOVERNANCE → 10 m — governance_evolution_engine
IDENTITY   →  1 h — long-horizon objective continuity
```

All intervals override via env: `NIBLIT_TCL_<TIER>_INTERVAL_S`.

### Multi-Axis Quality Arbitration (Phase 20B)

`_arbitrate_turn_quality()` now returns five partially-independent quality
dimensions alongside the backward-compatible scalar:

```python
{
  "resolved_quality": 0.72,          # scalar — unchanged for backward compat
  "quality_axes": {
    "reasoning":           0.82,     # evaluation_engine signal
    "engagement":          0.67,     # quality_feedback signal
    "factuality":          0.67,     # min(eval, qf) — conservative
    "strategic_alignment": 0.72,     # blended scalar
    "stability":           0.57,     # penalised by disagreement magnitude
  }
}
```

### NiblitOS Kernel changes (Phase 20)

- `NiblitRing` gains `volatile uint32_t epoch_id` — bumped on every IPC dispatch
- New syscall `SYS_NIBLIT_EPOCH_SYNC = 210`: advance (arg1=1) or read (arg1=0) epoch
- `SYS_NIBLIT_EPOCH_SYNC` lets the Python TCL synchronise its epoch counter with
  the kernel timeline across the IPC boundary at zero extra latency

---

## Project Structure

```
Niblit/
├── main.py                          # Boot sequence (Phase 0–7)
├── niblit_core.py                   # Core AI orchestrator
├── niblit_brain.py                  # Brain: HFBrain + RAG + SECA
├── niblit_router.py                 # Command routing + CLI
├── niblit_memory/                   # Knowledge database package
│
├── modules/                         # AI subsystem modules
│   ├── autonomous_learning_engine.py  # 32-step ALE cycle
│   ├── llm_architect_engine.py        # 🆕 LLM engineering pipeline (SFT/DPO/Eval)
│   ├── hf_brain.py                    # HuggingFace LLM interface
│   ├── llm_training_agent.py          # LLM-assisted training data generation
│   ├── trading_brain.py               # Trading AI (RSI/MACD/ATR + RL)
│   ├── rl_trading_policy.py           # PPO, DQN, Transformer RL policies
│   ├── trading_study.py               # Trading strategy research
│   ├── position_sizer.py              # 🆕 Kelly Criterion + drawdown circuit breaker
│   ├── reasoning_engine.py            # CoT, abduction, contradiction detection
│   ├── knowledge_comprehension.py     # Concept extraction (SECA)
│   ├── memory_graph.py                # Associative reasoning graph (SECA)
│   ├── reward_model.py                # Quality scoring for KB facts (SECA)
│   ├── concept_synthesizer.py         # Knowledge abstraction (SECA)
│   ├── rag_pipeline.py                # RAG: vector + SECA graph retrieval
│   ├── vector_store.py                # Sentence-transformer embeddings
│   ├── self_teacher.py                # SelfTeacher: internalise research
│   ├── self_healer.py                 # SelfHealer: repair KB / code
│   ├── self_maintenance.py            # Memory pruning + KB condensation
│   ├── niblit_cognitive_graph_kernel.py  # 🆕 CGK v1.0: unified event-driven runtime
│   ├── niblit_cyber_membrane.py       # 🆕 8-layer real-time security membrane
│   ├── niblit_defensive_evolution_loop.py  # 🆕 Self-attacking immunity loop
│   ├── niblit_kernel_v3.py            # 🆕 Cognitive Kernel v3 (fused + KCB)
│   ├── niblit_core_kernel.py          # Cognitive bus (think/remember/decide/act)
│   ├── niblit_core_kernel_v2.py       # 🆕 Local reasoning kernel (no LLM)
│   ├── sync_engine.py                 # 🆕 LCSP v1 multi-device sync
│   ├── memory_weighting.py            # 🆕 MWDS v2: adaptive memory decay/tiers
│   ├── cognition_core.py              # 🆕 Unified reasoning + goal + memory core
│   ├── goal_engine.py                 # 🆕 Goal-directed cognition (gap analysis)
│   ├── tokenizer_trainer.py           # 🆕 Domain-specific BPE tokenizer training
│   ├── phased_research_engine.py      # 🆕 3-phase structured research pipeline
│   ├── slsa_generator.py              # SLSA structured knowledge artifacts
│   └── ...                            # 70+ more modules
│
├── civilization/                    # STACA: multi-agent civilisation
│   └── civilization_core/
│       └── civilization_controller.py
│
├── nibblebots/                      # GitHub-based research bots
│   ├── research_bot.py               # LLM framework + RAG research
│   ├── ai_trading_bot.py             # Trading AI research
│   ├── llm_engineer_bot.py           # 🆕 LLM build pipeline research
│   ├── improvement_bot.py            # General improvement research
│   ├── aios_research_bot.py          # AIOS pattern research
│   └── aios_architecture_bot.py      # Architecture research
│
├── .github/workflows/               # GitHub Actions
│   ├── nibblebot-research.yml        # Friday: LLM/RAG research
│   ├── nibblebot-ai-trading.yml      # Saturday: trading AI research
│   ├── nibblebot-llm-engineer.yml    # 🆕 Thursday: LLM build pipeline research
│   └── ...
│
├── requirements.txt                 # Dependencies (see LLM training section)
├── .env.example                     # All environment variables
└── README.md                        # This file
```

---

## Running Tests

```bash
# Install dev dependencies
pip install pytest pytest-cov

# Run all tests
pytest -q

# Run with coverage
pytest --cov=modules --cov-report=term-missing -q

# Run specific test files
pytest test_code_tools.py test_full_upgrade_pipeline.py -v
```

---

## Troubleshooting

### `LOCAL_MODEL_PATH` set but fine-tuning doesn't run

Ensure `trl` and `peft` are installed:
```bash
pip install trl peft bitsandbytes accelerate datasets transformers
```
Then check `niblit llm-architect status` — it will show which libraries
are available.

### Out of memory during LoRA fine-tuning

1. Reduce `SFT_BATCH_SIZE=1` in `.env`
2. Enable 4-bit quantisation: install `bitsandbytes` and the model will
   load in 4-bit automatically when `bitsandbytes` is present
3. Use a smaller base model (0.5B instead of 7B)

### Trading: "No market data returned"

Check your API keys and ensure the exchange is accessible:
```bash
# Test Binance connectivity
python -c "from binance.client import Client; c = Client(); print(c.ping())"

# Test Alpaca connectivity
python -c "import alpaca_trade_api as tradeapi; api = tradeapi.REST(); print(api.get_account())"
```

### ALE not running

Set `NIBLIT_AUTONOMOUS_ENGINE=true` in `.env` and ensure `python main.py`
(not `server.py`) is used to start Niblit.

### Nibblebot workflows not triggering

1. Confirm workflows are enabled: **Actions → [Workflow] → Enable workflow**
2. The `GITHUB_TOKEN` secret is automatically provided in Actions — you
   don't need to add it manually unless running locally.
3. For local testing: `GITHUB_TOKEN=ghp_... python nibblebots/llm_engineer_bot.py`

---

## 🆕 Runtime Tooling Profiles (Phase Ω.7)

Niblit's runtime tooling layer is now profile-driven via `tools/runtime_profiles/`.

Available profiles:

- `niblit`
- `cloud-server`
- `termux-local`

Profile files define portable defaults for:

- app identity (`NIBLIT_APP_NAME`, `NIBLIT_RUNTIME_PROFILE`)
- control transport (`NIBLIT_CTL_SOCKET`, `NIBLIT_CTL_HOST`, `NIBLIT_CTL_PORT`)
- backend mode (`NIBLIT_GGUF_BACKEND`)
- inference URL/port (`NIBLIT_LLAMA_SERVER_URL`, `NIBLIT_LLAMA_PORT`)
- tunnel defaults (`NIBLIT_TUNNEL_TOOL`, `FLY_APP_NAME`)
- model locations (`NIBLIT_GGUF_MODEL_PATH`, optional `NIBLIT_LLAMA_BINARY`)
- runtime/governance mode defaults (`NIBLIT_RUNTIME_MODE`, `NIBLIT_SURVIVAL_MODE`, `NIBLIT_ATTENTION_PRESSURE`)

### Profile usage examples

```bash
# Termux launcher with explicit profile
bash tools/termux_inference_server.sh --profile termux-local

# Cloud/server profile
bash tools/install_llama_server.sh --profile cloud-server

# Sidecar client using cloud profile + TCP
python tools/niblit_ctl.py --profile cloud-server --transport tcp --host 127.0.0.1 --port 7681 --status
```

### `niblit_ctl.py` transport + output modes

`tools/niblit_ctl.py` now supports both UNIX and TCP transports:

```bash
# UNIX socket (default)
python tools/niblit_ctl.py --transport unix --socket /tmp/niblit-ctl.sock --status

# TCP socket
python tools/niblit_ctl.py --transport tcp --host 127.0.0.1 --port 7681 --status
```

Structured output options:

```bash
python tools/niblit_ctl.py -c "runtime status" --json
python tools/niblit_ctl.py -c "governance snapshot" --pretty
python tools/niblit_ctl.py -c "coherence state" --raw
```

Governance/runtime-aware convenience flags:

```bash
python tools/niblit_ctl.py --runtime-status
python tools/niblit_ctl.py --governance-snapshot
python tools/niblit_ctl.py --coherence-state
python tools/niblit_ctl.py --active-model-state
python tools/niblit_ctl.py --runtime-mode
python tools/niblit_ctl.py --attention-allocator-metrics
```

### Generalized local model validator

`tools/install_local_qwen_model.py` remains backward compatible by name, but now supports broader GGUF/runtime validation:

```bash
python tools/install_local_qwen_model.py --model-family qwen --verify filesystem
python tools/install_local_qwen_model.py --model-family llama --verify filesystem llama-binary
python tools/install_local_qwen_model.py --verify filesystem http --server-url http://127.0.0.1:8080
python tools/install_local_qwen_model.py --verify local-brain
```

### Portable runtime installer

`tools/install_llama_server.sh` now supports release overrides and upgrade behavior:

```bash
LLAMA_CPP_VERSION=b6129 bash tools/install_llama_server.sh --profile cloud-server --action upgrade
bash tools/install_llama_server.sh --action skip
bash tools/install_llama_server.sh --action overwrite
```

---

## 🆕 Distributed Runtime Unification (Niblit + Cloud + Lean)

Niblit now exposes a **cross-repo coordination layer** that treats:

- `riddo9906/Niblit` as governance + cognition authority
- `riddo9906/Niblit-cloud-server` as cloud runtime/inference node
- `riddo9906/niblit-lean-algos` as governed execution node

as one unified runtime contract surface.

### Runtime contract endpoint

```bash
GET /niblit/runtime
```

Returns schema-v2-compatible coordination payload with aligned fields for cloud/lean adapters:

- runtime mode + governance mode (`normal|cautious|survival|lockdown`)
- temporal epoch + coherence + coherence drift
- attention/resource pressure + runtime health
- forecast consensus + model trust + execution risk
- replay-safe trace metadata

### Federation-readiness endpoints

```bash
GET /cluster/status
GET /federation/peers
```

These expose federation-ready node registry state while remaining standalone-safe.

### Event-semantic alignment

The coordinator emits and preserves canonical Ω.7 events:

- `execution_envelope.published`
- `trade_reflection.ingested`
- `market_episode.ingested`
- `runtime_mode.changed`

This prevents cross-repo naming drift between core, cloud, and lean execution flows.

## Phase Ω.8 — Governance Authority Layer

Niblit now defines canonical cross-repo semantics in `shared/governance_contract/` for:

- schema-v2 envelope semantics
- runtime mode semantics
- event semantics
- advisor protocol normalization
- telemetry/replay metadata
- compatibility metadata
- federation readiness contract
- anti-drift validation

Runtime inspection surfaces:

- `GET /niblit/runtime`
- `GET /cluster/status`
- `GET /federation/peers`
- `GET /federation/status`

Tooling:

- `python tools/cloud_runtime_ctl.py diagnostics --json`
