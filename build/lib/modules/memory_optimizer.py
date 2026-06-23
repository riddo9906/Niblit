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
"""

import logging
import re
from typing import Any, Dict, List, Tuple
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


if __name__ == "__main__":
    print('Running memory_optimizer.py')

