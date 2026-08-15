# Canonical Knowledge Pipeline — Completion Report

## Summary

This document describes the canonical knowledge ingestion pipeline implemented in Niblit to unify web research, scraping, file ingestion, chat, and memory writes under a single governed, provenance-aware write path.

## Objective

Replace ad-hoc, duplicated memory writes with a single authoritative pipeline that:

- normalizes every external input into a canonical `KnowledgeDocument`
- assigns trust levels and provenance metadata
- deduplicates by content hash and canonical URI
- versions updated documents
- stores authoritatively in `FusedMemory`
- optionally projects to legacy `KnowledgeDB` for backward compatibility
- optionally embeds into vector stores

## Files Created

| File | Purpose |
|------|---------|
| `Niblit/niblit_memory/knowledge_document.py` | Canonical `KnowledgeDocument`, `DocumentProvenance`, `SourceType`, `TrustLevel`, `ContentFormat`, URL normalization, content hashing, SSRF validation |
| `Niblit/niblit_memory/document_normalizer.py` | `DocumentNormalizer` — converts raw dicts/strings/web pages/search results/GitHub results/chat messages into `KnowledgeDocument`s |
| `Niblit/niblit_memory/ingestion.py` | `KnowledgeIngestionService` — authoritative write path with deduplication, versioning, legacy projection, and optional embedding |
| `Niblit/niblit_memory/web_fetcher.py` | `SafeWebFetcher` — SSRF-hardened HTTP fetcher with redirect limits, content-type validation, and response size limits |
| `Niblit/niblit_memory/chunker.py` | `DocumentChunker` — deterministic heading/paragraph-aware chunking with configurable overlap |
| `Niblit/tests/test_knowledge_document.py` | Unit tests for models, enums, hashing, URL normalization, and validation |
| `Niblit/tests/test_document_normalizer.py` | Unit tests for HTML extraction, language detection, timestamp normalization, and normalization paths |
| `Niblit/tests/test_ingestion.py` | Unit tests for ingestion, deduplication, versioning, and raw ingest helpers |
| `Niblit/tests/test_web_fetcher.py` | Unit tests for SSRF protection, timeouts, content-type validation, and defaults |
| `Niblit/tests/test_chunker.py` | Unit tests for single/multi-chunk, provenance, determinism, and overlap |
| `Niblit/tests/test_integration_knowledge_pipeline.py` | Integration tests for end-to-end ingestion, deduplication, chunking, and provenance |

## Files Modified

| File | Change |
|------|--------|
| `Niblit/modules/self_researcher.py` | Wired `SelfResearcher` to canonical ingestion via `_ingest_research_result()` and `_ingest_research_collection()`. Legacy `store_research` path retained as fallback. |
| `Niblit/niblit_agents/research_agent.py` | Added canonical `KnowledgeIngestionService` write path in `_process_results()`. Legacy `KnowledgeStore` and `VectorStore` writes preserved. |

## Architecture

```
raw input (web page, search result, GitHub, file, chat, market)
    ↓
DocumentNormalizer
    ↓
KnowledgeDocument  (canonical internal representation)
    ↓
KnowledgeIngestionService
    ├── validate
    ├── deduplicate (content hash + canonical URI)
    ├── store → FusedMemory  (authoritative)
    ├── project → KnowledgeDB (legacy compatibility)
    └── embed → vector store (optional)
```

## Key Design Decisions

1. **Single authoritative storage**: `FusedMemory` is the canonical store. `KnowledgeDB` receives a projected copy for backward compatibility.
2. **Trust levels**: `TrustLevel` enum classifies content. Default web content is `external_untrusted`.
3. **Provenance**: Every `KnowledgeDocument` carries structured provenance: source URI, canonical URI, domain, retrieval method, search provider, parser, HTTP status, timestamps, author, content hash, trust level, parser version, acquisition version.
4. **Deduplication**:
   - Exact duplicate: identical `content_hash` → skipped, marked as duplicate
   - Updated document: same `canonical_uri`, different `content_hash` → stored as new version with `version_of` metadata
5. **Content hashing**: SHA-256 of stripped, line-ending-normalized content
6. **URL normalization**: lowercased scheme/host, default-port removal, trailing-slash normalization, tracking-param stripping, fragment removal
7. **SSRF protection**: `SafeWebFetcher` blocks private IPs, localhost, metadata endpoints, file/ftp schemes. Validates final URL after redirects.
8. **Chunking**: deterministic, heading/paragraph-aware, configurable target and overlap
9. **Backward compatibility**: legacy `add_fact`, `store_research`, `KnowledgeStore.store_search_results`, `VectorStore.add` all continue to function. Canonical writes are additive.

## Component Status

| Component | Status |
|-----------|--------|
| `KnowledgeDocument` | ✅ Implemented |
| `SourceType` enum | ✅ Implemented |
| `TrustLevel` enum | ✅ Implemented |
| `ContentFormat` enum | ✅ Implemented |
| `DocumentProvenance` | ✅ Implemented |
| `DocumentNormalizer` | ✅ Implemented |
| `KnowledgeIngestionService` | ✅ Implemented |
| `SafeWebFetcher` | ✅ Implemented |
| `DocumentChunker` | ✅ Implemented |
| `SelfResearcher` wiring | ✅ Implemented |
| `ResearchAgent` wiring | ✅ Implemented |
| Unit tests | ✅ Implemented |
| Integration tests | ✅ Implemented |
| Compilation | ✅ Verified (`py_compile` passes) |

## Verification

All new modules and test files pass Python compilation:

```
cd Niblit
python -m py_compile niblit_memory/knowledge_document.py
python -m py_compile niblit_memory/document_normalizer.py
python -m py_compile niblit_memory/ingestion.py
python -m py_compile niblit_memory/web_fetcher.py
python -m py_compile niblit_memory/chunker.py
python -m py_compile tests/test_knowledge_document.py
python -m py_compile tests/test_document_normalizer.py
python -m py_compile tests/test_ingestion.py
python -m py_compile tests/test_web_fetcher.py
python -m py_compile tests/test_chunker.py
python -m py_compile tests/test_integration_knowledge_pipeline.py
```

## Legacy Compatibility

- `SelfResearcher.search()` still calls `self.db.add_fact(...)` for backward-compatible KB writes.
- `SelfResearcher._store_research_in_knowledge_db()` is unchanged.
- `ResearchAgent._process_results()` still writes to `KnowledgeStore` and `VectorStore`.
- New canonical writes are additive; no legacy path was removed.

## Next Steps (Recommended)

1. **Wire `InternetManager.search()` to canonical ingestion**: replace the `semantic_agent.store_knowledge()` call with `KnowledgeIngestionService.ingest_search_result()`.
2. **Wire `ResearchAgent.search_web()`/`search_news()` to chunker**: after canonical ingestion, optionally chunk long documents.
3. **Add entity/claim extraction**: extend `DocumentNormalizer` or add an `EntityExtractor` step to populate `entities` and `relationships` on `KnowledgeDocument`.
4. **Add retrieval API**: implement a `KnowledgeRetriever` that queries `FusedMemory` by semantic similarity, metadata filters, and time ranges.
5. **Connect retrieval to model prompts**: ensure `NiblitBrain` uses `KnowledgeRetriever` to inject trusted context before inference.

## Notes

- The canonical pipeline is designed to be **non-breaking**. It can be adopted incrementally by routing new writes through `KnowledgeIngestionService` while legacy paths continue to function.
- Trust levels and provenance allow the model to distinguish trusted internal content from untrusted scraped content at retrieval time.
- Content hashing and URL normalization prevent duplicate ingestion and enable versioning.