# Niblit structured demo execution engine — draft architecture and implementation plan

Status: **source-first, partial implementation; NOT wired to the running release**.
Prepared 2026-11-20. Worktree HEAD when inspected: `301571f0` with pre-existing uncommitted changes preserved.
This design replaces speculative "evolving autonomous AI" with a deterministic, evidence-driven trading system.
It does **not** assume any indicator or strategy can predict the future with certainty.

## 1. Reproducible end-to-end pipeline

1. **Identity and feed:** bind broker, demo account, symbol, quote, M5 candles, contract size, time source and snapshot ID. Distinguish MT5 native bar data from Freqtrade exchange OHLCV.
2. **Market integrity:** reject stale quotes, incomplete forming candles, gaps, reversed OHLC, instrument mismatches, absent currency conversion and invalid precision. No missing-data zero defaults.
3. **Feature computation:** pure functions calculate SMA20/SMA50, EMA20/EMA50, RSI14, Bollinger bands, 20-bar highs/lows, volatility compression, Wilder ATR14 and market structure from *completed* historical candles.
4. **Regime/context:** determine descriptive trend/range/volatility conditions. Higher timeframes are advisory in current source, not independent votes. Changes to veto/weighting require an explicit policy version and backtest.
5. **Strategy evaluation:** evaluate all six registered human-authored strategies on the same snapshot. Every strategy records direction, conditions, data provenance, bar ID and evidence. A failure does not masquerade as an abstaining/agreeing vote.
6. **Consensus:** opposing eligible directions => WAIT; no eligible signals => WAIT; one or more agreeing candidates => current documented priority (breakout before registry order). Strategy eligibility is a trading **hypothesis**, not a probability forecast.
7. **Trade proposal:** convert selected direction to a structural stop, target and invalidation thesis. For BTC/ETH USD crypto, use the existing `crypto_stops.levels` M5 Wilder ATR14 + structure + spread + broker grid policy, not generic 200-point/spread stops.
8. **Sizing:** call MT5 `order_calc_profit` on candidate entry-to-stop at proposed *one-lot* quantity, expressed in account currency; set gross-loss-per-lot from that exact broker result. Budget `min(equity * risk_fraction, cash_cap)`; volume `floor_to_broker_step(min(max_lots, budget/loss_per_lot))`. If the minimum lot exceeds the budget, **no trade**. Never tighten the structural stop to make a minimum lot affordable.
9. **Costs and risk:** bind commission, spread, financing/slippage/funding assumptions to exact account/symbol/size/clock; distinguish observed vs simulation-bound costs; verify complete modeled downside and net target, exposure, open positions, margin and session/day caps.
10. **Execution:** immutable proposal with hash and expiring snapshot, pre-send revalidation, account-bound Core permission, durable claim, exactly-once dispatch attempt and broker receipt. Keep the removed **demo latch** absent. Normal order, risk and broker correctness checks remain; the user-visible activation workflow must not depend on eligible strategy signals.
11. **Order lifecycle:** `OBSERVED → PROPOSED → RISK_REVIEWED → PREPARED → SENDING → SUBMITTED/REJECTED/UNKNOWN → OPEN → CLOSED`; reconcile broker position/deal identifiers before a further attempt. Never infer a fill from the presence of a signal or HTTP response alone.
12. **Position lifecycle:** persist the entry strategy, initial stop, take-profit, indicators and decision snapshot. Existing exit policy uses strategy invalidation, broker protection and profit giveback; only exact Core-owned positions may be managed.
13. **Audit and evaluation:** record full input snapshot hash, strategy votes, parameter version, cost profile, broker ticket and actual net P&L. Replay bars point-in-time with fees, slippage and walk-forward out-of-sample periods. Separate hypothesis scorecards from production authority.
14. **Observation UI:** show *observed*, *qualified*, *prepared*, *submitted*, *filled*, *closed* separately; explain WAIT and every risk rejection. Compare simulated orders to broker readback on MT5/Freqtrade. Do not use visually optimistic trade counters.

## 2. Calculation finding

Active r3 MT5 Core instantiates `DemoOrders(... autonomous_max_volume=.10)` without `crypto_stops=True`.
For BTCUSDm, `mt5_orders.build` therefore uses:

```python
distance = max(200, broker_stop_points + ceil((ask - bid) / point) + 2) * point
stop = entry +/- distance
target = entry -/+ 2 * distance
gross_risk = -MT5.order_calc_profit(type, symbol, volume, entry, stop)
```

