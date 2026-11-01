# Next update: portable path manager

User requirement: Niblit must resolve paths correctly after moving to another
folder, drive, user account or supported operating system, and report what
prevents importing or booting. This file is the implementation brief, not an
implemented feature.

## Resolution contract

1. Explicit command-line overrides.
2. Environment overrides (retain compatibility with existing variable names).
3. A private user configuration file with a versioned schema.
4. Paths relative to the actual source/package location, not the working directory.
5. Platform-standard user data/config/cache directories and optional discovery
   of approved sibling repositories and executables on PATH.

Keep source roots, writable state roots, models, binary tools and UI/cloud
roots separate. Persist portable relative paths where sensible, resolve them
against an explicitly defined base, and use pathlib/os.pathsep. Do not depend
on a Windows username, drive letter or global sys.path edits. Python module
imports should use proper packages and launch entry points; a path resolver
alone cannot repair an incompatible dependency or a missing package.

## Initial integration targets

- Core `main.py`, `niblit_env.py`, UI launcher and cloud discovery.
- `modules/llama_server_manager.py` and local brain binary/model lookup.
- Cloud model registry, storage root and llama-server provider configuration.
- Build/packaging scripts and Linux/Windows native sidecar discovery.
- Memory lab dotenv, ledger, embedding cache and persistent storage.
- Trading sibling repositories and editor workspace/gateway configuration.

Preserve distinct server/CLI binary roles and platform executable suffixes.
Expose one resolved path snapshot with source/provenance and validation errors.
Never include keys, credentials or complete private dotenv values in reports.
Detect conflicting legacy aliases rather than silently selecting different
models or binaries in Core and cloud. Discovery must not execute untrusted
binaries merely to enumerate them.

## User-facing workflow

Provide `paths check`, `paths explain` and a relocation dry run. Show missing
paths, permissions, expected file types, model availability and executable
architecture. Propose an old-to-new mapping before writing configuration.
Back up changed configuration and make writes atomic. Never rewrite model
files, historical records, arbitrary source files or database content through
a blind global search/replace. Recreate venvs and native builds when required.

## Acceptance tests for implementation

- Boot from a non-project current directory.
- Move the workspace under another parent, including spaces and Unicode.
- Test Linux case sensitivity and Windows drive/path-list semantics.
- Test source and packaged layouts and unavailable optional sibling repos.
- Validate explicit override precedence and conflicting legacy settings.
- Missing models, unwritable state and stale tools produce actionable errors.
- Existing memories and private configs remain intact after relocation.
- Verify actual imports, Core boot, cloud health, UI connection, local inference
  and memory read/write after relocation; dependency reinstall requirements
  must be reported instead of promising arbitrary-environment portability.
