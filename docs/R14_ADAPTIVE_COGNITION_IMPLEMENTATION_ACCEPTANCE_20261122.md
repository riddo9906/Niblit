# Niblit R14 Adaptive Market Cognition — Implementation & Acceptance Record
**Date:** 2026-11-22 (Africa/Johannesburg)
**Issue:** https://github.com/riddo9906/Niblit/issues/422
**Working repository:** `C:\Users\Riyaad\Documents\GitHub\Niblit`
**Baseline branch/HEAD:** `fix/exness-demo-readiness-20261118` / `301571f0`
**Running frozen Core:** `D:\NiblitAIOS\releases\candidates\build-20261121-r14-mobile-integrated\niblit\niblit.exe`
**Build candidate (not deployed):** `D:\NiblitAIOS\releases\candidates\build-20261122-r14-cognition-shadow`

## Ground truth from existing R14 (read-only)
- Core canonical ledger: `D:\NiblitAIOS\data\r14-demo-eth-20261121\ledger.sqlite3`, opened with SQLite `mode=ro` and `PRAGMA query_only=ON`. Zero changes to the original ledger.
- Audit file: `D:\NiblitAIOS\diagnostics\R14-Market-Cognition-Audit-20261122.json`
- From the latest 1,000 trading events: 846 strategy-signal assessments, 206 unique retrospectively derived trace IDs, 21 position-reversal evaluations (all HOLD), and two completely reconciled realized outcomes. A third `trading_outcome` event lacked the complete verified information required by the audit.
- Reconciled ETHUSDm outcomes: breakout_v1 +0.60 account currency (net R approx +0.375); ema_pullback_v1 -0.56 account currency (net R -1.0). Historical trace IDs are retrospective reconstructions from originally recorded assessments, NOT identifiers that were originally emitted by the frozen runtime.
- Position sidecar: `D:\NiblitAIOS\data\r14-demo-eth-20261121\cognition-shadow-v1.sqlite3`. Records three identity-scoped, Core-owned ETHUSDm positions; two broker-reconciled closes and one open observation; 14 exact same-cycle executable bid/ask quote matches at last replay. No old/manual broker positions adopted.
- Backfill evidence: `D:\NiblitAIOS\diagnostics\R14-Position-Cognition-Backfill-Replay-20261122.json`. Running the backfill a second time did not duplicate known evidence.
- Core account ownership, broker position identity, account and symbol must match before any event is ingested; missing or mismatched observations are skipped, not synthesized.

## Implemented source modules

1. `modules/market_decision_trace.py` — `niblit.market-decision-trace/1` stable account-scoped IDs; original strategy candidates, chosen rule, versioned policy, original market thesis and optional regime evidence. Reconciled trading outcomes can include trace attribution. Historical legacy orders remain explicit.
2. `modules/position_cognition_record.py` — `niblit.position-cognition/1` SQLite append-only event ledger with dedupe by provider evidence ID and deterministic replay across restarts. Broker identity, sampled executable-price MFE/MAE, broker-reconciled realized cash, optional fee fields, quantity/fill and protective-stop changes. Never infer absent fees, assign hypothetical profits or adopt external positions.
3. `modules/market_regime_evidence.py` — `niblit.market-regime-evidence/1`; completed-bar M5/M15/H1/H4 input validation and derived ATR, ADX/+DI/-DI, RSI, EMA alignment, Bollinger width, range break and normalized volatility. Outputs uncalibrated regime hypotheses with deterministic evidence IDs, no trade direction or authority.
4. `modules/market_counterfactual_lab.py` — `niblit.market-counterfactual-shadow/1`; compare original strategy votes and WAIT using subsequently recorded executable bid/ask, fixed holding horizon and explicit assumed costs. Missing quote coverage or fees yield incomplete/unknown results. No hypothetical fill is ever called actual broker execution.
5. `modules/strategy_performance_shadow.py` — `niblit.strategy-performance-shadow/1`; account/symbol/timeframe/regime-scoped **broker-verified net-R only**, chronological train/validation split, minimum 30 training + 10 validation trades for shadow ordering. No autonomous promotion; present real sample is insufficient.
6. `scripts/inspect_market_cognition.py` — read-only Core ledger audit with evidence counts, original rule votes, trace reconstruction and broker outcome linkage. Does not query external broker.
7. `scripts/backfill_r14_position_cognition.py` — read-only Core-to-sidecar evidence backfill with exact same-cycle quote match, broker identity proof, idempotent replay and scoped outcomes.

