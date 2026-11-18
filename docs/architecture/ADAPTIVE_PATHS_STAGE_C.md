# Adaptive paths — Stage C, 2026-11-14

Status: implemented and source/test verified; packaged relocation acceptance is pending. No installed release was changed. This extends `niblit_core/config/paths.py` and the existing bootstrap; it is not a second launcher or service manager.

## Ownership and execution path

`main.py` → `modules/runtime_bootstrap.bootstrap_runtime_environment` → opt-in pinned environment manifest → existing Core/environment/UI lifecycle. The bootstrap validates before changing CWD or importing Core. Frozen installation root comes from `sys.executable`; bundle resources come from `sys._MEIPASS`; source workspace comes from the resolver's source location. CWD is never an installation authority. In manifest-enabled frozen startup the installation's parent is not added as an import root.

Existing unconfigured launches retain legacy behavior. `resolve_path` retains its absolute-path compatibility; it is not a security boundary. Manifest resources use separate bounded validation. External absolute paths retain their original drive and location. Service endpoints remain URLs, never filesystem paths. Existing source callers, PyInstaller's `SPECPATH` and Tauri's configured frontend output retain their owners. Tauri itself has no additional relocation manager.

## Manifest contract

Set `NIBLIT_INSTALLATION_MANIFEST` to an absolute JSON file and `NIBLIT_INSTALLATION_MANIFEST_SHA256` to its operator-verified SHA256 in the candidate process environment. Neither is set globally by this change. A manifest does not authenticate itself: the digest must come through trusted deployment configuration. Do not copy a pin from an untrusted model response. Limit: 128 KiB, 32 resources, 16 explicit non-root approved filesystem roots. Root junctions/links and resource escapes are rejected.

Schema `niblit-environment/1`:

```json
{
  "schema_version": "niblit-environment/1",
  "installation_id": "operator-assigned-stable-id",
  "approved_roots": ["D:/NiblitAIOS/releases/candidates/example/niblit", "C:/approved-existing-data", "D:/NiblitAIOS/runtime/example"],
  "resources": {
    "configuration": {"kind": "file", "path": "C:/approved-existing-data/config.env"},
    "memory": {"kind": "file", "path": "C:/approved-existing-data/memory.json"},
    "ledger": {"kind": "sqlite", "path": "C:/approved-existing-data/ledger.sqlite3"},
    "runtime_state": {"kind": "directory", "path": "D:/NiblitAIOS/runtime/example/state", "disposable": true},
    "cloud": {"kind": "service", "path": "http://127.0.0.1:8000"}
  }
}
```

Example paths are illustrative, not discovered installations. Supported filesystem kinds: file, directory, executable, sqlite, model. Base is `absolute` by default, or `installation`/`bundle` with traversal-free relative paths. Executables require the exact filename and SHA256; SQLite and GGUF headers are validated. Required external dependencies use `required: true`; missing optional resources yield an approval-required recovery item without preventing path readiness. Configured services must be credential-free loopback HTTP(S), with no query/fragment. Network readiness is separately `not_probed`, never inferred from path resolution.

There is no arbitrary-drive scan or binary execution during discovery. The operator explicitly registers verified paths; unavailable or incompatible resources require reconfiguration/review. ABI/driver compatibility and actual model loading still require runtime acceptance. No model/account/service execution failover is introduced.

## Safe reconstruction and persistence

`environment_plan()` is read-only. `apply_environment()` can create only declared, non-overlapping application-owned disposable `cache`, `logs`, or `runtime_state` directories outside the installation. It cannot install software, download models, change OS configuration, launch Cloud or create memory stores. Required configuration, JSON memory and SQLite ledger must already exist. Conflicting existing process bindings fail rather than redirecting them.

Applied bindings are limited to `NIBLIT_ENV_FILE`, `NIBLIT_MEMORY_PATH`, `NIBLIT_MEMORY_LAB_LEDGER`. Environment loading then uses only that explicit configuration, not a new CWD/bundle `.env`. Runtime observations record installation identity/location/manifest digest atomically, preserve content-addressed previous metadata, and detect relocation. Backups are bounded to 32; reaching the bound requires operator review, never automatic deletion. Observations are not configuration authority and cannot supply remembered paths.

