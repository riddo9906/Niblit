# Niblit r9 Android + Client Portal verification — 2026-11-21

## Preserved baseline
- Existing r7 Core remains the working trading baseline at http://127.0.0.1:5200/market-desk/.
- Existing r9 packaged Core: D:\NiblitAIOS\releases\build-20261121-android-14b-r9\niblit\niblit.exe.
- r9 release-preflight.json passed file presence and module checks **only**. It explicitly does not certify live Core, trading, Cloud inference or portal behavior. Do not promote it over r7 without isolated runtime checks and native broker reconciliation.
- Source tree contains prior uncommitted work; no reset, clean, stash, or force push occurred.

## Native Android
- Project: C:\Users\Riyaad\Documents\GitHub\Niblit\android\NiblitMobile
- Android toolchain installed under D:\NiblitAIOS\toolchains\android (JDK 17, Android 35, Gradle 8.9).
- Native Kotlin screens: Client Portal signup/login, account identity, local 3B/14B model picker and chat, read-only multi-market observations, grounded market advisory.
- Signup now explicitly requires the same shared-workspace visibility acknowledgement as the desktop Client Portal. Both Android Kotlin and desktop/mobile browser preview submit shared_workspace_acknowledged=true only after the user consents.
- Android Gradle :app:assembleDebug --offline --no-daemon: BUILD SUCCESSFUL (2026-11-21).
- APK: D:\NiblitAIOS\releases\android\niblit-mobile-r9-consent-debug.apk
- APK SHA256: 3075A7D3DD6FFE03820FD0799B612946D5C1510A2CABA4F08461479BD62C8A6B
- Android phone is not attached over ADB. This is a DEBUG-signed test APK, not a production release-signed distribution.

## Portal and gateway
- Client Portal local administrator page: http://127.0.0.1:8768/admin (HTTP 200).
- Mobile gateway preview: http://127.0.0.1:8214/mobile/ (HTTP 200 before latest gateway reload).
- The mobile gateway uses authenticated sessions from the existing Client Portal: /mobile/signup, /mobile/login, /mobile/me, /mobile/logout. Registration is pending administrator approval; approval email is administrator-directed and does not auto-approve.
- New gateway rule rejects missing/false shared workspace acknowledgement (HTTP 422). This is covered by automated tests; the optional direct live negative-case call was held for operator review.
- Gateway remains bound to 127.0.0.1. No public/LAN binding and no Android broker-execution endpoint were added.

## Verified tests
- Client Portal approval-email tests: 4 passed.
- Cloud/mobile/14B focused tests: 17 passed, including missing/false acknowledgement.
- Android Kotlin debug APK compilation: success.
- Existing portal-backed mobile smoke test previously confirmed real login, account identity, 14B answer NIBLIT, market observation, logout and revoked session HTTP 401.
- Keep source and already-frozen r9 executable distinction explicit: packaged r9 portal.js predates the latest source; rebuild a **new versioned** packaged Core before considering promotion.

## Physical phone setup and remaining work
1. Install the debug APK manually on the Android phone (or attach via USB debugging and use adb install -r with the APK file). Use only the APK from the trusted local desktop.
2. Configure a private encrypted link (WireGuard/Tailscale or equivalent) and private HTTPS reverse proxy terminating on loopback mobile gateway port 8214. Never expose 5200, 8966, 8967 or 8768 directly to the Internet.
3. Enter the resulting HTTPS origin in Android; register with a unique Client Portal username, password and explicit visibility acknowledgement.
4. Verify the pending registration appears in /admin; test the email notification. Administrator must sign in to approve. Re-open Android and sign in after approval.
5. Test model catalog, both model chat responses, and real observer-based market advisory. Test reconnect and session expiry.
6. Complete isolated r9 Core release acceptance and deploy separately after checking native broker orders/sessions, rather than replacing the known-good r7 automatically.

## Refreshed r9 desktop candidate (continuation)
- Full `node scripts/niblit-build.js --tauri` completed, return code 0, after creating the previously absent D: linker temp directory. Log: `D:\NiblitAIOS\diagnostics\android-frontend-20261121\r9-refresh-build-retry.log`.
- Versioned candidate bundle: `D:\NiblitAIOS\releases\candidates\build-20261121-r9-portal-android-refresh\niblit\niblit.exe`.
- Frozen preflight 14/14 files and 18/18 modules; rerun `--release-preflight` exited 0. Service acceptance still separate.
- Client Portal JavaScript SHA256 matches current repository source exactly; includes owner password-change UI and latest approval flow.
- Candidate now has a separate verified `release-runtime.json` binding to the existing approved operator configuration and a generated version-specific installation manifest. Original r7 installed bundle and runtime remain unchanged.
- Android debug APK exported as `D:\NiblitAIOS\releases\android\niblit-mobile-r9-consent-debug.apk` (845074 bytes, SHA256 `3075A7D3DD6FFE03820FD0799B612946D5C1510A2CABA4F08461479BD62C8A6B`).
- Verified: r7 Market Desk HTTP 200, mobile preview `/mobile/` HTTP 200, localhost Portal HTTP 200, latest mobile signup consent check HTTP 422, and 104 focused Core/Portal plus 17 focused Cloud/mobile tests passed.
- r9 candidate deliberately **not started or promoted** while r7 remains in service. No verified phone connection yet; `adb devices` returned no attached Android device. No Tailscale or other private HTTPS transport installed. A physically authenticated private HTTPS connection is required before the native APK can use the gateway; do not enter the loopback HTTP address on the phone.

