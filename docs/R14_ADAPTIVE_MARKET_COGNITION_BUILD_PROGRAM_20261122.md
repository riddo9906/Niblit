# Niblit R14 — Adaptive Market Cognition Program

**Status:** Source implementation in progress; existing frozen R14 demo executable remains unchanged.
**Baseline repository:** `C:\Users\Riyaad\Documents\GitHub\Niblit`
**Branch / HEAD audited:** `fix/exness-demo-readiness-20261118` / `301571f0`
**Frozen runtime:** `D:\NiblitAIOS\releases\candidates\build-20261121-r14-mobile-integrated\niblit\niblit.exe`
**Constraint:** Preserve all existing unrelated working-tree modifications (141 paths observed at kickoff). Never reset, clean, stash, force-push, override another agent's file, or change demo account permissions without validated handover. No funded trading.
**Execution goal:** Gradually enable measurable, explainable, broker-reconciled, regime-adaptive demo decisions; no profitability guarantees.

## Verified R14 reality (code + returned events)

- `CoreTradingSessions.cycle()` invokes `strategy_manager.assess_with_context` on the broker M5 snapshot. Registered strategy candidates and `market_thesis` are persisted in `signal`.
- `strategy_manager.assess()` uses deterministic rule eligibility and registry priority (specific agreeing breakout wins); conflicting directions abstain. This is not learned regime-specific profitability ranking.
- Core-owned positions are monitored and assessed by `position_exit_policy.assess_exit` and `assess_reversal`. Exit paths require the canonical permissioned session and broker reconciliation. Existing/manual/older-core positions are not silently adopted.
- Reconciled `trading_outcome` uses broker-reported realized net and stored entry strategy. Observed peak/adverse R are sampled, not actual intra-bar extrema.
- At kickoff R14's latest 100-event window showed 55 signal events, 3 position reversal evaluations, 2 realized broker outcomes (+0.60 breakout and -0.56 EMA pullback), and entries / exits. These prove use and basic attribution, not statistical edge or online learning.
- Separate `trading_brain`, `adaptive_market_cognition`, `rl_trading_policy`, `strategy_research`, `market_prediction`, `trading_study`, and Qdrant modules exist. No verified causal path promoting their outcome-based recommendations into Core's deterministic strategy selection.
- The running source tree has numerous user/agent worktree edits. Do not merge these as one anonymous commit.

## Task 01 — Decision Evidence Contract (Assistant + Desktop Commander)
**Files owned:** `modules/market_decision_trace.py`, `tests/test_market_decision_trace.py`. Narrow integration exclusively in `modules/core_trading_sessions.py`.
- Build deterministic versioned trace ID from market-thesis evidence + full strategy vote list + scoped account/venue/bar + selected rule/policy.
- Embed trace on `signal`, original `trading_orders.payload.decision`, and `trading_outcome.decision_attribution`. Historical orders without IDs stay clearly labeled legacy.
- Mark hypothetical outcomes null; never call them broker-verified. Trace has `broker_execution_authorized=false` and `learning_action=record_only`.
- Test stability, account isolation, all votes preserved, legacy reconciliation, no ticket submission. Keep Core execution unchanged.
**Gate:** Unit tests + Core trading session regression pass. Frozen execution is not modified before release packaging.

## Task 02 — Broker-verified position lifecycle (Codex; execute after Task 01 gate)
**Files owned:** `modules/position_cognition_record.py` (new), `tests/test_position_cognition_record.py` (new), plus a narrowly reviewed Core integration patch.
- Persistent position identity = venue + account + broker position identifier + Core-owned entry order ID; support concurrent positions and partial fills.
- Snapshot entry thesis, stop/target, expected horizon, setup evidence hash, strategy and trade-cost assumption; link every sampled MFE/MAE mark and broker modification to exact ticket/time.
- On reconciliation, resolve realized account-currency P&L incl. supported commission/swap/fill costs from native MT5 deals; do not infer missing fees.
- Explicit states: proposed, sent, open, partially closed, closed, uncertain; non-owned tickets remain observe-only.
- Record thesis invalidation separately from positive-profit reversal; keep exit authority tied to exact Core-owned scope. Do not silently auto-adopt historical BTC tickets.
**Gate:** Replay event log from synthetic broker doubles, crash/restart idempotence, account isolation, partial-close accounting, no duplicate close.

## Task 03 — Regime & pattern perception (Freebuff, isolated research only)
**Files owned:** `modules/market_regime_evidence.py` (new), `tests/test_market_regime_evidence.py` (new), research notes under `docs/research/`. No edits to Core/session/MT5 files.
- Read broker-aligned completed M5/M15/H1/H4 candles, ATR/ADX/EMA slope/RSI/Bollinger width, range structure and cost/spread features.
- Return schema-versioned hypothesis with raw feature evidence, freshness and competing regime probabilities *only when calibrated*. Prefer uncalibrated labels plus uncertainty until calibrated.
- Add regime transitions, false-breakout markers, trend-strength deterioration, cross-timeframe alignment. Numeric indicators must be independently unit tested on fixed known series.
- Never use a bar that had not closed at the event timestamp. No Qdrant similarity treated as directional truth.
**Gate:** Deterministic point-in-time tests, missing bars and spread spikes handled, no network in tests, no execution authority.

