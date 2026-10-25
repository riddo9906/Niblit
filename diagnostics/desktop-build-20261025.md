# Desktop build — 25 October 2026

Output: `dist/niblit/niblit.exe`. Distribute the entire `dist/niblit` folder.
It includes `niblit-ui.exe`, `cloud/niblit-cloud.exe`, and
`lean-algos/niblit-lean-algos.exe`, with their dependencies.

`npm run build` completed with exit 0. The cloud sidecar was subsequently
rebuilt and copied from staging into the final folder after startup checks
exposed two issues. The updated cloud spec makes those fixes reproducible
through the normal full build.

Changes made in this session:

- `modules/niblit_ui_launcher.py`: launch the co-located UI and cloud executables
  in frozen builds; fail when the packaged UI is missing.
- `scripts/niblit-build.js`: verify all three components in the final folder.
- `niblit.spec`: reject missing required staged executables.
- `tests/test_niblit_ui_launcher.py`: regressions for packaged UI/cloud launch
  and missing executables.
- Sibling `Niblit-cloud-server/niblit-cloud-server.spec`: include static assets
  at both entry-script and imported-module locations.
- Sibling `Niblit-cloud-server/app/main.py`: allow a discovered default model
  when configuration has no default; retain explicitly configured validation.

Validation:

- 13 packaged-launch and lifecycle tests passed.
- 45 orchestration/bootstrap tests passed.
- 18 Cloud UI, model identity, and discovery tests passed.
- Packaged core `--help`: exit 0.
- Final packaged Cloud `/health`: HTTP 200 on isolated port 18080.
- Final packaged Lean `/health`: HTTP 200 on isolated port 18100,
  paper backend and observe mode.
- Temporary service processes stopped after verification.
- The broader launcher test run stalled and was stopped; no full-suite pass
  is claimed. End-to-end desktop interaction and an inference request were
  not verified.

Evidence: `desktop-build-20261025.log`,
`desktop-cloud-rebuild-final-20261025.log`,
`desktop-bundle-verification-20261025.json`,
`desktop-core-help-20261025.log`, `desktop-smoke-cloud-20261025.log`,
`desktop-smoke-lean-20261025.log`, and focused test logs in this directory.

The checkout already contained extensive uncommitted work. Existing changes
were preserved; no staging, commit, reset, clean, or stash was performed.
