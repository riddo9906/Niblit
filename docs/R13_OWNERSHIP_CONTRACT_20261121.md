# R13 ownership provenance and offline adoption contract — 2026-11-21

## Current decision
- R13 observation-only Core remains running on port 5201.
- R12 original demo-trading Core remains running on port 5200.
- External read-only r13 handover observer actively monitors BTCUSDm ticket 591704289.
- Native demo position protections were not changed; no orders sent or account switched.
- Executable trading ownership transfer **not authorized**: r12 has not provided a durable old-owner release or an integrated lease handover.

## Strengthened native provenance
The read-only observer now requires all of the following, not merely a matching position ticket:
- Exact current demo account and terminal binding before/after broker history reads
- One Core open-order receipt with exact broker ticket, identifier, symbol and account
- Original Core prepared ticket token matching broker deal's niblit_ comment prefix
- Native deal and order magic 29102026, opening deal entry type, exactly matching broker volume and native order ticket
- Unique historical native order/deal attribution, valid broker stop loss/take profit, and zero pending native orders

The actual connected MT5 broker account passed this stricter check for BTCUSDm, including the original Core ticket/comment attribution. The separate historical EURUSD unknown record belongs to a different account identity and remains unresolved.

## New test-only adoption lease foundation
- modules/mt5_adoption_lease.py implements deterministic review and a SQLite-backed advisory-owner mutex.
- A simulated expired mutex cannot silently pass to a new holder, and concurrency among eight test workers yields one advisory holder.
- The review rejects live accounts, missing broker history, missing protections, duplicate claims, pending orders, account mismatch, malformed identifiers and lack of original runtime release.
- The review and mutex **never** grant execution or broker positions. R12 does not participate in this registry; this is not a cross-runtime lock or actual adoption.
- The active observer now includes adoption_review, which correctly reports review_passed=false, with blocker 'Original runtime has not issued an explicit ownership release'.

## Tests and runtime
- Focused run: 53 passed, 100%, against adoption-lease tests, handover, reconciliation, native exit advisory and exit policy.
- Live observation after restarting only the read-only observer: account and broker provenance eligible, exit recommendation HOLD_OR_ABSTAIN, orders_submitted=0.
- Snapshot: D:\NiblitAIOS\data\r13-observe-20261121\mt5-handover-latest.json.
- Original packaged r13 binary is unchanged by the new source additions. R12 and R13 remain separately healthy.

## Unfinished for actual broker takeover
1. Implement an explicit signed old-owner release and coordinated handover with r12; r12's already-expired session cannot be reinterpreted as a release.
2. Integrate a shared durable execution lease into both runtimes' order controllers and prove single-owner failover/restart/reconnect behavior.
3. Build an independent account-scoped position monitoring API and reconcile the missing position-intelligence endpoint.
4. Validate broker close lifecycle, partial fills, stop modifications, fee/slippage tracking, and historic EURUSD original-account evidence on test doubles and controlled demo.
5. Rebuild and frozen-test the new code before replacing r13's existing executable. Never use this observation result as funded trading authorization.
