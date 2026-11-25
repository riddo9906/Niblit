# Niblit R12 to R13 handover milestone — 2026-11-21

## Decision
Read-only broker observation handover: VERIFIED, actively monitoring in an independent process.
Trading-session/execution/exit ownership transfer: NOT performed.
R13 Core: http://127.0.0.1:5201/. R12 remains at http://127.0.0.1:5200/.

## Broker reconciliation
- Current native MT5 connection is DEMO; active broker position ticket 591704289, position identifier 591704289, symbol BTCUSDm, volume 0.01.
- Native stop-loss and take-profit present. Native pending-order count 0.
- Exactly one r12 open order matches the broker ticket, position identifier, symbol, account identity and terminal binding.
- Native position-linked broker deal history and order history were available, including a position-linked deal of the same symbol.
- Account and terminal binding were verified again after native history readback.
- R12 currently reports zero active trading sessions while the broker position remains open. Historical order receipt is not an active execution lease.
- A historical EURUSD unknown order belongs to a different account identity. It remains unresolved and was not cleared or adopted.

## New code and tests
- scripts/mt5_handover_observer.py: native MT5 read-only reconciliation with account-scoped receipts and atomic snapshot publication. No Core POST, order_send, login, close, or modification.
- scripts/Start-R13-Handover-Observer.ps1: health check, duplicate watcher guard, one-shot option.
- tests/test_mt5_handover_observer.py: binding, history, duplicate, switch, pending-order, missing position, cross-account, confinement cases.
- Full targeted run: 31 passed at 100% across handover, read-only reconciliation, active exit advisory and exit policy.
- Separate watcher running with --watch --interval 30, repeatedly updating the snapshot.
- Snapshot: D:\NiblitAIOS\data\r13-observe-20261121\mt5-handover-latest.json.
- Snapshot carries observation_handover_eligible=true, execution_authorized=false and trading_ownership_transferred=false.
- The observer runs via local Python MT5 SDK, not inside the frozen r13 trading engine; no execution authority has been migrated.

## Release preservation
- R12 frozen Core PID 9040, port 5200 HTTP 200; existing demo session and broker protections unmodified.
- R13 frozen Core PID 7416, port 5201 HTTP 200, observation-only with separate runtime data.
- MT5 terminal PID 19080 running.
- No trade, stop modification, service replacement, release overwrite or live activation performed.

## Blockers for true execution takeover
1. Implement an explicit single-owner adoption/exit contract for verified native positions and durable handover lease. Do not infer authorization from a historical Core ticket.
2. Test full native demo exit lifecycle, partial fills, restart/reconnect, cost/commission/slippage accounting and duplicate executor rejection.
3. Fix missing Core position-intelligence/service endpoints with evidence-backed independent broker observation.
4. Investigate the old EURUSD record against the original account's broker history, not the current account.
5. Build and validate a new frozen release after changes before controlled promotion. Live money remains disabled.

## Operator commands
One-shot recheck:
  & 'C:\Users\Riyaad\Documents\GitHub\Niblit\scripts\Start-R13-Handover-Observer.ps1' -Once
Read current observer result:
  Get-Content 'D:\NiblitAIOS\data\r13-observe-20261121\mt5-handover-latest.json' -Raw

## Continuous exit cognition added and verified
- The r13-independent read-only handover watcher now also evaluates the exact Core entry thesis against current native completed M5 candles and executable MT5 bid/ask via the pre-existing MT5 exit advisory. Its decision is added under exit_advisory in the same isolated JSON snapshot. It never transmits an order.
- First successful integrated poll: exit_advisory.status=observed; BTCUSDm entry_thesis_verified=true; breakout_v1; quote_fresh=true; exit_policy.action=hold; reversal_policy.action=hold; orders_submitted=0; execution_authorized=false.
- The first watcher was safely replaced with the updated implementation (only processes identified by the exact observer script were terminated); r12/r13 Core and MT5 terminal were untouched.
- Post-change combined focused regression command passed 31 tests at 100%.
- The active watcher was restarted using scripts/Start-R13-Handover-Observer.ps1, which checks Core health and refuses duplicate observers. Its output is refreshed approximately every 30 seconds; this does not create an OS-level autostart service.
- These changes are source-side utilities; the frozen r13 executable itself was not rebuilt or changed.
