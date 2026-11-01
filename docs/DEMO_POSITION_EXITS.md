# Strategy-aware MT5 demo exits

New entries filled during an authorized bounded demo session record their entry
strategy, original stop and breakout boundary. That context is required by the
exit policy. Old/manual positions are not automatically adopted. A restart does
not rearm execution; observation mode never submits exits.

The existing sequential 15-second worker evaluates executable bid/ask profit on
each cycle. Entry signals still use completed M5 bars. No new model or polling
worker is created, and no stop or exposure is increased.

- Trend and EMA strategies: two completed closes against the strategy mean can
  invalidate the entry thesis.
- Breakout strategies: two completed closes back inside the saved entry boundary
  identify a possible failed breakout, not certainty about future prices.
- Reversion strategies: a return to the mean or RSI neutral can close a position
  with a minimum price-gain/cost buffer.
- Profit protection: after at least 0.75 initial risk units of favourable movement,
  a 0.35R giveback can request closure while at least 0.20R and three spreads of
  price gain remain. Two quote checks separated by at least ten broker seconds
  are required. The actual worker normally checks every fifteen seconds.

Initial R is the entry-to-original-stop price distance. Bid/ask accounting includes
the current spread, but commission, swap, slippage and gaps can erase apparent
price profit. No profitable fill or avoided loss is guaranteed.

Every adaptive close goes through the existing exact-position demo-only order
builder, broker preflight and durable ticket protocol. Each submitted adaptive
exit is attempted once per tracked position; ambiguous outcomes stop the worker
for reconciliation. Entry strategy and exit evidence accompany realized broker
net outcomes for subsequent study. A counterfactual profit is never invented.

Predictions remain advisory: the online comparer has not been validated for exit
decisions. This is quote-based profit protection over M5 entry strategies, not a
validated M1 scalping strategy or a live-funded trading profile. Freqtrade's native
exit rules are unchanged by this update.

Tests cover long/short givebacks, distinct quote confirmation, saved breakout
invalidation, stale/invalid evidence, unknown entry context, between-bar delivery,
duplicate suppression and observation-only protection. No real order was sent
to test this feature.

Official broker-integration reference:
https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py
