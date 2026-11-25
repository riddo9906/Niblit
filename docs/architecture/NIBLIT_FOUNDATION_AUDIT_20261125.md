# Niblit Foundation Audit — 2026-11-25

**Status:** Initial evidence-based audit; partial scope, not a completion certificate.  
**Authority:** Conducted against the mandatory requirements in [NIBLIT_ENGINEERING_DOCTRINE.md](NIBLIT_ENGINEERING_DOCTRINE.md).  
**Scope in this pass:** Native cognition / structured keywords, memory and Qdrant projection, local GGUF / llama.cpp host integration.  
**Not yet audited:** Full native LLM training/architecture, full cognition stack beyond the inspected path, custom OS/kernel/firmware/driver design, trading research/strategy architecture, UI and Android integration.

## 1. Preservation and audit method

Repositories inspected:
- Core: `C:\Users\Riyaad\Documents\GitHub\Niblit`, HEAD observed `301571f0`.
- Cloud server: `C:\Users\Riyaad\Documents\GitHub\niblit-cloud-server`, HEAD observed `5dfec96`.

Both repositories contained extensive pre-existing uncommitted and untracked work. That work was preserved. No reset, clean, stash, stage, commit, discard or runtime source edit was performed in this audit. The only files created by this pass are this audit report and its read-only SQLite inspection helper under the R16 acceptance workspace.

Evidence was collected by direct source inspection and read-only runtime checks. Tests used the Core repository's existing `niblit-env` Python environment and a fresh basetemp under the R16 acceptance workspace.

## 2. Native cognition and structured keyword architecture

### Verified implementation

The Core repository contains `modules/native_cognition/` with:
- Unicode/alphabet inspection;
- lexical tokenisation and sentence signals;
- number and arithmetic primitives;
- relation cue extraction;
- a versioned keyword lexicon;
- deterministic cognitive procedure selection;
- seed-pack generation and source-to-cognition analysis.

The inspected analyzer declares schema `niblit.native-cognition/0.2`. It preserves source hashes and original character offsets, records numeric and relation candidates, creates keyword-group summaries and proposes a deterministic cognitive plan. The lexicon is versioned `0.2.0` and defines 21 English keyword groups. Hits are explicitly marked as lexical or numeric cues, not verified facts.

`modules/local_brain.py::_native_cognition_context` integrates this as a bounded prompt hint: it analyzes up to 4,500 characters, only adds context for sufficiently long input, and caps the hint at 1,800 characters. The code explicitly says cues are heuristics and not facts. This is a real deterministic preprocessing integration, but it is not a trained native LLM and does not alter model weights.

### Limitations explicitly present in the implementation/docs

- The word-number parser and keyword ontology are English-oriented.
- Part-of-speech, sentence and morphology signals are heuristic.
- Relation extraction finds lexical cues; it does not establish subject/object triples or verified causal links.
- Negation scope, coreference, idioms, complete grammar/dependency parsing and multilingual morphology are not implemented.
- Unit algebra, symbolic algebra, theorem proving, speech/phoneme support and adaptive curriculum integration are later work.
- The cognitive scripts are deterministic analysis plans; they do not independently perform general reasoning or execute instructions from untrusted sources.

### Audit classification

**Implemented:** deterministic source analysis, typed cue groups, source offsets/hashes, numeric extraction, candidate relation signals and prompt-context integration.

**Partial / prototype:** central structured keyword and knowledge representation. The current lexicon is a useful, inspectable cue ontology, but it is not yet a complete cross-domain, multilingual, compositional semantic representation with validated parsing, entity resolution, relation construction and typed domain contracts.

**Not established by this pass:** an independently trained Niblit LLM, full native language understanding, general reasoning engine or weight-learning lifecycle.

## 3. Memory and Qdrant

### Verified architecture

The inspected Memory Laboratory code describes SQLite as the canonical source ledger/outbox and Qdrant as a rebuildable projection. `MemoryRuntime` owns durable ingestion jobs, and the gateway contains embedding, point projection, read-back verification, retrieval and remote projection paths. The inspected Qdrant setup defines:
- HTTPS plus API-key requirements for remote endpoints;
- Qdrant server compatibility checks;
- a pinned `intfloat/multilingual-e5-small` model revision;
- CPU-only, bounded embedding batches with downloads disabled by default;
- E5 query/passage prefixes;
- versioned collection names incorporating model identity, revision, dimension and distance;
- payload indexes for schema, namespace, category, source identity, hashes, lifecycle, access principals, sensitivity, verification and update time;
- additive collection/index setup and preservation-oriented migration behaviour.

