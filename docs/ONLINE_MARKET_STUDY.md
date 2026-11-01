# Current-moment study and bounded prediction manager

`modules/online_market_study.py` adds a persistent numeric feedback loop to the
existing MT5 demo observer and Freqtrade read-only researcher. It makes no LLM
requests and has no broker, shell, external posting or configuration-write tools.

## The feedback loop

1. Accept a fresh, contiguous, completed M5 observation from the existing feed.
2. Compare new closes with forecasts saved on earlier observations. Only score
   targets whose candles have since completed. Save each score once.
3. Summarize error, zero-return baseline, empirical interval coverage, simple
   rising/falling/flat patterns and a recent-error deterioration indicator.
4. Issue the next forecast and all four shadow forecasts, with the input hash,
   parameter choice and rationale. Saved predictions are never rewritten.

Scopes separate venue, account or exchange, instrument, mode and timeframe.
MT5 uses the supplied broker quote clock; this does not certify that clock as UTC.
Stale, unfinished, missing or unordered observations cannot issue forecasts.

## What can adapt

The approved menu is zero change, mean of five recent returns, mean of twenty
recent returns, and reversal of the five-return mean. All are evaluated in shadow.
After forty settled forecasts, select using the older 70 percent of at most one
hundred observations. Require over ten percent lower error than zero change on
the later suffix before selecting that predictor for subsequent **research**
forecasts. Otherwise retain the zero baseline. This does not select a trading
strategy, change stops, increase size, alter leverage or grant execution access.

Residual bands use only earlier settled errors. Before twenty residuals exist,
the band is explicitly an uncalibrated volatility proxy. Coverage is measured,
not assumed. Monitoring reuses observations and is not independent final
validation. No profit is established by lower return-prediction error.

## Decision support and resource budget

The outcome/decision-support surface currently returns observe or abstain. It
acts on the system's research choices, not other participants or market prices.
Order decisions still belong to the existing explicitly authorized demo/runtime
and retain their original risk gates. There is no automatic strategy promotion.

One nonblocking process gate serves both integrations. Busy work is rejected
without a queue. Each update is bounded to 500 incoming candles, 500 older
forecasts and 100 settled scores. There are no added background workers, model
downloads, optimizer swarms or paid inference. SQLite stores the ledger beside
the existing private trading data.

## Verification

Tests cover immutable issuance, later-only scoring, environment separation,
sequential adaptation, training-prefix selection, stale/gap/non-finite rejection,
busy rejection and integration with existing demo/read-only researchers.

Relevant official documentation checked 2026-10-30:
- https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html
- https://www.freqtrade.io/en/stable/lookahead-analysis/

Next validation stages include untouched forward periods, data revision audits,
full fee/fill/slippage simulation, richer regime evaluation and independent
calibration. These are prerequisites for considering execution integration.