Thus spread and broker minimum determine stop distance, **not** equity risk fraction. Equity cap only acts downstream as an admission/sizing ceiling. The two observed BTCUSDm initial stop risks around $0.06 and $0.07 are far below the ~$25 equity risk cap. Gross 2:1 reward/risk may be net-unprofitable after spread/slippage/financing. No automatic tightening based on equity is authorized.

The existing `modules/crypto_stops.py` already implements a richer deterministic model but is **not currently enabled for local MT5**. Enabling it requires broker-contract verification, stop/risk model testing, correct per-venue cost modeling and broker-readback acceptance, **not** a blind toggle in a running session.

## 3. Source additions already implemented

- `modules/structured_trade_engine.py`: pure BTC/ETH M5 planner. Validates canonical candles/quotes; applies existing all-six-strategy consensus; uses existing crypto ATR + structure protection; floors broker-lot-grid size within risk budget; emits immutable plan hash and explicit `DRAFT_ONLY` with `execution_authorized=False`. It never calls an order API.
- `tests/test_structured_trade_engine.py`: replay-determinism, policy priority, invalid candles, stale quotes, invalid currency/spec, affordable/unaffordable minimum lots, broker volume-step floor and no execution authority.
- `modules/trading_session_adapters.py`: independently fixed Freqtrade native delivery receipt wrapper to `return guard()` instead of losing the Core receipt. Regression tests added to `tests/test_packaged_execution_repairs.py`.
- These are **source changes only**. The still-running D: r3 binary predates them, and changing them has **not** modified current sessions.

## 4. Next integration stages (do not compress without tests)

**A — Deterministic contracts and snapshots:** formalize venue-neutral `MarketSnapshot`, `Decision`, `TradePlan`, `ExecutionReceipt`, `PositionState`, `Outcome`, with versioning, checked currency/unit semantics, canonical hashes and explicit clock source. Add paired fake MT5/Freqtrade snapshot fixtures and no-network reproducibility tests.

**B — Risk-first geometry:** connect Core's MT5 `draft_entry`/ `prepare` to exact broker stop-value and pure structure plan; use `crypto_stops` consistently for BTC/ETH. Validate stop grid, broker distances, 0.01 minimum lot, stop-to-volume math and net cost assumptions at draft/confirm. Do not use 1-lot risk linearity without testing broker valuation across quantities.

**C — Freqtrade native delivery:** package the receipt-return fix, assert exact one-time final guard, confirm running dry-run identity and token callback, then verify a Core-approved order appears in isolated Freqtrade `18081` with matching `niblit_core:<ticket>` entry tag and durable native ledger. Preserve independent LabManager container `8080`; no position adoption.

**D — End-to-end state machine:** explicit order transition legality, idempotent claims by account/instrument/bar, no blind retry on unknown states, broker reconciliation across restarts. Decouple alert delivery from execution. Retain ordinary session scope and risk budgets but **do not reintroduce an emergency/demo stop latch**.

**E — Market prediction as tested hypotheses:** first output directional scenario + invalidation + uncertainty, not fake win percentages. Benchmark each strategy and consensus against no-trade and buy/hold baselines, train/test split by time, walk-forward validation, profit factor, drawdown, win/loss distribution, transaction costs and regime performance. Only after reproducible out-of-sample evidence consider separately versioned statistical forecasting; no self-rewriting or evolving AI.

**F — Release acceptance:** offline pure tests; replay property/invariant tests; broker-double contract tests; isolated MT5/Freqtrade dry-run acceptance; verify exact account/position/deal provenance, stop/target placements, broker-native closes, reconciled outcomes and restart behavior. Promote a new release only when the current session has finished or the user authorizes an interruption.

## 5. Current live evidence as of initial inspection

- r3 MT5 BTCUSDm one-hour demo session: active at initial inspection, two broker-linked and reconciled trades (+$0.13, -$0.12).
- r3 Freqtrade ETH/USDT:USDT CoreManaged dry-run: active at initial inspection, two rejected entries because `final_guard` returned `None` rather than Core's actual receipt.
- Both observers were running, six strategies were evaluated for each venue.
- Exact current session status must be checked at acceptance; do not assume session remains active after expiry.

## 6. Non-goals and hard boundaries

No profitability promise, no invented prediction confidence, no self-modifying AI, no live-funded order activation, no manual orders to force a green test, no trade/position deletion, no restart of running r3 before the intended test finishes, no unverified browser screenshots, no implicit fallback from isolated CoreManaged to historical LabManager.

