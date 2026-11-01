# Demo strategy laboratory — 2026-10-30

Open the host Market Desk at http://127.0.0.1:8767/. Select MT5 and its
visible broker symbol. The laboratory below the manual controls has trend and
breakout rules, a bounded Start button, Stop, reasons, outcomes and performance.
This is a source/host-desk update, not a newly packaged desktop executable.

## What executes and why

`modules/demo_strategy.py` defines two explicit experimental M5 rules:
20/50 simple means with five-bar momentum, and a close beyond the previous
20-bar high/low. Both use completed candles only. They are hand-authored
hypotheses, not trained discoveries or validated profitable systems.

`modules/demo_autotrader.py` runs one worker only after Start. Defaults are
30 minutes and at most three entry attempts; hard limits are 60 minutes and ten.
Restart never rearms a session. One decision per candle avoids duplicate entries.
Matching exposure is held; an opposing signal closes the exact owned Niblit
position. It does not reverse in that same cycle. Other exposure blocks entry.

The existing `DemoOrders` controller retains account identity checks, demo-only
delivery, broker preflight, durable tickets, stops/targets and uncertainty blocks.
Auto risk is rechecked during final broker-request construction as well as preview.
An unknown/partial/placed response stops the worker; reconcile before restarting.

## Small balances and risk

The stop-price risk budget is 0.25% of current equity, capped at 25 account currency
units. Broker-calculated sizing rounds down to its minimum/step, capped at 0.01
lots. If the minimum is too large, skip. The absolute budget can rise with equity
or fall with losses; there is no martingale, leverage escalation or ceiling removal.
The existing order controller caps margin at 10% of equity. Spread above 20% of
the stop distance blocks entries. Both session-start loss and peak drawdown stop
new work at 2%. These are sampled limits, not guaranteed maximum losses.

Stops/targets retain the original controller's fixed broker-valid distance and
2:1 target/stop distance. Stop-price risk excludes commissions, slippage and gaps.
**Stop, expiry and a loss halt do not liquidate positions.** Existing broker SL/TP
remain; use the existing manual close control when needed. No funded execution.

## The feedback loop

Completed candles → deterministic hypothesis and evidence → risk checks → durable
decision/ticket → broker response → closed broker deals → net outcome → descriptive
strategy statistics and the existing Core episodic outbox. MT5 outcomes link to
the actual entry order from that strategy decision. Unrelated manual trades are
excluded, and entry/exit commission, swap and fees are included in the reported net.
Account, symbol and currency samples stay separate. No automatic promotion or
model weight training occurs. A favorable small demo sample is not proof of edge.

Private SQLite journals live in ignored `runtime/trading-desk/`. The existing
permission-gated memory export queues demo-tagged evidence for Core's worker;
Core/Qdrant must be running and authorized for projection. The decision ledger
remains authoritative if vector memory is unavailable. Closed outcomes are checked
during running sessions (including subsequent sessions), not by an always-on service.
Broker collection covers seven days; older/missing histories need separate import.

## Macro learning

`modules/market_events.py` collects only the Federal Reserve's public monetary
policy RSS feed. Collection runs at most every ten minutes while a demo session
is active, or through the explicit Collect button. No arbitrary URL fetching or
paid inference. Titles/source links, publication time and first local availability
are stored separately. Only items already available and published within 24 hours
can be attached as decision context. Research context does not vote on direction.

The UI explains rate surprises, political/fiscal changes and supply/war shocks as
uncertain mechanisms. Politics/war feeds, instrument-specific event exposure,
expectation-versus-surprise data and causal/event-study validation remain pending.
Do not label these lessons or headlines as a trained geopolitical trading expert.

## Acceptance and remaining work

Offline tests exercise the real coordinator with simulated broker boundaries,
direction rules, small-account sizing, live/account-switch rejection, loss stops,
duplicate suppression, unknown delivery, net outcome linkage and route protection.
No paid model calls or funded orders are part of verification.

Live terminal connectivity, an actual automatic demo fill/exit, a sustained sample,
historical cost-aware backtesting, lookahead/recursive analysis and out-of-sample
evaluation are separate acceptance steps. Freqtrade's existing configured native
strategy/dry-run controls remain separate; this update does not switch its strategy
or claim that MT5 rules are installed there.

Official references:
- https://www.mql5.com/en/docs/python_metatrader5/mt5ordercheck_py
- https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py
- https://www.freqtrade.io/en/stable/strategy-101/
- https://www.freqtrade.io/en/stable/lookahead-analysis/
- https://www.federalreserve.gov/feeds/feeds.htm


## Strategy manager and notifier continuation

The Manager option compares both registered strategies every scan (15 seconds,
using the latest completed M5 candles). It logs all candidate conditions, chooses
only an eligible rule, prefers the more specific breakout when both agree, and
abstains if directions conflict. A pinned rule remains available. Once a manager
trade opens, its original strategy owns the exit thesis; another strategy cannot
silently take over that position. This selection policy is not learned proof of edge.

When the execution window expires, the worker changes to **observing** and keeps
collecting conditions/outcomes while the service runs. It never extends execution
authorization itself. Observe can also be started directly without enabling orders.
Restart remains disarmed; Stop ends both trading cycles and observation.

Observation can generate a qualifying-setup alert only after fresh data, no current
exposure/pending orders, sizing/spread policy and a non-delivering broker preflight.
Unresolved delivery blocks that preflight. Alerts persist with a two-minute expiry,
are deduplicated per account/symbol/strategy/direction/candle, and become unavailable
when the latest scan changes or fails its checks. An alert does not submit an order.

The user reviews the setup and explicitly approves a bounded new session. The
server rejects expired/changed alerts, and broker/risk checks repeat for delivery.
The browser can request optional desktop-notification permission from its Enable
button. In-page alerts work without that permission; desktop notifications require
the page/browser to stay open and remain subject to browser throttling. There is
no automatic Codex-chat, email or push delivery. Headline data is never authorization.
