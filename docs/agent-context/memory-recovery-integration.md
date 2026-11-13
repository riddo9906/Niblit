# NIBLIT v1.9 — memory throughput implementation checkpoint

Recorded 2026-11-03T17:24:17.317250+00:00. Integrated in `C:\Users\Operator\Documents\GitHub\Niblit`, HEAD `1b40c4113b0df61ecb561b73b8f7a38ed4280832`. All four authoritative roots/HEADs, staged/working diffs and untracked files inspected; prior dirty work preserved. Previous memory-recovery source hashes matched. No duplicate installation, memory authority, embedding service or worker.

## Production changes

- `modules/memory_laboratory/setup.py`: original pinned E5 CPU adapter now exposes serialized bounded `embed_many`; default4, clamp1..8. Same prefixes, normalization, model/revision/dimensions/collection identity. Scalar interface remains.
- `modules/memory_laboratory/gateway.py`: scope/principal/model/revision/content-hash cache bounded256; validated batch output, within-document deduplication, unsupported-backend scalar fallback and per-stage instrumentation. Up to4 short same-scope events reuse the ORIGINAL record/UUID builder and share SQLite preparation/activation and Qdrant writes/readback. Any partial write, bad vector, missing point or cancellation leaves unverified events unacknowledged. Canonical filters and ACLs remain. Idle read-only WAL handle holds no transaction and avoids repeated last-connection checkpoint churn; close releases it.
- `modules/memory_laboratory/runtime.py`: bounded grouped durable claims/acknowledgements with exact lease CAS, per-source retry/supersession, cumulative sanitized stage timings. General cognition retains32-event cycle budget; market phases retain up to8 eligible scopes with oldest-ready ordering and approximately64-chunk fairness allowance. Oversized documents remain whole; no event or ingestion source is dropped.
- Existing private `.env`: explicitly repaired stale `NIBLIT_MEMORY_SYNC_SOURCE` from missing `dist/niblit/niblit_memory.json` to the actual running Core knowledge producer `C:\Users\Operator\Documents\GitHub\Niblit\niblit_memory.json`. Core has empty NIBLIT_MEMORY_PATH, defaults to writable launch CWD, and this file is actively updated. No snapshot copied; fact source IDs remain `knowledge://core/` plus original key digest. Private configuration is excluded from patch/package.
- Transaction-local indexed lookup for FTS UNINDEXED IDs avoids repeated full scans during multi-record activation. It is built under the existing write transaction, maintains duplicate/reinsertion behavior, and disappears with the connection. No permanent table, schema migration or new memory authority. Read-only31945-row benchmark:52 original lookups2.490s versus index construction plus lookups0.102s; this is one stage, not total speedup.
+- Canonical ledger switched DELETE->WAL only after a private consistent backup. `synchronous=FULL(2)` retained; no ledger recreation, outbox purge or disabled modules. Backup stays private under `work/v19/private-pre-wal.sqlite3`.
- New `tests/test_memory_embedding_batches.py`: bounded/serialized adapter, scalar compatibility, IDs, ACL/cache isolation, invalid/partial vectors, partial Qdrant delivery, cancellation, restart, WAL durability, ownership, lease CAS, fairness and grouped publication regressions.

## Profiling and memory health

Initial observed window189.2s: pending1771->1785, arrivals25.37/min, completions20.93/min. Subsequent scalar instrumentation demonstrated both embedding and SQLite commit/activation costs; this was not solely an embedding-latency problem. Detailed stage timings and every window are in the JSON evidence.

Final source-enabled final window333.3s (16 samples): pending1154->1077, processing5->1, arrivals30.60/min, completions41.59/min. Oldest unfinished last-update age lower bound: 78568.2s. Active projection error classes: `{}`; knowledge source error: `None`. Cache-read counts include just-prefetched vectors and must not be described as entirely avoided model calls.