**Definition of done:** the same historical observations and configuration yield the same plan and hash; risk and costs are correctly broker-valued; both isolated demo venues can submit, reconcile and report exact Core-attributed orders; every rejected/unknown result is explained; the reproducibility suite remains green.

## 7. Source regression and final live-session snapshot

- Focused combined suite: **48 passed** (`tests/test_structured_trade_engine.py`, `test_strategy_manager.py`, `test_strategy_failure_consensus.py`, `test_packaged_execution_repairs.py`); one third-party Starlette deprecation warning, no failing tests. `git diff --check` found no whitespace errors.
- Final read-only r3 API inspection: MT5 BTCUSDm session `915f7d44c1e643b4b459c62ad02715f7` active, observer running, **3/3 entries**, 3 closed broker-reconciled orders: **+$0.13, −$0.12, −$0.15 USD**, realized combined **−$0.14 USD**.
- Freqtrade ETH/USDT:USDT session `d0952d90c8bc43a69f24b0d08ee68665` active, observer running, **3/3 attempted entries**, all rejected `Core delivery receipt mismatch; nothing submitted`. The observer then reported `Session entry limit reached`, consistent with the configured attempt budget, not proof of any Freqtrade fill.
- The isolated Freqtrade CoreManaged controller `127.0.0.1:18081` had 0 open positions and 0 trades when independently read through its authenticated API. The separate historical LabManager controller `127.0.0.1:8080` was not altered.
- **No frozen release rebuild or session restart was performed for the new structured planner or the Freqtrade receipt patch.** The original r3 demo scopes were left running without extending the entry limits. The source changes are not in r3 yet.

## 8. Continued direct Desktop Commander integration (source, not promoted)

- User explicitly requested continued development in chat, a structured deterministic bot Core, and **no renewed emergency latch or arbitrary UI-disable mechanism**. All existing working-tree changes were preserved; no reset/clean/stash or commit.
- Production installer in `modules/core_trading_sessions.py` now constructs local MT5 `DemoOrders(..., crypto_stops=True)` for BTC/ETH broker symbols. This selects the existing `crypto-atr-structure/1` stop/target calculations while keeping ordinary execution, non-crypto behavior and broker receipt verification unchanged.
- `MT5SessionAdapter.prepare()` now uses `structured_trade_engine.lot_grid()` to round the broker-verified volume **down** to the lot grid rather than a separately maintained calculation. Preview and final broker review still revalue the stop risk at the actual size.
- Each broker-reviewed BTC/ETH proposal now carries a **pure hashed `structured_plan`** of venue/account/symbol/side/strategy, completed M5 bar, ATR, structure anchor, actual reviewed entry/stop/target, quantity, gross stop risk and budget, with `execution_authorized=False` (the separate Core execution claim still owns authority).
- Added `test_core_mt5_demo_crypto_preflight_uses_atr_structure_not_spread_formula` to run against the MT5 broker double, confirming the reviewed stop is volatility/structure-based and no order is sent. The actual Freqtrade receipt-forwarding patch from the earlier pass is retained.
- No running D: release was edited or restarted; production behavior remains unchanged until the next explicit release promotion.
- Before promoting, run the broader Core and strategy regression suite; then a fresh release preflight, isolated demo risk/stop inspections and broker readback. Never interpret an unfilled claim or strategy signal as proof of a fill.

### Integration verification (direct Desktop Commander, 2026-11-20)

- **125 focused regression tests passed** across `tests/test_structured_trade_engine.py`, `tests/test_packaged_execution_repairs.py`, `tests/test_core_trading_sessions.py`, `tests/test_strategy_manager.py`, `tests/test_strategy_failure_consensus.py` (one nonfatal Starlette test-client deprecation warning). Log: `D:\NiblitAIOS\diagnostics\trading-repair-20261120\structured-integration-r2.log`.
- `git diff --check` returned exit code 0; pre-existing worktree changes, untracked files and branch HEAD were preserved.
- Last read-only live check: running Core was still packaged D: r3 PID `15656`; both one-hour session records reported `active` with `entries=3`; no restart or new activation was performed by this source integration.
- **Not deployed:** r3 continues to run its previous MT5 spread-based geometry and old Freqtrade receipt handling. A distinct tested release plus acceptance check must follow before saying structured stop geometry or repaired Freqtrade orders work in the actual runtime.

## 9. D: r4 built, promoted, and first real demo acceptance (2026-11-20)