## Source integration, explicitly observation only
- `modules/core_trading_sessions.py` now records `decision['regime_evidence']` in the established market assessment cycle, then computes `market_thesis` and `decision_trace`. Regime calculation errors return an `uncertain` shadow result without altering the original strategy manager's side, entry policy or execution pipeline.
- The final broker outcome emit adds `decision_attribution`, which references the immutable original decision trace when present; historical records remain explicitly labeled legacy.
- Currently only raw **M5** candles are passed to the live source integration. The MT5 bridge supplies summarized higher-timeframe context, not sufficient raw completed M15/H1/H4 series for the new regime engine. Source supports those inputs but multi-timeframe input integration is not complete.
- Position sidecar backfill is a separate read-only workflow. The running Core does not write to this new sidecar in real time until a separately tested, nonblocking ingestion adapter is promoted.
- Model prediction, RL, and Qdrant similarity remain separate research evidence; none is claimed to control the live deterministic strategy selector.

## Market Desk evidence panel — live static asset change
- Modern desk `http://127.0.0.1:5202/market-desk/` now contains `#cognition-proof` with the latest selected rule and reason, all registered strategy votes, latest reversal reason and up to five reconciled outcomes.
- UI data source: read-only `GET /api/trading/sessions`; no trading POST from this evidence viewer. Latest 100 event window is labeled; counts are NOT lifetime totals.
- Existing packaged assets `index.html`, `sessions.js`, `desk.css` were backed up to `D:\NiblitAIOS\diagnostics\market-desk-cognition-proof-20261122`, then updated in place without restarting or rebuilding the running Core.
- Server validation: all three live static URLs HTTP200, `node --check sessions.js` passed and `scripts/verify_r14_modern_market_desk.py` passed.

## Validation evidence
- Focused Task 02/03 tests passed; counterfactual, shadow ranking, audit and backfill unit tests passed.
- A combined regression run includes CoreTradingSessions, MT5 order, R14 broker minimum, portal/mobility and cognition components; see `D:\NiblitAIOS\diagnostics\R14-Cognition-Combined-Regression-20261122.log` for final pass/fail count.
- Frozen candidate PyInstaller build and offline self-test evidence: see `D:\NiblitAIOS\diagnostics\R14-Cognition-Shadow-PyInstaller-20261122.log` and release metadata when complete. **No deployment to the active demo Core has been authorized or performed.**
- No Core broker delivery guard, MT5 account controls, native SL/TP, live-funded trading or execution permission logic was altered by this adaptive cognition work.

## Repeatable proof commands (PowerShell)
```powershell
Set-Location 'C:\Users\Riyaad\Documents\GitHub\Niblit'
& '.\niblit-env\Scripts\python.exe' scripts\inspect_market_cognition.py --ledger 'D:\NiblitAIOS\data\r14-demo-eth-20261121\ledger.sqlite3' --out 'D:\NiblitAIOS\diagnostics\R14-Cognition-Audit-Rerun.json' --limit 1000
& '.\niblit-env\Scripts\python.exe' scripts\backfill_r14_position_cognition.py --core 'D:\NiblitAIOS\data\r14-demo-eth-20261121\ledger.sqlite3' --sidecar 'D:\NiblitAIOS\data\r14-demo-eth-20261121\cognition-shadow-v1.sqlite3' --report 'D:\NiblitAIOS\diagnostics\R14-Position-Cognition-New-Rerun.json'
```
Each report destination must be a new filename. The importer is idempotent and will skip already-recorded broker event IDs.

## Outstanding for fully adaptive demo execution
- Durable online position cognition with authority scoped across session expiry and exact ownership, including partial broker fills/modifications and crash recovery.
- Multi-timeframe raw closed-bar ingestion from M15/H1/H4 without increasing broker load or lookahead.
- Historical tick/bid-ask completeness and real broker fee model for counterfactual hold-vs-exit and competing strategies.
- Enough independent, regime-labeled, cost-complete real demo outcomes for walk-forward performance validation. Current two complete outcomes provide no statistical basis for an adaptive selector.
- Versioned selector promotion gate, retraining/rollback controls, correlated aggregate portfolio risk, MT5 hedging-vs-netting semantics, dynamic early-exit/partial-exit trial with explicit continuing-position authorization.
- Operator acceptance of a separately packaged cognition candidate before it can replace the running R14 baseline. Trading profits or avoided losses are not guaranteed.
