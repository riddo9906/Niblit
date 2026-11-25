# Niblit r12 — packaged runtime acceptance, 2026-11-21

## Verified in this session
- Candidate: D:\NiblitAIOS\releases\candidates\build-20261121-r12-memory-governed\niblit
- R11 rollback candidate retained, worktree modifications not reset.
- Offline release preflight: 14/14 bundle files and 18/18 frozen imports checked.
- Manifest anchor SHA-256 matched; UI and Cloud executable SHA-256 hashes matched the installation manifest.
- Frozen --trading-selftest: MT5 and Freqtrade passed against doubles; two fixture submissions per venue, zero broker orders.
- Focused source tests previously run: 28 cognition/memory tests, 3 governance tests, 14 route/thesis tests passed.
- Packaged Core started with its bound r12 profile using niblit.exe --serve. PID at verification: 9040; port 5200 listening.
- HTTP 200: /health (core_bound=true), /market-desk/, /api/boot (ready=true), /api/status, /v1/inference/health (api_ready=true, inference_ready=true, default_model=qwen2.5-coder-3b), /memory, /api/runtime/state, /api/intelligence/predictions, /api/trading/software-readiness.
- Qdrant /healthz passed on port 6333. Qdrant /collections requires authentication (401), so no live authenticated collection round trip was established.
- Cloud 8201 and inference 8966 reachable.
- /api/trading/software-readiness explicitly reported execution_authorized=false and mode='intercepted software validation'.

## Unresolved acceptance blockers
1. /api/trading/positions returned HTTP 503 (position monitor unavailable); reconciliation of historical MT5 position ticket 591103520 and unknown EURUSD ledger entry not achieved.
2. /api/trading/sessions timed out under short local request timeout. Investigate without activating sessions.
3. /api/memory/framework timed out; /memory page loaded but does not prove governed Qdrant recall/persistence.
4. /v1/runtime/health reported status='unavailable': docker_backend stopped and llama_server_manager unavailable, even while /v1/inference/health reported ready. Diagnose inconsistent health projections.
5. No MT5 terminal64.exe and no Freqtrade native engine were running during the acceptance checks. Native broker readback, fills, orders, reconnection and autonomous exits cannot be accepted.
6. r12 boot diagnostics reported degraded RuntimeManager, FoundationArchitecture, event_bus, persistence_memory_knowledge_understanding, LocalBrain_ModelManager_ALE, and health_verification despite phase 0 / nine-stage bootstrap success.
7. Live-money permissions and venue adapters remain demo/dry-run scoped. Live route descriptors alone do not authorize real-money execution.

## Release decision
R12 packaged Core startup and base HTTP/Market Desk/inference routes: PARTIAL PASS.
Memory governance: source regressions PASS, live Qdrant round-trip NOT VERIFIED.
Broker/trading runtime and live-account acceptance: NOT ACCEPTED.
Do not enable real-money order submission or treat demo fixtures as live evidence.

## Preservation and next steps
- Keep r11 untouched and do not overwrite the r12 candidate manifest.
- Reconcile broker-native positions and ledger claims with read-only MT5 history before starting or replacing trading workers.
- Repair position intelligence 503 and session-status responsiveness, then rerun packaged verification.
- Validate authenticated read-only Qdrant collection access and governed recall with no destructive migration.
- Bring native MT5/Freqtrade services online only after checking existing accounts, open positions, service ownership, and dry-run identity.
- Build a separate explicit-account, bounded live-execution implementation and test order/fill/cancel/restart/exit paths before any real-money activation.
- No real-money order, position change, activation, or release replacement was performed by this session.

## Position-monitor 503 root-cause inspection
`server.py:get_core()` constructs `position_intelligence` only when optional bootstrap is enabled and Core has an AIOS scheduler. The r12 boot log explicitly says optional bootstrap is disabled by deployment; the response at `/api/trading/positions` is therefore consistent with an uninitialized monitor. This is not proof of a broker disconnection alone. The correct fix is to provide an explicitly scoped position-reconciliation service for the release (with read-only broker verification and single ownership), not merely force the optional-bootstrap flag or manufacture an empty position list.