- Full multi-repository build succeeded and was promoted to `D:\NiblitAIOS\releases\build-20261120-structured-demo-r4\niblit\niblit.exe`; frozen preflight passed **14 checks**, Core PID `7192` booted and `/market-desk/` returned HTTP 200 on port 5200. Previous release and historic data retained.
- r4 MT5 BTCUSDm demo scope `72b377343cbf4b88be2658cc7753f610`, expiry **20:51:00 SAST**; readback recorded one OPEN 0.01 lot order with broker-returned structural stop **59740.40** and target **57592.36**, reviewed entry **59024.39**, policy `crypto-atr-structure/1`, canonical plan hash `bb694b5eb31ce864ef61cd5d8c4241931fe7eedc9e707f0cad1046233b03dd3b`. This confirms the actual packaged structural-stop path, not just a fixture.
- r4 isolated Freqtrade CoreManaged dry-run scope `947d76034f9840ef9d6fb2d7a3fc3179`, expiry **20:50:29 SAST**. Native API on port 18081 returned OPEN `ETH/USDT:USDT` trade ID **1** with `enter_tag=niblit_core:j351Fci5diFz4n467V0PCZKtkjQ25Yg-` and `count.current=1`. Core `execution_result` was `submitted` with `trade_id=1`. Thus Core successfully delivered the trade and Freqtrade actually opened a dry-run position.
- An additional live readback defect was revealed: Freqtrade `/status` lists open trades but its `/trades?limit=100` returned no open records. The r4 adapter only searched `/trades` and incorrectly marked the broker-confirmed open trade as `unknown: No unique engine attribution`. **Do not retry** the existing order; the native trade exists. r4 still owns active sessions and is not modified in place.
- Source fix AFTER r4 build: `modules/trading_desk.py` exposes `Desk.attributed_trades()` combining `/status` active records and `/trades` historical records keyed by `trade_id`, verifying symbol/tag agreement; both `Desk.reconcile()` and `FreqtradeSessionAdapter.reconcile()` use that read-only merged view. Three new regressions cover split open/closed lifecycle, duplicate IDs and conflicting attribution. Focused regression suite (Core, packaged fixes, structured engine) passed completely after correcting test fixture `profit_abs` fields. **This source correction is not included in r4.**
- Both r4 sessions were last confirmed **active** (1 entry each), both observers running without current errors. There were no further live order actions during the source reconciliation correction.
- Next release: bundle the updated readback source into a separately identified r5 candidate, pass preflight, and only then promote/restart **after** active r4 sessions complete or with separately reviewed interruption. Afterwards verify Core's order state moves from submitted/unknown to broker-linked OPEN and then CLOSED on exact Freqtrade trade ID, and MT5 records actual net outcomes.

## 10. r5 release verification and funded-route contract groundwork

- Desktop Commander connection was restored. r5 build log confirmed successful completion, and the full bundle was promoted **without starting it** to `D:\NiblitAIOS\releases\build-20261120-structured-demo-r5\niblit\niblit.exe`. Frozen preflight passed **14/14**; the running Core remained r4 PID 7192 to preserve open demo positions.
- At broker snapshot, Exness MT5 Niblit magic `29102026` position ID `590264787` (sell BTCUSDm, 0.01 lot) had entry 59024.39, current 58347.16, stop 59740.40, target 57592.36 and **floating +6.77 USD** (not realized). Freqtrade CoreManaged isolated dry-run on `127.0.0.1:18081` had open ETH/USDT:USDT trade ID `1`, tag `niblit_core:j351Fci5diFz4n467V0PCZKtkjQ25Yg-`, floating +0.06895368 USDT.
- New `modules/execution_venue_router.py` creates pure, deterministic route descriptors for `mt5` demo/live and `freqtrade` dry-run/live. Each route records broker adapter, environment, exact account, broker/terminal or exchange/config identity, symbol, instrument, currency, strategy direction, feed identity, risk-profile version and canonical plan hash. A route is only descriptive (`execution_stage=ROUTE_DESCRIPTION`) and has no broker client or credential access. `route_difference` exposes exact account/environment changes.
- `tests/test_execution_venue_router.py` covers route reproducibility, binding distinction, Freqtrade identity, invalid venue/symbol choices and WAIT; focused combined router/structured-planner/execution repair tests: **45 passed**, no failures; `git diff --check` exit 0.
- **Funded order delivery is not deployed or enabled.** The single profitable MT5 position is useful operational evidence of demo transport, structural stops and ongoing management, but not a statistically sufficient track record. Applying a demo plan to a funded account must involve a fresh account-specific broker snapshot and valuation, separate cost schedule, margin and quantity rules, independently versioned risk policy, operator review of actual account authority, order-receipt attribution, reconciliation after failures and a full integration acceptance suite. None of these may silently inherit demo identity or demo simulation-assumed fees.
- Next: add broker-specific account adapters and a unified `MarketSnapshot → StrategyDecision → VenueRoute → RiskValuation → OrderIntent → BrokerReceipt → Reconciliation → Outcome` schema; validate multi-week out-of-sample paper trading, slippage/drawdown/exits/restarts, then separately assess whether any funded execution should ever be connected. Keep the removed demo latch absent; route validation and risk accounting are ordinary execution correctness, not an additional emergency latch.

