# Desktop demo execution recovery audit — 2026-11-19

## Verified running state (read-only)

The installed candidate `dist/releases/build-2026-11-19T17-10-23-546Z-288fb2a6/niblit/niblit.exe` was running together with its UI, Cloud and Lean processes. Core `GET /api/trading/sessions` returned:

- `emergency_stopped: true` — persisted Core emergency latch.
- `remote_demo.configured: false` — no registered pinned Exness demo transport.
- Demo delivery policy: `delivery_authorized: false`; local MT5 and Freqtrade delivery disabled.
- Session states among last 30: pending 4, stopped 21, interrupted 5; none active.
- Order states among visible recent orders: one unknown MT5 EURUSD open, three rejected, one closed.
- Broker admission was idle. This does not prove safe reconciliation of the unknown order.

This is **not** solely a code-hardcoded emergency stop bug. `PermissionManager.activate_trading` intentionally persists stop and requires an affirmative reviewed bounded demo activation with `clear_stop=True`. For remote Exness, `CoreTradingSessions.activate` additionally requires a verified gateway, rejects unresolved remote deliveries, and coordinates the scope re-arm. `DemoReadiness` is read-only and must not reset any stop.

The one visible `unknown` MT5 delivery causes `CoreTradingSessions` to block new execution until reconciliation. It must never be manually rewritten to `rejected` or `closed` without broker attribution. A failed or missing MT5 transport cannot authorize a speculative retry.

## Patch

- Core API `execution_controls.recovery` now separately reports the persisted stop, requirement for scope-bound review, count of unresolved deliveries in the current status projection, lack of transport and that automatic rearming is disabled.
- Market Desk prints these independent blockers instead of merely showing `Emergency stop is latched`.
- A regression test proves the policy reports both latch and unknown claim without unlocking demo or funded execution.

## Required operational prerequisites (not performed)

1. Verify the missing private, exact Exness demo profile and gateway connectivity; the old VPS 0.2 cannot be assumed compatible with the current desktop.
2. Independently establish broker-side status and original receipt/deal history for the unknown EURUSD delivery. Preserve the Core SQLite ledger and original ticket identifiers.
3. Obtain complete account/symbol/currency-bound prospective cost evidence.
4. Only then review a new demo scope and use the existing affirmative Core activation/re-arm flow. Do not directly change the persistent `trading_control.stopped` database field.
5. Validate startup, gateway compatibility and broker readback with appropriate stops and no live-money account authority.

No broker orders, latch reset, VPS deployment or running-process restart was executed during this source patch.
