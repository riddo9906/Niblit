# Exness demo integration — 7 November 2026

## A. Implemented changes

Extended the existing VPS gateway, existing Core session authority and existing Market Desk. No second Core or strategy engine was created. New `modules/remote_demo_adapter.py` transports the existing `MT5SessionAdapter`/`DemoOrders` implementation. `deploy/vps-gateway/demo_execution.py` pins SDK-reported demo identity and the terminal data-directory identity. `modules/trading_values.py` removes the lightweight broker translator's dependency on the full Core import. Core/API/Desk changes register `exness_demo`, preserve its exact binding in session scopes, publish receipts/inventory, and retain all XM local-fallback denials. The six strategies and funded risk governor are unchanged.

## B. Verified runtime topology

Desktop Core `outputs/releases/exness-demo-20261107-r3/core/main.py --serve --headless --quiet` → pinned loopback SSH forward → InterServer gateway `C:/NiblitGateway/releases/0.3.3-exness-demo-20261107-r5` → explicit `C:/Program Files/MetaTrader 5/terminal64.exe` in the signed-in Windows session. Core is on 127.0.0.1:5000; existing React Trading at 127.0.0.1:5173/trading embeds Core's Market Desk. Gateway remains on 127.0.0.1:18765. Strategies and inference remain on the desktop. The existing source environment and canonical ledger remain the authority; no private dotenv values were copied into releases.

## C. Broker verification and correct market data

Exness Technologies Ltd / 486129611 / Exness-MT5Trial10, SDK trade_mode=0 (DEMO), USD. The operator added virtual funds; fresh API readback verified balance/equity 10000, zero positions/pending orders, account trading allowed and terminal Algo Trading enabled. Historical values must not be presented as permanently current.

BTCUSDm: minimum/step 0.01 lots, contract size 1 BTC, tick size 0.01 USD; advancing bid/ask and 200 completed native M5 candles were read through Core. ETHUSDm: minimum 0.10 lots, step 0.01, contract size 1 ETH. ETH is observable but its minimum exceeds Niblit's 0.01-lot execution ceiling. No ceiling was increased. SNXUSDm exists and is visible, but trade_mode=0 (DISABLED); its last stored quote is from October 2024. It is excluded from execution and must not be displayed as a current tradable quote. Commission schedule remains UNKNOWN; no zero-commission assumption was added.

Exports: `NIBLIT_EXNESS_MARKETS_FINAL.json`, `NIBLIT_EXNESS_SYMBOLS.csv`, `NIBLIT_EXNESS_CLOSED_M5.csv`, `NIBLIT_EXNESS_SNX_LOOKUP.json`. CSV prices are timestamped snapshots, not a live subscription. Native MT5 data and closed bars are used; XM/MetaQuotes candles are not substituted.

## D. Reconciliation and delivery evidence

The first real demo submission attempt returned a final preflight rejection before SDK delivery. Its durable VPS ticket `ce95714182c9fe85a083b9ca7b12bb50` remained PREVIEW with no sending transition. Core conservatively marked the failed transport result UNKNOWN and did not retry. Forensics established the PREVIEW state; gateway restart invalidated it as REJECTED, and Core reconciliation recorded REJECTED. The original exact preflight reason was not recorded and must not be guessed.

Gateway 0.3.1 added durable controlled reason codes for preflight failures: only an atomic PREVIEW→REJECTED transition proves no delivery began. SENDING/UNKNOWN/PARTIAL are never cleared by this path. Gateway 0.3.2 added an additional full account/permission check immediately before the SDK call, with a test for an account change between boundary checks. A subsequent attempt durably proved `price_moved_outside_review`, delivery_began=false. On BTC the old 20-point allowance was only USD 0.20. Gateway 0.3.3 explicitly configures the remote crypto demo review allowance as max(20 broker points, 0.01% of reviewed price), taking the smaller allowance from the old and rebuilt reviews. At the observed BTC prices this is one basis point. Broker point metadata is unchanged. Existing desktop demo orders retain their default 20-point limit. The cash-risk, volume, margin, exposure and protective-level checks remain unchanged; the funded governor was not modified. Final crypto/order compatibility tests passed (43 cases).

At 18:39 SAST the original scope was EXPIRED and all six strategies were WAIT, with no confirmed Niblit demo fill or exit. Two attempts were proven rejected before delivery. Subsequent readback showed virtual balance/equity 9999.20 with no positions/pending orders; that balance change is not attributed to Niblit because no matching Niblit fill was established. The initial 10000 observation is historical. Broker-double roundtrips passed; an actual broker fill/exit roundtrip remains unverified. Check `NIBLIT_EXNESS_CORE_FINAL.json` for the most recent saved state, and query Core for current state.

XM's separate database and RECONCILIATION_REQUIRED latch were preserved, never reset. Its original recorded terminal-unavailable-or-duplicated trigger remains historical. The operator intentionally switched the only VPS terminal to Exness: XM authentication/inventory is therefore unavailable now. Its historical $21.03 is not current broker evidence. The old separate desktop demo EURUSD ledger record was neither adopted nor closed.

## E. Windows startup reliability

The earlier real sign-in test passed and is evidenced by `NIBLIT_DAE1_P2_SIGNIN_ACCEPTANCE.json`. Existing guarded MT5 and gateway logon/RDP-connect tasks remain in use. Gateway action now selects the versioned 0.3.2 release and `--demo-config C:/NiblitGateway/config/exness-demo.json`. No Windows password or broker login was scripted. Interactive Windows sign-in remains required. The safe MT5 startup configuration disables Algo Trading; a restart must not rearm demo execution. Core restart interrupts grants, and gateway restart rejects outstanding unsubmitted previews. No additional reboot acceptance is claimed for this Exness extension.

