# Niblit Development Architecture Guide

## Purpose

This document explains how Niblit works as a unified runtime, how major scripts/modules interact, what was partially wired, and what was improved in this update.

---

## 1) System Identity and Runtime Shape

Niblit is an autonomous, evolving AI runtime built from five connected layers:

1. **Input & command handling**
2. **Routing & cognition**
3. **Memory & knowledge**
4. **Evaluation & policy feedback**
5. **Continuous learning & autonomous evolution**

Primary runtime entry is `main.py`, which boots `NiblitCore` (`niblit_core.py`).

---

## 2) Core Entry Scripts

- **`main.py`**
  - CLI shell runner, startup lifecycle, signal handling, non-blocking notifications.
  - Instantiates and drives `NiblitCore`.

- **`niblit_core.py`**
  - Orchestrator/runtime kernel.
  - Boots layered modules, routes commands and chat, triggers learning loops, and maintains unified loop health status.

- **`niblit_brain.py`**
  - General chat cognition path (non-command path).
  - Handles local/remote reasoning, context sanitation, and debate layer strategy selection.

- **`niblit_learning.py`**
  - Interaction-level learning memory.
  - Stores per-turn quality-aware learning entries and evolves them into persistent preference summaries.

---

## 3) Feedback and Learning Spine (Unified Loop)

### Primary loop per interaction

`User Input` → `Router/Brain` → `Response` → `QualityFeedback + EvaluationEngine` → `NiblitLearning` → `AdaptiveLearning` → `Policy/KB reinforcement` → `Loop status`

### Modules involved

- **`modules/quality_feedback.py`**
  - Scores answer quality.
  - Reinforces/decays relevant KB facts.
  - Emits reward signal for policy-level learning.

- **`modules/evaluation_engine.py`**
  - Tracks advisor quality and runtime outcome quality.

- **`modules/adaptive_learning.py`**
  - Tracks user preference trends and satisfaction-based strategy.
  - Can route satisfaction into quality loop via `score_override`.

- **`niblit_learning.py`**
  - Stores interaction metadata + quality.
  - Computes rolling quality/coherence profile (`evolve()`).

---

## 4) Nibblebots Evolution Stack

Located in `nibblebots/`.

- **`autonomous_evolution_agent.py`**
  - Autonomous fix scanning/planning/apply cycle.
  - Supports semantic planning lane + low-risk bulk lane.

- **`feedback_learner.py`**
  - Reads CI outcomes and journals real-world fix outcomes.

- **`causal_strategy_engine.py`**
  - Learns strategy rules from outcomes and context.

- **`stability_controller.py`**
  - Prevents unstable policy thrashing via mode memory/hysteresis.

- **`system_interface_layer.py`**
  - External-system mirroring/resonance and authority-domain conflict handling.

- **`governance_evolution_engine.py`**
  - Governance adaptation with constitutional floors and cadence.

- **`system_health_monitor.py`**
  - Reads runtime quality/evaluation signals and emits health snapshots.

---

## 5) What Was Partially Wired Before

### A) `AdaptiveLearning` in core boot

`NiblitCore._init_self_improvements()` created `AdaptiveLearning()` without wiring:
- `knowledge_db`
- `quality_feedback`

This meant adaptive feedback logic existed but did not fully participate in the same unified KB/policy quality loop by default.

### B) Per-turn adaptive feedback route

`NiblitCore._trigger_learning()` updated:
- `QualityFeedback`
- `NiblitLearning`

but did not also feed per-turn satisfaction into `AdaptiveLearning`, leaving that module underused in normal chat turns.

---

## 6) Wiring Improvements Implemented in This Update

### 1. Core initialization wiring fixed

`niblit_core.py` now initializes AdaptiveLearning as:
- `AdaptiveLearning(knowledge_db=self.db, quality_feedback=get_quality_feedback())`

This aligns adaptive-learning persistence and quality signal flow with the rest of the runtime.

### 2. Per-turn adaptive feedback connected

`_trigger_learning()` now routes each interaction into `self.adaptive_learning.record_feedback(...)` using turn quality converted to 1–5 satisfaction.

### 3. Duplicate quality-loop writes prevented

`AdaptiveLearning.record_feedback()` now supports:
- `propagate_quality: bool = True`

`_trigger_learning()` calls it with `propagate_quality=False`, so quality scoring is not double-counted when `QualityFeedback` already ran in the same turn.

### 4. Unified status visibility improved

`_refresh_unified_feedback_status()` now reports adaptive-learning status:
- current strategy
- feedback count
- recommended topics (top subset)

---

## 7) Validation Coverage Added/Updated

- `test_phase19_unified_feedback.py` now includes:
  - propagation-skip test for adaptive learning
  - verification that core turn loop triggers adaptive learning
  - verification that no duplicate quality feedback call occurs
  - adaptive-learning status presence in unified loop status

