# Phase 6 November 8 runtime acceptance — 2026-11-12

## Implemented and installed

The existing November 8 release at `C:\Users\Operator\Documents\GitHub\Niblit\dist\releases\build-2026-11-08T08-51-03-322Z-4395fdf0\niblit` was updated from a separately built and tested candidate. Its installed executable passed phase6 preflight, release preflight and broker-double trading self-test. The 56-file update has per-file SHA-256 checksums in `work/phase6/nov8-update-plan.json`; verified preimages are in `work/phase6/nov8-rollback/manifest.json`. No new Core, strategy engine or broker execution authority was introduced. Current acceptance Core PID is 23452; earlier r5 Core was retired.

New modules: `modules/observation_supervisor.py`, `modules/cognitive_observation_runtime.py`, `modules/remote_market_intelligence.py`, `modules/memory_laboratory/cognitive.py`, `modules/phase6_preflight.py`. Extended: `modules/desktop_market_intelligence.py`, `modules/niblit_ui_launcher.py`, `niblit_core.py`, `server.py`, `main.py`, and existing `assets/trading-desk` HTML/JavaScript. Focused tests cover the new observer, memory contracts, API ownership and existing launcher integration.

## Actual topology and contracts

Desktop MT5 → existing MT5Bridge → shared snapshot/evidence analysis → existing six-strategy Core ingress → canonical SQLite/outbox → existing Market Desk. Independently: VPS MT5 → gateway 0.5.1 loopback API → host-key-pinned SSH tunnel → existing remote demo adapter (read-only market operation) → same analysis ingress. Source lanes are independent, bounded and identity-bound. Account and terminal IDs are retained separately. Desktop M5/H1/H4 and remote M5 are implemented; missing remote higher frames remain unavailable.

Both terminals were bound to Exness demo 100000002 on Exness-MT5Trial10. Last historical inventory was empty; balance/equity was 9999.13 USD virtual. Current values must come from fresh readback. XM live 100000001 / XMGlobal-MT5 12 remains configured but is not authenticated on the shared VPS terminal while Exness is selected; it must not be reported as XM verified.

Versioned observer and NUCM/2 episodes retain availability time, provenance, epistemic type and immutable identifiers. Canonical episode insertion and outbox enqueue are transactional and idempotent. The two actual Core analysis receipts each contain six strategy candidates and HOLD, with execution false. Their latest projection state is in `work/phase6/nov8-cognition-readback-final.json`; canonical persistence does not establish completed Qdrant projection or verified predictive accuracy.

## Failure and UI acceptance

The actual November 8 API proves ownership by PID and bound Core. A foreign Core on port 5000 now blocks UI launch instead of being silently accepted. The native Tauri overview was inspected; the installed Market Desk served by that same Core was exercised in Chrome. Tunnel interruption made VPS observations unavailable/stale and blocked demo execution while desktop observation remained fresh. Restoring the original pinned tunnel recovered both sources automatically. Evidence: `nov8-tunnel-outage.json`, `nov8-tunnel-recovery.json`, `nov8-live-status.json` and the Market Desk screenshots in outputs. Gateway/MT5 were not stopped for this test.

Demo proposal forms now expose cash risk, equity risk, margin and position limits, plus a 900-second preset. Editing invalidates the previous review. A real review was tested at 0.1 lot; no Activate action was taken. The prior demo session was paused with user approval and was not reactivated. Hard risk and volume ceilings were preserved. This preset is a session duration, not proof of a calibrated scalping engine.

## Verification

358 regression tests passed, zero failed/skipped in the final broad run; two additional comparison tests and the Node UI check passed separately. The 104-test launcher run overlaps the broad suite and must not be added to that count. An initial ALE timing failure and initial mock ownership failures remain in retained logs; the final runs passed. Three offline preflights passed on the actual installed executable. No funded test orders were used.

The first updated UI/Core run exited after live readback; the cause was not established. The subsequent observed run remained operational through the tunnel failure/recovery test. Cold boot, sign-in startup and long-duration reliability were not re-proven in this milestone.

## Storage

Approved cache cleanup removed 40,451 unchanged .pyc files (784.80 MiB logical bytes); skipped 0. Original .py sources were checked before each removal; no directories, models, databases, configuration, package source, Docker volumes or Git objects were removed. Free-space changes include other concurrent writers. Caches regenerate on import; no runtime restart is required.

The audit measured 17.076 GiB readable logical files and 15.376 GiB unique NTFS file lengths, with 103 access errors and five skipped links. Full allocated workspace size remains unknown. Build/Rust/dependency cleanup remains proposal-only. Existing Git packs verified; eleven unmatched .idx files were preserved for investigation. No Git history was rewritten or pruned. See NIBLIT_PHASE6_STORAGE_AUDIT.md.

## Restrictions and incomplete scope

Funded submission/modification/cancellation/closure remain disabled. No breaker was automatically cleared; no demo session was reactivated. Inference remains native; no new model instance or paid inference was started for acceptance. Existing Qdrant volumes and collections were preserved.

This is a working Phase 6 vertical slice, not full completion. Remaining work includes calibrated predictions and walk-forward evaluation, full NUCM task-aware retrieval/graph expansion/consolidation/checkpoint restoration, MQL5 publisher acceptance, additional indicators/timeframes, complete capability activation coverage, full containerized Core integration and independent Kubernetes validation. Higher trading ceilings, live execution and intricate scalp-wave logic are not enabled. Containers and prior backup/restore evidence remain distinct from this native runtime acceptance.

## Recovery and rollback

Use the existing pinned tunnel supervisor after confirming the configured host identity. Never bypass host-key verification. For code rollback, first stop the updated Core/UI normally, then run `apply-nov8-update.py rollback` from work/phase6 with the original project interpreter. It refuses changed target files and uses the verified 56-file preimages and environment append receipt. Do not restore an old database or trading authorization as part of code rollback. Canonical online backup and integrity receipt are retained under outputs/backups/phase6-before-cognitive. Bytecode caches regenerate from preserved sources.

Next dependency-ready milestone: diagnose the unexplained exit, sustain runtime acceptance, then add bounded out-of-sample pattern evaluation and inspect projection backlog before extending execution controls.
