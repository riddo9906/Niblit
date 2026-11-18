# Scoped Windows build configuration — Stage B

This is an opt-in build profile. It does not change the installed application,
model/memory/service configuration or execution permissions. Stage B validates
configuration; no cross-drive packaged build or deployment is claimed.

## Planning entrypoints

From Core, including from a different working directory:

```powershell
& C:\Users\Riyaad\Documents\GitHub\Niblit\scripts\Invoke-ScopedBuild.ps1 `
  -BuildRoot D:\NiblitAIOS -BuildId stage-b-20261114
```

Cloud, LEAN and UI each expose `scripts/Build-Scoped.ps1` with the same
`-BuildRoot`/`-BuildId` parameters. They delegate to the existing sibling Core's
build profile. If Core is elsewhere, set `NIBLIT_CORE_SOURCE_ROOT` or pass
`-CoreSourceRoot` explicitly. No recursive drive search is performed.

Planning is the default: JSON describes paths, interpreters and commands without
creating output directories, loading models or starting services. It does not
certify that all build dependencies are installed or that compilation will pass.
Ordinary unscoped commands retain their legacy behavior and may write to C:.
Use this profile for the authorized D: workflow; no global TEMP/PATH/cache changes
are made.

## Declared directories for the example build ID

| Purpose | Path |
|---|---|
| Sidecar staging | `D:\NiblitAIOS\builds\stage-b-20261114\staged` |
| Candidate root | `D:\NiblitAIOS\releases\candidates\stage-b-20261114` |
| Final candidate | `D:\NiblitAIOS\releases\candidates\stage-b-20261114\niblit` |
| PyInstaller work | `D:\NiblitAIOS\pyinstaller-work\stage-b-20261114\_pyinstaller_{core,cloud,lean,freqtrade}` |
| Cargo target/cache | `D:\NiblitAIOS\cargo-target` |
| UI frontend | `D:\NiblitAIOS\builds\stage-b-20261114\ui-dist` |
| TypeScript metadata | `D:\NiblitAIOS\cache\typescript\stage-b-20261114` |
| Vite config/cache | Under `D:\NiblitAIOS\pyinstaller-work\stage-b-20261114` |
| TEMP/TMP/TMPDIR | `D:\NiblitAIOS\temp\stage-b-20261114` |
| Tool caches | `D:\NiblitAIOS\cache\{pip,npm,pyinstaller,node,python}` |

`NIBLIT_BUILD_ROOT` selects the profile. Existing explicit staging/dist/work
overrides remain supported. Build IDs reject traversal. Scoped outputs must stay
under the selected root and cannot overlap sources, models or configured memory,
including through existing Windows junctions. Existing candidate bundles are
rejected. An execution lock rejects overlapping/uncertain work for the same ID;
stale locks require operator reconciliation, never automatic expiry.

Python environments, Rust toolchains/Cargo home, Node dependencies, llama.cpp,
GGUF models, canonical SQLite and Qdrant mounts stay where already installed.
The profile disables implicit dependency installation and uses offline package
settings. Missing dependencies produce a diagnostic; installing/upgrading them
requires separately reviewed scope. Shared Cargo cache reuse is intentional.

## Existing implementation reuse

- Core's existing orchestrator still owns full packaging and calls the existing
  Core/Cloud/LEAN/Freqtrade PyInstaller specifications with explicit D: work/dist
  arguments. Specs already anchor source inputs to `SPECPATH`; they were retained.
- Tauri executable discovery respects `CARGO_TARGET_DIR` and an explicit Cargo
  target triple. It does not fall back to a stale C: executable when D: is selected.
- UI's existing build commands use no-emit TypeScript checks with D: build-info
  files, a D: Vite forwarding config and output/cache paths. Tauri receives the
  matching frontend directory through its supported config merge argument.
  Existing Tauri arguments, such as `--no-bundle`, remain forwarded.
- Vite preserves existing output contents (`emptyOutDir=false`) in the scoped
  profile. Neither the entrypoint nor its rollback removes old artifacts.

The current filesystem Path Manager can retain explicit absolute C: and D:
resources. Service URLs remain URLs through existing service configuration, not
filesystem paths. Full relocation detection, typed runtime resource resolution
and reconstruction belong to Stage C and are not implemented here.

## Candidate execution and acceptance gate

Do not append `-Execute` until an actual candidate build has been authorized.
When authorized, select a fresh build ID and review the emitted plan first.
The full build must reuse existing dependencies, record source revisions, hashes
and actual disk writes, and leave the November 8 installation unchanged.
Individual `-Component core/cloud/lean/ui/freqtrade` choices allow staged work;
Core still requires its complete sidecars. A partial component is not a release.

Before runtime acceptance, resolve which existing Cloud service is authoritative:
Stage A/B observed both a native C: Cloud instance and a D: review-directory
instance. Do not terminate either based solely on its directory or a connection
count. Attribute clients, coordinate shutdown if necessary and prevent duplicate
Core/model services. Keep trading inactive.

Candidate acceptance must prove owned Core/UI, approved C: inference/model/data
bindings, no duplicate memory, unchanged permissions, offline/unavailable states,
normal shutdown/restart and checksummed rollback. Successful configuration tests
or packaging alone are insufficient. No native training or funded orders are
part of this workflow. The known broker-view fixture defect remains open.

## Recovery

The installed release was never changed. To stop using the profile, use the
previous build entrypoint without scoped variables; no machine-wide settings
need reverting. Restore only Stage B's edited build files from recorded preimages
after checking for later edits. New scripts/tests may remain inert; do not clean
or reset the repository. Keep D: artifacts for review unless separately approved
for deletion. A stale build lock is not permission to restart or kill a process.

The task-continuation Stage B report records actual validation, modified files,
dependency ownership, limitations and source/installed checksums.