Different work mixes and service restarts preclude a controlled speedup claim. Sampled transitions miss complete-to-complete changes between polls; original enqueue time is absent. Earlier windows include reactivation of already projected records in both arrival and completion counts. Final window subtracts those reused completions from both; original worker counter is also reported separately. In-flight claims left by Core reload were preserved under original300-second leases; no forced reclaim or speculative acknowledgement. Short windows include restart recovery and variable research load. Final source-enabled queue trend, not the missing-source publication window, is the useful result. Backlog NOT fully recovered; no reliable long-term drain-time promise. Final observed state-transition rates subtract reactivation of already projected records from both sides; worker-only completion counter rate is separately reported in JSON. Canonical SQLite integrity `ok`; 161 exact expected points for three fixed real position receipts matched original UUIDs/content hashes in SQLite and actual local Qdrant, all outbox receipts complete. Four newly published small events after final activation also matched original deterministic IDs and hashes in real SQLite/Qdrant; sampled vectors retained pinned model/revision,384 dimensions and unit norm. This does not prove every backlog record is already projected.

## Inference and runtime continuity

Original quarantine recovered only using existing owner-only producer-stop/model-idle guard; original uncertain journal retained and never retried. An actual bounded Core->Cloud->Qwen tool invocation returned HTTP200, fallback=false, four completed delegated generations and released parent. runtime_status ran3 times; original repetition guard stopped repeats. This is not exact-once instruction compliance.

Activation encountered a startup connection gap; its orphaned maintenance reservation was recovered through the existing guard. A subsequent interruption left services stopped. The saved EXACT maintenance token matched and had zero delegations, so normal TaskAuthority.finish released it; no time-based ownership clear. Existing native model launcher restored original GGUF/8192ctx/2threads/1slot after its process/port were absent. Source-enabled Core reload then released its maintenance lease normally. See activation/recovery and final ownership evidence. No busy generation killed, ambiguous generation retried or autonomous permission granted.

Automatic review rejected a broad restore command that could explicitly start Freqtrade. That command did not run. Safer restoration started original Core/Cloud/observe-only Lean/memory and manual UI; no explicit Freqtrade start command. Previously approved Docker Desktop startup resumed containers under their existing restart policies; real read-only check confirms Freqtrade dry_run=true and engine stopped. No container recreated, removed or reconfigured.

## Verification and positions

Final broad Core suite: 146 passed, zero failures/errors. Adapter suite16, contract compatibility34, Cloud10, Lean26 passed; overlapping cases are NOT summed. XML evidence separates controlled doubles from actual SQLite/Qdrant/model/market checks. Initial test-directory setup error was corrected to an absolute isolated path; final runs passed.

Recorded dry-run positions remain40 XAU,42 XAG,45 BTC; all3 slots occupied; engine stopped. No submitted/closed/modified orders. Six-strategy and BTC recorded-thesis/XAU-XAG absent-thesis preservation evidence is in position-summary.json; recommendations remain analytical, not grants. Estimates and saved claims are not verified realized profit.

## Remaining issues

Final ownership caution: Core process remains running. The final sample has an active core_inference reservation, no child delegations for that reservation, and an idle healthy model slot. Idle model state alone does not prove the producer finished; reservation was retained. Historical journal includes one active and three uncertain child records across owners. Do not clear these by elapsed time, retry ambiguous generations, or infer that every research task is healthy. Next ownership action is to trace the current producer and obtain its normal release, or use existing owner-only recovery only after all required producer-stop/idle evidence.

- Backlog remains nonzero. A short positive drain window is not full recovery or a sustained-rate guarantee.
- Legacy remote HybridQdrant connections reset; local canonical Qdrant is separate and verified.
- SerpAPI monthly quota exhausted; preserved existing policy and other research capabilities.
- Full authorized demo order lifecycle and live-money operation are not verified by this work and were not attempted.
- Pending age needs an additive immutable enqueue timestamp if exact historical age is required; no inferred timestamp was written.

## Continuation

Read `C:\Users\Operator\Documents\GitHub\Niblit\docs\agent-context\NIBLIT_CONTEXT_MAP.md` and this checkpoint. Inspect real worktrees/status/HEADs/diffs first. Patch is ALREADY applied (reverse check passed), do not blindly reapply. Preserve all work and existing authorities. Highest-value next action: measure the same original worker for a longer source-enabled window, verify additional oldest pending identities in canonical SQLite and Qdrant, then optimize the largest measured remaining stage if completions cannot sustainably exceed arrivals. Do not clear backlog, reduce ingestion, add a worker or change financial permissions. Inspect current task journal/model slots before any inference recovery; never retry uncertain delivery. Do not repeat the already successful real tool request merely to inflate evidence.

Private recovery materials, SQLite backups, knowledge snapshots, credentials and raw task tokens are excluded from downloadable artifacts.
