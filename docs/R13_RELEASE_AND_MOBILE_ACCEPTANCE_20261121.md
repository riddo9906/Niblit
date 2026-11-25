# Niblit r13 desktop release + Android APK acceptance — 2026-11-21

## Release decision
**R13 is a completed, isolated, offline-validated desktop build. It is NOT live-money accepted or deployed as the active runtime.**
R11 and the running r12 installation are retained untouched. The existing MT5 demo position and broker protective orders were not modified.

## Windows desktop candidate
- Bundle: D:\NiblitAIOS\releases\candidates\build-20261121-r13-exit-dqi\niblit
- Executable: D:\NiblitAIOS\releases\candidates\build-20261121-r13-exit-dqi\niblit\niblit.exe
- Core executable SHA-256: 8f63a4b4b660d8261b7ff4f8cac2123c63f9436be69c1558e9afb7f7ee689766
- Installation manifest: D:\NiblitAIOS\config\demo-controls-20261115\installation-build-20261121-r13-exit-dqi.json
- The release-runtime manifest anchor hash was independently verified to match.
- Built from branch fix/exness-demo-readiness-20261118 at HEAD 301571f0 with uncommitted cognition/exit fixes preserved. Source hashes captured at finalization in release-provenance.json.
- The frozen archive contains modules.adaptive_market_cognition and modules.position_exit_policy. Freebuff Task 06 completed evidence-aware-v2 source before Core compilation; its status/result documentation was captured in the release provenance.
- New candidate includes Core, Tauri UI, local Cloud server/llama.cpp sidecar, Lean Algos, Freqtrade worker, trading/memory/client portal assets, strategy and launcher scripts. No services started during packaging.
- Frozen --release-preflight: 14/14 bundle checks and 18/18 frozen module imports passed; services_started=false, orders_submitted=false.
- Frozen --trading-selftest: PASS; MT5 broker double PASS (2 fixture submissions, 20 durable events, stopped session); Freqtrade broker double PASS (2 fixture submissions); real broker orders 0.
- Source-level exit/advisory/memory targeted tests: 16 passed in the prior integration run.
- Freebuff Task 06: 62 cognition/governance tests and 75 integration tests passed as documented. One unrelated server websocket test was explicitly deselected due to a pre-existing query_params mismatch.
- First full-build Core PyInstaller attempt crashed with Windows access violation 0xC0000005. A second **Core-only** retry with Python fault handler completed successfully (exit 0), reusing the successfully built sidecars. Offline poststage assets and fresh release binding were finalized independently. Diagnostic log: D:\NiblitAIOS\diagnostics\r13-core-faulthandler.log.
- No r13 Core runtime startup on an independent port, authenticated Qdrant write/recall, native broker live order/exit, mobile device installation, or full end-to-end acceptance was performed. Do not infer those outcomes from the offline self-test.

## Android mobile APK
- APK: D:\NiblitAIOS\releases\mobile\niblit-ai-v0.2.1-debug.apk
- SHA-256: 52904AE3C69C05C385F13D9D4F9C748C3AA96E60B1F64FE7BD20A97EF86C7BCE
- Size: 838361 bytes.
- Rebuild from Android SDK + Java 17 installed on drive D succeeded (Gradle 33 up-to-date tasks, exit 0).
- APK Signature Scheme v2 verification succeeded with one signer. Personal debug distribution, NOT Play Store signing.
- Mobile gateway tests: 6 passed. Local gateway /mobile/ HTTP 200, unauthenticated /mobile/models and /mobile/me return HTTP 401.
- Private tailnet delivery URL https://niblit.tail9bfde8.ts.net/mobile/apk was downloaded directly through the connected Windows host. The served APK matched the local APK SHA-256 exactly.
- The Android app connects to Niblit Core/Cloud and approved Client Portal accounts, exposing read-only markets and AI chat, not broker order submission.
- ADB devices list was empty, so physical installation, login/signup/admin approval, Android interaction, multi-turn LLM and mobile market observations remain unverified.

## Installation
On the Android phone, sign in to the same private Tailscale tailnet, open https://niblit.tail9bfde8.ts.net/mobile/apk, install the debug app from a trusted file manager, and enter https://niblit.tail9bfde8.ts.net as the Gateway URL on the Account screen. Sign in with an administrator-approved Niblit Client Portal account.

## Live-money boundary
R13 is not approved for real-money trading. Remaining blockers include the previously observed /api/trading/positions HTTP 503, unresolved historical EURUSD order state, Freqtrade engine/account-identity mismatch, and demo/dry-run-only execution implementations. Need full broker-native ownership, fill, restart/reconnect, partial-fill, fees/slippage, exit lifecycle and profitability evidence before live execution.

## Preservation
- Current r12 Core remains the running executable on port 5200; older r11 is kept for rollback.
- No real-money order, broker stop adjustment, Freqtrade live activation, or account change was performed.
- No user worktree changes were reset, stashed or cleaned.