## 11. Profitability versus signal validity; execution-route integration

- Review of actual r4 MT5 Core order `ec177151f3dcfb3486e5449deebbe060967929f3a9881b7c7b7f56670eaa56bb`: strategy `trend_v1` selected a BTCUSDm sell at 59024.39, completed M5 bar 1795196700; ATR 283.840454, structural anchor 59518.07, stop 59740.40, target 57592.36, gross modeled stop risk 7.16 USD versus budget about 24.997 USD. This supports functioning data-driven entry and broker-valued structural stops, not a proven statistical predictive edge.
- Later recorded completed-bar observations detected a bearish `breakout_v1`: close 58239.54 versus prior20 low 58589.99; RSI14 about 30.326, mean20 about 58980, mean50 about 59583. These are related technical features and **not independent proof** of future returns. Require multi-regime, out-of-sample testing with slippage, fees, funding, drawdown and baseline comparisons before any performance claim.
- Follow-on source integration: `modules/trading_session_adapters.py` now attaches an `execution_route` from `modules/execution_venue_router.py` to the existing hashed `structured_plan` for crypto MT5 trade preparation. It pins the exact observed MT5 server/terminal binding, account, demo environment, symbol, currency, completed M5 bar and risk-profile identifier, with route `source_plan_hash` equal to the calculation `record_hash`. Route stage remains `ROUTE_DESCRIPTION`; it does not create permission, an order or a funded transport.
- `tests/test_structured_trade_engine.py` verifies the nested route and immutable plan hash through actual fixture MT5 adapter preparation. Focused router/structured-plan/packaged-repair suite: **45 passed**, exit code 0. This change is **source only**, made after the r5 bundle was built; running r4 and staged r5 were not modified.

## 12. Owned-order early-reversal evaluator + measurable outcomes

- Added pure `modules/trade_performance_metrics.py`: calculates sampled executable-mark R, maximum favorable excursion (`mfe_r`), maximum adverse excursion (`mae_r`), peak retracement and post-close broker-net realized R. The values distinguish **sampled price-only** metrics from realized broker P&L; missed intrabar moves and fees remain explicit limitations.
- Extended existing `CoreTradingSessions._record_owned_positions` `position_watch` memory/audit events with the replayable performance record, based on saved original stop, executable bid/ask and previous observed extrema. No new trade authority or delivery path.
- Extended `CoreTradingSessions._reconcile` broker-verified `trading_outcome` with net realized R and the last observed MFE/MAE, linked to the original strategy and trading order.
- Added `position_exit_policy.assess_reversal`: deterministic v1 order evaluator for recorded Core-owned positions. It compares executable-price retained gross profit against original stop risk; requires peak excursion, meaningful retracement and at least two classes among counter-momentum across three completed M5 bars, opposite side of 20-bar mean, and RSI reversal from a prior extreme. Two-signal cases need confirmation on two **distinct completed bars**; three simultaneous signals may qualify immediately. Broker-reported floating profit must be positive when supplied. It never submits an order itself and makes no calibrated prediction claim.
- Wired `assess_reversal` into **the existing** `CoreTradingSessions.cycle` owned-position handling, alongside existing `assess_exit`, with `position_reversal_evaluation` telemetry. An early-reversal `close` recommendation flows to the original broker-specific adapter, atomic Core claim, normal native close order and reconciliation. No independent order sender, demo latch or additional disable flag is introduced.
- Tested short reversal detection, repeated-tick non-counting, stale quote/invalid thesis/nonprofit holds, gross and realized R measurement, actual fixture-Core early close delivery, and outcome persistence. Focused existing Core/exit-policy/performance suite and separate two end-to-end integration contract tests **passed**; only the existing Starlette test-client deprecation warning was reported.
- **Runtime deployment:** these changes were made after the r5 build and are **not installed into running r4 or staged r5**. Live r4 session entry windows had expired while actual MT5/Freqtrade demo positions were still open at previous checks. The evaluator can only submit an exit through a separately valid existing Core close authority; expiring an entry window must not be confused with broker-closed positions. Do not promote/restart the active executable while positions remain open unless specifically reviewing lifecycle impact.
- **Next:** build independently versioned r6 with these changes; replay against historical completed BTCUSDm/ETH/USDT:USDT data, compare v1 exit rules to broker protective levels on both venues, inspect false-positive exits, record net saved profit after fees/slippage, then run a fresh bounded demo with full stop-to-close reconciliation. Do not claim improved financial outcomes before observing them.