## Task 04 — Counterfactual strategy lab (Codex after Task 02; separate owner from Task 03)
**Files owned:** `modules/market_counterfactual_lab.py`, `tests/test_market_counterfactual_lab.py`, dedicated migration file if required.
- At each recorded decision, record every eligible alternative including WAIT/no-entry and exit-vs-hold.
- Replay alternatives against subsequent broker-grade bid/ask, commission, swap, market calendar, lot limits, max risk/margin, and plausible slippage.
- Strict partition between actual fills and hypothetical fills. Store outcomes and opportunity costs with confidence/coverage and lookahead-free evaluation.
- Include counterfactual exit trajectories: closed early vs holding to SL/TP/horizon, not claiming actual executable fills at unknown bid/ask.
**Gate:** leakage tests, same-timestamp tie handling, bootstrap on data gaps, out-of-sample baseline comparison.

## Task 05 — Adaptive selection registry (Freebuff analysis; Codex integration only after performance evidence)
- Score per account/symbol/timeframe/regime: realized net R, expectancy, fees, adverse excursion, drawdown, calibration, sample count, missing outcomes.
- Walk-forward with embargo, transaction cost sensitivity, uncertainty bounds and regime drift.
- Adaptive selection operates *shadow only* until performance gate passes a benchmark and reviewer approves a versioned candidate.
- Promotion replaces only the selector behind a versioned switch; immutable before/after replay and immediate rollback to known-good selector. No spontaneous self-editing rules in production.

## Task 06 — Multi-horizon planner & adaptive exit controller
- H4/D1 anchor bias and thesis versus M5/M15 tactical decisions; anchor is context, never an obligation to enter.
- Netting versus hedging accounts: detect actual MT5 account mode before combining legs, enforce account-wide risk and correlation limits, count all broker positions including manual ones.
- Build exit decision comparison (hold, close, partial close, tighten protective levels where broker-supported) with net executable costs and confidence; prioritize attribution/reconciliation.
- Clarify scope of position-management authority after entry session expiry; preserve protected broker SL/TP and require explicit continuing-position management scope.

## Task 07 — Market Desk + Android evidence dashboard
- Add trace viewer, original versus current thesis, regime transition, decision alternatives, selected policy version, predicted vs actual outcome and cost-aware baseline.
- API must return authenticated, bounded, redacted records; preserve original broker history and existing Android portal approvals.
- Show when cognition is observe-only, shadow, approved demo execution, and broker reconciled.

## Team workflow and daily Freebuff/Codex budget

1. **Desktop Commander (Assistant):** freeze baseline evidence, own Core integration and hard acceptance, inspect status/diffs before each edit. Use the main source tree only for reviewed, small integration points.
2. **Codex:** implementation of one numbered task at a time, owning exact file set; inspect `git status --short`, HEAD and diff before editing; never reset/clean/stash/commit without review. Deliver implementation, tests, migration notes, and file-by-file diff.
3. **Freebuff (5-hour daily budget):** prioritize isolated research, offline indicator calculations, replay test fixtures and invariants. Never touch the same source file that Codex is editing. Reserve budget for evidence/bugs, not speculative autonomous rewrites.
4. **GitHub:** coordinate through a feature branch/PR for each accepted component. Do not push the current 141-path dirty tree as one unreviewed commit; use a clean reviewed worktree or targeted path commits after file provenance is established.
5. **Verification:** run targeted tests, deterministic replay, offline broker-double self-tests and frozen preflight; only then stage a separately versioned release under `D:\NiblitAIOS\releases\candidates`. Do not overwrite currently running R14 or modify its open broker position.
6. **Operator trial:** shadow-evaluate while existing execution stays stable, then explicitly approve a bounded demo-only trial; compare against frozen original R14 on identical evidence, not against a cherry-picked profit.

## Operator questions answered by this program

- Which strategy decided? `decision_trace.selected_strategy` and `strategy_votes`.
- Why that strategy? Original evidence hash, rule version, completed bar, competing candidates and disagreement reason.
- Did reversal logic run? `position_reversal_evaluation` and persisted position-level exit report.
- Did it actually close? Core close claim + confirmed MT5 broker deal + reconciled net P&L.
- Did Niblit learn? Show that an outcome changes later *shadow* ranking and survives a forward replay; absent this evidence, learning remains unverified.
- Would another strategy have done better? Compare fully costed, point-in-time hypothetical trajectories with the actual trade; never label a simulated fill as real.

## Immediate acceptance command

```powershell
Set-Location 'C:\Users\Riyaad\Documents\GitHub\Niblit'
& '.\niblit-env\Scripts\python.exe' -m pytest tests/test_market_decision_trace.py tests/test_market_thesis.py tests/test_core_trading_sessions.py -q
```

**No execution or investment claim is proven merely by implementing code.**
