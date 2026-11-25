# Niblit Android + 14B local inference build plan
Date: 2026-11-21

## Constraints and dependencies
- Preserve R7 trading; no mandatory automation latch, no funded execution.
- Existing Cloud default remains 3B. 14B remains a separate CPU-local sidecar at 127.0.0.1:8967, never cloned into Cloud's process memory.
- Android phone cannot reach Windows `127.0.0.1`: it needs a private encrypted tunnel and an authenticated reverse proxy/gateway over HTTPS. Do not bind Niblit Core's unauthenticated trading/session endpoints to all interfaces.
- Native Android SDK, JDK, Gradle and ADB were **not installed** on the PC at initial discovery. Source can be created/tested on desktop, APK compilation cannot be claimed yet.

## Phase A: Cloud model routing
1. Identify existing Niblit Cloud model directory/aliases and desktop model picker.
2. Register 14B under `qwen2.5-coder-14b` with `large-coder` alias, keeping `qwen2.5-coder-3b` default.
3. Add a dedicated sidecar-backed model engine for 14B targeting fixed localhost 8967 and the existing API-key file. Do not load 14B a second time.
4. Advertise 14B only when its local sidecar is healthy; explicit 14B requests must not silently fall back to 3B.
5. Add regression tests for model identity, unhealthy engine, forbidden outbound URL, model discovery, and real reply validation.
6. Start a separate source Cloud test service; verify model list and full response. Promote the Cloud/desktop UI only after independent smoke verification and broker-state checks.

## Phase B: Android native UI
1. Create a standalone Android/Kotlin application in `Niblit/android/NiblitMobile`.
2. Screens: connection settings, model list/selection, chat with generation results, read-only market observers.
3. Use Android system TLS with **HTTPS-only private gateway** and a per-device short-lived bearer token. Never embed Windows inference API secrets in the APK or JavaScript.
4. Do not expose MT5/Freqtrade order execution to the mobile app in v1. Observation is read-only.
5. Package manifests, Gradle project and documented build commands. Install Android Studio/SDK/JDK before generating an APK.
6. Acceptance: correct model identity, network request timeouts, safe error handling, offline state, server address validation, and no cleartext Internet permission.

## Phase C: Secure mobile connectivity and deployment
1. Connect phone and desktop over an authenticated private VPN (e.g. Tailscale/WireGuard).
2. Put a tightly scoped HTTPS gateway between the phone and Niblit Cloud/Core; endpoints only for models, chat and read-only market summaries. Store mobile session tokens with Android Keystore or request token each launch; no local hard-coded credentials.
3. Verify on phone and native APK. Record exact tested Android version/device, installed APK checksums and first-run results.

## Completion definition
Actual 14B reply through Cloud + selectable desktop model and a built, signed Android APK with authenticated HTTPS reachability and read-only observation. A source scaffold or localhost server alone does not meet this definition.

## Implemented and verified on desktop (2026-11-21)
- Cloud source model registry updated in `niblit-cloud-server/app/local_models.py`: four real D: models, large-coder alias, 14B role, 2048-token runtime limit. Existing 3B remains default.
- `app/sidecar_gguf.py` routes only `qwen2.5-coder-14b` to the already-loaded, authenticated llama.cpp process on localhost 8967. It rejects arbitrary remote URLs, does not silently substitute 3B and does not load another 8.37 GB weight copy.
- New isolated Niblit Cloud source service on `http://127.0.0.1:8212`. Direct GET `/v1/models` returned all four model IDs; POST `/v1/chat/completions` selecting 14B returned exact `NIBLIT`, with `requested=resolved=executed=qwen2.5-coder-14b` and `fallback=false`. Production Cloud 8201 (which owns the known-good 3B process) was not replaced.
- Added `app/mobile_gateway.py`: localhost port 8214; separate 64-character random bearer token stored only in the D: config folder; `/mobile/models` and `/mobile/chat` route to already-running 3B/14B servers; `/mobile/observations` reads Core and strips responses down to symbol/adapter/direction/status; **no order send or account mutation APIs**. Unauthenticated model request returned HTTP 401; actual 14B chat returned `NIBLIT`. Observation returned HTTP 503 when Core port 5200 was offline, not invented data.
- Added a responsive desktop/browser mobile-preview UI on `http://127.0.0.1:8214/mobile/`, served with HTTP 200 and token-protected model APIs; no token is stored in browser localStorage.
- Created Android native source in `android/NiblitMobile`: AndroidManifest, Gradle project, MainActivity, documentation and Gradle wrapper config. The phone app requires a separately configured **private HTTPS tunnel** and asks for the mobile token at launch (not persisted); no Android-native order controls.
- Added idempotent launch scripts in `Niblit/scripts/Start-Niblit-Cloud-14B-Preview.ps1` and `Start-Niblit-Mobile-Gateway.ps1` and reused existing `Start-Niblit-14B.ps1`.
- Focused Cloud/mobile tests: **20 passed**; Cloud Git diff validation exit 0. Android manifest XML validation passed; Android APK compilation **not performed** because Java/SDK/Gradle/Android Studio were not installed.
- **Deployment still outstanding:** install Android toolchain and produce signed/tested APK; set up and authenticate a private HTTPS mobile transport; promote four-model Cloud from isolated 8212 into existing production desktop inference path at 8201/through Core 5200 after reviewing active sessions. Current production Chat model picker has not been switched, while the separate mobile preview can already select/use 14B.
