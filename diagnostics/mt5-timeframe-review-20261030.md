# MT5 trade review — 2026-10-30

Native accessibility identifies EURUSD,H1; image capture timed out, so no visual candle-pattern claim was made. Broker IPC provided completed H1/M5 bars and the saved entry record. No order, stop, target, account or chart setting was changed.

Buy: 0.01 EURUSD at 1.11584, SL 1.11384, TP 1.11984, entry stop-price risk estimated 2 USD. Entry strategy trend_v1: completed M5 close 1.11583 > SMA20 1.1155515 > SMA50 1.115467; EMA pullback also voted buy. Breakout rule voted WAIT.

At review, six completed H1 bars changed by about -44 pips, versus +10.2 pips over six M5 bars. Bid was about 1.11692, an unrealized +10.8 pips / +1.08 USD at that instant. This is a short-term buy during recent hourly selling pressure; no H1 confirmation gate exists in the current entry rule. It is not proof of the next price direction.

Current numeric forecast did not beat its zero-return baseline on MAE and reported uncertain_after_costs. It did not authorize the entry.

Found misleading explanation: multiple agreeing rules were always described as a completed breakout, even when no breakout rule qualified. Corrected future source explanation and added a regression check; actual strategy-selection logic unchanged. Historical journal retained as-is. Running trader was not restarted; future release must load the corrected wording. Multi-timeframe confirmation/regime handling needs separate design, historical validation and versioned rollout, not a post-hoc rule change to the current trade.