MemoryGateway validates the bound ledger before construction and each connection; URI `mode=rw` prevents SQLite creating a replacement. JSON memory path selection, KnowledgeDB initialization/writer and compatibility saves reject disappearance/rebinding under the profile. Existing canonical memory and Qdrant schemas are unchanged; there is no data migration or new Qdrant infrastructure. Other legacy stores still require audit in packaged acceptance; this is not a claim that every historical file path is portable.

UI launch in this profile requires an available, hash-verified `ui` executable resource. Implicit Cloud autostart is disabled. No existing Cloud is killed, redirected or adopted by this resolver. Known endpoints must separately pass ownership/readiness checks; path readiness is not execution permission.

## Tests and limitations

`tests/test_relocation_paths.py` exercises independent CWD, simulated frozen/bundle layout, same-drive move, actual C:/D: fixture resolution through a source-bootstrap subprocess, manifest pins, missing stores, executable substitution, traversal, conflicting bindings, optional absence, Windows junction escape, metadata rollback, Cloud autostart suppression and real MemoryGateway no-recreation behavior. The subprocess uses the source bootstrap with a simulated frozen executable, not a PyInstaller candidate. A symlink privilege test may skip on Windows; the junction test must pass separately.

Use existing venv Python with `-B`, disabled pytest cache and a new disposable `--basetemp` under D:. `NIBLIT_TEST_C_ROOT` enables the controlled second-drive fixture test. Tests create their own tiny stores; no production broker calls or orders are made. Launcher tests now isolate sibling UI/Cloud discovery for every test group, correcting an existing test isolation gap that could open real UI windows.

## Candidate procedure for a later authorized Stage D

1. Refresh Git diffs, C:/D: free capacity, existing service/process ownership, account/session state and installed-release checksums. Preserve all Stage B/C edits and preimages. Do not assume historical PIDs still exist.
2. Inspect the read-only scoped build plan, using a fresh identifier:
   `powershell -File scripts/Invoke-ScopedBuild.ps1 -BuildRoot D:\NiblitAIOS -BuildId stage-d-<unique> -Component all`
   The default is planning. Only after Stage D authorization and dependency/storage checks, the same command with `-Execute` may compile the isolated candidate. No installed-release destination is allowed.
3. Verify build/intermediate/cache outputs are D:-scoped; retain installed C: Python/toolchains, llama.cpp and model library. Inspect candidate contents, hidden imports, DLLs, private data exclusion and hashes. Confirm the new resolver/bootstrap modules are actually bundled.
4. Prepare a candidate-only pinned manifest with the candidate installation root and exact existing C: dependencies/data. Include verified candidate UI hash. Do not apply the diagnostic manifest as a production profile. Establish a trusted configuration pin and rollback preimage outside the candidate. Do not use private data copies as a replacement canonical store.
5. Resolve ownership and clients for every Cloud endpoint before selecting any service. Stage C found historical Cloud PIDs gone and health unavailable; this does not authorize restarting either installation. Obtain an ownership-safe procedure if services need intervention. Use no generation probes or account actions until dependencies are known.
6. Launch the candidate with explicit profile from a different CWD, isolated Core/UI ports and distinct process identity, without a competing Core. Verify UI → intended Core → intended Cloud → existing C: model; verify backend identity and honest service degradation. A free port does not prove ownership. Never silently adopt another Core.
7. Verify existing canonical store identities and permission scope before/after a bounded, identifiable permitted memory event; check restart/idempotence and no new SQLite/Qdrant store. Exercise missing-store and stale-config cases with fixtures, not production file removal.
8. Test normal/abnormal exit, same-drive candidate move, C:/D: dependencies, denied executable replacement, unavailable optional services and rollback. Preserve funded restrictions and paused demo state. No broker orders are needed for relocation acceptance.
9. Record packaged versus source evidence separately. Do not cut over or overwrite November 8 without its own reviewed release gate and verified rollback. Native-model training and future autonomous repair remain excluded.

## Rollback

No global configuration was changed and the installed release remains the known code fallback. Stop using the opt-in manifest to retain legacy startup. Before reverting source, compare Stage C postimage hashes and later edits, then restore only matching Stage C-owned preimages; never reset/clean or overwrite subsequent work. Newly added documentation/tests can remain inert. `restore_environment_observation(backup)` restores only validated metadata for the same installation/pin; the next startup still resolves current resources from the manifest. Never restore old databases, permissions, trading settings or broker inventories as code rollback.
