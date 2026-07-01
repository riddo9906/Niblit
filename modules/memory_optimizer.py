#!/usr/bin/env python3
"""
MEMORY OPTIMIZER MODULE
Compress, organize, and optimize memory storage.

Improvements over the original:
- _compress_text() now uses sentence scoring (word-frequency based extractive
  summarisation) instead of naively keeping the first 2 sentences.
- compress_memories() calls KB consolidate_facts() + decay_stale_confidence()
  when a KnowledgeDB is wired in, so the canonical store gets cleaned up, not
  just the in-memory list.
- compress_memories() guards against division-by-zero when facts list is empty.
- merge_duplicates() consolidates semantically identical records.
- detect_contradictions() flags records with opposing content on the same topic.
- link_related_concepts() extracts shared term clusters across records.
- archive_lifecycle_candidates() moves stale records to archived state instead
  of deleting them.
"""

import logging
import re
import time
from typing import Any, Dict, List, Set, Tuple
import hashlib

log = logging.getLogger("MemoryOptimizer")

# Maximum number of sentences to keep when compressing a text block.
_MAX_SENTENCES: int = 3

# Minimum word length to count for sentence scoring (stop-word filtering).
_MIN_WORD_LEN: int = 4
_STOP_WORDS: frozenset = frozenset({
    "the", "and", "for", "that", "this", "with", "from", "have", "will",
    "are", "was", "were", "been", "being", "also", "into", "than", "more",
    "some", "such", "when", "they", "them", "what", "which", "very",
})

# Word pairs commonly indicating contradiction in factual statements.
_CONTRADICTION_MARKERS: tuple = (
    ("is", "is not"),
    ("does", "does not"),
    ("can", "cannot"),
    ("works", "does not work"),
    ("supported", "not supported"),
    ("true", "false"),
    ("yes", "no"),
    ("increases", "decreases"),
    ("enables", "disables"),
)

# Number of days after which a fact not recently accessed is considered stale.
_STALE_DAYS: int = int(__import__("os").environ.get("NIBLIT_MEMORY_STALE_DAYS", "30"))


