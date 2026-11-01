# Niblit evidence memory

The desktop uses the existing `modules.memory_laboratory` gateway. The original
KnowledgeDB remains the compatibility store for Core and its learning engines.
A durable SQLite outbox copies readable knowledge into versioned Qdrant
collections using the pinned, local `intfloat/multilingual-e5-small` model.
No OpenAI embedding or inference calls are required for indexing or search.

## Data flow and guarantees

1. Core saves its original fact. A queue entry is committed before embedding or
   network projection. Existing facts are also read from the original JSON
   snapshot; the importer never rewrites that file.
2. A bounded worker embeds source text and upserts deterministic UUID points.
   Qdrant readback must confirm the content hash before the projection is made
   visible. Interrupted jobs recover after a five-minute lease; failures back
   off and retain the source evidence.
3. Dense search uses Qdrant's current `/points/query` API. SQLite FTS5 supplies
   text search, and reciprocal-rank fusion combines both result lists. Exact
   repeated passages appear once in a result set; original source observations
   remain available for audit. Repetition does not increase confidence.
4. Scope, principal, active lifecycle and verification are checked against the
   local authoritative ledger even after Qdrant filtering. Source corrections
   supersede old versions. Revocation takes effect locally before remote delete.
5. Chat and the original Core tool loop retrieve bounded, cited evidence before
   inference. Retrieved material is untrusted data. It cannot grant permissions
   or become a system instruction. UnifiedMemoryEngine also projects memories
   and conversation episodes through this gateway and recalls persistent data.

An indexed projection is **not a verified claim**. Imported content is unverified,
with its declared research confidence (default 0.5). The ledger keeps source
location, original key, topic, available provenance, model revision, timestamps,
content hash, versions and audit history. A previous `last_verified_at` field is
retained as legacy provenance, not treated as evidence that verification occurred.
Research summaries are not model weight training.

## Local deployment

`deploy/memory-laboratory.compose.yml` pins Qdrant v1.18.0, binds ports to
127.0.0.1, requires an API key and keeps storage in `niblit_memory_qdrant`.
The private `.env.memory-laboratory` is ignored by Git. The launcher starts the
dedicated service if needed; it never deletes or resets the volume. Its helper
records actual connectivity in `diagnostics/memory-service-startup.json`.

The root private `.env` enables the framework and specifies its profile, source
snapshot, permission file and persistent ledger. State lives under
`runtime/memory-framework/`, including a copy of the original KnowledgeDB made
before enabling the import. The desktop Memory tab shows queued work and cited
search results. `/api/memory/framework` reports local queue/index state;
`POST /api/memory/search` searches the configured desktop scope. A worker status
does not prove every original fact has finished indexing.

`scripts/configure-memory-framework.py` makes this configuration reproducible.
`scripts/run-memory-framework.py` runs the same worker independently for an old
desktop release. Stop that temporary worker after switching to the new Core;
the updated Core owns its worker. SQLite leases coordinate queue claims, but a
single worker is preferable to avoid loading duplicate embedding models.

The local embedding model is pinned to commit
`614241f622f53c4eeff9890bdc4f31cfecc418b3`, with 384 dimensions and Cosine distance.
Changing model, revision, dimension or distance creates a different collection
identity; vectors from incompatible embedding models must not be mixed.

## Documents, review and recovery

The existing operator entry point supports `ingest`, `retrieve`, `ask`, `status`,
`consolidate`, `review`, `backup`, `rebuild`, `migrate`, and `rollback`:

```powershell
.\niblit-env\Scripts\python.exe -m modules.memory_laboratory.operator --help
```

Supply the private `--env-file`, explicit `--ledger`, `--namespace` and
`--principal` before the subcommand. Ingest reads a permitted workspace-relative
text file or PDF and retains line/page citations. Partial or unreadable document
imports are rejected. Chat attachments have a separate bounded, temporary index;
attaching a document alone does not silently promote it into permanent knowledge.

`review` requires the distinct `memory.verify.<namespace>` operator permission,
an explicit verified/rejected decision, confidence and evidence. This permission
is not granted by the setup script. Consolidation produces review proposals;
it does not self-certify claims. Rejected records are excluded from retrieval.

