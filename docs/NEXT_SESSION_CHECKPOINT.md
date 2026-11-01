# Resume checkpoint — 31 October 2026

## Latest check — read this first

Final PyInstaller process increment: unique dated build output/work/staging,
canonical staging env propagated to specs, refuse existing final bundle overwrite,
quoted Python install command, ddgs hidden import. npm run build:plan is read-only.
Three Node build-path tests plus syntax and 20 build-input checks pass. No actual
compilation or working-exe replacement; see BUILD_CONTRACT_AUDIT.md.

Cloud local-AI source audit: CLOUD_LOCAL_AI_AUDIT.md. Existing Ollama11434 adapter,
actual /api/tags discovery and separate provider registry confirmed. Primary
/v1/chat/completions still uses ModelManager→on-disk GGUFEngine, not that registry.
No Docker Model Runner12434-specific app configuration found. Reuse/complete the
partial bridge; downloading a model is not proof primary chat routes to it.
Inspection only; no provider activation or inference.

Unified build audit: BUILD_CONTRACT_AUDIT.md. Existing root npm run build already
chains Tauri/Cloud/Lean/Freqtrade worker/Core. Added read-only npm run build:check
and mandatory full-build preflight (20 checks pass), exact niblit-ui.exe selection,
and Core static desk assets allowlist. Nine existing startup tests and JS syntax
check pass. No full compilation/release overwrite or live service changes.
Full frozen acceptance of newer memory/learning paths remains pending.

Owner discussion map/workbook: BUILD_MAP_2026-10-31.md. Separates verified scopes,
partial integration, staged research and release/hosting blockers; includes a
four-day planning workbook and next-week dependency order. No runtime/config
change was made to produce the map.

Latest completed increment: portable Docker prerequisite detection wired into
Start-Client-Portal.cmd, with per-user/system install discovery, bounded readiness
wait and no reset/rebuild/volume removal. Check-Niblit-Local.cmd exposes the
read-only native dependency check. Eight focused tests passed; actual Docker
version probe returned ready=true/started=false after switching away from slow
`docker info`. Docker portal healthy, Freqtrade and Qdrant running; native model
and gateway readiness passed. No inference, orders or strategy changes made.

Domain status supersedes older notes: both custom names are now attached to
enginehead-company, www redirects to apex. Namecheap DNS still parked; owner
explicitly deferred further domain work because it expires next month. See
DOMAIN_CONNECTION_STATUS.md. Do not continue DNS changes unless requested.

Later on 31 October: restored existing local services. See FOUR_DAY_RUN.md.
Model/memory readiness now PASS, Market Desk EURUSD auto observation is running,
portal health HTTP200, Docker portal/Freqtrade/Qdrant up. Verified Freqtrade
NiblitLabManager dry_run=true, three positions, max_open_trades=3; resumed running
without changing risk. Consistent portal backup created in existing volume.
Fifteen focused checks passed. Vercel portal latest deployment fails missing
FastAPI entrypoint; persistent storage/backend remains unresolved. Company URL
works; custom domain move blocked by automatic review of add-domain attempt.
Do not delete the old domain-owning project or pretend public portal is ready.

Read-only native readiness is now available via
`niblit-env/Scripts/python.exe scripts/check-native-runtime.py`.
It applies the bounded profile to the check only, verifies fixed local model/gateway
endpoints and task-idle state, and never generates, reserves, boots or trades.
Eleven focused readiness/evidence/admission tests passed on 31 October.
The real dependency check reported both model 8766 and gateway 8772 unavailable
from this session. Listener enumeration returned no matching rows. Do not assume
the earlier running-service inventory below is current, or call this full Core
acceptance. Next: establish actual process/listener state, reuse existing services
when present, then follow P1 native boot acceptance. No services were restarted,
no private settings edited, and no new release, APK or cloud deployment produced.

**Current full delivery plan:** [INTEGRATED_DELIVERY_PLAN.md](INTEGRATED_DELIVERY_PLAN.md). Covers runtime/brains, trading/micro/seconds research, native UI/Lean, Windows packaging, cloud and Android. Start with P0/P1; no new release/APK/cloud deployment has been produced by writing the plan.

## Active and verified

- Market Desk: http://127.0.0.1:8767/; MT5 EURUSD observation-only restored.
- Current-moment comparer: immutable forecasts, later scoring and bounded research
  selection. No prediction-based order authority.
