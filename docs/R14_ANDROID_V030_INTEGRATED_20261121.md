# Niblit R14 + Android v0.3.0 integrated release acceptance

## Scope

R14 remains the desktop trading baseline. The Android v0.3.0 client is a native four-tab frontend: Home, AI Chat, Market Desk, and Account. It authenticates through the same Client Portal that supports desktop user registration and administrator approval.

The new mobile-only REST API is embedded inside packaged niblit.exe and starts alongside the Core API on a mobile-enabled installation. It is **not** a raw desktop-shell proxy.

## Files

- Android debug APK: `D:\NiblitAIOS\releases\mobile\niblit-ai-v0.3.0-debug.apk`
- SHA-256: `2D3A3E00CD10368D11A7C7A3EB961830F1920107ACBC9CD62AA04270DACC71C4`
- APK size: 850798 bytes
- Android package: `ai.niblit.mobile`, versionName `0.3.0`, versionCode `4`
- OS compatibility: minimum Android API 26, target API 35.
- Exact Windows icon replicated from Tauri icon.png; source and drawable SHA `48316F090260098621B9F31573E78DE3715D3C7241156302C0EA8E73E35929A0`
- APK Signature Scheme v2 verified by Android apksigner; debug signed, one signer.
- Private APK URL: `https://niblit.tail9bfde8.ts.net/mobile/apk` (available on same private tailnet when the desktop runtime is online). Source gateway route downloaded and matched APK byte-for-byte.
- Integrated desktop candidate: `D:\NiblitAIOS\releases\candidates\build-20261121-r14-mobile-integrated\niblit\niblit.exe`
- Bound config: `D:\NiblitAIOS\config\r14-mobile-20261121\r14-mobile.env`

## Network arrangement

The `niblit.exe` launches, in the same process:
- Niblit Core API on loopback port 5202 (bound trading runtime).
- Client Portal on loopback port 8768.
- Authenticated mobile-only API on loopback port 8214.

Private Tailscale HTTPS proxy must route the mobile domain to port 8214. The Core API and Portal are *not* publicly exposed, and no mobile request can choose an arbitrary upstream Core path.

Mobile session credentials are existing Client Portal session tokens; no broker login/password or API key is placed in the APK. An approved `admin`/owner-role account is required for demo-trading controls, while an authenticated viewer can access read-only observations and local LLM chat.

## Functional controls

- System status and local LLM model selection.
- AI conversation with local desktop models, where those are running.
- Read-only market observations and session/MT5 position-claim summaries.
- Configurable MT5 demo session: instrument (broker symbols allowlisted), duration 15-240 min, max volume <= 0.10 lots, max entries <= 10, max simultaneous positions <= 5, per-trade cash risk <= 25, risk percentage <= 0.25%.
- Core validates all selected limits and broker conditions. Review → Propose → Activate are explicit separate actions. Stop session requires confirmation.
- No funded-account or live-money execution route, no raw shell command routing, and no model-driven action bypass of Core's broker controls.

## Tests run

- Source mobile gateway suite: 6 passed.
- Existing Client Portal, approval mail, deployment, and mobile suite: 16 passed.
- Standalone in-process source Gateway/Portal startup: /mobile/health HTTP200, /api/health HTTP200, unauthorized trading/sessions HTTP401.
- Source HTTPS private APK endpoint downloaded successfully, exact SHA matched release APK.
- Android Gradle assembleDebug BUILD SUCCESSFUL, 33 tasks; apksigner verify (v2), aapt manifest/version/icon verified.
- No Android phone attached via ADB. On-device touch layout, credential login, inference and actual broker demo order tests remain unverified.

## Release acceptance — to be completed

Frozen executable preflight: pending.
Frozen trading self-test: pending.
Frozen main process Core/Portal/mobile service startup: pending.
Frozen private APK route: pending.
Actual authorized mobile sign-in and session execution: pending.