This is substantially more than merely connecting a Qdrant URL. The code has an explicit provider-specific integration design.

### Live read-only verification

The Core ledger at `runtime/memory-framework/ledger.sqlite3` was inspected using SQLite read-only mode. For `native://niblit/foundation/%` seed sources, the database contained:
- 14 pending rows;
- 1 superseded row;
- 0 processing attempts for those rows;
- no completed native foundation seed projection evidenced by those rows.

The Qdrant read-only preflight was run against the configured Core `.env`. It returned `read_failed`, exception type `ResponseHandlingException`, and `writes_attempted: 0`. A separate diagnostic resolved the configured cluster host, connected TCP on ports 443 and 6333, then received `ConnectionResetError [WinError 10054]` during TLS negotiation on both ports. The same TCP-success/TLS-reset result was reproduced from the VPS, so this is not isolated to the desktop's local route. No database write was attempted. The evidence points to a remote endpoint/service-side or upstream transport problem; it does not yet distinguish a suspended/unhealthy cluster from an upstream TLS/network policy. Qdrant Cloud retrieval acceptance therefore remains unverified.

### Audit classification

**Implemented:** governed SQLite outbox, Qdrant projection/retrieval code, versioned collection identity, embedding configuration, payload/index definitions and read-back verification logic.

**Blocked / not accepted:** live Qdrant Cloud connectivity and end-to-end native foundation seed retrieval. The seed records remain pending/unverified. Do not claim the native foundation has been learned or is retrievable from Qdrant until live ingestion, read-back, filtered retrieval and provenance checks pass.

**Architecture issue to resolve:** a separate legacy `modules/embedding_engine.py` declares a fixed 384-dimensional embedding contract for `intfloat/multilingual-e5-small`, while Memory Laboratory has its own pinned `DedicatedEmbedder` and versioned dynamic collection contract. Their ownership, lifecycle, model revision and intended consumer boundaries must be formally reconciled; do not merge them or assume they are interchangeable based on matching dimensions.

## 4. Local GGUF and llama.cpp

### Verified host configuration

The Cloud Server's `.env.local` configures `NIBLIT_GGUF_MODEL_DIR=D:/models`. That directory contains:
- Qwen2.5-Coder 3B Q4_K_M;
- Qwen2.5-Coder 14B Q4_K_M;
- Qwen2.5 0.5B Q4_K_M;
- Llama 3.2 1B Q4_K_M;
- Gemma 3 4B Q4_K_M;
- Qwen3 1.7B Q8_0;
- Qwen3 4B Q4_K_M;
- a multimodal projector GGUF.

The current local model registry explicitly recognises canonical IDs for Qwen2.5-Coder 3B/14B, Llama 3.2 1B and Qwen2.5 0.5B. Other files are not automatically guessed into executable model IDs. This is a sensible identity boundary, but the intended support/registration plan for Gemma and Qwen3 must be explicit.

### llama.cpp backend evidence

The source tree exists at `C:\Users\Riyaad\llama_migration\llama.cpp`. One CMake build cache has `GGML_VULKAN=ON`; a separate `build-x64-windows-msvc-release` cache has `GGML_VULKAN=OFF`. The Vulkan-enabled `llama-server.exe` reports build version `9205 (dd7cad719)`. Its read-only `--list-devices` output identifies `Vulkan0: Radeon RX 580 Series (8192 MiB)`.

This proves that this particular standalone llama-server binary exposes the Vulkan device. It does not prove that Niblit's active Python inference route uses that binary or offloads model layers to the GPU.

### Important active-runtime mismatch

The Cloud Server virtual environment contains `llama-cpp-python 0.3.16`. Its native runtime reports `llama_supports_gpu_offload() == False`, and the inspected package directory contains CPU GGML DLLs but no Vulkan backend DLL. The primary `GGUFEngine` in `app/main.py` uses this Python binding directly.

The alternative native Windows `QwenServerProvider` launches the standalone llama-server, but its versioned profile validation currently rejects any GPU-layer value other than zero. Therefore the inspected Windows provider path is explicitly CPU-only even though the standalone Vulkan binary can enumerate the RX 580.

**Finding:** a Vulkan-capable llama.cpp build exists, but the inspected Cloud Server runtime paths do not currently demonstrate GPU-offloaded GGUF inference. This is a genuine build/runtime integration gap, not something to hide by setting an environment variable. The correct next step is to define one authoritative inference backend and build/package it against the intended Windows/Vulkan toolchain, then verify device placement, layer offload, memory use, throughput and model correctness with a real model load.

