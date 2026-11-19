# Packaged Niblit desktop UI render fix — 2026-11-19

## Root cause and fix

The standalone bundled Core launcher previously passed
`NIBLIT_DESKTOP_BINDING.release = ''` when a versioned, uninstalled PyInstaller
release was started without `NIBLIT_INSTALLATION_MANIFEST`.
Tauri `src/runtimeBinding.ts` requires a non-empty owner release identity and
rejected this value before `main.tsx` mounted the React application.
In `modules/niblit_ui_launcher.py`, the release binding now prefers the
integrity-pinned installed manifest, otherwise the canonical parent directory
of the co-located `niblit-ui.exe`. Core PID and desktop instance checks remain.

## Verified on device

- Focused UI launcher and testing-build startup regression suites passed using
  the existing `niblit-env` virtual environment and writable D: test temp.
- Full `npm run build` exited 0; new separate candidate:
  `dist/releases/build-2026-11-19T18-03-36-503Z-21fda08f/niblit`.
- Verified five packaged executables: Core, Tauri UI, Cloud, Lean, Freqtrade worker.
- Used an isolated dummy health server with a temporary Core PID/instance binding,
  launched **the packaged** Tauri executable and inspected WebView2's DOM via
  localhost-only Chrome DevTools Protocol. React mounted one child under
  `#root`, title `Niblit 3-Layer Control Center`, and navigation text rendered.
  No real Core, trading account or VPS was involved.
- `scripts/verify-desktop-build.py` on that candidate passed Cloud and Lean
  health, static assets, three-model discovery, local inference (`READY`),
  Core API identity, desktop overview/architecture/cognitive/memory/conversation/
  inference/execution/trading/settings endpoints, desktop CORS, command catalogue,
  and Freqtrade operator discovery. The **full acceptance script exited 1**
  with `error: timed out` after these checks, while executing later commands.
  This independent timeout remains to be investigated; it is not a UI DOM
  render failure. Evidence resides under
  `D:/NiblitAIOS/temp/ui-core-acceptance-20261119/verification.json`.
- No real trading was enabled, no emergency stop cleared, and no broker order
  was submitted. The old release remains intact.

## Remaining

The source test and isolated DOM prove a specific rendering failure was fixed;
a human-visible normal installation launch has not yet been validated end to end.
Use the new release when next deliberately switching installations. Ensure there
are no competing Core processes or ports, and validate exactly the owning
private runtime configuration; do not copy a guessed Exness profile. Retain
independent review/reconciliation before any demo activation.