---

## 8) Module Interaction Map (High-Level)

- **Input/CLI:** `main.py`, `modules/command_registry.py`, `niblit_router.py`
- **Cognition:** `niblit_brain.py`, `modules/reasoning_engine.py`, `modules/reflect.py`
- **Memory/Knowledge:** `niblit_memory/*`, `modules/knowledge_db.py`, `modules/vector_store.py`, `modules/rag_pipeline.py`, `modules/graph_rag*.py`
- **Quality/Policy:** `modules/quality_feedback.py`, `modules/evaluation_engine.py`, `modules/policy_optimizer.py`
- **Learning:** `niblit_learning.py`, `modules/adaptive_learning.py`, `modules/autonomous_learning_engine.py`
- **Evolution/Autonomy:** `nibblebots/*` (planner, strategy, governance, health monitor)
- **Security/Resilience:** `modules/security_membrane.py`, `modules/niblit_cyber_membrane.py`, `modules/circuit_breaker.py`, `modules/resilience_wrapper.py`

---

## 9) Direction for Next Capability Phase

To move toward architectural identity continuity, next changes should focus on:

1. **Identity Drift Detection**
   - track long-horizon shifts in objective, policy, and feedback coherence.

2. **Constitutional Memory Layer**
   - persist non-negotiable design principles and enforce them during evolution proposals.

3. **Longitudinal Coherence Scoring**
   - add trend metrics across loop quality, stability, governance conflict rate, and strategy volatility.

4. **Cross-Layer Reflection Reports**
   - periodic “why we changed” summaries combining planner decisions, CI outcomes, and policy updates.

This will preserve directional coherence while Niblit continues increasing capability.

---

## 10) Additional Cross-Layer Gaps Found (Beyond Nibblebots)

After the previous wiring update, a deeper audit of core runtime logic identified two higher-order integration risks:

1. **Cross-loop quality conflicts had no explicit arbitration**
   - `EvaluationEngine` and `QualityFeedback` were both feeding quality semantics.
   - Downstream modules consumed signals, but there was no explicit conflict policy when those signals diverged.

2. **Unbounded per-turn learning aggregation cost**
   - `NiblitLearning.evolve()` aggregated across full history every turn.
   - This creates avoidable runtime cost growth as interaction logs become large.

---

## 11) New Runtime Enhancements in This Iteration

### A) Feedback arbitration in `NiblitCore`

Added `_arbitrate_turn_quality(...)` to resolve quality signals into a single turn-level authority:

- single source available → use that source
- both sources available and strongly disagree → conservative guard (`min`) to avoid confidence inflation
- otherwise → weighted blend (`evaluation` bias by default, configurable via env)

This creates explicit *feedback hierarchy behavior* without introducing a separate engine yet.

### B) Arbitration diagnostics exposed in unified status

`_refresh_unified_feedback_status()` now includes:

- `feedback_arbitration` payload:
  - source scores
  - disagreement magnitude
  - strategy selected
  - resolved quality

This makes quality-source decisions inspectable and debuggable.

### C) Adaptive-learning mapping now uses resolved turn quality

`_trigger_learning()` now maps satisfaction from the arbitrated turn quality (not raw single-source fallback), improving coherence between:

- evaluation
- reinforcement
- adaptation

### D) Learning bottleneck reduction in `niblit_learning.py`

`NiblitLearning.evolve()` now uses a bounded recent aggregation window:

- `NIBLIT_LEARNING_EVOLVE_WINDOW` (default `300`)
- `NIBLIT_LEARNING_SCAN_MULTIPLIER` (default `3`)

This preserves adaptive behavior while reducing per-turn aggregation overhead as logs grow.

---

## 12) Practical Impact

These changes improve architectural quality on four fronts:

1. **Coherence**
   - quality semantics are now resolved before adaptation decisions.

2. **Stability**
   - conservative guardrails on large signal disagreements reduce destabilizing over-reinforcement.

3. **Observability**
   - arbitration state is visible in unified loop status.

4. **Performance**
   - bounded learning aggregation reduces long-run runtime pressure.

---

## 13) Full-System Script Collaboration (Deep Dive)

This repository functions as a unified stack by splitting responsibility across script groups that exchange explicit state:

### A) Bootstrap + Runtime Entry

- `main.py` — primary interactive boot and lifecycle loop.
- `aios_runtime.py` — canonical phase-boot coordinator (ENV→INTERFACE).
- `niblit_core.py` — runtime orchestrator and turn loop authority.

### B) Cognition + Routing

- `niblit_brain.py` — inference and response generation.
- `niblit_router.py` — command/chat/intent routing.

### C) Memory + Knowledge

