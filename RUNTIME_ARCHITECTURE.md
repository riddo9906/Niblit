# Niblit Runtime Architecture

## Overview

The Niblit runtime now centers around a deterministic bootstrap contract implemented by RuntimeManager. The manager owns the shared runtime services, tracks lifecycle state, exposes extension points, and publishes a structured runtime report for operators and tests.

## Boot sequence

1. RuntimeManager initialization creates the core event bus, task queue, and orchestrator.
2. Lifecycle transitions move the runtime from created to loaded to ready.
3. Shared services are initialized in a fixed order:
   - knowledge_db
   - memory_graph
   - knowledge_comprehension
   - reasoning_engine
   - local_brain
4. Optional modules are loaded through module_loader and reported as loaded or failed.
5. RuntimeManager bridges core and module-level event streams and exposes the bridge state through diagnostics.

## Lifecycle model

The runtime state is intentionally simple and explicit:

- created: the manager instance exists but services are not yet initialized.
- loaded: services have been created and registered.
- ready: initialization completed and the runtime is available for orchestration.

## Event architecture

The runtime maintains two event surfaces:

- core event bus: used by RuntimeManager and the orchestrator.
- modules event bus: used by module-level components and the broader runtime stack.

RuntimeManager mirrors events between both surfaces so they can remain compatible while the architecture evolves.

## Diagnostics and observability

RuntimeManager exposes two public surfaces:

- get_diagnostics(): lightweight service and environment summary.
- get_runtime_report(): structured architecture snapshot including lifecycle state, boot sequence, event bridge state, and extension points.

These surfaces make startup behavior inspectable without forcing callers to depend on the internal implementation.

## Extension points

Extension points are registered by name and can be used to add future managers such as:

- memory_manager
- agent_manager
- tool_manager
- model_manager
- task_manager
- plugin_manager

The current contract is intentionally lightweight and can grow into a richer registry over time.
