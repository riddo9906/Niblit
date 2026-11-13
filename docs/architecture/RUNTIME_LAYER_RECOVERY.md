# Runtime layer recovery — 2026-11-07

Fixed the actual deployed Core rather than changing only availability labels.

Root causes and changes:
- The staged VPS-integration launcher explicitly set NIBLIT_AUTONOMOUS_ENGINE=false. The replacement versioned profile loads ALE (true) but retains its existing loaded-idle lifecycle: no ALE worker or learning cycle starts at boot. Training, paid background loops, unrestricted execution and funded trading were not enabled.
- core/runtime_manager.py called the current get_local_brain() singleton with a removed persistence_manager keyword. Removed that unsupported argument and corrected singleton binding to _gateway.
- RuntimeManager._initialize_service() marked a None factory result ready and cached it permanently. Missing services now stay degraded, can recover on a subsequent successful factory call, and clear stale failure details only after a real instance exists.
- Core and RuntimeManager previously constructed separate ALE objects, one unbound to Core. RuntimeManager accepts the already-created Core ALE and returns that same instance. Live diagnostics confirm Core binding and shared identity, with no ALE-BackgroundLoop thread.
- Core expected legacy local model-cache fields from the current CloudRuntime gateway status and falsely reported missing model files. The current contract now reports actual CloudRuntime transport health, separately from an untested generation claim.
- modules/desktop_diagnostics.py now distinguishes current_layers and ale_runtime from historical startup_stages. The new launcher also uses the normal initialization wait rather than skipping it, so the actual new staged startup report passes all nine stages.

Deployed desktop source: outputs/releases/layer-recovery-20261107-r1/core. Supported launcher: work/layer-recovery/Start-Core.ps1 with its versioned Start-Profile.ps1. Previous demo-volume-commands-20261107-r2 source is preserved. No running release files were edited. The Exness gateway 0.5.1, VPS MT5 process and r8 were not changed. Command grants remain in the canonical permission store.

Actual acceptance:
- initialization complete, essential_ready=true, no essential failures, optional service initialization complete.
- Current runtime-manager service diagnostics contain no degraded services; local_brain is a real LocalBrainGateway rather than NoneType.
- All nine staged bootstrap checks report success, including RuntimeManager, FoundationArchitecture, event bus, persistence, LocalBrain/ModelManager/ALE and health verification.
- ALE is initialized, bound to the real Core and shared with RuntimeManager. running=false, no ALE worker thread. It is ready for explicit governed learning, not automatically researching or training.
- ale_status, ale_code_status and ale_processes all report EXECUTABLE and each returned success through the actual governed command API.
- Exness demo binding remains verified, autonomous lot ceiling remains 0.10, no active demo sessions were rearmed; real_money_enabled=false.
- 68 tests passed: 14 focused layer/desktop/foundation diagnostics plus 54 cognitive-foundation/command-registry checks. A pre-existing diagnostic test expectation omitted the existing normalized memory summary/confidence fields; its expected contract was updated, without changing memory behavior.

The API remains loopback-only at port 5000 and the existing desktop UI at 5173 consumes it. No paid model inference or broker order was used as a test. Transport health is not proof of a successful new model generation. Ruflo still requires its separate external service/configuration; shell-only/unimplemented historical commands and native desktop automation limitations were not fabricated as restored layers.

Evidence: NIBLIT_LAYER_RECOVERY_BEFORE.json, NIBLIT_LAYER_RECOVERY_AFTER.json, NIBLIT_LAYER_RECOVERY_ALE_COMMANDS.json, NIBLIT_LAYER_RECOVERY_FINAL_TESTS.xml, NIBLIT_LAYER_RECOVERY_FOUNDATION_TESTS.xml. Protected identity/worker checks are retained in work/layer-recovery/private/runtime-check.json.

Rollback: coordinate any active demo or learning work; gracefully exit only this owned Core and wait for its process and listener to close. Launch the preserved prior Core with the same canonical ledger, permission store and protected gateway profiles. Never restore an older ledger over new records. Restoring the old profile disables ALE initialization again. Do not restart or terminate MT5/VPS/r8 as part of desktop rollback.
