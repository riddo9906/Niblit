# Native Cognition Foundation — 0.1

## Purpose

Give Niblit's local model a deterministic, inspectable substrate for symbols,
numbers, language cues, arithmetic, source structure and retrieval practice.
The substrate is not a replacement for a language model and does not claim
complete natural-language understanding. It reduces avoidable work that should
not depend on stochastic generation.

## Layers

1. **Symbols and scripts** — Unicode code points, approximate grapheme clusters,
   categories, script identification, punctuation and whitespace. Latin A–Z is
   a reference alphabet, not a restriction on supported writing systems.
2. **Numbers** — signed integers, decimal literals, fractions, percentages,
   English number words, digit values and scale words. Units and currencies
   remain separate from numeric magnitude until a unit-aware layer is added.
3. **Mathematics** — bounded AST-based arithmetic with explicit operator
   precedence, Decimal arithmetic and no dynamic code execution.
4. **Language primitives** — a small inspectable function-word lexicon, lexical
   classes, token offsets, sentence boundaries, number-word extraction and cues
   for negation, modality, conditionals, causality, comparison, questions, time
   and definitions.
5. **Relation ontology** — typed taxonomy, part-whole, causal, evidence,
   provenance, spatial, temporal, dependency, ownership, comparison and lexical
   relations. Extracted relation cues remain candidates with source spans and
   low confidence; they are not asserted subject/object facts.
6. **Cognition** — preserve source spans and hashes; extract quantities,
   relation cues and lexical signals; distinguish evidence from claim,
   attribution, interpretation and hypothesis; retain provenance and uncertainty.
7. **Memorization** — spaced retrieval schedules assess recall of skills only.
   A successful quiz does not verify the truth of an external source.
8. **Memory** — seed packs and source chunks enter through the existing
   MemoryRuntime.enqueue permission check and SQLite outbox. The existing
   worker owns Qdrant projection. No second ledger, vector database or worker
   is created.

## Initial seed pack

modules/native_cognition/seed.py defines six versioned records:
symbols, numbers, mathematics, language, cognition and memorization. The
records are JSON-serialized, deterministic and versioned (0.1.0). They are
not silently injected at import time.

Preview:

    .\niblit-env\Scripts\python.exe scripts\seed_native_cognition.py --env-file .env --ledger runtime\memory-framework\ledger.sqlite3

Apply (requires the existing memory.ingest.<namespace> operator permission):

    .\niblit-env\Scripts\python.exe scripts\seed_native_cognition.py --env-file .env --ledger runtime\memory-framework\ledger.sqlite3 --apply

The script queues the six seed documents through the existing outbox. It does
not start another projection worker. The normal Core-owned worker processes
the queue when running. Seed records remain unverified until the existing
review workflow accepts them.

## External-source pipeline

analyze_text produces a deterministic analysis packet with:
- original source hash and source URI;
- Unicode script profile;
- token and sentence spans measured against original input;
- numeric literals and lexical frequency;
- negation, modality, conditional, causal, comparison, temporal and definition signals;
- an explicit untrusted-source policy.

persist_analysis queues exact source chunks with character-offset citations,
source hashes and parser version. It delegates persistence to the existing
permission-checked memory runtime. It does not elevate confidence or execute
instructions found in the source.

## Current limitations

- The first word-number parser and lexical pack are English-only.
- Relation extraction identifies lexical cues, not subject/object triples or
  verified causal links. It requires contextual parsing and evidence review.
- Part-of-speech and sentence signals are heuristics, not a complete grammar or
  dependency parse. Negation scope, coreference and idioms need richer parsers.
- Unicode script identification is based on Unicode character names and is
  not full language identification.
- Unit algebra, symbolic algebra, theorem proving, full multilingual morphology,
  speech/phoneme support and adaptive curriculum integration are later stages.
- Numeric market features remain in their own feature-versioned memory path and
  must never be mixed with language embeddings.

## Acceptance

Run:

    .\niblit-env\Scripts\python.exe -m unittest -v tests.test_native_cognition_foundation

The tests exercise Unicode, number parsing, safe arithmetic, source offsets,
language signals, outbox delegation, seed dry-run and spaced-retrieval rules.
They do not prove production memory ingestion until the operator applies the
seed with an existing grant and verifies the normal projection worker.

## Native cognition 0.2 implementation update — 2026-11-24