## Installation and operation

1. Run the packaged R14 main executable. For headless desktop server mode, from PowerShell:
   `& 'D:\NiblitAIOS\releases\candidates\build-20261121-r14-mobile-integrated\niblit\niblit.exe' --serve`
2. On the same private Tailscale network, open `https://niblit.tail9bfde8.ts.net/mobile/apk` on Android and install v0.3.0.
3. Account tab → gateway `https://niblit.tail9bfde8.ts.net` → login with approved existing Client Portal account.
4. Market Desk → edit limits → Review → Propose → Activate. Activation does not guarantee an immediate order. Stop prevents new entries, but existing broker positions may remain under their SL/TP.
5. Chat tab → refresh local models. Offline model services will not appear until available.
6. Desktop read-only acceptance: `& 'C:\Users\Riyaad\Documents\GitHub\Niblit\scripts\Test-Niblit-Android-Integrated-R14.ps1'`

## Outstanding

The APK is debug signed for private phone testing, not Play Store distribution. This v0.3.0 provides Niblit's authenticated AI, account, market observation and MT5 demo-session controls; it does not yet mirror every desktop feature (arbitrary task creation, unrestricted files, all MT5 broker order types, or real-money execution). The current Windows Market Desk full visual redesign remains separate work.

## FINAL FROZEN ACCEPTANCE — PASSED (2026-11-21 23:54 SAST)
- Final packaged Core executable built after main.py normal-launch mobile gateway startup integration: `D:\NiblitAIOS\releases\candidates\build-20261121-r14-mobile-integrated\niblit\niblit.exe`
- SHA256: `48632d5c8e9ed7fe5ea7cfc4a5ff9f2bbe1d6f5217a58db712151222fd09300e`
- Frozen preflight passed: **14/14 required files, 18/18 frozen imports**; manifest anchor SHA verified. MT5/Freqtrade frozen broker-double selftests PASS with zero real orders.
- One frozen `niblit.exe --serve` process (PID 10400 at acceptance) launched **three loopback-only services** concurrently, all owned by the same PID: Core 5202 `/health` HTTP200, mobile 8214 `/mobile/health` HTTP200, Client Portal 8768 `/api/health` HTTP200. The packaged acceptance script `Test-Niblit-Android-Integrated-R14.ps1` exited 0.
- A fresh `/api/trading/sessions` GET returned HTTP200 and **0 active trading sessions**. The earlier transient request failure occurred during Core initialization and cleared after startup.
- Anonymous `/mobile/trading/sessions` returned HTTP401. No broker orders were submitted during acceptance.
- New APK **v0.3.0 debug** downloaded from the private Tailscale HTTPS route after frozen startup and verified byte-identical to the generated release APK (SHA256 `2d3a3e00cd10368d11a7c7a3eb961830f1920107acbc9cd62aa04270dacc71c4`, 850798 bytes).
- Source integration tests **116 passed** (mobile, Portal/approval, MT5 Core). APK `assembleDebug` passed, v2 signature verified, zipalign verified, only INTERNET permission. Android launcher icon is byte-identical to Tauri Windows icon PNG.
- The main executable also contains logic to start the API and mobile gateway on ordinary desktop launch when mobile autostart is configured, but a separate no-argument GUI startup test was not performed; `--serve` startup is explicitly verified.
- **Not yet tested on an attached physical Android phone:** installation, approved administrator login through the private tailnet, LLM inference, touch layout and actual demo trade activation from phone. ADB device list empty.
- This release offers authenticated mobile system/chat/market observation and scoped MT5 demo session configuration, review/propose/activate/stop. It does **not** enable arbitrary OS/device control, unrestricted MT5 order edits, position closes or funded trading.
- As of acceptance, the frozen integrated R14 `niblit.exe` was left running; the previous R14 package remains preserved. The earlier one-hour demo session had already expired. No new demo session was activated here.
