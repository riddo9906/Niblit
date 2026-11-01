# Niblit Market Desk

Open `http://127.0.0.1:8767/` or use the current native release's Trading tab.
The environment selector now also exposes the connected MT5 desktop adapter.
See `docs/MT5_DEMO_CONNECTION.md` for observation and non-executing demo preflight.
`Start-Niblit-Memory.cmd` starts the host desk alongside the connected desktop.
`Start-Trading-Desk.cmd` opens just the desk. Docker/Freqtrade must be running.

The host service reads the private existing sibling `freqtrade/user_data/config.json`
API credentials. It talks only to fixed loopback port 8080; credentials never reach
the browser. The native trading tab embeds this same desk. Historical Lean replay
is explicitly separate and remains available below it.

## Implemented

- Actual Freqtrade exchange whitelist, completed analyzed candles, configured
  strategy entry/exit flags, age/freshness, account balances, positions and profit.
- Refresh every 15 seconds while visible, with connection failure clearing the
  current market view. This is periodic REST polling, not a tick stream.
- Manual long entry and full trade exit in verified dry-run mode. Review expires
  after 30 seconds. Stake is capped at 100 account currency units, leverage 1.
  Configuration identity and relevant position/data checks repeat before delivery.
  Binance minimum quantity/notional rules and a conservative reserve are checked
  before entry. A definitive engine entry rejection is shown as rejected; delivery
  timeouts remain unknown and are never retried automatically.
- Same-origin session token and Host validation on all mutations. No LLM execution
  tool, arbitrary URL, Docker command or shell execution endpoint.
- Durable tickets committed before sending. Confirmation is idempotent. Sending
  or uncertain delivery blocks new tickets until matching Freqtrade evidence is
  reconciled. No automatic order resubmission after timeout or restart.
- Closed outcomes from the latest 100 engine trades are captured idempotently in
  a separate SQLite ledger and queued as unverified episodic evidence to the existing
  Core memory worker. Projection is handled by that worker, without another local
  embedding model or paid inference. Imports retain engine mode and provenance.
  Older histories beyond 100 require a separate paginated import.

## Explicit limits before funded use

Funded orders are structurally disabled in this desk. A live engine is view-only.
The current engine is Binance futures, dry-run, SampleStrategy. This work does not
validate that strategy's profitability or replace its strategy/risk settings.
Freqtrade remains responsible for balances, exchange constraints and stop/ROI rules.
Manual exits are market exits; entry is long only. No order cancellation/partial
exit/short entry UI is exposed. Outstanding delivery cannot be cleared merely by
clicking a button; reconciliation requires engine evidence. An uncertain failed
entry with no matching trade needs an operator investigation of the private ledger.

No real exchange order was submitted by implementation acceptance. Simulated engine
operations were preserved. A funded venue/account, allowed products, manual versus
automated policy and explicit capital/risk limits must be established before adding
and enabling a funded execution path. No claim is made that other broker adapters
are implemented by this one exchange integration.

Official API contract: https://www.freqtrade.io/en/stable/rest-api/
Verification: `niblit-env/Scripts/python.exe scripts/verify-trading-desk.py`.
Tests: `tests/test_trading_desk.py` and existing `tests/test_freqtrade_operator.py`.
Private runtime data and the pre-change Freqtrade configuration backup are under
ignored `runtime/trading-desk/`. Never publish that backup or configuration.


## 2026-10-30 demo automation update

The host desk also includes the [bounded MT5 strategy laboratory](DEMO_STRATEGY_LAB.md): trend/breakout selection, explicit session start/stop, reasons, equity-based risk sizing, linked net outcomes and public monetary-policy research context. The manual controls above retain their original behavior. The laboratory is demo-only and separate from Freqtrade native strategy execution; see its guide for limits and acceptance evidence.
