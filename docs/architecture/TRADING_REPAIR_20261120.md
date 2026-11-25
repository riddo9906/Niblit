# Trading repair checkpoint — 2026-11-20

## Worktree and scope
- Original Niblit HEAD at inspection: 301571f0. Existing uncommitted changes in trading desk, permission manager, trading sessions and build scripts were preserved. UI and cloud server repositories were clean.
- Requested removal is ONLY the persistent demo emergency stop latch. Core trading_control latch initialization, activation gating, admission checks, stop persistence, UI button, and reset acknowledgement were removed. Remote demo no longer persists/checks a stopped flag or exposes emergency-stop as a demo action.
- Ordinary Core stop remains; session/account identity binding, exact demo authorization, concurrency, expiry, risk limits, strategy consensus, unknown-delivery reconciliation and independent funded XM breaker remain intact. Historical persisted DB columns, if present, are not destructively dropped.
- The separate funded VPS observer breaker and its /emergency-stop endpoint have NOT been modified; this is not the demo latch.

## Verification
- Core trading-session suite passed fully (76 tests).
- Legacy configuration, demo controls and remote demo suite passed fully (79 tests).
- Python compilation and git diff --check passed.
- HTTP 200 on http://127.0.0.1:5200/market-desk/ and /api/trading/sessions.
- No broker order or position mutation performed in this repair.

## Freqtrade findings
- Freqtrade API on 127.0.0.1:8080 responds with auth; Core's Desk successfully authenticated read-only.
- API show_config: dry_run=true, state=stopped, strategy=NiblitLabManager, trading_mode=futures, timeframe=5m. Status returned THREE open positions. Do NOT start or switch strategies casually while these positions exist.
- The active Niblit native delivery contract checks for strategy=NiblitCoreManaged and state=running, so native Freqtrade submissions remain blocked for this profile; this is independent of removed latch.
- Freqtrade pair_candles returned empty columns/data because the bot is stopped; source fallback failed because CCXT was not installed in system Python. Python 3.14 user environment now has ccxt 4.5.93. The read-only Desk source test returned 200 completed BTC/USDT:USDT candles, fresh=True, source=public CCXT. Old local Freqtrade feather bars end July 2026; not fresh.
- Important: running Core process PID 16048 is the packaged niblit.exe in dist/releases/build-2026-11-20T04-42-56-640Z-2bc4d37f; installing into system Python does NOT patch that binary. Must rebuild/bind/test a fresh release before switching runtime.

## Pending acceptance
1. Confirm Chart and VPS gateway regressions; inspect any failing tests.
2. Ensure PyInstaller bundle collects installed CCXT, then run full existing multi-repository build with an operator-bound release runtime manifest. Do not overwrite the installed release or kill active Core before proving new bundle boots.
3. Verify new packaged Market Desk and embedded Tauri TradingPage show the same source and fresh candles, MT5 account/inventory readback, Freqtrade live protected data, strategy outcomes and chart annotations.
4. Reconcile 3 existing Freqtrade dry-run positions and explicitly plan strategy profile migration; preserve trade ledger and no unintended liquidation.
5. Verify restart behavior and release acceptance; do not claim trading execution fixed until dry-run sessions are reviewed and safely tested.

No credentials, account identifiers, funding changes or active positions were modified.

## Later live packaged acceptance
- Active Core was subsequently observed on PID 20928, executable D:\NiblitAIOS\releases\build-20261120-demo-control-retired\niblit\niblit.exe; its source/origin and build initiator were not asserted.
- Live GET /market-desk/ has NO core-emergency button, GET /api/trading/sessions exposes no emergency_stopped or latch/reset recovery fields.
- Live GET /market-desk/api/snapshot returned connected=True, Freqtrade configuration state=stopped and market_fresh=True, candles=200.
- Live GET /market-desk/api/charts/snapshot?environment=freqtrade&symbol=BTC%2FUSDT%3AUSDT&timeframe=5m returned market_fresh=True, candles=200, source=ccxt_public_exchange_ohlcv. This validates displayable public candles but NOT native Freqtrade analyzed signals while the bot is stopped.
- Follow-up repaired the observation-only request guard in modules/trading_desk.py for POST demo/start, mt5/confirm and core-trading/activate. The installed observation-only policy now responds with EXECUTION_DENIED before body validation; missing desk tokens still return 403. This is independent of the retired demo latch.
- Updated the focused trading desk regression to check both missing-token denial and valid-token execution denial. Targeted regression passed; complete trading desk + chart annotations batch passed (52 tests). Python git diff --check showed no whitespace errors.
- The running packaged binary was not overwritten by this latest source patch. Rebuild and package acceptance are still required.
- Existing three Freqtrade dry-run positions were not modified. Strategy still NiblitLabManager, not required NiblitCoreManaged; execution remains intentionally unverified.

## Live demo sessions after D: r3 promotion (2026-11-20, SAST)

- Rebuilt complete multi-repository release: `D:\NiblitAIOS\releases\build-20261120-demo-trading-r3\niblit\niblit.exe`; frozen offline preflight passed 14 checks and Core is serving Market Desk on `127.0.0.1:5200`, PID 15656 at acceptance.
- MT5 demo BTCUSDm entry costs: hash-pinned `D:\NiblitAIOS\config\demo-controls-20261115\mt5-btcusd-demo-simulation-costs.json`, `simulation_assumption` restricted to bound local demo identity/terminal/symbol/currency/size. Source tests and a real MT5 *read-only* buy/sell paper-cost preview both confirmed `costs_complete=True`. Charges are simulation assumptions, **not broker-certified**. No order was sent by either preview.
- Freqtrade isolated CoreManaged container at `127.0.0.1:18081`: `dry_run=True`, `force_entry_enable=True`, `state=running`, zero initial open positions. Historical LabManager at 8080 and its original trades left untouched.
- Stopped previous MT5 session `e5a97f91390b46878d2d3d7e7a62a613` via ordinary stop API before switching binaries; confirmed zero active sessions.
- Activated MT5 demo BTCUSDm 60-minute scope `915f7d44c1e643b4b459c62ad02715f7`; expiry 2026-11-20 **20:01:33 SAST**.
- Activated Freqtrade CoreManaged dry-run ETH/USDT:USDT 60-minute scope `d0952d90c8bc43a69f24b0d08ee68665`; expiry 2026-11-20 **20:02:01 SAST**.
- Both verified `active`, observer `running`, six strategy candidates, current consensus `wait`, entries `0`, no session-associated `trading_error` at first check. Market may change during the hour; no order/fill asserted. Both scopes allow up to three entries and one concurrent position, respecting Core account-specific risk policy.
- Earlier Freqtrade error was the container's `force_entry_enable=false`; this is now true and verified live via the Freqtrade API. Earlier MT5 cost error was no configured complete cost profile; the demo-only estimate is now loaded by the r3 source/build and the account-bound source previews succeeded.
- Do not purge the C: release directory that still hosts active Cloud/Lean services. Do not delete broker databases, MT5 logs, model files, strategies, configurations, Qdrant data, or historical trade records.
