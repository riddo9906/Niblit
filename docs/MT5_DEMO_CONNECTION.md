# MT5 desktop connection

Open the existing Market Desk at `http://127.0.0.1:8767/` (also embedded in
Niblit's Trading tab) and choose **MT5 desktop · demo connection**.

The host process attaches to the currently logged-in Windows MT5 terminal through
MetaQuotes' official Python package. It never calls login, switches account,
collects a password or changes trading permissions. Explicit human confirmation
can submit orders to verified demo accounts through a separate durable ticket controller.

## Setup

The optional pinned dependency is in `requirements-mt5.txt`. It is installed in
Niblit's host virtual environment; it is not a Linux Docker dependency. Default
terminal: `C:\Program Files\MetaTrader 5\terminal64.exe`. An operator may set
`NIBLIT_MT5_TERMINAL` for a different terminal installation. Restart Market Desk
after installation or changing that path.

Start through `Start-Niblit-Memory.cmd` or `Start-Trading-Desk.cmd`. The existing
launcher starts the local desk on port 8767. MT5 must be open and connected.
This host-side adapter does not require repackaging the native Core executable.

## Observable capabilities

- Demo/live account mode, currency, balance, equity, margin and terminal status.
  Full account login and name are excluded from browser responses.
- Exact broker symbol names from Market Watch, bid/ask/spread and completed M5
  bars. Bar position 1 excludes the terminal's current unfinished bar.
- Current positions and pending-order count. Close controls are restricted to exact
  positions tagged with Niblit's test magic number 29102026.
- Same-origin, token-protected **demo preflight** for buy/sell, capped at 0.01 lots.
  It validates account identity, account mode, tick advancement and symbol volume
  rules before calling `order_check`. That function does not submit an order.
  Result acceptance does not guarantee that a future order would fill.
- Live accounts are observation-only. Preflight and submission reject live and
  contest accounts. No order execution tools are exposed to a model.
- **Review demo order → Submit MT5 demo order** calls the real demo server's
  `order_send` after a repeat broker preflight, account/mode/permission checks and
  bounded-price review. Entry is capped at 0.01 lots and one Niblit test position.
  Stop loss and take profit are attached. Estimated stop risk is limited to the
  smaller of 25 account currency units and 1% of equity; post-check margin is
  capped at 10% of equity. These are simulation test limits, not a promise about
  fills, gaps or realized loss. Existing symbol exposure and pending orders block entries.
- Confirmation expires after 30 seconds; the ticket is durably marked sending
  before delivery. Repeated confirmation never resends. Unknown/time-out delivery
  blocks further orders until matching broker deal evidence reconciles it. A
  missing deal is not treated as proof that an order failed.
- **Review demo close** sends an opposite full-size order referencing the exact
  Niblit position. It cannot close positions belonging to other tools or manual trades.

## Time and freshness

On the connected MetaQuotes-Demo feed, raw tick/bar timestamps were approximately
7200 seconds ahead of the host UTC clock. The PC's local display timezone is UTC+2.
The adapter preserves raw broker timestamps and labels their timezone unverified;
it does not silently subtract two hours or present a guessed conversion as UTC.
Charts use the terminal's completed-bar index, not an assumed timezone filter.

Freshness here means **observed tick advancement within the last 60 seconds**, using
a local monotonic clock. The first tick is unconfirmed until a later raw timestamp
advances. Refresh again or wait for the 15-second update. It is not proof of absolute
exchange-to-PC latency or UTC age. A frozen feed disables preflight. During closed
markets, the last quote may remain visible but is not treated as updating.

Terminal Algo Trading may remain off for observation/preflight. The bridge leaves
it untouched. Actual demo submission requires terminal and broker permissions to
already allow it; the UI reports permission status separately. Broker rejections
and uncertain deliveries are shown without automatic retries.

Official contracts:
- https://www.mql5.com/en/docs/python_metatrader5
- https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrompos_py
- https://www.mql5.com/en/docs/python_metatrader5/mt5ordercheck_py

Tests: `tests/test_mt5_bridge.py`, `tests/test_mt5_orders.py`, plus the existing
trading-desk and Freqtrade regression tests. Private ticket ledger:
`runtime/trading-desk/mt5-orders.sqlite3`.
