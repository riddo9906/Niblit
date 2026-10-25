# Working trading architecture completion plan

25 October 2026. Budget baseline: Codex account usage 26% of the reported weekly
window. Check usage after each milestone; stop at 45%, leaving a buffer below the
user's 50% ceiling. No cosmetic work or repeated full builds between milestones.
Account usage is shared, so other active work can also consume that budget.

## Product target

Niblit should target **$100/month net after fees** from AI-assisted trading.
This is a performance target, not a promised return or a software acceptance
test. Report capital, fees, realized/unrealized PnL, drawdown and historical/paper
period. Do not claim the target achieved from one simulated order or an overfit
backtest. Live orders are outside this completion run.

## Architecture that must actually operate

Local historical market data -> Freqtrade strategy/advisory signal -> Core-owned
decision contract and policy -> trading-runtime validation/risk/idempotency ->
paper execution and durable accounting -> reconciliation -> Core API -> desktop.
Cloud supplies local model inference/advice; it does not own execution authority.
The trading runtime remains the single authority for fills and portfolio state.
Offline replay must identify historical data and its replay clock explicitly.

## Confirmed gaps

- `Niblit/modules/trading_runtime_client.py` is read-only; packaged Core cannot
  submit a decision or reconcile a paper account through that bridge.
- `niblit-ui/src/pages/TradingPage.tsx` only reports status.
- `niblit-lean-algos/adapters/paper/adapter.py` records filled positions but does
  not debit/reserve capital, and its saved state omits positions and prices.
- `niblit-lean-algos/services/execution_coordinator.py` labels persisted requests
  `freqtrade` even for paper execution; filled results are stored as submitted.
- A local Freqtrade checkout and historical Binance candle files exist, but its
  Python environment lacks the strategy/data dependencies. Presence is not proof
  of an operational strategy layer.
- Desktop production builds must override the UI developer URL on port 8080
  with Core's port 5000. The source build script now enforces that boundary.

## Milestones and pass/fail gates

1. **Paper execution authority (checkpoint <=30%).** Fix real cash/reserved
   capital, positions, fees, PnL, fill state and atomic persistence. Bind paper
   fills to validated quote prices. Deny insufficient cash, invalid prices,
   duplicate decision IDs and observe-mode execution. Prove buy, mark, close and
   restart with actual backend objects and persisted records.
2. **Core-to-runtime execution contract (<=34%).** Add operator-only paper
   session/decision endpoints through the existing HTTP boundary. Require the
   actual selected backend to be paper; preserve live/Freqtrade safety gates.
   Expose authoritative balances, positions, executions and reconciliation.
   Prove a Core API request changes runtime accounting and survives restart.
3. **Actual strategy and data layer (<=39%).** Use the local Freqtrade checkout,
   its real strategy code and existing historical candles. Add an explicit
   offline replay path and persist its cursor/provenance. Feed resulting intents
   into the same Core/risk/execution pipeline; exercise local model advice with
   validated output where enabled. Prove strategy-produced entry/exit, denied
   intent, fees/PnL and repeatable replay. No invented live quotes or fills.
4. **Operator controls (<=42%).** Connect the Trading tab to those same working
   endpoints: paper activation/pause, decision validation/submission, portfolio,
   fills and history. Actions reflect backend outcomes. UI is a client, not a
   separate trading engine. Keep original commands and Core connection fixes.
5. **One final package and acceptance (<=45%).** Freeze source after focused
   tests. Build into a fresh folder; repackage components only when verification
   finds a defect. Test the packaged HTTP boundaries,
   real simulated orders, duplicate protection, restart recovery, strategy/data
   integration and correct desktop URL. Save a machine-readable result and exact
   launcher. Keep the running older desktop and existing data intact.

## Completion evidence

Completion requires backend execution records, cash/position conservation,
recovered positions after restart, actual strategy provenance and a passing
packaged execution test. Health badges and screenshots alone do not satisfy it.
The paper evaluation report must state whether the $100/month target has been
measured; if the evaluation period/capital is insufficient, report that plainly.

## Execution record

**Completed for historical paper testing at 39% account usage.** All five software
milestones are implemented and verified. The $100/month performance goal remains
unmet and unvalidated.

Bundle: `dist/testing-20261025-final/niblit`. Close the previous Niblit app and run
`Start-Niblit-Testing.cmd`. The previous build and user data were preserved.

Core, Cloud, Lean and the owned Freqtrade strategy worker run as separate packaged
services. Source and frozen Core use the same HTTP boundary. The native frontend
defaults to port 5000. Trading provides activation/pause, manual entry/close,
dataset/strategy selection, local AI approval, replay steps and authoritative
balances, positions and fills. The ledger, execution IDs, activation and pending
replay step survive restart.

Validation: **99 focused tests** (29 accounting/runtime, three actual Freqtrade
replay/recovery, 17 Core gateway/startup/configuration, 50 UI) and **37 acceptance
checks** against the final package:

- `PAPER_ACCEPTANCE_REPORT.json`: 14 checks, 520 recorded candles, 11 strategy
  fills, five closed strategy trades and one open position; actual local AI vote,
  cash/fees, initial fee-inclusive PnL, duplicate protection, restart recovery,
  conservation and paused-order denial.
- `DESKTOP_ACCEPTANCE_REPORT.json`: 16 checks, including every desktop section,
  architecture connections, Windows CORS, original commands, file rendering and
  source-grounded chat.
- `UI_ACCEPTANCE_REPORT.json`: seven checks after actual UI actions. ETH advanced
  two candles with a stored boolean approval from local Qwen, the position was
  closed, orders paused and cash reconciled. There were 16 total fills after the
  additional UI tests. The saved screenshot shows the connected final interface.
- `BUILD_INFO.json`: hashes for all five executables.

Verification found and fixed missing TA-Lib packaging, transient Windows file
locks, per-request connection churn, initial position fee display and truncated
model explanations. Replay/runtime HTTP connections are reused. Only safe reads
and the durable pending/ack handshake retry transport errors; ambiguous order
submissions do not automatically repeat. AI output is a strict boolean vote;
malformed output remains blocked.

Final baseline evaluation: 10,000 initial USDT, 100-USDT stakes, -1.958421 USDT
realized PnL, 10,001.325287 USDT ending equity including the open position,
1.299241 USDT fees and 0.063246% maximum observed drawdown. It includes the manual
round-trip acceptance test. Subsequent UI close/ETH tests finished with all
positions closed, 0.597103 USDT realized profit and 1.602199 USDT fees. Neither
result establishes a monthly return.

This is an unleveraged long-only historical signal/replay profile. It does not
certify live exchange execution, Freqtrade's full ROI/intrabar stop engine, every
optional AIOS component, or a profitable trading strategy. Forward paper
evaluation and strategy qualification remain necessary for the income target.
