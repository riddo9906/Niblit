# r10 Market Cognition — Runtime Acceptance Audit (2026-11-21)

## Outcome
**Candidate validated offline and with read-only native market evidence; NOT cleared for broker-connected runtime promotion.** The running r7 Core and all broker positions were left unchanged. No market orders, exits, or account modifications were submitted by this audit.

Candidate executable: `D:\NiblitAIOS\releases\candidates\build-20261121-r10-market-cognition\niblit\niblit.exe`.
Candidate build successfully bundled Core, Tauri UI, local Cloud, Lean Algos and Freqtrade. Frozen preflight returned exit 0 with 14/14 bundle checks and 18/18 import checks. The frozen module list contains `modules.market_thesis`. The prior 165-test cognition/trading regression run returned exit 0.

## Read-only broker assessment
- r7 Market Desk: HTTP 200 at `http://127.0.0.1:5200/market-desk/`; r7 Core remained the executable owning port 5200.
- r7 observer state: six healthy MT5/Freqtrade BTC/ETH/SOL observers; old EURUSD observer reports an unavailable visible symbol.
- Core sessions: 0 active, despite an MT5 BTCUSDm Core ledger entry still marked `open`. A separate historical MT5 EURUSD order remains `unknown` with the reason "Original ticket unavailable." The status API explicitly reports broker reconciliation required.
- Independent native MT5 bridge: connected to a **demo** account, one open BTCUSDm position, 0.01 lot, broker position ticket **591103520**, which matches the ledger's open-order `position_id`. The observed floating P&L was **-8.63 USD at the check**; it is not a realized outcome and will vary. Broker-side stop-loss and take-profit were present. **A closed/expired Core entry scope must not be inferred to provide active autonomous exit management.**
- Native Freqtrade API at loopback 18081: `dry_run=true`, strategy `NiblitCoreManaged`, `state=running`, zero native open trades. Native performance endpoint reports one closed trade at **+1.9779354 USDT** realized and one win. This is insufficient to assess long-run edge.
- MT5 read-only 15-day history filtered for magic `29102026` returned 13 deals across 8 position identifiers, with several entry-only identifiers. Only identified closed deal pairs with full matching entry/exit evidence may be treated as realized outcomes; the magic number does not reliably map all positions to release r7. Do not sum mixed USD/USDT P&L or infer any r10 performance from this history.

## Read-only cognition validation
- Independently pulled 200 native completed BTCUSDm M5 candles and higher-timeframe context via `MT5Bridge.snapshot(..., include_context=True)`. No order APIs called.
- `assess_with_context` evaluated six strategies: all WAIT; assessment complete; market thesis `no_qualifying_setup` and execution_authorized=false.
- `assess_observation` replay on the same broker-sourced completed bars produced **HOLD**, `regime=range`, market thesis `no_qualifying_setup`, six abstaining strategies, deterministic evidence ID and provenance bound to BTCUSDm/MT5, analysis_only=true, execution_authorized=false.
- Running r7 BTCUSDm observer, same latest candle timestamp, also reported WAIT with complete assessment but **no market_thesis field**. The r10 source-level replay shows a richer explanation, **not a superior entry decision**.
- This validates read-only source cognition and broker data compatibility. It does **not** constitute proof that the frozen r10 Core can run through full broker lifecycle without a controlled switchover.

## Deployment decision and next acceptance gates
1. Reconcile the broker position **591103520** and the EURUSD unknown-order claim against terminal-native deals/orders; preserve broker tickets, native stops and existing result history. Do not misinterpret zero active Core scopes as zero broker positions.
2. Ensure no broker position depends on an old r7 worker before controlled shutdown. Confirm ownership/exit management and journal consistency.
3. Run one Core instance only: stop r7 normally, then start r10 from its versioned bundle with the existing approved demo profile. Check market UI, all six observers, native MT5 and isolated Freqtrade status, and that the thesis is delivered in runtime observation/market-memory output.
4. Reconcile all original orders after restart and confirm no unexpected submissions or duplicate tickets. Confirm service/portal/mobile routing if moved.
5. Run r10 in demo long enough to collect broker-confirmed sample outcomes. Compare per-trade net P&L, realized R, drawdown, win/loss distribution, fill error, and matching market regimes/timeframes with r7. **No head-to-head r7/r10 profitability comparison is possible yet**, because r10 has no broker executions.

Audit scripts/logs: `D:\NiblitAIOS\diagnostics\android-frontend-20261121\r10-freqtrade-readonly-audit.py`, `r10-frozen-preflight.json`, `r9-cognition-release-tests.log`.

**No production/real-money deployment authorized or implied.**
