# Exness demo account-scoped uncertain-delivery guard — 2026-11-19

## Verified deployment facts

- Niblit Core service is running on the installed port 5200 via `niblit.exe --serve` using an explicit, SHA256-pinned release manifest. The original installation manifest is retained.
- The VPS gateway was upgraded to the version providing the reviewed `/demo/resume` route. VPS gateway and Exness demo order ledgers were backed up with SQLite integrity checks before deployment.
- The desktop's pinned SSH forward to VPS loopback port 18765 and `RemoteDemoAdapter.status()` verified the Exness demo gateway/account identity. No demo delivery was issued during integration.
- Core API confirmed `remote_demo.configured=true`, `verified=true`, `delivery_authorized=true`, with Core emergency stop latched and no active trading session.
- Gateway reported no unresolved demo deliveries, but its MT5 terminal reported `terminal_trade_allowed=false`. Core retains an unrelated historical MT5 EURUSD order in `unknown` state with reason `Original ticket unavailable`.
- The separate inference admission lease remains quarantined; do not clear it without tracing its unfinished work.

## Source changes

- In `CoreTradingSessions`, uncertainty guards for ongoing broker ticks and quarantined broker-lease release now match the *broker account identity*. A delivery unknown on the **same account** remains blocking regardless of which adapter (local MT5 vs remote demo) created it.
- Unknown deliveries belonging to another broker account remain unchanged in the ledger; they do not automatically block this verified demo account. Global recovery checks for dead owner processes and instrument uniqueness remain conservative.
- `configured_demo_profile()` handles an explicitly empty `NIBLIT_MT5_DEMO_PROFILE` by falling back to `NIBLIT_EXNESS_DEMO_PROFILE`.

## Evidence and remaining work

- Focused tests in `test_core_trading_sessions.py`, `test_legacy_trading_config.py`, and `test_remote_demo_readiness_policy.py`: passing on 2026-11-19; no broker orders submitted by these tests.
- Additional `test_joint_trading_safety.py` and `test_trading_desk.py` run had two unrelated denial-message assertion failures (`EXECUTION_DENIED` vs alternate existing text); not treated as a green comprehensive suite.
- Before execution: verify terminal Algo Trading is enabled **on the Exness demo account only**, get current clean broker inventory/readback and market snapshot, submit a fresh operator-reviewed bounded demo session, and clear the Core stop only via the explicit reviewed activation pathway. Never change the historical unknown order to closed/rejected without original broker evidence; never activate funded trading.
- A model GGUF download and future migration to `D:\models` are independent from broker activation.