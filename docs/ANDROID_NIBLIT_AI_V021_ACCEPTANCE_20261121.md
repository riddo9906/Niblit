# Niblit AI Android v0.2.1 — verified local delivery (2026-11-21)

## Completed
- Native Kotlin UI redesigned into independent Chat / Markets / Account surfaces, with AI-style message bubbles, model discovery, quick prompts and bounded multi-turn context. Mobile chat requests now respect the gateway's 12-message limit (up to 10 historical messages + current user request) and 6000-character message limit.
- Application label `Niblit AI`, custom launcher vector icon, versionCode 3, versionName 0.2.1, Android API 26–35.
- Native build via the D-drive Java 17 / Android SDK 35 / Gradle 8.9 toolchain: `assembleDebug` **BUILD SUCCESSFUL**.
- Signed debug APK copied to `D:\NiblitAIOS\releases\mobile\niblit-ai-v0.2.1-debug.apk` (838361 bytes).
- SHA-256 `52904AE3C69C05C385F13D9D4F9C748C3AA96E60B1F64FE7BD20A97EF86C7BCE`.
- Android APK Signature Scheme v2 verification **PASSED**; package badge and icon verified with AAPT.
- `niblit-cloud-server/tests/test_mobile_gateway.py`: **6 passed**.
- New fixed-file `GET /mobile/apk` route is available only via the existing loopback mobile gateway / tailnet-only HTTPS proxy; no user-controlled paths, no credentials or broker orders in the APK.
- Gateway restarted under owner-controlled PID to load new route; local `/mobile/` returned HTTP 200, unauthenticated `/mobile/models` returned 401, `/mobile/apk` returned 200 with 838361 bytes.
- **Verified real HTTPS download from `https://niblit.tail9bfde8.ts.net/mobile/apk`** and SHA-256 equality to the source APK; temporary verification copy deleted.
- Core remained running and healthy on port 5200; MT5 terminal stayed running. No trading configuration, position, or order was modified.

## Android installation
On an Android device signed in to the same private Tailscale tailnet, open `https://niblit.tail9bfde8.ts.net/mobile/apk` and install the downloaded APK. In the app's Account tab, use gateway origin `https://niblit.tail9bfde8.ts.net`, then sign in with an approved Client Portal account. Chat/market APIs require authentication. Registration goes through existing admin approval.

## Limits
- **Not installed on physical Android**: ADB showed no attached device. No UI touch/visual/emulator acceptance yet.
- APK is locally debug-signed, not production/release-signed or Play Store compliant.
- Chat uses bounded session context, not a tested persistent Core/Qdrant cognition conversation pipeline. Market advisory is read-only.
- No live trading, order submission, exit control or broker account management exists in the Android client. R12 live-account trading acceptance remains independently blocked.
- Freebuff Task 06 DQI work is an independent pending handoff; these Android changes did not alter its cognition files.