## 13. Multi-symbol observation and concurrent demo instruments (r7 source)

- Added `CoreTradingSessions.observe_many(adapter,symbols)` for one independent observer per unique exact symbol, up to 12 in a request, no order submission. Existing per-(adapter,symbol) workers remain authoritative.
- Added operator endpoint `POST /api/trading/sessions/observe-many`, with an explicit adapter and symbol list, and a watchlist field / button in `assets/trading-desk/index.html` and `sessions.js`. Current Core sessions and six-strategy observations are shown per symbol in the existing dashboard.
- Changed account session activation uniqueness to `(adapter,account,instrument)`, rather than just `(adapter,account)`, in `modules/permission_manager.py`; two different symbols on one verified demo account may now have simultaneous, independently scoped sessions. Same-instrument duplicates still use the existing worker/claim rather than overwriting it. Account-wide broker exposure, margin, open-position count and risk calculations remain unchanged.
- Added regression tests in `tests/test_core_trading_sessions.py` for independent multi-symbol observation without order submission and concurrently active distinct-instrument sessions on one account, plus duplicate instrument handling. Combined source suite: **143 passed**, JavaScript syntax, Python compileall and git diff integrity checks all passed.
- The isolated CoreManaged Freqtrade config had `max_open_trades=1` despite a six-pair whitelist. Backed it up to `config.json.before-multi-pair-20261120.bak` and staged `max_open_trades=3` in `D:\NiblitAIOS\data\trading-software-20261115\freqtrade\user_data\config.json`, preserving dry_run=True and strategy=NiblitCoreManaged. The running Freqtrade instance still reported 1 until it is restarted/reloaded; no existing position or container was interrupted by the config edit.
- The prior r6 build may not contain the changes because they were added during packaging. A fresh r7 full bundle (`build-20261120-multi-symbol-r7`) was started after code/tests were stable to package all new features together.
- Same-symbol multiple positions, and self-activating every watched market, are **not** claimed here. Broker/account netting-vs-hedging modes, per-position ownership/exit and native Freqtrade support must be verified separately before implementing same-symbol stacking. Multi-symbol observation is read-only and does not automatically create a new trading authority.

## 14. Final r7 packaging and native Freqtrade capacity acceptance

- The r6 `build-20261120-early-reversal-r6` candidate completed, but its PyInstaller analysis began before multi-symbol edits, so it is not the definitive test release.
- The fresh r7 `build-20261120-multi-symbol-r7` build started after source and UI stabilized. Full source acceptance: **143 passed**, JavaScript syntax passed, Python compileall passed and Git diff check exit 0. Includes early-reversal evaluation, observed excursion / realized R records, Freqtrade open-status reconciliation, venue route binding, multi-symbol watchlist API/UI and independent account/instrument demo scopes.
- Native Freqtrade CoreManaged dry-run trade #1 has now closed **realized +1.9779354 USDT** with its original `niblit_core:` entry tag. The isolated port-18081 controller had **no open positions** before restarting its named Docker container `niblit-coremanaged-demo`; original `freqtrade` container on port 8080 was not touched. After isolated restart, `/api/v1/show_config` verified `dry_run=True`, strategy `NiblitCoreManaged`, `max_open_trades=3`, `state=running`; the closed trade persisted in history.
- MT5 Core-owned position 590264787 was still open with broker SL 59740.40 and TP 57592.36 in latest independent verification. Do not treat an expired Core entry window as a broker-closed position. Before replacing Core, verify exact broker protection, any pending orders and both native ledgers, and preserve existing broker positions and records.
- UI watchlist accepts up to 12 exact symbols separated by comma or newline; each unique `(adapter,symbol)` worker observes independently. User starts/activates separate reviewed demo execution scopes per instrument. Same-symbol stacking and autonomous blanket scope minting are not part of this release.
