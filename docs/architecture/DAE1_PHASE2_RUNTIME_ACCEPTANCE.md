# DAE-1/P2 runtime acceptance

## Release and live topology

Phase 2 operational acceptance is in progress. The final Windows sign-in cycle is pending.
All funded mutations remain disabled and RECONCILIATION_REQUIRED remains latched.

The existing React TradingPage now embeds Core /market-desk/, replacing the standalone 8767
target. Core is started through main.py --serve --headless --quiet from a staged source release.
No second Core, gateway or dashboard was introduced. Existing dirty source, untracked files,
frozen r8 and r9.1 releases were retained. The operator exited r9.1 before the staged Core started.

Active gateway: C:/NiblitGateway/releases/0.2.2-dae1-p2-20261107-b.
It uses the existing hash-pinned 0.2.0 release virtual environment; that environment must be retained.
Core candidate: Codex task outputs/releases/dae1-p2-20261107-r3/core.
React artifact: outputs/releases/dae1-p2-20261107-r3/ui-final.
Core API: 127.0.0.1:5000. UI acceptance: 127.0.0.1:5173/trading.
Gateway: VPS 127.0.0.1:18765, reached by the owned pinned-host SSH local forward.
Canonical ledger: C:/Users/Operator/Documents/GitHub/Niblit/runtime/memory-framework/ledger.sqlite3.
Canonical permission file: the same directory's permissions.json. No permission grants were changed.

## Runtime boundary map

| Boundary | Implementation / contract | Validation, failure and persistence |
| --- | --- | --- |
| XM to VPS MT5 | User-authenticated saved terminal; XMGlobal-MT5 12 / 100000001, live USD | Terminal process alone is not authentication; exact API identity required |
| MT5 to Python | deploy/vps-gateway/broker.py, explicit existing terminal in same session | Bounded initialize; binding before/after inventory/history; no login or order_send |
| Probe to gateway | File-backed bounded subprocess I/O, 10-second deadline | Controlled errors; no uncontrolled launch loop; no terminal termination |
| Gateway to SQLite | gateway.py Monitor, transaction per observation | Stable tickets, fingerprint upserts, checkpoints/windows; no inferred fills |
| Gateway to tunnel | Loopback authenticated HTTP under pinned-host SSH | Separate read/stop credentials; no public API; no broker mutation/reset routes |
| Tunnel to desktop | Start-ObservationTunnel.ps1 | Key auth, strict host keys, loopback bind, mutex, 2-30 second reconnect backoff |
| Desktop to Core | remote_broker_gateway.py; explicit private profile | Pinned gateway/account/terminal identity, no redirects/proxy, response bound, freshness checks |
| Core observation | broker_observation.py: niblit.broker-observation/1 | Missing values UNKNOWN/null; source and receipt times; independent auth/inventory/safety states |
| Core to ledger | CoreTradingSessions.remote_status | Existing trading_events + ingestion_outbox transaction; state-transition dedup; labelled historical restore |
| Core to Desk | trading_session_api.py + existing hosted trading_desk.py | Local operator route; selected remote profile rejects desktop MT5/demo paths |
| Desk to React/Tauri shell | TradingPage.tsx, existing API config/runtime store | Core-hosted iframe; remounts after Core recovery; current values withheld on outage |

## Broker and reconciliation evidence

API-proven identity: XM Global Limited, 100000001, XMGlobal-MT5 12, live USD.
VPS terminal identity: 1741e470ad3a01c44884.
Gateway identity: 2128e13d6b61120feab258131da5477dc006eaf7b601c24192df4e62a90ff333.
The live acceptance snapshot showed balance/equity 21.03, margin 0 and free margin 21.03,
zero positions and zero pending orders. These values must always be read with their observation time.
EURUSD's stored quote is older than account readback; it is not a current quote.
Account subtype and authoritative commission schedule are UNKNOWN.

The original journal trigger was terminal_unavailable_or_duplicated at 2026-11-07 15:24:52 SAST,
repeated at 15:25:10 after the earlier reboot. The trigger row had no authenticated account snapshot;
the durable database remained bound to the expected account. That combined failure code does not
independently prove whether the terminal was absent, duplicated or not ready. Later API inventory
was empty. No gateway order-delivery path exists, and no gateway sending/unknown-delivery state exists.

The canonical Core ledger has one historical OPEN EURUSD record bound to a DEMO account
b95a8bc3fd731d67. It was not adopted as an XM position, altered or treated as current broker evidence.
This separate unresolved demo ledger record needs its own account-bound reconciliation.

History has two type=2 balance operations, not trading profits. Historical records are retained,
but collection covers bounded windows, not proven account-lifetime history. Empty current inventory
does not establish full historical reconciliation. No complete position lifecycle or missing-fill
resolution may be inferred from it. The gateway reports REVIEW_REQUIRED and complete=false.

