#!/usr/bin/env python3
"""
modules/knowledge_filter.py — Knowledge Storage Filter & Summarizer for Niblit.

Ensures that only genuine research, learning, and domain knowledge is persisted
in Niblit's KnowledgeDB — not internal system noise such as routing events,
ALE step metadata, loop counters, or command-dispatch records.

When Niblit is asked to recall or summarize what it knows, this module
returns clean, human-readable summaries instead of raw JSON blobs of
system state.

Design principles
-----------------
* **Purely additive** — does not remove any existing storage calls; acts
  as a guard/filter at the boundary.
* **No false negatives** — knowledge about trading, research topics, code,
  science, etc. always passes through.
* **Graceful summarization** — long research blobs are compressed to the
  key insight before storage, reducing disk usage and improving readability.
* **Summarization on retrieval** — a ``summarize_facts()`` method transforms
  any list of raw KnowledgeDB facts into a readable bullet-point digest.

Integration points
------------------
* ``KnowledgeDB.add_fact()`` calls ``should_store()`` before storing.
* ``KnowledgeDB.get_knowledge_summary()`` calls ``summarize_facts()`` to
  return a human-readable digest.
* ``KnowledgeDB.store_research()`` (new additive method) is the recommended
  entry-point for research/learning content; it always summarizes before storing.
"""

from __future__ import annotations

import re
import logging
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("KnowledgeFilter")

# ─────────────────────────────────────────────────────────────────────────────
# Patterns that indicate SYSTEM / INTERNAL noise — never worth persisting
# ─────────────────────────────────────────────────────────────────────────────

# Key prefix patterns for entries that are internal metadata, not knowledge
_NOISE_KEY_PREFIXES: Tuple[str, ...] = (
    # ALE step metadata (cycle counters, loop state)
    "ale_step",
    "ale_cycle",
    "ale_loop",
    "ale_arc:",
    "ale_phase:",
    "ale_cmd:",
    # Routing / command dispatch records
    "route:",
    "routing:",
    "cmd:",
    "command:",
    "dispatch:",
    # Internal system notifications / events
    "notif:",
    "notification:",
    "system_event:",
    "internal:",
    "heartbeat:",
    # Performance / metrics records (not knowledge)
    "metric:",
    "counter:",
    "loop_tick:",
    "latency:",
    # Startup / shutdown records
    "startup:",
    "shutdown:",
    "boot:",
    # Trading system internal state (cycle bookkeeping, not insights)
    "trading_cycle_raw:",
    "trading_loop:",
    "brain_raw:",
    # LEAN internal job tracking (not results, just tracking)
    "lean_job:",
    "lean_thread:",
)

# Tag patterns that mark entries as system noise
_NOISE_TAGS: Tuple[str, ...] = (
    "system_noise",
    "internal_only",
    "routing",
    "loop_tick",
    "command_dispatch",
    "heartbeat",
    "startup",
    "shutdown",
)

# Value patterns in stored text that indicate pure system chatter
_NOISE_VALUE_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(r"^\s*\[ALE\] (step|cycle|arc|phase|loop)\s+\d+", re.I),
    re.compile(r"^\s*\[Router\]", re.I),
    re.compile(r"^\s*(routed|dispatched|command handled):", re.I),
    re.compile(r"^\s*heartbeat\s+tick", re.I),
    re.compile(r"^\s*loop iteration\s+\d+", re.I),
)

# ─────────────────────────────────────────────────────────────────────────────
# Tags that ALWAYS indicate genuine knowledge worth keeping
# ─────────────────────────────────────────────────────────────────────────────

_KNOWLEDGE_TAGS: Tuple[str, ...] = (
    "research",
    "learning",
    "ale_learned",
    "ale_reflection",
    "ale_research",
    "trading_study",
    "market_data",
    "lean",
    "backtest",
    "quantconnect",
    "software_study",
    "code",
    "compiled",
    "knowledge",
    "fact",
    "topic",
    "science",
    "finance",
    "trading",
    "memory",
    "study",
)

# Maximum characters to store per fact value (prevents huge blobs)
_MAX_FACT_VALUE_LEN = 600
# Maximum characters to store per research summary
_MAX_SUMMARY_LEN = 400
# How many sentences to keep in a plain-text summary
_MAX_SENTENCES = 4


