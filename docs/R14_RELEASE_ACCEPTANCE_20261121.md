# Niblit r14 — Handover Contract Packaged Release Acceptance (2026-11-21)

## Result
**Built and offline-validated. NOT activated as the primary runtime; no broker execution authorization transferred.**

### New Windows Core package
- Root: D:\NiblitAIOS\releases\candidates\build-20261121-r14-handover-contract
- Core: D:\NiblitAIOS\releases\candidates\build-20261121-r14-handover-contract\niblit\niblit.exe
- Core SHA-256: e7ad9914a4e1ed25ea65d05be1327a459c87ebe2c0a58365b99942ccc345a156
- Standalone observer: D:\NiblitAIOS\releases\candidates\build-20261121-r14-handover-contract\handover\niblit-handover-observer\niblit-handover-observer.exe
- Observer SHA-256: 76e030d6702e9d5a9bd2f83af8f512ef4d0f15afccb7e07730b2d5f6561b505b
- Release launcher: D:\NiblitAIOS\releases\candidates\build-20261121-r14-handover-contract\Start-R14-Handover-Observer.ps1
- Separate Core observation profile: D:\NiblitAIOS\config\r14-observe-20261121\r14-observe.env
- Versioned installation manifest and hash anchor verified. Intended r14 API port 5202, but no r14 Core server has been started.

### Contents
- New modules.mt5_adoption_lease verified inside the frozen Core PyInstaller archive, alongside modules.position_exit_policy and modules.adaptive_market_cognition.
- Source copies of scripts/mt5_handover_observer.py, mt5_active_exit_advisory.py, mt5_readonly_reconciliation.py and Start-R13-Handover-Observer.ps1 in niblit/tools/handover.
- Bundled Tauri UI, local Cloud executable, Lean Algos executable, Freqtrade worker, browser assets and existing runtime files.
- Reused validated r13 sidecar staging inputs; r14 Core compiled from current Niblit repository, HEAD 301571f0 plus uncommitted changes. No source worktree reset/clean/stash.
- r14 configured with isolated memory and a read-only backup copy of the r13 SQLite memory ledger, separate runtime paths, order execution and demo delivery disabled.

### Checks
- Source regression suite: 53 passed covering adoption lease, broker provenance, native MT5 reconciliation, read-only exit advisory and exit policy.
- Frozen Core release preflight: 14/14 required file checks and 18/18 frozen import checks passed (exit 0). No services started or real orders submitted.
- Frozen trading self-test: PASS for MT5 and Freqtrade offline broker doubles, with real_broker_orders=0 (exit 0).
- Standalone observer first build had a NumPy import failure; rebuilt with NumPy collected. The corrected standalone exe passed a real read-only MT5 receipt check (exit 0).
- Release Start-R14-Handover-Observer.ps1 one-shot succeeded, confirming BTCUSDm ticket 591704289, verified broker receipt and original Core prepared-ticket attribution, no pending orders, and read-only exit advice HOLD_OR_ABSTAIN.
- Ownership review remains BLOCKED: old runtime has not issued an explicit durable ownership release. The observer reports execution_authorized=false, trading_ownership_transferred=false, orders_submitted=0.
- Packaged Core and observer SHA-256 hashes recorded above. Manifest anchor hash verified against the versioned installation manifest.

### Runtime preservation
- r12 on 127.0.0.1:5200 returned HTTP 200, original demo owner unchanged.
- r13 on 127.0.0.1:5201 returned HTTP 200, observation-only unchanged.
- r14 port 5202 is NOT listening; the new release was packaged, not activated. Existing active MT5 demo position and protective levels were not modified.

### Running packaged observer on demand
PowerShell:
  & 'D:\NiblitAIOS\releases\candidates\build-20261121-r14-handover-contract\Start-R14-Handover-Observer.ps1'
For ongoing observation in the current terminal session:
  & 'D:\NiblitAIOS\releases\candidates\build-20261121-r14-handover-contract\Start-R14-Handover-Observer.ps1' -Watch
Snapshot: D:\NiblitAIOS\data\r14-observe-20261121\mt5-handover-latest.json

### Acceptance limitation
This is a packaged observation/ownership-contract candidate. The advisory mutex is not wired to both frozen runtimes' order controllers and must not be interpreted as an ownership handover or broker close authority. Real-money trading remains disabled and unapproved. A controlled runtime adoption protocol, restart/partial-fill/close tests, and an end-to-end broker demo run remain necessary before any execution promotion.