### Legacy path and workaround risks

- `modules/local_brain.py` still defines `_WINDOWS_MODEL_ROOT=C:\Users\Riyaad\llama_migration\models` and its discovery routine scans that obsolete path. The actual Cloud Server model directory is configured as `D:/models`. LocalBrain's discovery can therefore report zero models while the Cloud Server registry sees the configured model directory. This is a real stale path contract that needs a proper shared configuration contract, not another fallback patch.
- The Cloud Server `GGUFEngine` contains Windows-specific workarounds/comments around `use_mmap=False` and omitted constructor arguments after reported native crashes. These require a disciplined upstream-version/issue/reproduction audit before being accepted as permanent design.
- Three `app/debug/patch_*.py` files exist. No runtime imports/references to those patch scripts were found in the inspected Cloud Server Python source. They are classified as legacy/debug artifacts for review, not as proof that the current runtime monkey-patches itself. Do not execute or delete them without a separate provenance and usage review.

### Audit classification

**Implemented:** GGUF model registry, model identity checks, local model directory configuration, llama.cpp standalone Vulkan build and device enumeration.

**Partial / not accepted:** one coherent, authoritative local inference backend with verified Vulkan execution, consistent model path ownership, hardware-aware resource scheduling and documented performance acceptance.

## 5. Test evidence

Command executed from the Core `niblit-env`:
`pytest -q tests/test_native_cognition_foundation.py tests/test_native_cognition_local_brain_integration.py tests/test_native_cognition_research_integration.py tests/test_memory_framework_runtime.py`

Result: process exited with code 0; all collected test indicators completed successfully (66 progress dots). Deprecation warnings were emitted by the installed Binance/websockets dependency. These tests verify local logic and integration contracts; they do not prove live Qdrant connectivity or GPU inference.

## 6. Required next engineering sequence

1. **Resolve the memory provider acceptance blocker:** restore Qdrant Cloud connectivity; verify server version, collection schemas, vector dimensions/metric, payload indexes and API scopes read-only first. Then use the existing governed outbox and approved seed sources to project only the intended records. Verify point read-back, filtered retrieval, source provenance, namespace/principal isolation and retrieval quality. Do not bypass the canonical worker or create another memory ledger.
2. **Define the canonical structured information contract:** specify typed representations for source, token/span, keyword/concept, entity, relation, claim, evidence, uncertainty, temporal scope, units and provenance. Version the schema and specify normalization, parsing, validation, unknown/ambiguous handling and provider adapters. Keep current cue extraction explicitly as a feature layer until richer parsers are implemented.
3. **Unify embedding ownership deliberately:** decide which embedding service owns each workload, document immutable model/revision/dimension/normalization/prefix contracts and collection migration rules, then add contract tests across all consumers.
4. **Resolve the local GGUF backend mismatch:** choose the authoritative runtime (Python binding or standalone llama-server), build/package the selected backend with the intended Vulkan support, remove conflicting CPU-only profile assumptions through a proper versioned contract, and verify real GPU offload on the RX 580. Correct LocalBrain's model discovery to use the same canonical model registry/configuration as Cloud Server.
5. **Audit native LLM development honestly:** map any tokenizer, training-data, training, fine-tuning, evaluation and inference components; classify what is native versus delegated to Qwen/Llama/Gemma models. Do not call prompt preprocessing or GGUF orchestration an independently trained Niblit LLM.
6. **Continue the same evidence-based audit for cognition, OS/kernel/boot/firmware/drivers and quantitative trading** before changing those subsystems.

## 7. Change policy for the next pass

This audit does not authorize a wholesale rewrite. Preserve all existing uncommitted work. Make one contract-level correction at a time, first write the specification and acceptance tests, then implement the correct integration. No runtime source was modified in this audit. The read-only helper is located under the R16 acceptance workspace, not in the application runtime.


## 8. Authoritative platform references consulted

- llama.cpp Windows/Vulkan build procedure: https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md#vulkan
- llama.cpp server build and runtime interface: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- llama-cpp-python official installation configuration, including `CMAKE_ARGS="-DGGML_VULKAN=on"`: https://github.com/abetlen/llama-cpp-python#installation-configuration
- Qdrant Cloud cluster endpoint, REST ports and database API-key usage: https://qdrant.tech/documentation/cloud-getting-started/
- Qdrant Cloud authentication and granular API-key permissions: https://qdrant.tech/documentation/cloud/authentication/

These references inform the next implementation work. Re-check current upstream instructions and version compatibility at the time of implementation; do not assume that a current upstream page exactly matches the locally pinned package revision.
