# Niblit memory structure

Updated 25 October 2026.

## Storage responsibilities

| Layer | Implementation | Responsibility |
| --- | --- | --- |
| Canonical knowledge | `niblit_memory.KnowledgeDB` | Facts, preferences, events, learning records, relationships; JSON persistence through its coordinator |
| Compatibility facade | `niblit_memory.NiblitMemory` | Legacy memory API; shares canonical state, lock, and writer when configured for the same file |
| Chat history | `modules.llm_chat_memory.LLMChatMemory` | Durable user/assistant exchanges in SQLite across application restarts |
| Context selection | `modules.memory_context.select_recent_messages` | Pure rules for selecting recent conversation context; no database or inference access |
| Unified cognitive memory | `niblit_memory.unified_memory_engine.UnifiedMemoryEngine` | Category-specific in-process recall, importance, anchor protection, and forwarding to knowledge/governed memory |
| Semantic retrieval | Fused memory and governed Qdrant memory | Vector retrieval and governed records; optional backend availability is separate from chat persistence |
| Graph memory | Existing cognitive memory and graph-scoring modules | Structured concept relationships and retrieval-backed reasoning |

## Write ownership

KnowledgeDB owns the canonical JSON snapshot. A NiblitMemory facade configured
for that same path shares its dictionary and lock and delegates saves to the
existing persistence coordinator. This prevents two independent snapshots
from overwriting each other's updates. A facade explicitly configured for a
different file keeps independent storage and uses the existing atomic commit
manager. An invalid snapshot is serialized before replacing existing data.

Unified semantic writes use the actual `add_fact` API. The previous adapter
checked for a nonexistent `store_fact` method and silently skipped those writes.
Memory IDs now incorporate full content, rather than only its first 120
characters. Repeated records retain accumulated tags and gain in-process
anchor protection when pinned or promoted above the importance threshold.

This change does not rename or migrate existing memory files and does not
provide cross-process JSON coordination. Historical records already lost by
the earlier prefix collision cannot be reconstructed from the in-process cache.

## Conversation continuity

Completed turns use `add_exchange(user, assistant)`: both messages commit in a
single SQLite transaction, or neither does. Dashboard file-question responses,
chat completions, and the HF integrations use this method. Individual `add`
writes remain supported. Connections close after use, and session IDs use UUIDs.

History remains stored when Niblit restarts or inference is paused. Loading
context selects at most 40 messages and 24,000 content characters by default.
The selection preserves a chronological suffix and whole messages, and drops
an assistant reply whose question fell outside the window. If the newest
message is too large to fit, older context is not substituted for it. Selection
does not delete stored history. Explicit `max_chars=None` disables the text
budget; nonpositive limits return no messages.

Character budgets are not model token budgets. The full prompt, source
evidence, and requested output still require provider-specific token accounting.
Automatic summarization and per-conversation isolation are separate future
changes; current default history intentionally spans application sessions.

## Reasoning fallback

An empty parsed inference response does not count as successful reasoning.
The existing ranked graph-memory fallback remains available when the provider
returns no conclusion. This does not fabricate a successful model response.

## Verification

Tests use disposable SQLite/JSON files and disable external model downloads.
Coverage includes restart continuity, concurrent turn ordering, transaction
rollback, bounded context, prefix collisions, anchor promotion, shared JSON
ownership, invalid serialization, semantic forwarding, and graph fallback.
The existing memory, cognitive architecture, HF, chat-completions, and dashboard
file-question regressions were also exercised. Machine-readable results live
under `diagnostics/memory-*.xml` and are excluded from source control.

These changes update source code. The previously built desktop executable
must be rebuilt to include them. No full interactive inference session or
memory migration is claimed by the unit and integration checks.