## F. Core acceptance

The real supported Core runtime consumed the actual remote demo identity, quotes, closed candles and broker risk state. It used the existing canonical permission manager, broker admission, trading ledger and ingestion outbox. An explicit BTCUSDm demo scope was activated: at most one entry, one position, 0.01 lots, existing per-entry risk ceiling min(25 USD, 0.25% equity), and existing session/day/drawdown/margin/exposure limits. Staging and recovery scopes stayed within the original approximate 18:38 SAST end time; no continuous renewal was introduced. The scope ended at approximately 18:38:37 SAST and was not renewed past that window. Observation continues. Entries and owned-position exits require a newly reviewed scope. No manual/pre-existing positions are adopted.

## G. Market Desk acceptance

The actual existing React Trading page displayed Exness demo identity, virtual equity, advancing quotes, symbol constraints, six-strategy votes, session limits, delivery receipts and position/pending-order inventory. The separate XM panel honestly remains unverified. A real owned-tunnel interruption disabled demo observation/review/activation and showed unavailable/stale state; restoring the existing tunnel supervisor restored readback without granting authority. Evidence: `NIBLIT_EXNESS_TUNNEL_OUTAGE.json`, `NIBLIT_EXNESS_TUNNEL_RECOVERY.json`, UI outage image, and final Core/market snapshots. The React artifact is the existing verified Phase 2 build; Desk assets are served by the new Core. No native Tauri rebuild is claimed.

## H. Tests

169 focused regression cases passed, zero failures/errors/skips (`NIBLIT_EXNESS_TESTS_FINAL.xml`). After the SDK-boundary tightening, all 29 dedicated Exness cases passed (`NIBLIT_EXNESS_BOUNDARY_TESTS.xml`); these overlap with the regression suite and must not be added as independent totals. The final crypto-review change then passed 43 focused Exness and existing DemoOrders cases, zero failures/errors/skips (`NIBLIT_EXNESS_CRYPTO_REVIEW_TESTS.xml`). These counts overlap and must not be summed. The gateway's separate 16-test suite passed locally and on the real VPS before each cutover, including 0.3.3. JavaScript syntax checks passed. Tests cover exact binding, live/contest/wrong-server rejection, terminal permissions, expired scopes, protected stops, partial/unknown delivery, idempotent tickets, unauthenticated/read-token rejection, unsupported mutation types, restart invalidation, and the real six-strategy/Core/permission/ticket path using broker doubles.

Real acceptance exercised account readback, quote advancement, native closed candles, non-delivering broker preflight, one proven unsent rejection, restart reconciliation and tunnel outage/recovery. No funded tests or orders were sent. The previous 113/132-test baselines remain historical evidence, not newly added totals.

## I. Security and trading restrictions

Dedicated ACL-protected demo credential; original read and stop credentials unchanged. No credentials in source archives, reports, scripts or logs. SSH host-key pinning, key authentication and local forward process verification remain enforced before credentials are sent. No public gateway listener. Both preflight and the final SDK boundary require the exact configured account/terminal and broker-reported DEMO mode. Only bounded demo market entries and exact owned exits are supported; modifications, pending-order cancellation, switching accounts and all funded mutations remain disabled. Emergency stops persist and are not automatically reset. Manual account switching should be preceded by stopping the demo session; MT5 has no atomic compare-account-and-send primitive, so do not intentionally switch accounts during a broker call.

## J. Remaining blockers and limits

No confirmed real demo fill/exit yet; current strategies may legitimately WAIT or fail strict preflight. ETH's minimum exceeds the test cap. SNXUSDm is broker-disabled and stale. Commission/account-subtype evidence remains incomplete. Full-history lifecycle/backfill, off-server encrypted backup restore/retention, dedicated non-admin runtime identity, extended outage stress acceptance and native Tauri packaging remain separate work. XM live observation cannot resume while this shared terminal is signed into Exness; do not switch automatically. Original full XM Phase 2 acceptance is not declared complete by this demo milestone.

Both account databases use separate durable state. `Niblit-Exness-Demo-Backup` runs daily at 03:05 server time using the existing consistent SQLite backup helper and a separate backup directory; inspect `NIBLIT_EXNESS_DURABLE_STATE.json` for actual integrity evidence. Local backups are not offsite disaster recovery.

## K. Recovery and next milestone

Open the normal Trading page; inspect the Exness section, choose BTCUSDm, Observe, Review demo scope, then Activate that exact scope. New sessions default to a maximum of one entry. Do not clear emergency stops merely to get a trade. After Windows sign-in, verify demo identity and enable Algo Trading only on the demo account if needed. Never paste passwords into chat.

Stop Core execution before planned upgrades. Gateway rollback restores only the scheduled task's prior arguments and working directory from `C:/NiblitGateway/artifacts/exness-033-rollback.json`; retain both current databases and the shared 0.2.0 venv. Do not overwrite a current journal with an old backup. Rolling back to the original 0.2.2 gateway disables demo RPCs; use the compatible older Core/profile and leave scopes interrupted. Core rollback uses its supported graceful shutdown, then the prior immutable release; never run two Cores on port 5000. Core launchers and deployment scripts are in `work/exness-demo`. An incomplete unused staging copy was preserved privately and is not a release.

Next: observe an actual naturally qualifying demo signal and reconcile the broker-confirmed fill/exit, fees and protection without widening risk limits; then perform bounded multi-session strategy evaluation. Resume separate XM observation only through a deliberately selected account/terminal arrangement. No profit target or funded authorization is implied.
