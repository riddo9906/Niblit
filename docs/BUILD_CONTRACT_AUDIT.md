# Unified build contract audit — 31 October 2026

## Final PyInstaller build-process corrections

Default outputs now go into a new unique dated `dist/releases/build-.../niblit`
directory. Work/staging directories are isolated per build and propagated to
the Core spec explicitly. An existing final bundle causes a clear failure rather
than being overwritten by PyInstaller --noconfirm. Existing launchers/releases
are not switched automatically. `npm run build:plan` prints paths without writes.
The UI binary name is exact, Python installation paths are quoted, desk static
assets are included, and the current ddgs package is listed as a hidden import.

Three additional Node build-path tests pass (unique outputs, existing-release
protection, staging separation), as do JS syntax and all 20 preflight checks.
The nine earlier startup tests also passed in this session. Full compilation
and new executable boot acceptance have not been performed.

Commands from the Niblit repository:

```text
npm run build:check
npm run build:plan
npm run build
```

The last command performs compilation/dependency steps and prints the actual
new release path. Inspect its result before using the release; a successful build
is not a successful runtime acceptance. Do not run it against the current live
release directory via an override. Dependencies/toolchains and the Docker model
bridge's pending integration remain separate from build input validation.

From the Niblit repository, `npm run build` already runs the complete desktop
orchestrator. `npm run build:check` now validates source inputs and parses the
four Python specs without executing them. The full build runs this preflight
before installations, compilation or output changes. The UI repository's own
`npm run build` remains frontend-only; it is intentionally not the unified command.

## Repository contracts

| Repository | Packaging owner | Expected staged output |
|---|---|---|
| Niblit | niblit.spec | dist/niblit/niblit.exe plus co-located components |
| Niblit-cloud-server | niblit-cloud-server.spec | _staged/cloud/niblit-cloud.exe |
| niblit-lean-algos | niblit-lean-algos.spec | _staged/lean-algos/niblit-lean-algos.exe |
| niblit-lean-algos / Freqtrade checkout | freqtrade_worker.spec | _staged/freqtrade/niblit-freqtrade-worker.exe |
| niblit-ui | Cargo.toml + Tauri config (not a Python spec) | src-tauri/target/release/niblit-ui.exe |

The build already compiles Tauri, Cloud, Lean and the worker before Core packaging.
This update makes UI executable selection exact, so stale unrelated executables
cannot be selected. The Core spec now explicitly includes static HTML/JS/CSS and
allowed web assets for Market Desk, Memory Desk and the client portal. Personal
runtime data, .env and model weights are not added by this asset allowlist.

The worker's spec requires BTC/ETH recorded 1h futures datasets. These are build
inputs for that existing worker, not a claim of live market data. Docker Freqtrade
and the frozen worker are distinct execution environments; never run both against
one account merely because both have been packaged.

## Boot contract observed in source

Core owns the startup context. The desktop launcher inspects trading readiness,
starts/waits for the authoritative Core API, checks/starts Cloud inference, then
gates UI startup on required readiness. Frozen startup refuses unavailable Core
or Cloud; trading readiness is required by default for a frozen build. Existing
ownership tests cover attachment versus owned service shutdown and frozen path
discovery. This pass does not replace the established boot owner or alter trading
permissions, start order-submit sessions or enable recurring inference.

## Verification and limits

- `npm run build:check`: all 20 source/spec checks passed.
- `node --check scripts/niblit-build.js`: passed.
- `tests/test_testing_build_startup.py`: nine tests passed; dependency deprecation
  warnings remain.
- No compiler, PyInstaller analysis, dependency installation, release replacement
  or service restart was run in this pass. Current trading runtime is untouched.

Full compilation and cold-start acceptance are still required. The check does
not prove installed toolchains, every dynamically imported module, API replies,
resource budgets or model availability in a new frozen release. In particular,
the newer memory/shared-admission/native-learning paths still require integrated
frozen acceptance. No complete new executable is claimed.

Next release acceptance: build into a new dated output directory, preserving the
old release; run verify-desktop-build.py using isolated data/ports; verify actual
UI chat, PDF page citations, command dispatch, local inference/memory, and a
non-submitting trading inspection. Inspect outcomes before switching launchers.

## Local model hardware note

Hardware queried today: i7-7700, 4 cores/8 threads, 48 GB RAM, Radeon RX 580.
Windows WMI reports roughly 4 GB AdapterRAM, which is not a reliable measurement
of the card's full dedicated VRAM. Do not assume GPU support in Docker based on
that field. Preserve the existing 3B GGUF service until a candidate is benchmarked
separately and integrated into the same one-task admission path.
