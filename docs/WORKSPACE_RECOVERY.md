# Save and restore the desktop workspace

Open `Niblit.code-workspace` in VS Code to work with all five repositories.
Its relative paths work after cloning the repositories into the same parent
directory. Build and dependency folders are excluded from search and watchers.
Personal editor settings are local; the shared workspace contains no credentials.

Repositories and branches:

| Repository under github.com/riddo9906 | Branch |
| --- | --- |
| Niblit | main |
| niblit-ui | main |
| Niblit-cloud-server | main |
| niblit-lean-algos | master |
| freqtrade | develop |

Companion revisions saved for this desktop build (25 October 2026):
UI `25972e6`, Cloud `c6f2291`, Lean `53032d8`, Freqtrade `78084cadf`.
The Core commit containing this document completes the matching source set.

The Freqtrade repository includes only the two small public BTC/ETH hourly
market fixtures used by `niblit-lean-algos/freqtrade_worker.spec`. Other user data
and trading configuration remain ignored. The worker and strategy integration
source lives in the Lean repository.

## Before deleting local files

GitHub saves source, tests, configuration templates and build instructions.
It does not back up ignored files. Keep a separate private backup of:

- `.env` files, credentials and any personal editor configuration you need.
- Runtime memory, chat history, SQLite databases and paper account state,
  including `%LOCALAPPDATA%\Niblit\testing-20261025`.
- Local model files and inference binaries outside the repositories.
- The complete tested `Niblit/dist/testing-20261025-commands/niblit` folder
  if you want to keep testing without rebuilding. Keep all its files together.

Once the source pushes have been verified and private data backed up, old
`build`, `dist`, `src-tauri/target`, dependency and cache folders can be recreated.
Deleting them removes installed dependencies and executable builds, so a fresh
build needs the relevant Python/Node/Rust tools and dependency downloads.
No local data is deleted by the source cleanup commit.

## Rebuild

Clone all five branches above as sibling folders. Create Python environments
and install each repository's declared dependencies; install the UI's locked
Node dependencies. Configure local environment files from the example templates.
From Core, `npm run tauri:build` runs the integrated build; explicit interpreter
and repository overrides are documented in `scripts/niblit-build.js`.
The full build output is `dist/niblit`; copy
`scripts/Start-Niblit-Testing.ps1` beside its `niblit.exe`, then run that script
to start a fresh bundle for testing.

See `NIBLIT_TESTING_GUIDE.md`, `COMMAND_TAB_RESTORATION.md` and
`PAPER_TRADING_COMPLETION_PLAN.md` for validation and current limits.
The tested paper profile uses recorded market data; the monthly income target
has not been established.