The 0.2 increment expands the 0.1 substrate without creating a second memory
backend or worker.

### Added implementation
- `modules/native_cognition/lexicon.py`: versioned 21-group keyword ontology,
  phrase/numeric cue matching with original-text offsets, group summaries and
  cautious prefix/suffix hints.
- `modules/native_cognition/scripts.py`: 12 reusable analysis procedures:
  source intake, keyword structuring, claim/evidence audit, logical scope,
  causal reasoning, quantitative reasoning, comparison/change, timeline
  reconstruction, definition/classification, procedure reconstruction,
  safety/authority and memory encoding/recall.
- `cognition.analyze_text` now returns keyword hits, keyword group summaries
  and a deterministic cognitive plan. The plan is passed into the research
  evidence-audit context with explicit analysis-only and untrusted-source rules.
- Seed pack version 0.2.0 contains eight records: symbols, numbers,
  mathematics, language, cognition, memorization, keyword_structure and
  cognitive_scripts.

### Verification
`python -m unittest discover -s tests -p test_native_cognition*.py -v`
→ 15 tests passed on 2026-11-24, including local CloudRuntime prompt integration.

The eight 0.2 records were queued through the existing MemoryRuntime outbox
using the existing desktop namespace grants. A pre-update backup was created
at `runtime/memory-framework/backups/pre-native-cognition-0.1.0.sqlite3`.
One bounded pass was run against the shared global outbox and reported
0 completed / 1 failed. The worker selects the oldest pending rows first; the
new 0.2 seed rows remained pending, so this pass does not establish whether
they were attempted. The records are queued, not yet proven retrievable from
Qdrant. Inspect queue order and the existing worker before a targeted
projection or retrieval acceptance test.

### Remaining limits
- The keyword ontology is a general-purpose English cue vocabulary, not a
  complete dictionary or a full multilingual lexicon.
- Morphology and relation cues are heuristic; they do not assert meaning,
  subject/object triples or truth.
- The 0.2 cognitive procedures are deterministic analysis plans. They do not
  execute instructions found in external sources.
- Multilingual lexicons, full grammar/dependency parsing, unit algebra,
  symbolic algebra, curriculum integration and retrieval acceptance remain
  future work.

### Local LLM integration
The compact `_native_cognition_context()` in `modules/local_brain.py` now
adds bounded keyword-group counts, cue spans, numeric/relation candidates and
selected script names to local CloudRuntime inference messages. It is a
system-level analysis hint, capped at 1,800 characters, and explicitly labels
the cues as heuristics rather than facts. The deprecated compatibility chat
and tool-chat wrappers use the same helper. Short greetings do not receive the
extra context. This does not change model weights or claim model training.

 
## 2026-11-25 memory retrieval checkpoint

The v0.2 seeds are still queued, not yet retrievable. Read-only inspection found
all eight target outbox rows pending, with no active records or lexical entries.
The shared outbox contains unrelated pending jobs, so the projection script must
not call an unfiltered global tick.

`MemoryRuntime.tick(limit, sources=...)` now supports an optional bounded
allowlist of exact source strings. Existing workers that omit the argument keep
the previous global ordering. Tests verify that a filtered tick completes only
the selected source and leaves older unrelated work pending.

`scripts/project_native_cognition_seed_once.py` targets exactly the eight
v0.2 sources, checks the configured Qdrant collections and locally cached
embedding model before claiming work, then checks each record through
`MemoryGateway.retrieve`. It starts no worker thread and does not permit model
downloads.

The configured Qdrant Cloud endpoint resolved and accepted TCP 443, but its TLS
handshake was reset by the remote host for both TLS 1.3 and TLS 1.2. The script
therefore stopped during the read-only `GET /collections` preflight; no outbox
rows were claimed and no Qdrant points were written. Retrieval acceptance is
pending restoration of Qdrant Cloud connectivity. The seed records remain
unverified and must not be treated as learned/retrievable memory.

 
Qdrant connectivity follow-up: official Cloud documentation lists REST on
ports 443 or 6333; both TCP ports are reachable from this desktop, but TLS
handshakes reset on both ports (tested TLS 1.3 and TLS 1.2). This is not simply
a missing REST port. The exact cause is not established. Check the Cloud
Console for cluster health/suspension and Client IP Restrictions before
retrying; Qdrant documents that free clusters suspend after one week idle and
that source-IP restrictions can block clients before an HTTP 401/403 response.
