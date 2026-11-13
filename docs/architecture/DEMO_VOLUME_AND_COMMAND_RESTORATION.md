# Demo volume editor and command restoration — 2026-11-07

## Delivered behavior

The remote demo panel and local MT5 autonomous session panel now provide **Maximum volume per entry (lots)**. Default is 0.01; reviewed hard maximum is 0.10. This is an upper bound, not forced sizing: broker minimum/step, cash risk, margin, exposure, daily/session loss and drawdown checks can reduce or reject an entry. One position at a time and maximum three reviewed sequential entries remain the UI scope. All entries retain SL/TP. Crypto retains crypto-atr-structure/1; other explicitly configured MT5 symbols use the existing MT5 protective-stop policy.

Editing volume, duration, symbol, entry count or account view invalidates the previous review, including while a request is in flight. Input and change events both invalidate immediately. No existing authorization is enlarged. Choose volume, Review, inspect the exact account and limits, then explicitly Enable. The agent left demo execution paused as requested, reset the editor to 0.01 and did not click Enable.

Manual MT5 human ticket controls retain their separate 0.01 cap. The new larger ceiling applies only to Core-owned autonomous tickets with a current guard. SDK demo classification, exact login/server/broker/terminal binding, expiry, durable tickets and final pre-delivery checks remain mandatory. XM live 100000001 on XMGlobal-MT5 12 remains strictly read-only; the funded governor bytes are unchanged. No funded submission, modification, cancellation or closure was added. No account switching or credentials were requested.

## Implementation

- assets/trading-desk/index.html: remote and local MT5 autonomous volume editors, truthful maximum labels.
- assets/trading-desk/exness-demo.js and sessions.js: volume included in reviewed limits, exact confirmation, immediate and in-flight review invalidation.
- assets/trading-desk/broker-view.js and remote-observation.js: broker-derived remote demo labels and selected demo header preservation.
- modules/core_trading_sessions.py: default 0.01 review, adapter-observed ceiling up to 0.10, fresh ceiling validation on activation/delivery, optional generic NIBLIT_MT5_DEMO_PROFILE alias with legacy compatibility.
- modules/trading_session_adapters.py: size from broker minimum using broker-calculated risk, round down to broker step under the reviewed cap.
- modules/mt5_orders.py: separate autonomous ceiling (constructor default remains 0.01), Core-owned durable guard required for larger tickets; manual tickets unchanged.
- modules/remote_demo_adapter.py: strict pinned Exness, XM or MetaQuotes demo profiles; accepts mt5-demo/1 config while preserving legacy wire/API compatibility.
- deploy/vps-gateway/demo_execution.py: final SDK volume ceiling and exact demo binding; configured symbol allowlist; immutable database/account binding remains enforced.
- deploy/vps-gateway/gateway.py: explicit --demo-max-volume (default 0.01, maximum validated 0.10), --demo-state-name restricted to a single safe directory name, preserving the exness-demo default.
- deploy/vps-gateway/discover_demo.py: bounded existing-terminal, SDK-demo-only, read-only candidate discovery. Never logs in, switches accounts, changes startup, sends orders or overwrites an existing candidate.
- niblit_core.py: essential, idempotent command-registry initialization independent of optional improvements. The reduced launcher previously disabled the registry together with unrelated background services.

## Actual releases and runtime

Desktop: outputs/releases/demo-volume-commands-20261107-r2/core, supported main.py --serve --headless --quiet; API 127.0.0.1:5000. Existing canonical ledger and protected profile paths retained. UI remains the established React workspace on 127.0.0.1:5173, embedding the actual Core-hosted Market Desk. No new Core or dashboard was introduced.

VPS: C:/NiblitGateway/releases/0.5.1-demo-volume-20261107-r1; existing scheduled gateway task and shared Python environment. Existing MT5 process is unchanged. Demo configuration, credentials and Exness journal retained. Gateway remains bound only to 127.0.0.1:18765 over pinned-key SSH. Prior releases, task arguments and consistent SQLite backups retained for rollback. r8 was not touched.

Exness verification: login 100000002, Exness-MT5Trial10, SDK demo, terminal 1741e470ad3a01c44884. Fresh real broker preflights accepted both buy and sell at exactly 0.02 lots, risk approximately 1.91 USD before unknown charges, with protective stops/targets. Both previews were canceled without submission. Current state must always come from fresh Core readback; saved balance 9999.13 USD is historical evidence only.

## Command restoration and practical limits

