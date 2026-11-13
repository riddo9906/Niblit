# Cloud execution governance source map v1.6
Updated: 2026-11-01T17:18:24.489046+00:00

## Authority reused
The existing Core human ticket contract is the execution authority: Intent -> /api/preview -> random durable ticket, current session token and CONFIRM_SIMULATED_ORDER -> Desk.confirm -> final engine/account/config/risk validation -> persisted sending -> broker submission -> submitted/rejected/unknown -> reconciliation.
Neither schema-v2 governance defaults, market-analysis permission, specialist/LLM approval nor the legacy TradeIntent.approved field proves permission to execute. No generic transferable Core grant issuer/verifier was found. This revision does not invent one.

## Verified execution chain
Cloud POST /trading/trade/execute -> app/trading/router.execute_trade
 -> only canonical core_confirmation + X-Core-Desk-Token
 -> FreqtradeAdapter.confirm_core_ticket (existing flag required, strict dry-run shape, frozen JSON)
 -> fixed loopback bound Core API /api/trading/cloud/confirm on NIBLIT_API_PORT default5000
 -> server.cloud_ticket_confirm requires actual bound get_core(), explicit dry-run and current human token
 -> existing Core human desk8767 /api/cloud/confirm under original same-origin/session-token middleware
 -> BoundConfirm -> Desk.confirm(expected={intent,identity})
 -> atomic binding/current dry-run checks, original ticket expiry/risk validation
 -> original durable sending record before original forceenter/forceexit.
No token acquisition, ticket preview/minting, new approval authority, broker credential handling or direct broker mutation exists in Cloud. The request must already have been deliberately reviewed at the existing human desk. Generic analysis results cannot be used as tickets.
Both hops disable environment proxies and redirects and make exactly one POST. Any unverified response is blocked/unknown with execution_authorized=false and no automatic retry.

## Bindings and recovery
Expected identity and intent are compared to the stored Core ticket inside BEGIN IMMEDIATE, including replay requests. Current engine configuration must still match and dry_run must be exactly true.
This uses the existing Core definition of the local dry-run engine/account profile. It is not independent proof of broker authentication. Live/demo-account delegation through this Cloud path is not supported.
Entry/close action, pair, stake, trade_id and stored engine identity cannot be altered after preview.
Revoked/rejected tickets remain denied; expired previews cannot send. Submitted/reconciled responses are submission history, not fills or reusable grants.
Duplicate or unknown/sending tickets cannot submit again. Core's existing durable ledger owns restart/reconciliation; Cloud keeps no parallel execution ledger.
A running human desk with the bound Core API unavailable cannot authorize Cloud. The dedicated contract test verifies this boundary.

## Complete observed mutation inventory
1. app/trading/router.py POST /trading/trade/execute formerly coerced approved with bool() and called raw adapter execution. Generic legacy payloads now return execution_blocked, preserving the dict/HTTP interface without fake success.
2. app/trading/pipeline.py run_cycle (also reached through POST /trading/trade/proposal) may still create approved specialist intents. Its FreqtradeAdapter.execute now always blocks; it cannot mint or forward a human ticket. Market data/intelligence/research remain available.
3. app/trading/freqtrade_adapter.py formerly posted directly to Freqtrade /api/v1/forceentry and generated fake dry/ft IDs. Direct mutation and synthetic execution confirmations are removed. Read-only sync_open_trades/status/history remain.
4. app/trading/freqtrade_supervisor.py start_bot, stop_bot, restart_bot and emergency_shutdown reach _request. All non-GET requests or payload-bearing calls are blocked before URL/header/network construction because the existing Core ticket contract has no lifecycle grant. Emergency shutdown truthfully reports broker mutation blocked and local monitor stopped. Heartbeats/read-only sync/get operations remain.
5. app/execution/freqtrade_adapters.py has interface-only start_bot/stop_bot; now explicitly reports execution_blocked. ExecutionManager.start initializes interface state only, with no financial network call.
6. app/trading/trading_supervisor.py monitors via a placeholder; no order submission/close call exists.
7. Whole-repository Python search (excluding dependency environments/tests) found no other financial order send/modify/cancel/close transport. Generic inference/provider POSTs are not financial execution paths.
Unsupported lifecycle/configuration/cancel operations remain denied, even with a generic approval flag; no unverified grant support was added.

## Core and UI compatibility
Core's original /api/confirm(body) and MT5 DemoOrders APIs are unchanged for callers. The optional expected binding is used only by the new bound Cloud path.
Existing Core demo, dry-run limits, stale-market checks, risk, human acknowledgement, ambiguity and idempotency tests pass.
Cloud old proposals still return a structured response, but status is deliberately execution_blocked and no fake trade_id is returned.
No frontend, deployment, private configuration, risk limit, live flag, FREQTRADE_ENABLED value or actual running service was changed.

## Verification
34 nested actual Cloud -> bound Core -> existing human desk tests pass with a fake broker.
279 Core tests pass;238 Cloud tests pass in the final scoped matrix. The outer Cloud wrapper is included in238 and verifies all34 nested cases; do not add it as34 independent broker integrations.
One unchanged Windows/Termux dry-run launcher test fails independently. Earlier mixed-suite import collisions were corrected by isolating the sibling Core contract in a child interpreter. Child memory is forced into temporary test data with personal memory projection disabled.
Two session-created700-byte import snapshots (absent from baseline) were preserved under work/v16/import-artifacts, not left as a competing Cloud memory store. Metadata only is in evidence/v1.6/test-import-artifacts.json.
Exact commands/source hashes/JUnit/logs: packet_manifest.v1.6.json and evidence/v1.6/.

## Next integration implemented
Core scripts/check-market-pipeline.py uses existing read-only Desk.configuration/whitelist/market, existing assess_observation and the existing Core analysis forwarder.
It computes the same dry-run profile scope, exercises real registered rules when data exists, and requires fresh feed, completed Core analysis, Core allow and canonical-memory enqueue for analysis readiness.
It never previews/confirms orders, obtains human tokens, changes mode, starts services or claims execution readiness.10 unit/contract tests pass (also included in279).
Actual run failed ConnectError. TCP presence probes show no listeners5000/8767/8080/8100/8766/8772; Docker engine unavailable. No real broker/order/Qdrant demonstration was attempted or claimed.