`backup <new-file>` creates a consistent SQLite backup including evidence,
outbox and audit. Stop the memory worker before restoring a backup to a new ledger
path and changing `NIBLIT_MEMORY_LAB_LEDGER`. Keep the original ledger. `rebuild`
checks/creates compatible Qdrant schemas and replays all active scoped records in
batches, preserving IDs and original payloads. It refuses a model revision mismatch.
Trading numeric observations have their own local durable journal and pending
projection recovery. No Qdrant collection is recreated destructively.

## Trading memory

`MarketJournal` stores numeric feature vectors in separate, feature-versioned
collections. Identity includes venue, symbol, interval, execution/data mode and
vector dimension. Language embeddings never share these collections.

Observations are immutable and record observed and available times. Outcomes
are separate, require actual evidence and an availability timestamp, and are
immutable once recorded. Historical queries exclude the current/future state,
future outcomes, incompatible modes and stale observations. The original trading
brain writes and retrieves this journal when the framework is enabled. If Qdrant
is unavailable, numeric local fallback is explicitly labeled.

Similarity supplies comparable observations, not a buy/sell direction. The old
similarity-only heuristic remains HOLD in the new framework mode. Existing explicit
RL/forecast settings are preserved; memory does not validate those strategies or
authorize orders. There is no automatic outcome fabrication, funded trading,
profit claim or execution-enablement change in this framework.

Before using a strategy with money, its own point-in-time data, fills, fees,
slippage, outcomes and paper performance still need separate validation.

## Cloud option

The same gateway accepts a Qdrant Cloud HTTPS URL and private API key through the
profile. Remote HTTP and credential-bearing URLs are rejected. No cloud account
is created and no private knowledge is uploaded by the local configuration.
To move deliberately, back up the ledger, configure the intended endpoint, run
setup with `--apply`, then rebuild the authorized scopes. Cloud deployment is
supported by the configuration but was not exercised in the local acceptance run.

## Verification and documentation

`scripts/verify-memory-framework.py` exercises actual Qdrant, local embeddings,
local-model answers, Docker restart persistence, isolation, deletion and temporal
market/outcome retrieval using an isolated acceptance namespace. The report is
`diagnostics/memory-framework-acceptance/report.json`. Its fixtures are not market
data or trading performance. Unit tests exercise outages, correction/reversion,
backup integrity, permissions and unavailable future outcomes.

Implementation references checked on 2026-10-28:

- https://qdrant.tech/documentation/quickstart/
- https://qdrant.tech/documentation/search/filtering/
- https://github.com/qdrant/qdrant-client

The source ledger is part of the recovery design: a Docker volume alone is not
the only copy of the original evidence.

## Browser control desk

Open **http://127.0.0.1:8766/** or `Start-Memory-Desk.cmd`. The normal Niblit
launcher also starts this local service. It runs on the host, alongside the
Docker services, without mounting or publishing the Docker socket.

- **Overview:** actual Core/worker connectivity, Qdrant version, import progress,
  source-backed recall, retry and consistent backup controls.
- **Evidence:** paginated source browsing, declared confidence, provenance,
  verification filters and explicit operator review with a reason.
- **Documents:** bounded PDF/text parsing into the persistent source queue. The
  existing Core worker owns embeddings; this web service does not spawn a second
  Core or load another model for ordinary search.
- **Containers:** only the named Qdrant and Freqtrade services, including actual
  IDs, images, CPU/memory samples, storage mounts, recent redacted logs and
  start/stop/restart controls. Data volumes are preserved. Freqtrade start and
  restart are refused unless its existing configuration still has `dry_run=true`.
- **Niblit view:** the existing Core web console embedded beside the memory
  controls. This console follows Niblit's own inference/model budget settings.

The desk binds only to 127.0.0.1. Browser writes require its same-origin session
token, and memory operations still check the existing operator permission file.
Qdrant keys and Freqtrade credentials are used only by the backend and are not
placed in browser source or URLs. There is no arbitrary shell/Docker command
endpoint, model-inference endpoint, financial-order endpoint or collection-drop
button in the desk. Manual review was enabled for the desktop operator; no LLM
review tool was added.

The activated Freqtrade container uses its existing configuration: dry-run,
Binance futures, SampleStrategy, 5-minute timeframe. Its status and heartbeat
were checked, including authenticated `show_config`. This is simulation, not
funded execution. The separate Lean runtime retains paper/replay configuration;
it is not relabeled as a live exchange feed.

The machine-local desktop release has a private `.env` so direct launch can use
the configured memory paths. Do not include that private file when sharing a
release. Prefer `Start-Niblit-Memory.cmd`, which reads the canonical root `.env`.