- Freqtrade: NiblitLabManager, dry_run=true, running. Native reload HTTP 200;
  three positions before/after, zero forced exits. New filled trades get durable
  adaptive-exit context. Existing trades keep legacy reversal/stop/ROI rules.
- Native container callback acceptance passes. Nineteen focused parity tests pass.
- Local portal/tutor tools and single-task study controls are deployed on 8769.
- Company site: https://enginehead-company.vercel.app/.
- Private portal source: https://github.com/riddo9906/niblit-client-portal.

## Next: micro-trading experiment

Staged `deploy/freqtrade-lab/NiblitMicroDemo.py`; copied alongside native strategies,
but NOT activated, not backtested and not proven profitable. Real 1m indicators,
one open trade, five entries/ten-minute explicitly timestamped session, 45-second
post-close cooldown, stake <=10, <=0.25% planned equity risk including cost reserve,
<=1%/2-unit session realized loss, spread <=0.05%, unchanged 1x leverage.
Missing/expired session means no entries. Exchange minimum above cap means skip.
Use a separate dry-run profile/database. Do not replace the running manager.
First verify full callbacks and forward/cost behaviour; add start/stop UI with
explicit session state, then user-started demo acceptance. No actual micro session
or orders have been started. Stops/time exits can still lose money.

## Remaining direction, in order

1. Consolidate legacy Core/ALE/local inference under one scheduler and shared
   resource budget; the portal/tutor gate does not yet cover every old path.
2. Improve evidence-based memory recall and separate finance/software/general
   curricula; measure answers and gaps rather than counting saved facts.
3. Validate trading entries AND adaptive exits after costs on untouched periods;
   study minute strategies separately. Predictors stay advisory until validated.
4. Complete Path Manager and a clean-machine-tested Windows installer/release.
5. Finish hosted clients: durable cloud database, responder, owner bootstrap,
   tenant isolation and production acceptance. Vercel client deployment remains
   incomplete; Turso setup and enginehsd.site domain move need verification.
6. Add isolated code proposal/test/review/rollback workflows and scoped OS tools.
7. Later add consent-based camera/object/activity events and retention controls.

No paid OpenAI tests, funded execution, camera deployment or unattended new
micro-trading engine has been enabled. Preserve existing .env/model choice and
dirty source. Detailed historical plan: docs/NIBLIT_MASTER_PLAN.md.


Android remote-access work: docs/ANDROID_REMOTE_ACCESS.md, deploy/client-portal/compose.tunnel.yml, deploy/android/ readiness templates, modules/portal_remote.py and tests/test_portal_remote.py. 22 focused portal checks pass. Remote owner/tool/learning routes blocked; secure cookies and exact Host/Origin/CSRF tested. Need real tunnel-provider account/token/DNS, then phone Wi-Fi/mobile-data acceptance. No remote endpoint or APK active.


P0/P1 continuation: credential-free listener inventory in diagnostics/runtime-inventory-20261030.json. Shared task authority deployed in existing memory gateway; local portal/tutor use it. Real host-vs-Docker admission and native-router-to-GGUF synthetic response passed. Source wrappers added to native router/LocalBrain/tool loop. Missing LocalBrain route_inference restored with explicit local transport and no paid fallback. 70 focused tests passed. Core/Cloud/Lean boot and all legacy/ALE callers still need migration; frozen build not repackaged. See SHARED_TASK_ADMISSION.md and owner-only scripts/runtime-task-status.py.


Native ALE source increment: per-step shared admission now belongs to the worker thread and survives caller timeout. Active-user cycles yield. Opt-in local-evidence profile replaces legacy 32-step work with one memory-grounded local question; defaults to 3 bounded cycles. Existing memory bridge reused; no second embedder. Production ALE cycle/worker method acceptance (minimal dependency fixture, not full Core boot) recalled3 real passages, made1 real local call and saved an unverified knowledge_gap observation. 32 focused checks pass. Profile template deploy/runtime/native-local.env.example; docs/NATIVE_ALE_LOCAL_PROFILE.md. Next: actual Core startup/profile configuration, remaining independent producers/Cloud delegation, native controls and frozen packaging. Do not claim full Core or rebuilt executable is verified.