## Android sign-in feedback fix
- Symptom reported: tapping Sign in appeared unresponsive despite editable credentials.
- Reproduced by source inspection: authenticate validates HTTPS gateway before networking; without configured gateway error was assigned to a status label below the buttons (possibly hidden by keyboard).
- Updated native Kotlin UI: status at top with clear missing-gateway explanation; toast feedback for gateway/credential errors and request failures. Existing Portal credentials/account service unchanged.
- Android debug compile: BUILD SUCCESSFUL.
- Latest APK: D:\NiblitAIOS\releases\android\niblit-mobile-r9-login-feedback-debug.apk
- Remaining blocker: no private HTTPS endpoint configured and no Android device connected via ADB; phone sign-in cannot complete until a secure endpoint is established.

## 2026-11-21 continuation: private HTTPS, r9 and trading-engine verification
- Tailscale Serve verified active at `https://niblit.tail9bfde8.ts.net` with a tailnet-only HTTPS proxy to `http://127.0.0.1:8214`. Do not use the phone's loopback IP or expose the Core directly.
- Browser mobile preview originally defaulted to desktop-only `http://127.0.0.1:8214`; mobile browser login could show `Failed to fetch`. Updated `niblit-cloud-server/app/mobile_ui/mobile-v2.js` to select `location.origin` for HTTPS-hosted pages. HTTPS `/mobile/` and `/mobile-v2.js` both returned HTTP 200 and served the modified asset.
- Native Kotlin APK login feedback update remains available at `D:\NiblitAIOS\releases\android\niblit-mobile-r9-login-feedback-debug.apk`; physical phone login not verified. `No active account` is the preview's signed-out label rather than an account database diagnosis.
- Live r7 Core remains in service at `http://127.0.0.1:5200`. Six MT5/Freqtrade BTC/ETH/SOL observers healthy, legacy EURUSD observer has visible-symbol error. Session API shows 30 total recorded sessions, ONE active MT5 demo BTCUSDm scope with `open,close` actions. Do not launch a second broker-connected Core or replace r7 while that session may have native activity.
- r9 packaged candidate at `D:\NiblitAIOS\releases\candidates\build-20261121-r9-portal-android-refresh\niblit\niblit.exe` passed frozen `--release-preflight` (exit 0). This is not full runtime/broker acceptance. The r9 candidate has not been promoted.
- Trading regression: `tests/test_structured_trade_engine.py`, `test_execution_venue_router.py`, `test_position_exit_policy.py`, `test_trade_performance_metrics.py`, `test_core_trading_sessions.py` passed 120/120 (exit 0). Log `D:\NiblitAIOS\diagnostics\android-frontend-20261121\r9-trading-verification.log`.
- Mobile advisory regression initially failed because explicit evidence projection dropped supplied `rsi14`. Updated `niblit-cloud-server/app/market_advisory.py` to include selected measured indicators (RSI, ATR, averages, prices and trend) while preserving the sanitizer's exclusion of unknown fields. Reran `tests/test_mobile_gateway.py tests/test_sidecar_14b.py`: 9 passed, 0 failed.
- Remaining work before r9 promotion: confirm real mobile sign-in with the Portal owner credentials; complete isolated release runtime acceptance; broker-native reconciliation and operator-controlled transition when the active MT5 demo session is quiescent. No trading orders were requested by these checks.

## Market cognition thesis enhancement (source only; not yet frozen into r9)
- Added `modules/market_thesis.py`: deterministic, evidence-linked observational thesis describing directional agreement/disagreement, abstaining and failed strategies, evidence hash, provenance, re-evaluation conditions, and explicitly uncalibrated uncertainty. No model-based vote or execution authority.
- Attached market_thesis to validated `strategy_manager.assess_observation` results and multi-timeframe `assess_with_context` outputs without changing registered strategy decisions, held position ownership, or broker order code.
- New independent tests `tests/test_market_thesis.py` cover directional, opposing and incomplete strategy-vote cases plus stable evidence fingerprint.
- Existing frozen r9 package and running r7 executable do not contain this new source change. Rebuild a future versioned candidate and run the full isolated acceptance process after any active demo position has been reconciled; do not hot-swap the trading Core.

## r10 cognition candidate build - 2026-11-21
- New isolated full release: D:\NiblitAIOS\releases\candidates\build-20261121-r10-market-cognition\niblit\niblit.exe.
- Build: Tauri UI, Cloud, Lean Algos, Freqtrade worker, Core. Full build completed successfully. Log: D:\NiblitAIOS\diagnostics\android-frontend-20261121\r10-market-cognition-build.log.
- Frozen PYZ-00.toc includes modules.market_thesis; frozen preflight exit 0, files 14/14, modules 18/18; services_started=False, orders_submitted=False.
- r10 release-runtime.json bound to existing approved demo-controls profile; generated new release-specific installation manifest. Existing releases unchanged.
- Affected cognition/market/trading regression: 165 passed, 0 failed. New thesis provenance excludes volatile poll-time as_of, preserving market episode deduplication.
- NOT PROMOTED. r7 runs port 5200 with active MT5 demo session. Broker runtime acceptance and controlled switchover remain separate.
