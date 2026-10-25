# Phase 5S — Governance hardening

Phase 5S closes the two governance defects prioritized by the Phase 5R reality
map. It records code changes and regression coverage; it does not claim that all
18 capabilities are complete or that Niblit is production-ready.

## Closed in this phase

1. **ExecutionGraph tool bypass removed.** `ExecutionGraph` no longer scans
   request text for tool names or invokes `niblit_tools.tool_registry.run()`.
   The graph clears caller-supplied tool-result fields and reports tool
   execution as disabled. Tool execution must go through `LlmToolLoop`, which
   owns schema validation, permissions, and execution limits.
2. **Runtime status gets the active Core.** `NiblitToolExecutor` accepts a
   dynamic Core provider. The governed-loop singleton uses it so tools created
   before Core initialization can resolve the live Core later.
3. **Capability reporting avoids duplicate availability checks.** A snapshot
   resolves its context once and evaluates each command once. Core report
   commands use the registry's context provider.
4. **BrainRouter supports the local gateway interface.** Availability checks
   work with gateways that expose `status()` instead of `is_available()`, and
   routing stats no longer assume the latter method exists.
5. **Test isolation improved.** MemoryGraph decay/prune tests use a temporary
   persistence file, so they do not load the developer's persisted graph.

## Verification

Regression tests cover the bypass removal, spoofed tool results, late Core
resolution, single-pass capability checks, and gateway availability. The
focused batch covering those regressions, the governed tool loop/runtime,
command surfaces, and `test_cognition_core.py` completed with **130 passed, 1
skipped** in 3:54.

The earlier full repository suite completed with failures across environment-
dependent tests (including unavailable shell/Docker/network/model dependencies),
and it is not a clean green build signal in this Windows environment. Its
generated tracked state files were restored. Use the focused batch above as the
verification for this phase; run the full suite in a provisioned CI environment
to classify the remaining failures.

## Next build gaps

- Re-run the full suite in CI with its declared system dependencies and
  hermetic test state.
- Profile and fix the 139-second `runtime_capabilities` path beyond the
  redundant availability checks removed here.
- Consolidate duplicate memory, vector, routing, conversation, research, and
  runtime paths identified in Phase 5R.
- Supply local model weights and a running Cloud service to validate inference
  end to end.
- Trading remains observation-only: the runtime package is absent and the
  Freqtrade adapter only translates signals. Live order execution is not
  implemented and must remain separately authority-governed.
