# Predictive strategy research — 2026-10-30

## Scope and sources

The host Market Desk now compares six explicit rule families: simple-mean trend
and momentum, prior-range breakout, Cutler RSI recovery in a flat regime,
Bollinger-band recovery, EMA pullback recross, and contraction-to-breakout.
All record their conditions, measured indicators, hypothesis, invalidation and
documentation provenance. Pinned choices remain available alongside the manager.

These are Niblit implementations of documented strategy families, not a claim
that there is one universal latest strategy list or access to traders' private
systems. Exact parameters and the policy that chooses between them are experimental.

- https://www.quantconnect.com/docs/v2/writing-algorithms/strategy-library
- https://www.freqtrade.io/en/stable/freqai/
- https://www.freqtrade.io/en/stable/lookahead-analysis/

## Prediction

`modules/strategy_research.py` is an independent numeric research engine, with
no order, shell, generated-code execution or paid model capability. It estimates
the next completed M5 close return using 15 nearest historical feature states.
Features describe recent returns, momentum, deviation and volatility. Scaling is
fitted only to the available training states at each prediction time.

At least 140 contiguous completed M5 bars are required. Validation uses an expanding
walk-forward sequence and reports prediction error versus a zero-return baseline,
direction accuracy, sample counts and an audit trace. Neighbor return percentiles
are descriptive, not calibrated confidence intervals or guaranteed price ranges.
Fresh forecasts are saved immutably; only a later completed target candle creates
their realized-return/error record. These scores are not trade P&L.

The recent 200-bar input is a small, regime-specific exploratory sample, not broad
independent profitability validation. History gaps stop research. MT5 broker bar
timestamps retain their unverified broker clock; local availability is stored separately.

## Candidate creation while waiting

When all entry conditions wait, the research engine composes eight structured
experiments from momentum/reversion families, 10/20-bar lookbacks and 0.75/1.5
deviation thresholds. Every candidate explains why/how it was constructed. There
is no arbitrary generated Python or automatic addition to execution's strategy list.

Training uses the first 70% prefix, purges the label crossing the split boundary,
and ranks candidates only on that training prefix, requiring 20 training trades.
The following holdout is reported separately. All trials are disclosed. These are
one-bar close-to-close decision studies, not broker SL/TP execution simulations.
Multiple comparisons and repeated research can still overfit; independent periods,
realistic fill/cost models and robustness tests remain required before promotion.
Every generated candidate has `execution_eligible=false`.

The cost proxy includes assumed round-trip slippage of 0.0001 return units.
MT5 adds the currently observed spread, not historical spreads. Commission is
unknown. Freqtrade research currently omits spread as well as commissions and
discloses that limitation. Positive proxy results do not establish a trading edge.

## Freqtrade parity

Select a Freqtrade pair and use **Refresh Freqtrade research**. This reads its
completed analyzed exchange candles and applies the same strategy and research
code. While that environment is visible, the view refreshes every 30 seconds.
Reports and later forecast scores have a separate durable SQLite journal with
venue/pair/mode identity. Live environments remain research-only.

`deploy/freqtrade-lab/NiblitLabManager.py` stages seven native classes: the manager
and six pinned variants. Run `scripts/install-freqtrade-lab.py` after shared-kernel
updates to copy the same rules into sibling Freqtrade's strategy directory.
The native adapter uses only prefixes during historical calculations and records
the selected entry rule in each trade tag. An open trade's tagged rule owns its
signal exit. Broker/native SL and ROI remain active independently.

The staged catalog refuses funded entries, fixes leverage at one, and estimates
stake from a 0.25% equity budget with a 1% stop plus 0.2% cost reserve, 10% notional
cap and absolute stake cap of 100. An override loosening the stop beyond 1% blocks
entry. Broker minima can force a skip. These are sampled/estimated limits, not
guaranteed loss bounds; the native catalog does not implement the host desk's
timed session or its opportunity-approval lifecycle.

After the user closed the sample trades, the API confirmed zero open positions.
Freqtrade now loads NiblitLabManager in stopped dry-run mode, with the expected
1% stop and M5 timeframe. Compose and private startup configuration both select
the manager; restart stays stopped. No new trading start was sent. Native import/funded-block/prefix checks passed inside its actual
container; exchange-history backtesting and Freqtrade lookahead/recursive tools
remain separate acceptance steps. FreqAI itself was not installed or enabled by
this work; the current forecast implementation is the inspectable local baseline.

## Storage and UI

MT5 reports/scores live in `runtime/trading-desk/demo-learning.sqlite3` and
Freqtrade research in `runtime/trading-desk/freqtrade-research.sqlite3`. They are
private host journals. Research reports do not silently train model weights,
publish private memory or promote themselves into an order-capable strategy.
Signup was left unchanged at the user's request.
