# Niblit AI Mobile v0.2.1 — Android debug APK

Niblit AI Mobile is a native Android frontend connected to the existing Windows-hosted Core, local models and Client Portal account system. **This is a signed debug build for personal device testing, not a Play Store release.** It does not include or control the MT5/Freqtrade trading engines.

## Build completed on 21 November 2026

- APK: `D:\NiblitAIOS\releases\mobile\niblit-ai-v0.2.1-debug.apk`
- Source: `android\NiblitMobile\app\src\main\java\ai\niblit\mobile\MainActivity.kt`
- Android package `ai.niblit.mobile`, version **0.2.1**, versionCode **3**
- Minimum Android 8 (API 26); targets API 35
- Kotlin/Gradle `assembleDebug`: **BUILD SUCCESSFUL**
- Android APK Signature v2 verification: **passed**
- SHA-256: `52904AE3C69C05C385F13D9D4F9C748C3AA96E60B1F64FE7BD20A97EF86C7BCE`
- Backend gateway unit tests: **6 passed** (`niblit-cloud-server/tests/test_mobile_gateway.py`).
- Physical installation, touch layout and ChatGPT-like interaction testing: **NOT DONE**; no Android phone was connected to ADB.

## New AI-app layout

- **Chat:** branded welcome, quick prompts, model selector, role-labelled conversation bubbles and a message composer.
- **Markets:** separate read-only market-observation list and evidence-grounded AI briefs.
- **Account:** Client Portal login, registration with administrator approval, sign out and account ID.
- Recent chat context is passed to the model as the last 10 prior messages plus the new prompt, bounded to 24 in-memory messages.
- Session credentials and conversations are not persisted to device storage. The APK has only the INTERNET permission.
- Never embeds broker credentials, mobile tokens, API secrets or trading execution.

## Connect your phone

1. Ensure the phone has **Tailscale** and is signed in to the **same private tailnet** as the PC.
2. On the phone, open **https://niblit.tail9bfde8.ts.net/mobile/apk** to download the APK through the private HTTPS gateway. You can alternatively copy the APK from the Windows path above by USB/Bluetooth.
3. Open the downloaded APK in your trusted file manager and allow that manager to install it. This is a **debug** app for personal device testing only.
4. Open **Niblit AI → Account** and enter this private HTTPS Gateway URL: `https://niblit.tail9bfde8.ts.net`
5. Sign in with an already approved Niblit Client Portal account. Registration requests require administrator approval.
6. Navigate to **Chat**, refresh the local model list and send a message. Test short and multi-turn chats. Navigate to **Markets** to view read-only observations and request an advisory.

The Tailscale HTTPS endpoint is **tailnet-only**, not an Internet-public deployment. The desktop proxy forwards to the loopback mobile gateway at `http://127.0.0.1:8214`. The gateway was started and responded `GET /mobile/` → HTTP 200, unauthenticated `/mobile/models` and `/mobile/me` → HTTP 401. The tailnet HTTPS URL likewise returned 200/401. The desktop Core continues at port 5200.

If the desktop gateway is not running after a reboot, start it with:
```powershell
& 'C:\Users\Riyaad\Documents\GitHub\Niblit\scripts\Start-Niblit-Mobile-Gateway.ps1'
```

## Rebuild the app

Java 17, Android SDK Platform 35, Build Tools 35 and Gradle 8.9 are already installed under `D:\NiblitAIOS\toolchains\android`. Rebuild with:
```powershell
& 'C:\Users\Riyaad\Documents\GitHub\Niblit\scripts\Build-Niblit-Android.ps1'
```
The script uses the D-drive toolchain and writes only a new or bit-for-bit matching v0.2.1 APK to the versioned release path. Increase versionCode/name and release artifact filename before changing this version again.

## Remaining mobile acceptance

- Install and launch on the actual Android device; verify appearance, keyboard, scroll/bubble usability and account approval flow.
- Verify both 3B and 14B model replies, multi-turn context, gateway reconnection and logout.
- Verify market observations and advisory error handling when Core/Freqtrade is unavailable.
- The Android gateway does not expose trade submission, execution grants, or position closing. Live trading validation is separate and remains incomplete.
