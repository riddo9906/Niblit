# Crypto strategy protection — implementation and acceptance

7 November 2026. Current gateway: **0.4.0**. Policy: **crypto-atr-structure/1**.

## Problem established with broker evidence

The first attributable Niblit demo BTCUSDm position (546973967) opened and closed on Exness, linked exit deal 480380847, realized net **−0.07 USD virtual money**. Commission/fee/swap readback for that position was zero; this does not establish a general commission schedule. The old generic stop was about 6.42 USD from entry when spread was 6.40 USD, leaving only **0.02 USD beyond the executable closing quote**. That is inappropriate room for this crypto feed. The close attribution is recorded in `NIBLIT_BROKER_SWITCH_RUNTIME.json`.

## Changes and scope

`modules/crypto_stops.py` supplies deterministic protection for Exness demo crypto. The existing six-strategy signal engine was preserved. `modules/mt5_orders.py` enables the new rule only with explicit crypto_stops=True; existing desktop/forex demo defaults remain unchanged. `deploy/vps-gateway/demo_execution.py` enables it on the pinned Exness demo adapter, publishes policy metadata and read-only price/cash-risk previews. `modules/trading_session_adapters.py` and `modules/remote_demo_adapter.py` carry the selected strategy into that rule. `modules/core_trading_sessions.py` binds the policy/version into canonical session grants and rechecks it before delivery. Market Desk shows the preview and the exact policy in its reviewed scope. No second Core, gateway, strategy engine or permission authority was created.

## Initial stop and target rule

Only native **completed M5 bars** are used (SDK index 1; latest 64 bars). At least 30 contiguous, finite, valid bars are required; forming/future bars, gaps, stale history and unknown contract values reject the entry. ATR is a deterministic 14-period Wilder-smoothed true-range estimate, seeded within that bounded window. It is not claimed to equal every platform indicator's seeding convention.

| Strategy | ATR multiple | Recent swing bars |
|---|---:|---:|
| Trend | 2.5 | 10 |
| Breakout | 2.0 | 10 |
| RSI reversion | 2.0 | 5 |
| Bollinger reversion | 2.0 | 5 |
| EMA pullback | 2.0 | 10 |
| Squeeze breakout | 2.5 | 10 |
| Read-only default preview | 2.0 | 10 |

A buy stop is beyond the recent swing low and below bid by at least the ATR distance, three spreads, and the broker distance plus two ticks. A sell stop mirrors this above ask and the recent swing high. Structure buffer is max(0.25 ATR, two ticks). Stop/freeze distances are read in broker points and used conservatively; prices round outward to the actual tick-size grid. Target is initially at least 2× the entry-to-stop distance, before unknown fees/slippage. An initial stop beyond 5% of entry is rejected, never clamped closer.

Broker `order_calc_profit` values the actual stop loss in account currency. Existing limits remain: at most 0.01 lots, per-entry estimated cash risk min(25 USD, 0.25% equity) for automatic sessions, and existing margin/exposure/day/session/drawdown limits. If the broker's minimum volume makes the structural stop unaffordable, reject the order. **Never squeeze the stop to make the volume fit.** ETHUSDm minimum 0.10 remains above the unchanged lot cap. SNXUSDm remains disabled/stale and is not admitted.

At confirm, approved stop/target prices are frozen. Fresh quote, tick grid, broker distance, spread clearance, reward/risk, SDK cash risk, review expiry, identity and Core scope are rechecked. The levels cannot silently widen or move between preview and delivery. A crossed/invalid review requires a fresh review. No trailing-stop or stop-modification route was added. Stop orders and broker preflight cannot guarantee a price through gaps; these are experimental demo rules, not proof of profitability.

