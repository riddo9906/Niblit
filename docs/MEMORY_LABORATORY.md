# Memory Laboratory v0.1 — Phase 6

This is an additive Core module, not another cognitive orchestrator. The user
clarified that no v0.1 archive existed; this implementation creates it.
Discovery and migration decisions are in `PHASE6_MEMORY_INVENTORY.md`.

## Local service

Docker Desktop runs Qdrant 1.18.0 in `niblit-memory-lab-qdrant-1`, with persistent
named volume `niblit_memory_qdrant`. HTTP 6333 and gRPC 6334 bind only to
127.0.0.1. An API key is generated into a private external profile at
`%LOCALAPPDATA%/Niblit/memory-laboratory/.env`; current launch scripts use that
external profile. The original Core `.env` and its former Cloud configuration are preserved.
Do not commit or share the private local profile or Docker inspect environment.

From Core in PowerShell:

```powershell
./scripts/Start-Memory-Laboratory.ps1 -SetupCollections
$profile = "$env:LOCALAPPDATA/Niblit/memory-laboratory/.env"
./niblit-env/Scripts/python.exe -m modules.memory_laboratory --env-file $profile
```

The setup command defaults to read-only. `--apply` creates missing versioned
collections/indexes and verifies point write/read/delete permissions using only
its own disposable probe. It never recreates an existing collection. All four
categories use dedicated CPU E5-small embeddings, pinned to revision
`614241f622f53c4eeff9890bdc4f31cfecc418b3`. A real local probe measured 384
dimensions. Zero/non-finite vectors are rejected; no coder-model substitution.
Downloads are disabled unless explicitly configured.

Collection identity includes schema 6.1, model/revision, measured dimension and
distance. Current suffix is `ca47ec0609270416`, categories working, episodic,
semantic and procedural. New model revisions get new collections even when
dimensions match. Existing mismatches stop with migration required.

