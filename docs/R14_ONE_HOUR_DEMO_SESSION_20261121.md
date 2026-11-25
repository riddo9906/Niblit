# R14-v2 one-hour MT5 demo session — 2026-11-21

## Result
**Activated and independently verified from the canonical Core ledger.**
- Core: `D:\NiblitAIOS\releases\candidates\build-20261121-r14-demo-ready-v2\niblit\niblit.exe`
- UI: http://127.0.0.1:5202/market-desk/
- Session ID: `2e68f4f4870c4ed6b5dd29f7de77578d`
- Adapter: MT5, demo-only, symbol ETHUSDm.
- Duration: 3600 seconds, start approximately **2026-11-21 22:51:21 SAST**, expiration **2026-11-21 23:51:21 SAST**.
- Source report: `D:\NiblitAIOS\diagnostics\r14-v2-one-hour-session.json`
- Core status: `active`, observer `mt5/ETHUSDm` `running=True`, no observer error at first postactivation verification.
- ETHUSDm order records: **0 at first observation**. The strategies had no qualifying entry at the earlier readiness review; an active session does not imply an immediate broker trade.
- Native MT5 account: verified `demo=True`, connected. No pending broker orders. Existing BTCUSDm ticket 591704289 remains broker-open at 0.01 lots, with SL and TP present.
- Independent BTC observer: eligible, read-only, current advice HOLD_OR_ABSTAIN. The BTC entry receipt is pinned in a separate evidence file; R14 is not authorized to close the original BTC trade.
- Original R12 trading Core (port 5200) stopped after its authority returned `stopped`, with zero active sessions or in-flight delivery and without killing terminal64.exe.
- R13 remains observation-only at port 5201.
- The session expires automatically after 3600 seconds for new broker permissions. Broker-open positions are not guaranteed to be liquidated exactly at expiry; they continue under the existing broker protection / validated exit lifecycle.

## Fixed and verified before activation
- Rebuilt Core after replacing ambiguous TCP-connect timeout behavior in `modules/mt5_orders.py` with explicit Windows listening socket and old-executable process checks.
- Frozen Core build exit 0; 14/14 file checks, 18/18 frozen imports, offline MT5 and Freqtrade selftests passed (0 real broker orders).
- Versioned build: `build-20261121-r14-demo-ready-v2`, core SHA-256 `77df8774154e0a9140f47dfa37991f2e8d408f623612f2d36eb722b2579282d4`.
- Preserved three pre-migration backups for the new release binding and reused the same R14 installation ID as the existing ledger, resolving an environment-observation identity mismatch. The corrected manifest anchor hash was verified.
- Preserved the original v1 package, the r12 package, and r13 package. No worktree clean/reset/stash.
