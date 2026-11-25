# Niblit r7 — multi-symbol deterministic demo testing

Release: `D:\NiblitAIOS\releases\build-20261120-multi-symbol-r7\niblit\niblit.exe`
Local Market Desk: http://127.0.0.1:5200/market-desk/
Isolated CoreManaged Freqtrade: http://127.0.0.1:18081/
Historical LabManager Freqtrade: http://127.0.0.1:8080/ (not part of CoreManaged trades)

## Deployment acceptance
- Built from stable source after 143 focused tests passed (no test failures); JavaScript syntax, Python compileall and git diff checks passed.
- Full desktop/UI, local Cloud, Lean Algos, Freqtrade worker and Core packaged into a new D: release.
- Frozen r7 preflight: 14 checks passed; released bundle verified Market Desk HTTP 200, watchlist element present, operator Core session API available.
- r7 Core PID 18368 (at time of deployment), executable matches the versioned release path.
- New POST `/api/trading/sessions/observe-many` accepted three MT5 symbols and three Freqtrade pairs with `execution_started=false`. All six observer workers were later confirmed running with empty error fields.
- Existing r4 broker positions and ledgers were left intact. After observing and reconciling, both original orders were confirmed CLOSED: MT5 realized +3.75 USD; Freqtrade native CoreManaged trade #1 realized +1.9779354 USDT. There were no new automated entry scopes activated by the r7 validation.

## Test 1: Watch multiple markets
1. Refresh http://127.0.0.1:5200/market-desk/ (Ctrl+F5).
2. For MT5, choose `MT5 desktop · demo connection`. In `Multi-symbol watchlist`, enter `BTCUSDm, ETHUSDm, SOLUSDm`. Click `Observe watchlist symbols`.
3. In the Core observer list, confirm three independent running MT5 workers and check each of the six strategy votes.
4. Switch environment to Freqtrade, enter `BTC/USDT:USDT, ETH/USDT:USDT, SOL/USDT:USDT` and click `Observe watchlist symbols`.
5. Confirm three independent Freqtrade workers. Observation alone makes **zero broker orders**.

## Test 2: Independent concurrent demo entries
1. Choose a specific instrument with a verified eligible strategy direction; review its `Demo readiness` and `Review selected demo scope`.
2. Activate that exact demo scope via `Activate reviewed scope` when its account, symbol, 0.25% equity cap and strategy direction match your intent.
3. Switch to another *different* instrument and repeat. A broker-owned position in the first instrument no longer monopolizes the demo account. Core attaches a separate session ID, account/instrument binding and broker receipt to each.
4. Monitor `Core sessions`, `Position watch`, `position_reversal_evaluation`, `reconciliation` and `trading_outcome`. A signal is not a native fill.
5. Only native MT5 order/deal and isolated Freqtrade positions/history count as confirmed fills.

## Market specifics observed
- MT5 BTCUSDm: `trade_mode=4` (full broker trading), broker volume minimum 0.01 lot.
- MT5 ETHUSDm: `trade_mode=4`, broker minimum **0.1 lot**. The current configured MT5 demo max volume is **0.01 lot**; it cannot open an ETHUSDm order until a new validated volume/risk scenario accommodates the broker minimum. Observation is still available.
- MT5 SOLUSDm: `trade_mode=0` (broker disabled the instrument for orders). Niblit may observe its market, but cannot execute orders contrary to the broker's contract mode.
- Freqtrade CoreManaged: isolated Binance futures dry-run, strategy `NiblitCoreManaged`, `max_open_trades=3`, native state RUNNING after restart, historical trade #1 preserved. Its pair whitelist includes BTC, ETH, SOL, BNB, XRP and DOGE.
- Live r7 Freqtrade SOL/USDT:USDT read-only readiness produced a BUY signal with a completed risk/cost preflight; session activation was not automatically performed.

## New early-reversal evaluator
- For each Core-owned open trade with an active close scope, evaluates retained gross price profit vs initial stop risk, sampled MFE/MAE, short-term counter-momentum, 20-bar trend and RSI.
- Emits `position_reversal_evaluation` records and, when confirmed, uses the existing Core close-order path. Records outcomes in broker-net realized R.
- It does not guarantee that a detected reversal will occur or that the resulting close fill remains profitable after costs. A session expiry does not itself close broker positions.

## Boundaries / next enhancements
- Concurrent sessions apply to **different instruments**. Same-symbol hedging/stacking is not implemented; it requires account netting/hedging validation and separate position-ticket lifecycle.
- Watchlists do not automatically mint or activate trading sessions.
- Risk and broker contract checks remain; there is no reintroduced demo emergency latch or extra arbitrary UI disable.
- Do not infer trading profitability from the small number of successful demo outcomes; validate over many trades with market-regime diversity, net costs and out-of-sample comparisons.

## Final live deployment verification
- r7 was promoted from its candidate and is running at PID 18368 from `D:\NiblitAIOS\releases\build-20261120-multi-symbol-r7\niblit\niblit.exe`; Market Desk returned HTTP 200 with the embedded watchlist UI.
- Direct r7 operator API accepted both 3-symbol `observe-many` requests: MT5 `BTCUSDm, ETHUSDm, SOLUSDm`; Freqtrade `BTC/USDT:USDT, ETH/USDT:USDT, SOL/USDT:USDT`. All six selected observers were confirmed running with **no errors**, and `execution_started=false` for both API calls.
- Previously active r4 order records were broker-reconciled by r7 to **CLOSED**, with realized net **+3.75 USD** on MT5 and **+1.9779354 USDT** on Freqtrade. Current open Core entry scopes: 0. No new orders were submitted during watchlist verification.
- Final Core status showed 7 running observer workers in total, including an older **EURUSD** MT5 observer that reports `Choose a visible broker symbol from the MT5 list`; that unrelated legacy observation does not affect the six selected watchlist instruments.
- Freqtrade isolated native `show_config`: `dry_run=True`, strategy `NiblitCoreManaged`, `state=running`, `max_open_trades=3`; separate port-8080 historical engine unchanged.
