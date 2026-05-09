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
