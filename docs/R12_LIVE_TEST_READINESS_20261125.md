# Niblit r12 — Wednesday 2026-11-25 real-money readiness handoff

**As assessed 2026-11-21:** r12 is NOT accepted for live money, and live execution remains disabled. This is a release-engineering status, not a forecast of profitability.

## Validated today
- Frozen r12 Core is running from `D:\NiblitAIOS\releases\candidates\build-20261121-r12-memory-governed\niblit\niblit.exe`; local port 5200 health returns HTTP 200.
- Existing MT5 terminal is attached to a DEMO account (MT5 trade_mode=0). Current BTCUSDm position ticket `591704289`, 0.01 lot, with native stop-loss and take-profit present. Niblit magic=29102026. No trade actions were submitted.
- `GET /api/trading/sessions` showed one active **demo** MT5 BTC/USD scoped session, one BTCUSDm order in `open` state with position_id `591704289`, and one older EURUSD `unknown` order without a proven original position ticket.
- Core and MT5 have a matching BTCUSDm ticket NUMBER. This alone is not full account binding, receipt, lifecycle, and autonomous-exit proof.
- Three MT5 observers were running without reported errors. Three Freqtrade observers reported refused connections; old EURUSD observer reported a non-visible broker symbol.
- Qdrant authenticated `get_collections()` succeeded with the memory-laboratory environment, confirming episodic/reflection/semantic/memory-laboratory collections; zero writes performed. Governed write/recall round-trip not yet tested.
- Read-only reconciliation utility tested: 7 tests passed (includes terminal unavailable, live account observation without authorization, exact ticket, no ledger creation, localhost-only Core URL and open/unknown Core record parsing).
- Installed Qdrant is reachable, while the r12 Freqtrade API at 127.0.0.1:18081 is not. Another Docker Freqtrade container serves 127.0.0.1:8080 but its authenticated `show_config` returns 401 with the r12 selected profile. Do not repoint services until ownership and credentials are verified.

## Preflight command for Wednesday (does not trade)

Open PowerShell and run:
```powershell
& 'C:\Users\Riyaad\Documents\GitHub\Niblit\scripts\Invoke-Niblit-Wednesday-Preflight.ps1'
```

This wrapper queries local Core health, the optional position monitor, the configured Freqtrade API port, broker/ledger position ticket evidence, and authenticated Qdrant collection listing. It prints JSON with `readiness` and `blockers`; it does not send/modify/cancel/close orders or authorize trading.

## Current blockers
1. `GET /api/trading/positions` returns HTTP 503. Source `server.py:get_core()` initializes the Freqtrade-specific PositionIntelligence only with optional bootstrap and scheduler; r12 disables optional bootstrap. Implement explicit independent broker reconciliation for MT5 and separately owned Freqtrade position observation; do not substitute a fabricated empty position list.
2. `GET /api/trading/sessions` contains one EURUSD order in `unknown` state. Investigate native deal/order history and reconcile the precise historical account and ticket. Never mark resolved on the basis of an unrelated existing broker position.
3. Freqtrade dry-run service identity mismatch: r12 expects port 18081; container reachable on 8080 rejects r12 profile credentials. Identify authoritative profile and get an isolated dry-run engine configured before enabling native execution/observers.
4. Existing trading permission and delivery implementations are DEMO/DRY-RUN ONLY (`permission_manager.py`, `core_trading_sessions.py`, `mt5_orders.py`, `trading_session_adapters.py`, and `trading_desk.py`). Route descriptors listing `live` do not implement live execution. Do not bypass these checks.
5. Live account login/server identity, broker minimum size, actual commissions/spread/slippage, min/max stops, execution type, partial fill/order acknowledgement, restart recovery, autonomous close ownership, and end-to-end live fill/ledger reconciliation have not been tested.
6. Risk-adjusted performance is not established: a single historical Freqtrade dry-run gain and a handful of demo deals cannot predict profitability. Before committing real money, validate a sufficiently broad out-of-sample demo sample and worst-case loss/drawdown.

## What was preserved
- r11 rollback and r12 candidate files/manifests were not overwritten.
- Current demo Core/broker position were not restarted, cancelled, modified, or closed.
- Source worktree kept all parallel Freebuff and other changes.
- The new checks live in `scripts/mt5_readonly_reconciliation.py`, `scripts/qdrant_readonly_check.py`, `scripts/Invoke-Niblit-Wednesday-Preflight.ps1`, and `tests/test_mt5_readonly_reconciliation.py`.

**Decision:** do not use the current r12 package for unattended real-money trading on Wednesday. Continue demo/read-only testing until the blockers are closed and an explicit live-capable release passes genuine full-lifecycle acceptance.
