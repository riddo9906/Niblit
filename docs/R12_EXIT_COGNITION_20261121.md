# R12 source exit-cognition hardening — 2026-11-21

## Scope
Preserved the running r12 demo executable, the open broker BTCUSDm position, MT5 protective levels, the r11 rollback, and concurrent Freebuff Task 05 work. Source-only edits in `modules/position_exit_policy.py` and tests; created a standalone read-only advisory for active MT5 positions. No Core or broker restart, and no order API was called.

## Fixes
1. `assess_reversal` now requires the newest completed M5 candle to be contemporaneous with its quote (within the following 600 seconds under the broker timestamp contract); rejects missing, future, and stale quote/candle pairs.
2. Its two-bar confirmation must advance by exactly one M5 interval (300 seconds). Skipping one or more bars no longer counts as consecutive confirmation.
3. The independent `scripts/mt5_active_exit_advisory.py` attaches to an existing demo terminal, retrieves native completed M5 bars and executable bid/ask, and evaluates copies of Core's saved entry thesis through `assess_exit` and `assess_reversal`. Only exact matching Core order ticket/symbol and one unique context qualify; no order-send, position edits, stop adjustments, or persistence.
4. Tests include temporal evidence, skipped bars, duplicate calls, live-account observation-only boundary, missing entry context, and unique Core receipt selection.

## Tests
- `pytest tests/test_position_exit_policy.py`: 9 passed.
- `pytest tests/test_mt5_active_exit_advisory.py tests/test_position_exit_policy.py`: 12 passed, exit 0.
- Broader Core session / demo control / Freebuff cognition regression suite: see separately recorded terminal result; do not claim completion without process exit verification.

## Broker-sourced read-only snapshot
- `python scripts/mt5_active_exit_advisory.py --symbol BTCUSDm` against the active local Core and MT5 demo terminal returned exit 0.
- Broker ticket `591704289`, matched to one saved Core `breakout_v1` entry thesis.
- Fresh native quote; both policies recommended HOLD at observation time, with `orders_submitted=0`, `execution_authorized=false`.
- The exit policy reported gross current_R around -0.097 and peak_R around 0.336. The reversal policy declined a profitable reversal because the native broker's floating result was not positive. These are time-varying observations, not realized P&L.
- This proves source-level read-only evaluation against native evidence. It does not certify broker order delivery, executable profitability, or a newly packaged release.

## Independent Freebuff Task 05 integration concern
The corrected reflections are longer and `_calculate_dqi` still uses `min(1, len(reflection.split()) / 40)` as the reflection-quality component. That means output verbosity can raise DQI without better evidence. The source-level DQI fix must replace the word-count proxy with a semantic/evidence-completeness criterion and version the policy; do not rescore historical memories silently. This is separate from exit policy and was not edited here.

## Deployment status and limitations
Current running frozen r12 predates these source changes; it has NOT been rebuilt or restarted with the new exit evaluator. Live-account execution remains disabled. Additional broker reconciliation, fees/slippage accounting, live lifecycle verification and r12 acceptance blockers remain outstanding.

## Broader regression result (completed)
The broader command `python -m pytest tests/test_core_trading_sessions.py tests/test_demo_controls.py tests/test_adaptive_market_cognition_evidence.py tests/test_adaptive_market_cognition_quality.py -q --basetemp=.pytest-exit-cognition-integration-r12` completed at 100%, **exit 0**, runtime 270.37 seconds. Warnings were Starlette/httpx deprecation and two SWIG import deprecations. No failed tests. The terminal output did not include a numerical test summary, so no unverified count is claimed.

## 2026-11-21 later integration continuation
- Enforced a measured, finite positive native broker floating-profit observation for the profitable-reversal branch. Previously `observed_profit=None` allowed the evaluator to proceed; now missing, zero, negative, boolean, non-numeric, NaN or infinite values return HOLD. No broker order path was changed.
- Added regression `test_reversal_requires_measured_positive_broker_profit`. Exit/advisory/governed-memory targeted suite: 16 passed, exit 0.
- Freebuff's in-progress DQI policy changed from `evidence-aware-v1` to `evidence-aware-v2`. Adjusted legacy governance/evidence test labels to the explicit v2 policy while retaining checks that low DQI must not suppress otherwise admissible memory recall.
- The old quality-test formula computed the DQI reasoning term from reflection word count, which is obsolete under v2. Updated the test helper to use the auditable recorded `dqi_components.terms.reasoning`, leaving the independently supplied risk term to be verified against the documented weights.
- A scoped *plan only* for the separate `build-20261121-r13-exit-dqi` candidate was inspected; the build was not started while Freebuff Task 06 remains unfinalized. Previous released r11/r12 executable directories and active demo position remain untouched.