There is no breaker reset route. Future recovery requires broker-confirmed identity, fresh inventory,
explicit required history coverage, resolution of uncertain operations in their own accounts, durable
evidence and a reviewed operator recovery procedure. No such clearance was granted in this milestone.
Account changes, stale inventory, missing history and unresolved delivery invalidate eligibility.
Emergency stop remains a separate persistent latch. This work did not reset either latch.

## Startup and supervision

MT5: Niblit-XM-Observed-Terminal, Administrator Interactive/Limited, 15-second sign-in delay,
explicit terminal path and safe INI, minimized terminal with hidden PowerShell host, one launch only,
30-second process deadline and 1 MB rotating startup log. Ambiguous terminals fail closed.
Gateway: Niblit-VPS-Gateway-0.2, same interactive user/session, 45-second sign-in delay.
Windows sign-in remains required; no password was stored and no automatic Windows login was configured.
The operator observed an automatic MT5 launch. Final sign-out/sign-in process/API proof is pending.

Daily Niblit-Gateway-Backup uses SQLite backup API as SYSTEM. Local backup integrity passed.
Credentials are excluded. Off-server encrypted backups, retention selection and a restore drill remain pending.
A separate least-privilege Windows account would require an interactive MT5 login in that account;
current runtime uses the existing Administrator user's limited token, not a Session 0 MT5 service.

## Verification

Baseline retained: previous 113 focused tests. Current combined run: 125 passed, 0 failed, 0 skipped.
Gateway suite: 16 passed locally; candidate tests also ran successfully on the real VPS before cutover.
React TypeScript/Vite build passed. JavaScript syntax passed.
Real Core readback and canonical journaling passed against the actual remote XM terminal.
Real React TradingPage rendered the Core-hosted remote account, inventory and latched breaker.
Actual tunnel interruption made current account values unavailable and retained the historical timestamp.
Restoration recovered observations in the same UI; execution stayed disabled.
Wrong SSH host key was rejected (exit 255) and invalid API bearer returned 401.
Full Core shutdown/restart and final sign-in acceptance are recorded separately as they complete.

Untested or incomplete: provider/network-wide extended failure, lifetime history backfill,
full historical position lifecycle, arbitrary legacy delivery recovery, nonadmin Windows-account
migration, encrypted offsite backup restoration and packaged native Tauri executable acceptance.
The source snapshot and UI build are versioned; this is not a newly frozen desktop executable.

## Operational incident during acceptance

A diagnostic accidentally serialized PowerShell provider metadata into oversized output, contributing
to CPU/memory pressure. Owned diagnostic sessions were stopped. After the operator closed empty
diagnostic PowerShell windows, resource checks recovered from about 84% CPU / 91% RAM to 14% CPU /
24% RAM with 4.5 GiB available. Subsequent diagnostics use bounded primitives/native metrics.
This was an acceptance tooling defect, not evidence that MT5 needs a larger VPS.
Docker Desktop installation was cancelled by the operator; Windows Server is not a supported
Docker Desktop host. No Docker dependency was added to the VPS gateway.

## Recovery and rollback

Keep RDP/provider-console recovery available, especially if the desktop public IP changes.
Do not loosen firewall rules, bypass host-key verification or delete journal state to restore connectivity.
Start the existing observation-tunnel task; it reconnects with bounded backoff.
Use the versioned Start-Core.ps1 with the protected existing gateway profile and private log directory.
Do not launch another Core while port 5000 or the existing Core owner is active.
Check Core health, /api/trading/sessions, broker observation time and account identity before UI acceptance.

Gateway rollback: stop only Niblit-VPS-Gateway-0.2, restore its previous action arguments and working
directory from C:/NiblitGateway/artifacts/p2-022-rollback.json, and start it again. Retain the shared state
database; additive metadata tables are ignored by the older release. Do not restore an old database
over newer journal events. Local pre-cutover backups are recovery evidence, not routine rollback.
Retain the 0.2.0 virtual environment because both newer gateway releases reference it.

Core rollback: gracefully stop only the owned staged Core API, then launch the previous reviewed
release/profile. Never rearm sessions or clear breaker/control tables. Existing canonical state is shared.
UI rollback: select the prior versioned UI build; retain current account-unavailable semantics.

## Next milestone

Finish the coordinated Windows sign-in drill and sustained final acceptance. After that, implement
bounded history/backfill/lifecycle acceptance and nonadmin/offsite recovery hardening before considering
any further financial authority. No funded execution approval is implied by a successful observation run.


## Exness demo extension — 2026-11-07 (supersedes earlier pending/current-state claims)

The earlier Phase 2 sign-in acceptance is now evidenced in outputs/NIBLIT_DAE1_P2_SIGNIN_ACCEPTANCE.json: the automatic terminal and gateway start passed after actual Windows sign-in. Windows sign-in is still required; no unattended auto-login was added. Full lifetime history/non-admin/offsite recovery remain pending.

At the operator's request the existing VPS terminal is now Exness Technologies Ltd, DEMO 100000002 on Exness-MT5Trial10, terminal identity 1741e470ad3a01c44884. Fresh readback verified virtual equity/balance 10000 and advancing BTCUSDm/ETHUSDm ticks. XMGlobal-MT5 12 / 100000001 is not currently authenticated on that shared terminal. Its historical balance is not current proof. XM's reconciliation latch is retained and all funded mutations remain disabled.