The operator API went from `Core command registry is not ready` to 414 exposed original commands at acceptance, with executable/authorization/unavailable states. The existing Commands page displayed 452 combined original and assistant commands. The canonical audit folds aliases and therefore has a different count. Actual `time`, `runtime status` and `tools` command responses were verified. An initial help request exceeded its HTTP deadline during startup; not every command has been executed. Windows shell (`cmd exec`/`ctrl`) and mesh command handlers are registered, retaining existing authorization and confirmation requirements. No blanket permissions, unrestricted shell mode, SSH access expansion or paid inference was enabled.

Nine shell-owned commands remain unavailable on the desktop operator surface by design: debug on/off, exit/quit/shutdown, learn about, notifications history, session summary and sidecar status. They require an actual interactive CLI context. Other unresolved desktop entries were heal, lean algo, lean deploy, memory dump, my (missing callable original handlers) and runtime provider (Ruflo unavailable). No placeholder success or invented implementation was substituted. Availability may improve as optional components finish initializing; timestamped acceptance JSON records the actual observed states. Full capability of unavailable dependencies is NOT claimed. The unchanged native desktop UI tool is not connected, as the tool workspace explicitly reports.

## XM demo / MetaQuotes onboarding

Local MT5 demo: the same volume editor supports broker-confirmed demo accounts, including XM and MetaQuotes (double-tested). Under the active remote profile there is deliberately no direct-desktop MT5 execution fallback.

Remote demo onboarding, once the user adds the account:

1. Stop new demo actions; reconcile all uncertain deliveries and outstanding position obligations. Keep the old account journal and backups. Do not terminate a terminal managing positions.
2. Sign in manually in the VPS MT5 terminal; keep credentials out of chat and source. Confirm that the intended account is DEMO, not XM live.
3. In that same interactive Windows user session run the installed discovery helper with an explicit executable and actual broker symbols. Example: `python discover_demo.py --terminal "C:/Program Files/MetaTrader 5/terminal64.exe" --symbol EURUSD --output "C:/NiblitGateway/config/xm-demo-candidate.json"`. Use the gateway Python environment and candidate release working directory. Symbols must match the actual account. Discovery writes only a candidate and rejects live/unknown accounts.
4. Review exact account/broker/server/terminal and SDK demo classification. Stage the new demo config and protected desktop profile using its printed gateway ID, same verified SSH peer and protected demo credential path. Never substitute the live XM identity.
5. Stage the existing gateway task with `--demo-config <verified candidate> --demo-state-name xm-demo-<login> --demo-max-volume 0.10`. The separate state name avoids reusing or erasing the Exness journal; the immutable binding check also rejects accidental reuse. Keep the primary live XM observation config and state unchanged. The task directory/executable must remain a versioned release with rollback.
6. Verify fresh status, prices, inventories, journal, and demo classification. Only then explicitly enable Algo Trading for the demo account and review a new Core scope. One pinned remote demo is active at a time; switching the shared terminal alone does not register or authorize another account.

XM demo and another MetaQuotes demo have NOT been live-verified because those accounts were not supplied/connected for this task. No credentials are needed until the user adds them directly in MT5. Simulated profile tests are not broker acceptance.

## Validation and rollback

165 demo/Core/order/crypto cases passed across the focused suites (161 +3 local +1 broker minimum); 1 additional read-only discovery test passed. Command suite: 89 passed, 1 optional real-Core bootstrap test skipped; actual Core/API/UI acceptance was performed separately. Existing gateway unittest suite passed before both versioned cutovers. Node tests passed for exact reviewed volume/entry/position limits, immediate input invalidation and stale in-flight response rejection. No real test order was submitted.

Core rollback: while no active grant, open broker obligation or uncertain delivery exists, gracefully exit only the owned staged Core and wait for its process/listener to close. Start the preserved multi-demo-20261107-r2/core or previous demo-volume release through the supported launcher with the same protected profiles and canonical ledger. Never restore an older ledger over newer events. Restart never rearms scopes.

Gateway rollback: stop only Niblit-VPS-Gateway-0.2 after the same safety checks; restore the exact previous task arguments/directory saved in C:/NiblitGateway/artifacts/demo-volume-051-rollback.json and start that task. Retain current journal state; all versions share compatible schema and immutable account binding. Reverify demo identity, no unresolved delivery, loopback binding and funded deny. Keep MT5 running.

Evidence: NIBLIT_DEMO_VOLUME_COMMANDS_ACCEPTANCE.json; NIBLIT_DEMO_VOLUME_LIVE_PREFLIGHT.json; VPS deployment records; command surface/operator/governed snapshots; JUnit XML files; NIBLIT_DEMO_VOLUME_FINAL.png; NIBLIT_COMMANDS_RESTORED.png. Initial permission-folder errors and superseded failed test reports are retained; final suites above supersede them. No claim of unattended reboot acceptance or full DAE-1 completion is made by this change.
