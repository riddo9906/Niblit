# Remote MT5 demo execution recovery — GitHub patch (19 November 2026)

Status: **code committed on draft PR #421; remote runtime, broker acceptance and packaged UI unverified**. Not a live-account trading authorization.

## Why the old UI could not enable execution

The Market Desk and Core kept separate state from the VPS gateway. Core's `trading_control.stopped` could be cleared during activation, whereas the gateway's `remote_demo_meta.stopped` had no reset operation. Once the operator used Core emergency-stop, the Exness view disabled its Review button and could not recover through a newly reviewed demo scope. Generic readiness also mislabeled `exness_demo` as a disabled local transport and tried calling local-only cost/draft methods. Installed builds may additionally have `NIBLIT_DESKTOP_OBSERVATION_ONLY=1` in their pinned environment; no code patch should override that protected deployment setting.

## Intended authority boundary

1. A local operator opens the Core-hosted Market Desk. View selection never switches the VPS account.
2. Core returns a pinned remote demo status with `configured`, `verified`, account identity, terminal Algo Trading permission, outstanding delivery count, Core stop and gateway stop. Live XM remains read-only.
3. Review creates a bounded, account/symbol/risk/policy-hashed **pending** Core session. No broker order or emergency reset occurs.
4. Activation requires the existing authenticated operator nonce, reviewed scope hash, and explicit reset acknowledgement if either stop is latched. Core refuses activation if the installed observation-only lock is active, broker identity is stale/invalid or unresolved delivery exists.
5. Core commits its local scoped activation. Before starting an autonomous worker, it calls the separate pinned demo gateway `/demo/resume` with the one-time Core session ID and review fingerprint. The gateway verifies the exact configured DEMO identity, terminal trading state, readable broker inventory, no uncertain/partial tickets, review expiry and replay uniqueness; then clears only its own demo stop. If the roundtrip fails, Core stops the session and conservatively relatches the demo stop if reset was requested.
6. The existing Core admission/token/stop/risk/broker-protection guards remain mandatory for entries and owned-position exits. This patch never arms funded trading, clears XM reconciliation, adopts preexisting positions or renews a session after expiry.

## Source files

- `modules/permission_manager.py`: no silent local stop clearance when `clear_stop=False`.
- `modules/core_trading_sessions.py`: coordinate both state stores before starting a worker.
- `modules/remote_demo_adapter.py`: pinned outbound scoped resume transport.
- `deploy/vps-gateway/demo_execution.py` and `gateway.py`: authenticated single-use demo recovery and durable replay tracking.
- `assets/trading-desk/exness-demo.js`: enable new review while a recoverable gateway stop is latched; require reset confirmation and display separate deployment-lock errors.
- `modules/trading_session_api.py`: accurate `exness_demo` readiness and deferred broker preflight.
- Dedicated fixture regressions cover local Core stop, remote stop, identity binding, replay and unresolved ticket refusal.

## Operator acceptance after pulling and deploying the matching versions

**Do not treat GitHub source changes as a VPS deployment.** The local Core and the remote gateway must both run compatible reviewed builds. Keep existing VPS state/journals, protected credentials and known-good rollback releases. Do not overwrite the shared SQLite databases.

1. Check the new branch and Git diff; preserve all uncommitted work. Run focused tests in an isolated test profile: `pytest -q tests/test_exness_remote_demo.py tests/test_core_trading_sessions.py tests/test_demo_controls.py tests/test_remote_demo_readiness_policy.py`.
2. Verify the installed UI/Cloud/Core build identity and its pinned manifest; `npm run build` builds an artifact but does not automatically switch the running installation to that artifact. In the pinned configuration, `NIBLIT_DESKTOP_OBSERVATION_ONLY=1` still intentionally denies all activation; change deployment authority only through an explicit reviewed operator release process, not a code bypass.
3. Deploy a versioned *matching* VPS gateway candidate using the existing protected demo credential, tunnel and account binding. Verify the gateway is using the new `resume` route. Preserve the old gateway release and original demo journal for rollback.
4. With an authenticated DEMO account, verified fresh quote/candles, broker inventory, Algo Trading permission and no ambiguous or partial broker tickets, open the Core-hosted Market Desk. Confirm XM live remains read-only and the Exness view displays the exact verified account.
5. Engage emergency stop. Observe both Core and gateway stops latched, with no new orders. Review a new bounded **demo** scope; activation must fail without reset acknowledgement and remain blocked for wrong account, wrong review, stale status or uncertain delivery.
6. Explicitly acknowledge resetting the two demo stops for the new scope. Confirm both states are clear, **but do not infer any profit or actual order until the broker provides order/deal evidence**. Run a brief bounded demo observation/strategy test and verify Core, remote ticket journal and broker ledger reconcile the same order (if any signal meets all conditions). If six strategies abstain, zero orders is the correct result.
7. Stop/expire the session, restart Core and gateway, and verify no automatic rearm, no duplicate resend, unchanged funded restrictions and retained evidence. Test a rollback with binaries only; never roll a journal backward.

## Limitations and follow-up

CI results and all live remote acceptance must be recorded after the actual run. This source patch cannot inspect the currently installed pinned configuration or the live VPS while remote access is disconnected. Existing user reports establish working boot/UI startup but **not** the identity of the active bundled UI, its release manifest, or execution authority. The D: package suggestion should be traced against the running bundle and pinned UI resource after reconnection, not replaced by guessing a path.