Gateway 0.3.3 at C:/NiblitGateway/releases/0.3.3-exness-demo-20261107-r5 adds separately scoped, pinned demo RPCs using the existing DemoOrders/MT5SessionAdapter; it runs no strategies and never switches accounts. Desktop Core release outputs/releases/exness-demo-20261107-r3 uses modules/remote_demo_adapter.py with optional NIBLIT_EXNESS_DEMO_PROFILE (omitted means no demo registration). Existing Core permissions, admission, canonical trading ledger/outbox, six strategies and hosted Market Desk are used. Heavy inference stays desktop. No auto-activation/renewal after restart or expiry.

An explicit one-entry, 0.01-lot BTCUSDm scope was activated within the original ~18:38 SAST window. First attempt was rejected before delivery (durable PREVIEW, later REJECTED); the original exact preflight cause was not recorded. No confirmed demo fill/exit exists yet; current strategies were WAIT at acceptance. Final guard checks exact SDK demo identity immediately before delivery. ETHUSDm min 0.10 is above the unchanged 0.01 cap. SNXUSDm is listed but trading disabled and last quoted October 2024; no stale or substitute feed is claimed current. Broker costs/subtype are UNKNOWN where unverified.

169 regression tests passed; final additional SDK-boundary tightening passed all 29 overlapping Exness cases. Separate gateway 16-test suite passed on the real VPS. Actual Core/React UI quote display and tunnel outage/recovery passed with execution fail-closed. Separate daily demo journal backup is configured. See docs/architecture/EXNESS_REMOTE_DEMO_ACCEPTANCE.md and task outputs/NIBLIT_EXNESS_RELEASE_MANIFEST.json for exact paths, evidence, rollback and limitations. This is not a claim that original full XM Phase 2 or a broker demo fill/exit cycle is complete.

Final update, 18:39 SAST: original demo window EXPIRED without automatic renewal; all six strategies WAIT, zero current positions/pending orders, no confirmed Niblit fill. Two pre-delivery rejections are reconciled. One was explicitly price_moved_outside_review under the old USD 0.20 BTC review band. Gateway 0.3.3 now reports and enforces remote crypto review fraction 0.0001 (greater of that relative amount and the legacy 20-point floor); all risk/volume/protection limits remain. Existing desktop demo default is unchanged. Final 43 overlapping crypto/order tests passed and the real VPS's 16 gateway tests passed before deployment. Latest virtual balance 9999.20 is not attributed to a Niblit fill. Use Review demo scope → Activate reviewed demo scope for a new explicit bounded session. Final UI evidence: outputs/NIBLIT_EXNESS_MARKET_DESK_FINAL.png. No funded authority was enabled.


## Broker selector, demo roundtrip and crypto protection — 2026-11-07

Market Desk now offers Follow MT5 / XM read-only / Exness demo views, and explicit scoped Review / Enable / Stop demo controls. View selection never changes the MT5 login or grants authority. Live UI verified XM fresh/read-only, Exness mismatch blocking, and subsequent Exness DEMO SDK verification after the user's manual switch. Nine Node UI cases and 27 gateway protocol cases passed. A real Niblit Exness BTCUSDm 0.01-lot position 546973967 was broker-confirmed opened/closed, linked exit deal 480380847, realized net -0.07 virtual USD under the OLD stop rule. It is not a funded trade or a performance/commission-schedule claim.

At the user's request, gateway 0.4.0 and Core outputs/releases/crypto-protection-20261107-r1 replace the remote crypto stop rule with crypto-atr-structure/1: completed M5 Wilder TR14, 2–2.5 ATR by strategy, swing structure plus 0.25 ATR buffer, >=3 spreads and broker distances, actual tick grid, initially 2R gross target. Reviewed prices freeze before delivery. Too-wide/unaffordable stops reject entry; no tighter fallback or stop widening. Existing desktop/forex defaults and all cash/lot/margin/funded limits remain. Core grants bind the exact protection policy. Both directions passed real Exness non-delivering order_check (example 133.67 USD distance, 1.33–1.34 USD estimated loss at 0.01 lots); no new ATR-policy fill/exit is claimed yet. 206 regression and 67 overlapping targeted cases passed; 16 gateway tests passed on VPS. See docs/architecture/CRYPTO_STOP_POLICY.md and task outputs/NIBLIT_CRYPTO_STOP_LIVE_PREFLIGHT.json.

Gateway release C:/NiblitGateway/releases/0.4.0-crypto-protection-20261107-r1 uses unchanged protected account config, credentials, shared venv and journals. Demo scopes paused for fresh review; no automatic rearm. Existing broker positions/MT5/r8 were not modified or terminated. Funded governor unchanged and funded execution disabled; XM breaker preserved. DAE-1 still has independent reconciliation/history/non-admin/offsite-recovery acceptance remaining.