Official contracts consulted: [MT5 symbol properties](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants), [MT5 ATR](https://www.metatrader5.com/en/terminal/help/indicators/oscillators/atr). Multipliers and buffers above are Niblit's explicit engineering defaults, not broker recommendations or calibrated evidence of an edge.

## Verification

**206 focused regression cases passed**, zero failures/errors/skips. After adding read-only preview valuation, **67 overlapping targeted tests passed**. The separate **16-test gateway suite passed on the actual VPS** before cutover. JavaScript syntax checks passed. Tests cover buy/sell protection across every strategy, tick rounding, stops/freeze/spread constraints, future/forming/missing/gapped/stale bars, oversized structural stops, unknown broker valuation, unaffordable minimum volume, frozen levels, policy changes, restart/uncertain delivery, live-account rejection and the actual Core/six-strategy/permission/ticket pipeline with broker doubles.

Actual Exness DEMO order_check accepted **buy and sell** prepared reviews with the new protection. One timestamped trend example had a 133.67 USD price stop distance and broker-calculated estimated loss **1.33–1.34 USD at 0.01 lots**. These were expiring **non-delivering reviews**; no new order was sent by this preflight validation. See `NIBLIT_CRYPTO_STOP_LIVE_PREFLIGHT.json` and `NIBLIT_CRYPTO_STOP_COMPARISON.json`. Values are historical snapshots, not permanently current quotes.

The normal Core API and actual Market Desk displayed live policy/version, native prices, stop/target/ATR previews, cash-risk estimates and a pending policy-bound review. Source evidence: `NIBLIT_CRYPTO_STOP_CORE_PREVIEW.json`, `NIBLIT_CRYPTO_STOP_RUNTIME.json`, `NIBLIT_CRYPTO_STOP_MARKET_DESK.png`.

## Runtime, preservation and rollback

Desktop Core: task `outputs/releases/crypto-protection-20261107-r1/core`, supported main.py --serve --headless --quiet, canonical original ledger/permissions, 127.0.0.1:5000. Existing React Trading at 127.0.0.1:5173 embeds the hosted Desk. VPS gateway: `C:/NiblitGateway/releases/0.4.0-crypto-protection-20261107-r1`; shared hash-pinned venv from 0.2.0 retained. Exact Exness demo binding is 100000002 / Exness-MT5Trial10; explicit MT5 executable/data identity unchanged. SSH pin, protected credentials, loopback-only gateway and both SQLite journals are retained. Code was deployed as new versioned releases; owned candidates were shut down gracefully. Original dirty work and r8 release were preserved; no MT5 process or broker position was terminated/modified.

Demo scopes were paused for the policy change. No authority was renewed automatically. Use Exness view → Review demo execution → Enable reviewed demo execution for a fresh scope. The review includes policy version/rules, one entry, 0.01-lot cap and exact account identity. If the five-minute proposal expires, review again. Existing broker protection remains independent of desktop connectivity; no account login/switch is scripted.

Gateway rollback: stop only its owned scheduled task, restore previous arguments/working directory from `C:/NiblitGateway/artifacts/crypto-040-rollback.json`, restart that task. Keep current journals; never overwrite them with old backups during a routine code rollback. Restore the matching prior Core release if rolling back the protocol: the new Core refuses demo grants when the protection policy is missing or changed. All grants stay stopped/interrupted. Both databases were backed up before gateway cutover.

## Market Desk selector and demo execution acceptance

The previous requested selector is deployed and preserved: Follow MT5 account, XM live/read-only, Exness demo/testing. It changes the displayed profile, never the terminal login. Actual account identity is always independently verified. Selecting Exness while XM is connected shows a mismatch and blocks demo controls. Live UI acceptance verified this, then verified Exness after the operator's manual switch. The selector/old observation UI suites passed 9 Node cases; Core/gateway protocol suite passed 27 cases. Explicit Review/Enable/Stop demo controls are scoped to Exness; Stop does not stop unrelated Freqtrade scopes. Stale/unverified Exness data clears immediately. Core demo authorization and MT5 Algo Trading are displayed independently. A prior real demo fill/exit is now confirmed; an actual filled/closed trade under the **new** ATR policy is not yet claimed.

## Remaining limitations

Funded submission/modification/cancellation/closure remain disabled, and the funded governor is byte-unchanged. XM reconciliation breaker remains latched; no reset was attempted. Current XM observation depends on which account the operator selects in the shared terminal. Full account-lifetime history, dedicated non-admin runtime, offsite restore/retention and extended operational testing remain separate DAE-1 work. The new stop defaults need measured replay/demo evaluation before any performance claim. No paid inference or new hosting purchase was performed for this work.