- `niblit_memory/*` and `modules/knowledge_db.py` — persistent KB and memory APIs.
- `modules/vector_store.py` and retrieval layers — semantic retrieval backbone.

### D) Quality + Adaptation

- `modules/evaluation_engine.py` — evaluation signal.
- `modules/quality_feedback.py` — reinforcement signal.
- `modules/adaptive_learning.py` — user-adaptation strategy.
- `niblit_learning.py` — long-horizon interaction preference evolution.

### E) Governance + Autonomy

- `nibblebots/*` — strategic, governance, and autonomous evolution layers.
- `nibblebots/system_health_monitor.py` — cross-loop health reflection.

### F) AIOS / Kernel Integration

- `kernel/*` (Python kernel abstractions) — host/runtime OS-adjacent services.
- `os/kernel/*` (C++) — bare-metal kernel and syscall/runtime substrate.
- `os/userland/niblit_tool/*` — userspace bridge into Python `NiblitCore`.

---

## 14) Additional Partial Wiring Fixed in This Pass

### C++ NiblitOS IPC authority mapping

`os/kernel/niblit_iface.cpp` now maps the allocated ring frame at the canonical
`NIBLIT_RING_VADDR` with user-accessible page flags, instead of using a
physical-only pointer. This aligns:

- syscall contract (`SYS_NIBLIT_MMAP_RING`),
- kernel-side ring ownership,
- userspace bridge expectations.

This removes a hidden address-authority mismatch in the OS integration layer.

### NiblitOS userspace runner build wiring

`os/Makefile` and root `Makefile` now expose explicit targets for the userspace
Niblit runner bridge:

- `runner` / `runner-run` (inside `os/`)
- `niblit-runner` / `niblit-runner-run` (repo root wrappers)

This makes the kernel↔Python bridge reproducible in development workflows.

---

## 15) Remaining High-Value Follow-Ups

To continue reducing architectural drift:

1. **Multi-axis quality arbitration** — ✅ **Implemented in Phase 20** (see §16).

2. **Adaptive memory compression**
   - preserve high-impact events while compressing low-impact historical noise.

3. **Kernel↔Python reliability contract**
   - add explicit ring health, timeout, and backpressure metrics in `/proc/niblit`.

---

## 16) Phase 20 — Temporal Coherence Layer

### Problem addressed

Adaptive systems spanning multiple timescales suffer from *cross-timescale
instability*: a fast subsystem (per-turn learning) can reinforce stale
information produced by a slow subsystem (governance) that has not updated
recently.  This creates unsynchronised learning that slowly undermines
arbitration authority and policy coherence.

### Solution: `modules/temporal_coherence.py`

A new first-class module providing three primitives:

| Class | Responsibility |
|---|---|
| `AdaptationClock` | Per-tier cadence gate — `should_adapt(tier)` returns True at most once per min_interval for that tier |
| `EpochManager` | Monotonically increasing runtime epoch counter; stamps every decision dict with `_epoch` / `_epoch_ts` |
| `SynchronizationBarrier` | Cross-tier staleness guard — fast tier skips adaptation if slow tier heartbeat is stale |

**Tier hierarchy:**

```
REALTIME  (0 s) — kernel IPC, ring signals
FAST      (0 s) — per-turn quality scoring (always fires, caller controls)
MEDIUM   (60 s) — NiblitLearning.evolve() — bounded aggregate (Phase 19+20)
STRATEGY (300 s) — CSE rule derivation
GOVERNANCE (600 s) — governance_evolution_engine
IDENTITY  (3600 s) — long-horizon objective continuity
```

All intervals are overridable via environment: `NIBLIT_TCL_<TIER>_INTERVAL_S`.

### `NiblitCore` integration

`_trigger_learning()` now:

1. Calls `self._tcl.tick()` — advances the runtime epoch once per interaction.
2. Stamps the arbitration result with the current epoch via `_tcl.tag_decision(...)`.
3. Passes `epoch_tag` to `NiblitLearning.process_interaction(...)` — every
   stored learning entry is now epoch-tagged for delayed-outcome attribution.
4. Gates `NiblitLearning.evolve()` behind the `MEDIUM` cadence — instead of
   aggregating on every turn, the expensive window scan only fires when the
   MEDIUM interval has elapsed.

`_refresh_unified_feedback_status()` now exposes `temporal_coherence` in the
unified loop status, including epoch count, uptime, per-tier clock state, and
barrier coherence.

### Multi-Axis Quality Arbitration (Phase 20B)

`_arbitrate_turn_quality()` now returns a `quality_axes` dict alongside the
backward-compatible `resolved_quality` scalar:

```python
{
    "resolved_quality": 0.72,          # scalar (unchanged — backward compat)
    "quality_axes": {
        "reasoning":           0.82,   # evaluation_engine signal
        "engagement":          0.67,   # quality_feedback signal
        "factuality":          0.67,   # min(eval, qf) — conservative
        "strategic_alignment": 0.72,   # blended scalar
        "stability":           0.67,   # penalised by disagreement magnitude
    }
}
```

