# Phase 6 architecture and migration inventory

Discovery recorded before implementation, 25 October 2026.

## Preserved baseline

Core HEAD `46f864ece0eea8710ddb4e864bade67e4e08ba83`; Cloud HEAD
`c6f2291f0ca9fc76ab77b3f2723d439c7dd78c32`. Both had clean status, no
working diffs and no untracked files at discovery. Existing ignored/restored
memory, credentials, environments and builds remain in place. No reset, clean,
stash, collection deletion or source-store conversion is authorized by this plan.

## Existing architecture

| Concern | Existing owner / contract | Integration decision |
| --- | --- | --- |
| Canonical facts and persistence | `niblit_memory/__init__.py`, KnowledgeDB, shared JSON coordinator; `docs/MEMORY_STRUCTURE.md` | Keep authoritative snapshots and shared-writer ownership; migrate via read-only export and reconciliation, never replace files in place. |
| Conversation evidence | `modules/llm_chat_memory.py`, SQLite paired exchanges | Keep authoritative chat history outside Qdrant; only governed derived records enter retrieval. |
| Unified categories and graphs | `niblit_memory/unified_memory_engine.py`, `modules/cognitive_memory_layer.py`, `modules/memory_graph.py`, `modules/memory/graph/memory_graph.py`, memory and graph routers | Stable gateway adapter, no new cognitive orchestrator; explicit mapping to working/episodic/semantic/procedural records. |
| Existing document ingestion | `niblit_memory/ingestion.py`, `document_normalizer.py`, `knowledge_document.py`; `modules/ingestion.py`, `modules/governed_document_cognition.py` | Extend canonical ingestion behind adapters after checking Laboratory format; preserve legacy result and document contracts. |
| File and PDF understanding | `modules/workspace_tools.py` read/search/PDF functions, `modules/workspace_understanding.py` | Reuse authorized-root, secret-path, size and page bounds. Preserve text line ranges and PDF pages. No automatic workspace crawling. |
| Governed vector memory | `niblit_memory/governed_qdrant_memory.py`, `qdrant_engine.py`, `modules/vector_store.py`, `modules/hybrid_qdrant_manager.py` | Preserve existing collections; add versioned projection and persistent source/audit ledger. Current governed catalog and vector-ID map are in-process: restart reconciliation is required. |
| Embeddings | `modules/embedding_engine.py` strict E5-small/384 contract; `modules/vector_store.py` configurable backends and cache | Do not change legacy fixed-dimensional contract. Separate versioned Phase 6 embedding identity, measured vectors, no zero/hash fallback presented as semantic embeddings. |
| Collection contracts | `shared/governance_contract/memory_contracts.py`, `qdrant_cluster_logic/collections`, payload/governance schemas | Existing blueprint families include semantic, episodic, runtime and execution. Do not change/recreate these collections; version Phase 6 schema and model independently. |
| LLM context | `modules/brain_router.py` optional memory retriever; `modules/llm_tool_loop.py`, `modules/chat_completions.py`, Core/server request paths | Attach bounded evidence through existing context interfaces after gateway tests. Treat retrieved records as quoted untrusted data, never tool or system authority. |
| Governance | `modules/permission_manager.py`, `modules/core_tool_runtime.py`, `modules/llm_tool_loop.py`, `shared/governance_contract` | Writes require existing operator/governance authorization; model proposals cannot grant themselves permission. Namespace and access scope derived from trusted caller. |
| Learning/consolidation | Unified engine, memory compressor, memory optimizer/loop, ALE, governed training and research | Bounded scheduled worker emits proposals/relationships; no silent promotion, deletion or evidence loss. |
| Events | `core/event_bus.py`, `modules/event_bus.py`, Cloud `app/event_bus.py` | Publish metadata-only lifecycle events through existing buses; no credentials or private document bodies in event logs. |
| Cloud | `app/memory_proposals.py`, `app/cloud_governance.py`, cognitive gateway embeddings/working memory | MemoryProposal validates provenance but explicitly does not persist. Keep Core as write authority. Cloud embedding service currently returns zero vectors on failure; never use that fallback for Phase 6 writes. |

## Readiness findings

- Core `.env` contains a HTTPS Qdrant Cloud URL, API key, collection and prefix.
  Credentials were checked only for presence, never printed or copied.
- Read-only root and collection-list requests both failed with ConnectError.
  Server version, collection names, dimensions, point counts, permissions and
  payload schemas are therefore **not yet verified**.
- No listener on loopback 6333/6334; Docker executable absent from PATH and
  the standard Windows installation location. Existing Cloud should be repaired
  first; a persistent loopback-only Docker configuration is a fallback.
- Core environment has qdrant-client 1.18.0, sentence-transformers 5.5.1,
  httpx 0.28.1, Torch and pypdf. Dedicated E5-small snapshot is cached locally:
  `614241f622f53c4eeff9890bdc4f31cfecc418b3`. Qwen is not selected as an embedder.
- No Laboratory archive exists: the user clarified that v0.1 must be created.
  `modules/memory_laboratory` is the new additive module and test harness, not
  an imported archive or a replacement cognitive orchestrator.
- Follow-up: Docker Desktop was installed per user. It was located in the
  per-user Programs directory and started. The first Linux-engine checks failed
  while it initialized; the engine subsequently became available. Local Qdrant
  configuration is now being applied as requested in “Useful Projects Build”.

## Incremental migration path

1. Implement and test read-only readiness and additive setup; measure a real
   cached embedding before proposing collections. Collection identity includes
   schema, model revision, dimension and distance. Existing mismatches stop with
   a new-version recommendation, never destructive recreation.
2. Create Laboratory v0.1 and map existing records/stores to the typed contract;
   identify provenance gaps, permissions and private data. There is no external
   Laboratory archive to migrate; v0.1 exports will use the new typed contract.
3. Add a persistent SQLite source/audit ledger and versioned Qdrant projection
   behind a governed gateway. Deterministic document/chunk IDs, verified upserts,
   tombstones/outbox and replay make partial writes recoverable. Source documents
   and original evidence remain authoritative outside Qdrant.
4. Adapt existing authorized text/code/PDF readers and canonical ingestion.
   Implement dense+lexical fusion and explicit namespace/ACL filtering; retain
   citations, version identity and confidence. Test outage and injection behavior.
5. Integrate the gateway into actual LLM context construction with feature gates;
   preserve BrainRouter/ToolLoop/Graph contracts. Add bounded consolidation as
   proposals requiring verification, never a second reasoning controller.
6. Migration tool defaults to dry-run; take private backups before apply. Record
   source counts/hashes, destination IDs and write outcomes. Reconcile by source
   and namespace. Rollback selects the previous projection/manifest, preserving
   originals and audit. No blanket collection deletion.
7. Run isolated regressions, then a real permitted-document → Qdrant → Niblit
   answer/citation → service restart → repeat demonstration. A mocked client or
   in-process vector store does not satisfy that live acceptance gate.

## First implementation boundary

The first increment supplies the typed record contract, dedicated embedding
probe, non-destructive Qdrant setup command, loopback-only Docker fallback,
example configuration and tests. It does not enable ingestion, migrate personal
data, alter boot or claim that Phase 6 integration/live acceptance is complete.
