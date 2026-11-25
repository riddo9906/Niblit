# Freebuff handoff — R14 Task 03: Point-in-Time Regime & Pattern Evidence

Read `docs/R14_ADAPTIVE_MARKET_COGNITION_BUILD_PROGRAM_20261122.md` and https://github.com/riddo9906/Niblit/issues/422.

Repo: `C:\Users\Riyaad\Documents\GitHub\Niblit`; baseline HEAD `301571f0`, branch `fix/exness-demo-readiness-20261118`. ~141 existing changed paths. Inspect HEAD/status/diff before edits; never reset, clean, stash, commit, push or overwrite another agent's edits.

**Your exclusive files:** new `modules/market_regime_evidence.py`, new `tests/test_market_regime_evidence.py`, new `docs/R14_TASK03_REGIME_EVIDENCE.md`. Do not modify `core_trading_sessions.py`, MT5/order controllers, strategy selector, tracing, or position-cognition files owned by Codex.

Build a deterministic observation-only `market-regime-evidence/1` engine using explicit timestamped, CLOSED M5/M15/H1/H4 broker candle inputs plus optionally fresh executable quote/spread. Extract ATR, ADX and directional movement, EMA alignment/slope, RSI, Bollinger width, range structure, realized volatility, spread/ATR and missing-data flags. Label trend_up/down, range, compression, breakout_candidate, unstable or uncertain with cited numeric features and regime transitions. No invented probabilities, no broker execution, no autonomous parameter edits, no network requirements.

Strict point-in-time safeguards: reject future/unclosed higher-timeframe bars; tests for gaps, malformed OHLC, constant-series indicators, stale quotes, timeframe alignment, spread spikes, lookahead and missing candles. Run pytest, document results and limitations, then stop at review gate. Use the 5-hour daily allowance on this self-contained component and objective replay evidence—not speculative multi-file rewrites.