Different subsystems should consume the axis most aligned to their function
rather than collapsing to one scalar (e.g. causality_tracker uses `reasoning`,
adaptive_learning uses `engagement`, governance uses `stability`).

### NiblitOS C++ changes (Phase 20)

| File | Change |
|---|---|
| `os/kernel/niblit_iface.h` | Added `volatile uint32_t epoch_id` + `_ring_pad` to `NiblitRing`; added `advance_epoch()` / `current_epoch()` to `NiblitIface` namespace |
| `os/kernel/niblit_iface.cpp` | `send_request()` now bumps `s_ring->epoch_id` before every dispatch; `advance_epoch()` / `current_epoch()` implemented |
| `os/kernel/syscall.h` | Added `SYS_NIBLIT_EPOCH_SYNC = 210` |
| `os/kernel/syscall.cpp` | `sys_niblit_epoch_sync(advance)` implemented; case 210 registered in dispatcher |
| `os/userland/niblit_tool/niblit_runner.c` | `NiblitRing` struct updated to include `epoch_id` + `_ring_pad` matching kernel layout |

The userspace Temporal Coherence Layer can call `SYS_NIBLIT_EPOCH_SYNC(1)` to
advance and read the kernel epoch, keeping Python epoch in sync with the
hardware timeline without additional IPC overhead.

### What this prevents

| Risk | Mitigation |
|---|---|
| Fast loop reinforcing stale governance signal | `SynchronizationBarrier` detects staleness and blocks adaptation |
| O(n) evolve() cost per turn | `MEDIUM` cadence gate limits aggregate scans to once per 60 s |
| Delayed outcomes attributed to wrong epoch | `epoch_tag` on every learning entry enables accurate attribution |
| Single-score overcompression of quality | `quality_axes` preserves independent dimensions |
| Kernel / userspace epoch desync | `SYS_NIBLIT_EPOCH_SYNC` + `ring->epoch_id` create a shared truth surface |

---

## Runtime Tooling Subsystem (Portable / Governance-Aware)

Tooling is now split into a portable runtime operations layer:

- `tools/runtime_profiles/*.env` — profile-based runtime configuration
- `tools/runtime_profiles/profile_loader.sh` — shared bash profile loader
- `tools/lib/runtime_profiles.py` — shared python profile loader
- `tools/lib/sidecar_client.py` — reusable UNIX/TCP sidecar client with schema-safe normalization
- `tools/niblit_ctl.py` — thin CLI wrapper over shared client library

### Governance-aware runtime telemetry

`tools/termux_inference_server.sh` now emits structured runtime telemetry aligned with Phase Ω.7 semantics and event naming:

- `EVENT_RUNTIME_MODE_CHANGED`
- `EVENT_EXECUTION_ENVELOPE_PUBLISHED`
- `EVENT_RESOURCE_ADAPTED`
- `EVENT_ATTENTION_ALLOCATED`
- `EVENT_REFLECTION_COMPLETE`

These are emitted as operational log events (non-invasive) and do not change core runtime event bus behavior.

### Backward compatibility principles

1. Existing default paths and env vars remain supported.
2. Existing `tools/install_local_qwen_model.py` entrypoint remains valid.
3. Existing sidecar UNIX socket workflow remains default.
4. New features (profiles, TCP transport, output modes) are additive.

### Targeted tooling test coverage

`test_runtime_tooling_layer.py` covers:

- profile discovery and key presence
- profile env application
- sidecar response normalization
- output formatter modes

---

## Distributed Runtime Coordination Layer

`modules/distributed_runtime_coordinator.py` is the Niblit-side unification layer for the three-repo runtime ecosystem.

Responsibilities:

- merges cloud runtime status + local lean signal into one normalized schema-v2 contract
- normalizes governance/runtime modes (`normal`, `cautious`, `survival`, `lockdown`)
- ingests trade reflection + market episode streams and republishes canonical events
- writes replay-safe coordination traces for causal/temporal reconstruction
- maintains federation-readiness node registry state (`core`, `cloud_runtime`, `governed_execution`)

Core integration points:

- `NiblitCore._init_optional_services()` initializes coordinator
- `_refresh_unified_feedback_status()` includes `distributed_runtime` status
- `_cmd_status()` surfaces current runtime mode

API integration points:

- `/niblit/runtime` — canonical runtime contract (cloud/lean adapter-compatible)
- `/cluster/status` — federation-readiness status
- `/federation/peers` — known peers from node registry

Validation:

- `test_distributed_runtime_coordinator.py` checks contract normalization, event compatibility, and cloud-status mapping.