Qdrant collection parameters and payload indexing follow the
[official collection](https://qdrant.tech/documentation/manage-data/collections/)
and [indexing](https://qdrant.tech/documentation/manage-data/indexing/) APIs.

## Runtime and governance

`scripts/Start-Niblit-With-Memory.ps1` starts SOURCE Core through existing
`main.py`, preserving the established desktop boot path. It enables the new
projection/context adapter only for that process, using an external persistent
ledger at `%LOCALAPPDATA%/Niblit/memory-laboratory/ledger.sqlite3`.

On the first explicitly authorized setup, use
`./scripts/Start-Niblit-With-Memory.ps1 -GrantMemoryAccess`. This grants only
`memory.read.desktop`, `memory.ingest.desktop` and `memory.consolidate.desktop`
through the existing operator permission store. It grants neither deletion nor
arbitrary execution. Without a grant, retrieval/writes fail closed. Existing
permissions and original memory files are not replaced.

The source launcher has been supplied but a full interactive desktop session
with it has not been certified. The earlier frozen Commands executable predates
Phase 6; it did not gain the new code by restarting. The fresh complete desktop
build is verified at `dist/testing-20261025-memory/niblit`. Its testing
launcher reads the external profile and uses a persistent, explicit permission
file. `Enable-Memory-And-Start.cmd` is the explicit desktop-scoped grant entrypoint.

`context.py` integrates retrieval into the existing `LlmToolLoop.chat` before
inference. Source bytes occupy an untrusted data message, never a system role.
Only a constant trusted policy is inserted. Caller scope comes from operator
configuration, never the model or a retrieved document. Core appends actual
retrieved-source citations when the model omits them. These links identify
retrieved evidence, not proof that every generated sentence is grounded.

`KnowledgeIngestionService` routes embedding/indexing through this gateway when
the feature is enabled, including duplicates and updated documents. Permission
denial never falls back to the old vector writer. Existing authoritative
FusedMemory/KnowledgeDB behavior is retained; remaining older ingestion facades
and legacy Graph/Brain direct-retrieval paths have not all been redirected.

## Ingest and query a permitted file

The operator CLI is not an assistant tool. Use a relative file path under the
existing authorized workspace (`NIBLIT_WORKSPACE_ROOT`). Existing text/code and
PDF readers enforce path/secret/size limits; line or page citations survive.
Truncated reads and overlarge chunks are rejected rather than replacing a
complete source with a partial one. Credential-like token content is rejected.

```powershell
$ledger = "$env:LOCALAPPDATA/Niblit/memory-laboratory/ledger.sqlite3"
./niblit-env/Scripts/python.exe -m modules.memory_laboratory.operator --env-file $profile --ledger $ledger grant read ingest consolidate --confirm
./niblit-env/Scripts/python.exe -m modules.memory_laboratory.operator --env-file $profile --ledger $ledger ingest docs/example.txt
./niblit-env/Scripts/python.exe -m modules.memory_laboratory.operator --env-file $profile --ledger $ledger retrieve "your question"
```

Record IDs combine namespace, principal, source, source version, chunk index and
embedding collection. SQLite retains evidence/audit before projection; readback
must verify every point before the new source version becomes visible. Old
source versions become superseded; originals remain in the ledger. Failed
projection writes remain pending; retry the same ingest. Failed supersession or
deletion projection is recorded; explicit source deletion can be retried. There
is not yet an automatic outbox repair scheduler.

Retrieval fuses scoped SQLite FTS5 lexical ranking and filtered Qdrant dense
candidates using reciprocal ranks, with importance, recency and verification
weighting. Local ACL/namespace checks remain mandatory even after vector search.
Duplicates are suppressed. Outages explicitly report lexical degradation; a
changed embedder does not query old vectors with the new model.

## Consolidation and migration

`consolidation.py` scans at most 100 records per run and has a 2-second maximum
configured scan budget. Optional background runs have at least a 30-second
interval. It records unverified review proposals for repeated/stable information,
source corrections, simple possible contradictions, concept relationships,
stale records and reusable procedures. It does not silently promote or erase
anything. Semantic contradiction resolution and verified promotion remain
operator-review work; heuristics are not a general reasoning verifier.

The migration API/CLI accepts explicit KnowledgeDB JSON facts or typed Laboratory
JSONL. It does not silently import preferences, conversations or runtime state.
Dry-run reports counts/hashes without printing private facts. Apply requires a
fresh namespace and a new backup directory, copies the source, snapshots the
ledger, records a manifest before each write and reconciles outcomes. Rollback
revokes only the manifest's exact namespace/principal/sources; original files and
audit survive. Unknown store formats require explicit adapters.

```powershell
# Dry-run only (add --apply --backup-dir <new-private-folder> after review):
./niblit-env/Scripts/python.exe -m modules.memory_laboratory.operator --env-file $profile --ledger $ledger --namespace migration_review migrate path/to/knowledge.json --format knowledge-json
```

The apply namespace needs its own existing operator permission grant. Never
delete Docker's named volume during cleanup: source code is not a backup of
Qdrant points, the ledger, credentials or personal memory.

## Validation and limits

Live source report: `diagnostics/memory-phase6-live-final-20261025/verification.json`.
All eleven checks passed: readiness, idempotent verified upsert, actual points and
payload, rejected unauthenticated access, source correction/supersession, source
deletion propagation, denied cross-caller access, real model answer/citation,
Qdrant restart, actual points surviving restart and persistent answer/citation.
Tests used a generated permitted
document and isolated ledger/scope; no personal memory was migrated. The test
Cloud processes were stopped; local Qdrant remains running.

Run `scripts/verify-memory-laboratory.py --output <isolated-output> --restart-qdrant`
with Core's interpreter to repeat. This restarts only the dedicated lab service.
It requires the existing packaged Cloud binary and installed local model paths.
The completed frozen bundle separately passed the same 11 real-memory checks,
4 packaged ingestion/retrieval/citation checks, 13 original-command checks,
14 paper-runtime checks (520 recorded candles, 5 closed strategy trades) and
32 desktop/API checks. Its final boot reported `core_degraded: false`. Source
regressions passed 184/184 tests. Reports and executable hashes are copied beside
the new executable. This does not certify every cognitive path, bulk migration,
all optional AIOS subsystems or exhaustive prompt-injection resistance.

For a new frozen build, add `--core-executable <bundle>/niblit.exe` to the live
verifier. This asks through its real `--memory-lab-operator` entrypoint with an
isolated permission store and checks the packaged model path. Frozen standalone
setup is available as `niblit.exe --memory-lab --env-file <private-profile>`.
