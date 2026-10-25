# Testable Niblit desktop build

25 October 2026. Scope: a Windows desktop build for testing the integrated
assistant, memory, file/code understanding, and paper/observe trading runtime.
This is not certification of every long-term AIOS feature in the README.

## Execution plan

1. Review current source, existing local changes, the boot log, and all four
   repository handoffs. Preserve existing work and the running older bundle.
2. Fix the demonstrated startup boundaries: packaged Core must connect to the
   separately packaged Lean runtime rather than import its source-only manager;
   readiness checks must run after deferred components initialize and must not
   report successful verification for failed stages. Reuse healthy services.
3. Run focused startup/launcher tests and the memory, chat, file-understanding,
   and orchestration regressions using disposable data and observe mode.
4. Build UI, cloud, Lean, and Core into a fresh `dist/testing-20261025-final/niblit`
   folder with the new memory work. Check all required executable/dependency
   handoffs and record build output. Do not overwrite the running old build.
5. Smoke-test packaged Core and both services on isolated local ports. Verify
   health, recent conversation persistence, and a read-only file question where
   inference is available. Record actual results and remaining limitations.
6. Deliver the exact executable path and a short manual test guide covering
   chat, restart recall, file/code questions, runtime status, and paper/observe
   trading. Keep model files/configuration outside source control.

## Completion criteria

- Full build exits successfully and contains Core, UI, Cloud, and Lean.
- Recent memory changes are included in the frozen Core.
- No source-only Lean import is required by the packaged Core.
- Readiness reporting reflects checks made after initialization.
- Relevant regression tests pass; packaged health checks have recorded output.
- Test instructions distinguish verified behavior from capabilities that still
  depend on external credentials, model availability, or manual interaction.

## Execution record

Completed for the testing scope below. Final bundle:
`dist/testing-20261025-final/niblit`. Start with `Start-Niblit-Testing.cmd`.

## Desktop interface acceptance

Verify every subsystem tab against Core-owned read-only diagnostics. Verify the Windows Tauri origin can access Core, disconnected services stay visibly unavailable, Settings saves bounded preferences, and original commands retain their actual execution and authorization status. Build the revised interface into the fresh UI test bundle; preserve all earlier running builds.


### Source verification completed

- UI: final 50 tests passed; production TypeScript/Vite and native Tauri builds passed.
- Desktop API, original command dispatch and surface audit: 75 passed, one optional live test skipped.
- Windows Tauri CORS preflight is covered, including rejection of unrelated origins.
- Browser checks confirmed the disconnected state, persisted connection preference,
  live subsystem tabs, configured workspace, source rendering, original command
  catalogue search/preparation/execution, restored conversation and streamed model chat.

### Final packaged acceptance

`diagnostics/desktop-ready-verified-20261025/verification.json` records **32/32
checks passed**, including Core/Cloud/Lean health, all nine desktop data views,
Windows Tauri CORS, all eight architecture wiring checks, original command alias
execution, workspace listing and code rendering, real local inference through
Core, grounded file understanding, canonical memory writes, actual memory records
returned after restart, and the paired grounded conversation in SQLite.

The real local model answered that `add(a, b)` returns their sum and cited
`calculator.py` after a successful governed `workspace_read`. After restart,
`recall` returned one entry: key `build_check`, value
`niblit-packaged-memory-20261025`. Matching a query echoed in a failure message
is no longer accepted as proof of recall.

The original surface contains **289 command entries** and **46 governed
capabilities**. Browser acceptance executed `knowledge stats` and `recall` through
the governed form with successful real results. Selecting a catalogue entry
prepares a form; it does not execute automatically or silently send chat.

Named-file and desktop endpoint regressions: **14 passed**. Earlier startup
regressions: **15 passed**. Command-runtime/surface/desktop suite: **75 passed,
one optional live test skipped**. These suites overlap; their totals are not
added together. Memory regression records remain in the memory XML reports.

The native desktop was built successfully; interaction acceptance used the same
production UI assets in the local browser against the packaged Core, with the
Windows desktop origin separately verified. Remote API credentials were removed
for packaged acceptance, and actual local model weights were used.

### Scope and remaining limitations

This is a complete integrated **testing build**, not certification of every
optional AIOS feature. Credential-free startup reported 103/106 components ready;
required lifecycle and architecture checks passed. Remote services and web
research need their own available configuration/network.

The legacy `-c` one-shot CLI path still prefers an older router and can interpret
`recall ...` as a general question. The desktop Commands recall path is verified.
Converging that CLI route on canonical command dispatch remains a follow-up.
No changes were committed or pushed, and earlier desktop bundles were preserved.