# ─────────────────────────────────────────────────────────────────────────────
# KnowledgeFilter
# ─────────────────────────────────────────────────────────────────────────────

class KnowledgeFilter:
    """Filter and summarizer for Niblit's KnowledgeDB entries.

    Usage::

        kf = KnowledgeFilter()

        # Gate before storing
        if kf.should_store(key, value_str, tags):
            db.add_fact(key, kf.compress(value_str), tags)

        # Summarize on retrieval
        readable = kf.summarize_facts(raw_facts)
    """

    def __init__(self, llm: Optional[Any] = None) -> None:
        """Parameters
        ----------
        llm: Optional LLM adapter. When provided, ``summarize_text()`` uses it
             for richer narrative compression. Gracefully absent.
        """
        self._llm = llm

    # ─────────────────────────────────────────────────────────────── gate ────

    def should_store(
        self,
        key: str,
        value: Any,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """Return True if this entry is genuine knowledge worth persisting.

        Always returns True for entries explicitly tagged as knowledge.
        Returns False for entries matching noise patterns.
        Returns True by default (permissive) so no legitimate content is lost.
        """
        tags = tags or []
        key_lower = key.lower()

        # Fast pass: explicitly tagged as knowledge → always store
        if any(t in _KNOWLEDGE_TAGS for t in tags):
            return True

        # Fast fail: explicitly tagged as noise → skip
        if any(t in _NOISE_TAGS for t in tags):
            log.debug("[KnowledgeFilter] SKIP noise-tagged key: %s", key[:80])
            return False

        # Key prefix noise check
        for prefix in _NOISE_KEY_PREFIXES:
            if key_lower.startswith(prefix):
                log.debug("[KnowledgeFilter] SKIP noise-prefix key: %s", key[:80])
                return False

        # Value pattern noise check
        value_str = str(value)[:300]
        for pat in _NOISE_VALUE_PATTERNS:
            if pat.search(value_str):
                log.debug("[KnowledgeFilter] SKIP noise-value key: %s", key[:80])
                return False

        # Default: permit storage (never silently drop unknown content)
        return True

    # ──────────────────────────────────────────────────────── compression ────

    def compress(self, text: Any, max_len: int = _MAX_FACT_VALUE_LEN) -> str:
        """Compress a raw value to *max_len* characters for compact storage.

        For dict/list values, JSON-encodes then truncates.
        For strings, keeps the first *max_len* characters with a suffix marker.
        """
        if isinstance(text, (dict, list)):
            import json
            try:
                s = json.dumps(text, ensure_ascii=False)
            except Exception:
                s = str(text)
        else:
            s = str(text)

        if len(s) <= max_len:
            return s
        return s[:max_len - 3] + "..."

    def summarize_text(
        self,
        text: str,
        max_sentences: int = _MAX_SENTENCES,
        max_len: int = _MAX_SUMMARY_LEN,
    ) -> str:
        """Produce a short readable summary of *text*.

        Priority:
        1. If LLM is available, ask it for a 1-sentence summary.
        2. Otherwise, extract the first *max_sentences* sentences.
        """
        text = text.strip()
        if not text:
            return ""

        # Try LLM summarization
        if self._llm is not None:
            try:
                prompt = (
                    f"Summarize this in 1-2 clear, readable sentences "
                    f"(max {max_len} characters):\n\n{text[:1000]}"
                )
                if hasattr(self._llm, "generate_code"):
                    result = self._llm.generate_code(prompt)
                elif hasattr(self._llm, "chat"):
                    result = self._llm.chat(prompt)
                else:
                    result = None
                if result and isinstance(result, str) and len(result) > 10:
                    return result[:max_len]
            except Exception as exc:
                log.debug("[KnowledgeFilter] LLM summarize error: %s", exc)

        # Fallback: sentence extraction
        sentences = _split_sentences(text)
        kept = sentences[:max_sentences]
        summary = " ".join(kept)
        if len(summary) > max_len:
            summary = summary[:max_len - 3] + "..."
        return summary

    # ─────────────────────────────────────────────────────── bulk retrieval ──

    def summarize_facts(
        self,
        facts: List[Any],
        max_items: int = 50,
        title: str = "Knowledge Summary",
    ) -> str:
        """Convert a list of raw KnowledgeDB fact entries to a readable digest.

        Each fact is presented as a concise bullet point.  System-noise entries
        are filtered out before rendering.

        Returns a multi-line string suitable for display in the CLI or web UI.
        """
        if not facts:
            return f"{title}: (empty)"

        lines = [f"=== {title} ==="]
        count = 0

        for fact in facts:
            if count >= max_items:
                remaining = len(facts) - count
                if remaining > 0:
                    lines.append(f"  … and {remaining} more entries")
                break

            # Normalise to (key, value, tags)
            key, value, tags = _unpack_fact(fact)

            # Filter noise
            if not self.should_store(key, value, tags):
                continue

            # Format the bullet
            bullet = _format_bullet(key, value)
            if bullet:
                lines.append(f"  • {bullet}")
                count += 1

        if count == 0:
            lines.append("  (no knowledge entries found)")

        return "\n".join(lines)

    def summarize_for_storage(
        self,
        key: str,
        value: Any,
        tags: Optional[List[str]] = None,
    ) -> str:
        """Return a compressed, readable string suitable for KB storage.

        Combines compression + optional LLM summarization for research text.
        """
        tags = tags or []
        raw = str(value) if not isinstance(value, str) else value

        # For long research/reflection content, try to summarize
        if len(raw) > _MAX_SUMMARY_LEN and any(
            t in ("research", "ale_research", "ale_reflection",
                  "ale_learned", "trading_study") for t in tags
        ):
            return self.summarize_text(raw, max_len=_MAX_SUMMARY_LEN)

        return self.compress(raw)


# ─────────────────────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────────────────────

def _split_sentences(text: str) -> List[str]:
    """Split text into sentences using a simple regex."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p.strip() for p in parts if p.strip()]


def _unpack_fact(fact: Any) -> Tuple[str, Any, List[str]]:
    """Extract (key, value, tags) from a fact dict or raw string."""
    if isinstance(fact, dict):
        key = str(fact.get("key", ""))
        value = fact.get("value", fact.get("text", fact.get("content", "")))
        tags = fact.get("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        return key, value, list(tags)
    if isinstance(fact, (list, tuple)) and len(fact) >= 2:
        return str(fact[0]), fact[1], []
    return "", str(fact), []


def _format_bullet(key: str, value: Any) -> str:
    """Format a key/value pair as a single readable bullet line."""
    if not key and not value:
        return ""

    # Clean up the key for display
    display_key = key.replace("_", " ").replace(":", " › ").strip()
    # Strip noisy timestamp suffixes like ":1775305015"
    display_key = re.sub(r"\s*›\s*\d{10,13}$", "", display_key)
    # Truncate very long keys
    if len(display_key) > 60:
        display_key = display_key[:57] + "..."

    # Format value
    if isinstance(value, dict):
        # Pick the most informative field
        for field in ("summary", "reflection", "research", "text", "content", "value"):
            if field in value:
                val_str = str(value[field])
                break
        else:
            import json
            try:
                val_str = json.dumps(value, ensure_ascii=False)
            except Exception:
                val_str = str(value)
    else:
        val_str = str(value)

    val_str = val_str.strip()
    # Remove raw ALE metadata prefixes
    val_str = re.sub(r"^\s*\{.*?'step':\s*'[^']*'\s*,\s*", "", val_str)
    if len(val_str) > 150:
        val_str = val_str[:147] + "..."

    if display_key and val_str:
        return f"[{display_key}] {val_str}"
    return val_str or display_key


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_knowledge_filter: Optional[KnowledgeFilter] = None


def get_knowledge_filter(llm: Optional[Any] = None) -> KnowledgeFilter:
    """Return the global :class:`KnowledgeFilter` singleton."""
    global _knowledge_filter
    if _knowledge_filter is None:
        _knowledge_filter = KnowledgeFilter(llm=llm)
    elif llm is not None and _knowledge_filter._llm is None:
        _knowledge_filter._llm = llm
    return _knowledge_filter