class MemoryOptimizer:
    """Optimize memory storage and retrieval."""

    def __init__(self, knowledge_db=None):
        self.db = knowledge_db
        self.compression_stats: Dict[str, Any] = {}

    def compress_memories(self, facts: List[Dict]) -> Tuple[List[Dict], Dict]:
        """Compress memory entries: deduplicate + extractive text compression.

        When a KnowledgeDB is wired in, also calls the KB's own
        ``consolidate_facts()`` and ``decay_stale_confidence()`` methods so
        that stale / duplicate entries are removed at the canonical storage
        level as well.
        """
        if not facts:
            stats: Dict[str, Any] = {
                "original_count": 0,
                "compressed_count": 0,
                "duplicates_removed": 0,
                "compression_ratio": "0.0%",
            }
            self.compression_stats = stats
            return [], stats

        log.info("🗜️ [OPTIMIZE] Compressing %d memory entries", len(facts))

        compressed: List[Dict] = []
        seen_hashes: set = set()
        duplicates = 0

        for fact in facts:
            fact_str = f"{fact.get('key')}{fact.get('value')}"
            fact_hash = hashlib.sha256(fact_str.encode()).hexdigest()

            if fact_hash not in seen_hashes:
                value = fact.get("value", "")
                compressed_value = self._compress_text(str(value))
                compressed.append({
                    "key": fact.get("key"),
                    "value": compressed_value,
                    "tags": fact.get("tags", []),
                    "confidence": fact.get("confidence"),
                })
                seen_hashes.add(fact_hash)
            else:
                duplicates += 1

        ratio = (1 - len(compressed) / len(facts)) * 100
        stats = {
            "original_count": len(facts),
            "compressed_count": len(compressed),
            "duplicates_removed": duplicates,
            "compression_ratio": f"{ratio:.1f}%",
        }
        self.compression_stats = stats
        log.info("✅ [OPTIMIZE] Compressed: %s", stats)

        # KB-level consolidation/decay if available
        self._kb_consolidate()

        return compressed, stats

    def merge_duplicates(self, facts: List[Dict]) -> Tuple[List[Dict], int]:
        """Merge semantically near-duplicate facts into a single consolidated record.

        Two facts are considered duplicates when their content-text similarity
        (normalised token overlap) exceeds 0.85.  The merged record keeps the
        highest confidence score and the union of all tags, and its summary is
        the compressed extractive version of the combined text.

        Returns
        -------
        (merged_facts, merge_count)
            merged_facts — deduplicated list
            merge_count  — number of records that were merged into others
        """
        if not facts:
            return [], 0

        log.debug("[MemoryOptimizer] merge_duplicates: %d facts", len(facts))
        merged: List[Dict] = []
        consumed: Set[int] = set()
        merge_count = 0

        for i, fact_a in enumerate(facts):
            if i in consumed:
                continue
            group = [fact_a]
            text_a = _fact_text(fact_a)
            for j, fact_b in enumerate(facts[i + 1:], start=i + 1):
                if j in consumed:
                    continue
                text_b = _fact_text(fact_b)
                if _token_similarity(text_a, text_b) >= 0.85:
                    group.append(fact_b)
                    consumed.add(j)
                    merge_count += 1

            if len(group) == 1:
                merged.append(fact_a)
                continue

            # Merge group → single record
            combined_text = " ".join(_fact_text(f)[:400] for f in group)
            best_conf = max(
                (float(f.get("confidence") or f.get("confidence_score") or 0.5) for f in group),
                default=0.5,
            )
            union_tags: List[str] = list({
                t for f in group for t in (f.get("tags") or [])
            })
            merged.append({
                "key": fact_a.get("key"),
                "value": self._compress_text(combined_text),
                "tags": union_tags,
                "confidence": best_conf,
                "confidence_score": best_conf,
                "merged_count": len(group),
            })

        log.info("[MemoryOptimizer] merge_duplicates: %d → %d (merged=%d)",
                 len(facts), len(merged), merge_count)
        return merged, merge_count

    def detect_contradictions(self, facts: List[Dict]) -> List[Dict]:
        """Detect pairs of facts whose content statements appear contradictory.

        Uses simple marker-pair matching to flag candidate contradictions.
        Returns a list of contradiction records, each containing the two
        conflicting fact keys and a reason string.  Does not modify the
        original facts list.

        Callers should re-weight the confidence scores of flagged facts.
        """
        findings: List[Dict] = []
        texts = [(_fact_text(f).lower(), f.get("key", "")) for f in facts]

        for i in range(len(texts)):
            text_a, key_a = texts[i]
            for j in range(i + 1, len(texts)):
                text_b, key_b = texts[j]
                for pos, neg in _CONTRADICTION_MARKERS:
                    if pos in text_a and neg in text_b and text_a[:100] != text_b[:100]:
                        findings.append({
                            "key_a": key_a,
                            "key_b": key_b,
                            "reason": f"contradiction: '{pos}' vs '{neg}'",
                            "detected_at": int(time.time()),
                        })
                        break
                    if neg in text_a and pos in text_b and text_a[:100] != text_b[:100]:
                        findings.append({
                            "key_a": key_a,
                            "key_b": key_b,
                            "reason": f"contradiction: '{neg}' vs '{pos}'",
                            "detected_at": int(time.time()),
                        })
                        break

        if findings:
            log.info("[MemoryOptimizer] detect_contradictions: %d pairs flagged", len(findings))
        return findings

    def link_related_concepts(self, facts: List[Dict]) -> Dict[str, List[str]]:
        """Build a concept→related-concepts map from shared term clusters.

        For each fact, extract its top-5 meaningful terms.  Two facts share a
        cluster edge when they have at least 2 terms in common.  The returned
        map links each fact key to a list of keys with overlapping vocabulary,
        suitable for populating the ``related_concepts`` intelligence field.
        """
        if not facts:
            return {}

        # Build term sets
        term_sets: List[Tuple[str, Set[str]]] = []
        for f in facts:
            key = f.get("key", "")
            text = _fact_text(f).lower()
            terms = {
                w for w in re.findall(r"[a-z]+", text)
                if len(w) >= _MIN_WORD_LEN and w not in _STOP_WORDS
            }
            # Keep only the most frequent terms (by length as a proxy)
            top_terms = set(sorted(terms, key=len, reverse=True)[:10])
            term_sets.append((key, top_terms))

        links: Dict[str, List[str]] = {}
        for i, (key_a, terms_a) in enumerate(term_sets):
            for key_b, terms_b in term_sets[i + 1:]:
                if len(terms_a & terms_b) >= 2:
                    links.setdefault(key_a, []).append(key_b)
                    links.setdefault(key_b, []).append(key_a)

        return links

    def archive_lifecycle_candidates(self, facts: List[Dict]) -> Tuple[List[Dict], int]:
        """Mark stale records as archived instead of deleting them.

        A record is a lifecycle-archive candidate when:
        - Its ``last_accessed_at`` timestamp is older than ``_STALE_DAYS`` days, AND
        - It is not pinned or governance-locked, AND
        - It is not already archived.

        Returns the modified list and the count of newly archived records.
        """
        now = int(time.time())
        stale_cutoff = now - (_STALE_DAYS * 86400)
        archived_count = 0

        for fact in facts:
            val = fact.get("value") or {}
            if not isinstance(val, dict):
                continue
            lifecycle = val.get("lifecycle") or {}
            if lifecycle.get("state") == "archived":
                continue
            if lifecycle.get("pinned") or lifecycle.get("governance_locked"):
                continue
            last_accessed = int(
                val.get("last_accessed_at") or val.get("last_updated_at") or now
            )
            if last_accessed < stale_cutoff:
                lifecycle["state"] = "archived"
                lifecycle["archive_candidate"] = True
                val["lifecycle"] = lifecycle
                fact["value"] = val
                archived_count += 1

        if archived_count:
            log.info("[MemoryOptimizer] archive_lifecycle_candidates: %d archived", archived_count)
        return facts, archived_count

    def organize_hierarchically(self, facts: List[Dict]) -> Dict[str, List[Dict]]:
        """Organise facts hierarchically by key-prefix category."""
        log.info("📊 [OPTIMIZE] Organizing %d facts hierarchically", len(facts))
        hierarchy: Dict[str, List[Dict]] = {}
        for fact in facts:
            key = fact.get("key", "")
            category = key.split(":")[0] if ":" in key else "uncategorized"
            hierarchy.setdefault(category, []).append(fact)
        log.info("✅ [OPTIMIZE] Organized into %d categories", len(hierarchy))
        return hierarchy

    def optimize_retrieval(self, facts: List[Dict]) -> Dict[str, List[str]]:
        """Build a tag + key index for faster retrieval."""
        log.info("⚡ [OPTIMIZE] Creating retrieval index")
        index: Dict[str, List[str]] = {}
        for fact in facts:
            key = fact.get("key", "")
            val = fact.get("value", "")
            index.setdefault(key, []).append(val)
            for tag in fact.get("tags", []):
                index.setdefault(tag, []).append(val)
        log.info("✅ [OPTIMIZE] Index created with %d entries", len(index))
        return index

    # ── Internal helpers ───────────────────────────────────────────────────────

    def _compress_text(self, text: str, max_sentences: int = _MAX_SENTENCES) -> str:
        """Extractive compression: score sentences by meaningful-word frequency.

        Steps:
        1. Split into sentences.
        2. Build a word-frequency map (stop-word filtered, length ≥ _MIN_WORD_LEN).
        3. Score each sentence by the sum of frequencies of its words.
        4. Return the top ``max_sentences`` sentences, preserved in original order.

        Short texts (< 80 chars or ≤ max_sentences sentences) are returned as-is.
        """
        if not isinstance(text, str):
            text = str(text)
        if len(text) < 80:
            return text

        # Split into sentences on period/exclamation/question mark
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        if len(sentences) <= max_sentences:
            return text

        # Build word frequency map
        word_freq: Dict[str, int] = {}
        for sent in sentences:
            for word in re.findall(r"[a-z]+", sent.lower()):
                if len(word) >= _MIN_WORD_LEN and word not in _STOP_WORDS:
                    word_freq[word] = word_freq.get(word, 0) + 1

        # Score sentences
        scored: List[Tuple[int, float, str]] = []
        for idx, sent in enumerate(sentences):
            words = re.findall(r"[a-z]+", sent.lower())
            score = sum(
                word_freq.get(w, 0)
                for w in words
                if len(w) >= _MIN_WORD_LEN and w not in _STOP_WORDS
            )
            scored.append((idx, score, sent))

        # Select top-N by score, preserve original order
        top = sorted(scored, key=lambda x: x[1], reverse=True)[:max_sentences]
        top_sorted = [t[2] for t in sorted(top, key=lambda x: x[0])]
        return " ".join(top_sorted)

    def _kb_consolidate(self) -> None:
        """Run KB-level consolidation and confidence decay when available."""
        if self.db is None:
            return
        try:
            if hasattr(self.db, "consolidate_facts"):
                self.db.consolidate_facts()
                log.debug("[MemoryOptimizer] KB consolidate_facts() called")
        except Exception as exc:
            log.debug("[MemoryOptimizer] consolidate_facts failed: %s", exc)
        try:
            if hasattr(self.db, "decay_stale_confidence"):
                self.db.decay_stale_confidence()
                log.debug("[MemoryOptimizer] KB decay_stale_confidence() called")
        except Exception as exc:
            log.debug("[MemoryOptimizer] decay_stale_confidence failed: %s", exc)


# ---------------------------------------------------------------------------
# Module-level helpers used by MemoryOptimizer methods
# ---------------------------------------------------------------------------

def _fact_text(fact: Dict) -> str:
    """Extract the best text representation from a fact dict."""
    val = fact.get("value") or {}
    if isinstance(val, dict):
        return str(
            val.get("content") or val.get("text") or val.get("summary")
            or val.get("content_text") or ""
        )
    return str(val or "")


def _token_similarity(text_a: str, text_b: str) -> float:
    """Compute normalised token-overlap (Jaccard) between two text strings."""
    words_a = set(re.findall(r"[a-z]+", text_a.lower()))
    words_b = set(re.findall(r"[a-z]+", text_b.lower()))
    if not words_a and not words_b:
        return 1.0
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


if __name__ == "__main__":
    print('Running memory_optimizer.py')

