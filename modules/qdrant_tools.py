#!/usr/bin/env python3
"""
modules/qdrant_tools.py — Batch-populate Qdrant from KnowledgeDB / FusedMemory / LocalDB-compatible DB.

Provides :func:`batch_populate_qdrant`, which reads all facts / records from a
DB-compatible object (KnowledgeDB, LocalDB, or any object that implements
``list_facts()``) and upserts them into a :class:`~modules.vector_store.VectorStore`
(Qdrant backend when configured, otherwise in-memory / FAISS fallback).

Usage::

    from modules.qdrant_tools import batch_populate_qdrant
    from modules.vector_store import VectorStore

    vs = VectorStore()
    batch_populate_qdrant(db, vector_store=vs)

If ``vector_store`` is omitted a fresh :class:`~modules.vector_store.VectorStore`
is created with the default environment settings.
"""

import hashlib
import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("QdrantTools")

# ── optional VectorStore import ────────────────────────────────────────────────
try:
    from modules.vector_store import VectorStore as _VectorStore
except ImportError:
    _VectorStore = None  # type: ignore[assignment,misc]

# Maximum characters written as the searchable text payload for a vector point.
_FACT_TEXT_MAX_CHARS = int(__import__("os").getenv("QDRANT_TEXT_MAX_CHARS", "6000"))


# ──────────────────────────────────────────────────────────────────────────────
# TopicSummariser
# ──────────────────────────────────────────────────────────────────────────────

class TopicSummariser:
    """Generate a short, human-readable topic description from raw text.

    This is a **zero-dependency** heuristic summariser — it does not call any
    LLM or ML model.  Its purpose is to produce a concise (≤ 80 character)
    label that describes the *subject* of a text fragment so that it can be
    stored as the ``topic`` field of a Qdrant point payload alongside the full
    text.

    The topic description is:
    * derived from the first coherent clause/sentence of the text
    * capped at ``MAX_TOPIC_LEN`` characters with word-boundary trimming
    * never a database or topic ID — always human-readable prose

    Usage::

        ts = TopicSummariser()
        topic = ts.summarise("Bitcoin is a decentralised digital currency...")
        # → "Bitcoin is a decentralised digital currency"

        # Pass an optional explicit hint (e.g. a KB key / title)
        topic = ts.summarise(long_text, hint="cryptocurrency overview")
    """

    MAX_TOPIC_LEN: int = 80

    @staticmethod
    def summarise(text: str, hint: str = "") -> str:
        """Return a short topic description for *text*.

        Parameters
        ----------
        text:
            Raw document text.  May be long; only the first sentence is used.
        hint:
            Optional short label (e.g. a KB key or metadata title).  When
            provided and short enough, it is returned as-is, making it the
            preferred topic description.

        Returns
        -------
        str
            A concise topic description, never longer than ``MAX_TOPIC_LEN``
            characters and never an opaque ID.
        """
        import re

        max_len = TopicSummariser.MAX_TOPIC_LEN

        # 1. Use hint if it looks like real text (not a slug/ID)
        if hint and hint.strip():
            clean_hint = hint.strip()
            # Accept hints that look like human text (contain a space or are short)
            if len(clean_hint) <= max_len and (" " in clean_hint or len(clean_hint) <= 30):
                return clean_hint

        if not text or not text.strip():
            return "(no topic)"

        # 2. Strip common prefixes added by the enricher (e.g. "[source | title]")
        raw = text.strip()
        if raw.startswith("[") and "]" in raw:
            end = raw.index("]")
            raw = raw[end + 1:].strip().lstrip("|").strip()

        # 3. Take the first sentence-like fragment
        first = re.split(r"[.!?\n\|]", raw, maxsplit=1)[0].strip()

        if not first:
            first = raw

        # 4. Trim to MAX_TOPIC_LEN at word boundary
        if len(first) <= max_len:
            return first

        truncated = first[:max_len]
        last_space = truncated.rfind(" ")
        if last_space > max_len // 2:
            return truncated[:last_space].strip()
        return truncated.strip()


def _get_facts(db: Any, limit: int = 2000) -> List[Dict[str, Any]]:
    """Return a list of fact-dicts from *db*, supporting multiple DB APIs.

    Tries the following methods in order:
    1. ``db.list_facts(limit)``
    2. ``db.list_records(limit)``
    3. ``db.get_acquired_data()``
    """
    if hasattr(db, "list_facts"):
        try:
            return db.list_facts(limit) or []
        except Exception as exc:
            log.debug("list_facts() raised: %s", exc)

    if hasattr(db, "list_records"):
        try:
            return db.list_records(limit) or []
        except Exception as exc:
            log.debug("list_records() raised: %s", exc)

    if hasattr(db, "get_acquired_data"):
        try:
            data = db.get_acquired_data() or {}
            # get_acquired_data returns a dict of category→list; flatten it.
            facts: List[Dict[str, Any]] = []
            for category, items in data.items():
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict):
                            facts.append(item)
                        else:
                            facts.append({"key": str(category), "value": str(item)})
            return facts[:limit]
        except Exception as exc:
            log.debug("get_acquired_data() raised: %s", exc)

    log.warning("DB object has no compatible fact-retrieval method: %s", type(db))
    return []


def _fact_to_text(fact: Dict[str, Any]) -> str:
    """Convert a fact-dict to a searchable string for embedding.

    Stores up to ``_FACT_TEXT_MAX_CHARS`` characters so the full content is
    preserved in the payload rather than being silently truncated to 500 chars.
    """
    key = fact.get("key") or fact.get("topic") or fact.get("id") or ""
    value = fact.get("value") or fact.get("content") or fact.get("text") or ""
    tags = fact.get("tags") or []
    tag_str = " ".join(tags) if isinstance(tags, list) else str(tags)
    parts = [str(p) for p in (key, value, tag_str) if p]
    return " | ".join(parts)[:_FACT_TEXT_MAX_CHARS]


def _fact_to_id(fact: Dict[str, Any], index: int) -> str:
    """Derive a stable, hash-based unique ID for a fact.

    The ID is *never* stored in the Qdrant payload — it is only used to
    compute the integer point ID via an MD5/SHA hash inside VectorStore.
    Using a content-hash guarantees determinism across restarts without
    embedding topic names in the ID string.
    """
    # Build a stable seed from the primary key and the text value so that
    # two facts with the same key but different values get distinct hashes.
    key_part = str(fact.get("key") or fact.get("id") or fact.get("topic") or index)
    val_part = str(fact.get("value") or fact.get("content") or fact.get("text") or "")
    seed = f"{key_part}::{val_part[:200]}"
    return f"fact_{hashlib.sha1(seed.encode('utf-8', errors='replace')).hexdigest()[:16]}"


def batch_populate_qdrant(
    db: Any,
    vector_store: Optional[Any] = None,
    limit: int = 2000,
    batch_size: int = 100,
) -> int:
    """Populate a :class:`~modules.vector_store.VectorStore` from *db*.

    Parameters
    ----------
    db:
        Any object that implements ``list_facts()``, ``list_records()``, or
        ``get_acquired_data()``.  Compatible with KnowledgeDB, LocalDB, and
        FusedMemory.
    vector_store:
        A :class:`~modules.vector_store.VectorStore` instance.  When ``None``
        a new instance is created with default settings (reads ``QDRANT_URL``
        and ``QDRANT_API_KEY`` from environment).
    limit:
        Maximum number of facts to read from *db*.
    batch_size:
        Number of facts to upsert per logging checkpoint (for progress
        visibility in long runs).

    Returns
    -------
    int
        Number of facts successfully added to the vector store.
    """
    if vector_store is None:
        if _VectorStore is None:
            log.error("VectorStore not available — cannot batch-populate Qdrant")
            return 0
        try:
            vector_store = _VectorStore()
        except Exception as exc:
            log.error("Failed to create VectorStore: %s", exc)
            return 0

    facts = _get_facts(db, limit=limit)
    if not facts:
        log.info("[QdrantTools] No facts found in DB — nothing to populate")
        return 0

    log.info("[QdrantTools] Batch-populating %d facts into vector store (backend: %s)",
             len(facts), getattr(vector_store, "backend", "unknown"))

    added = 0
    _summariser = TopicSummariser()
    for i, fact in enumerate(facts):
        try:
            text = _fact_to_text(fact)
            if not text.strip():
                continue
            doc_id = _fact_to_id(fact, i)
            # Build the short topic description from the fact's key/topic hint
            # and the full text.  This is stored as a human-readable ``topic``
            # field — never as a topic ID.
            hint = str(
                fact.get("key") or fact.get("topic") or fact.get("id") or ""
            )
            topic = _summariser.summarise(text, hint=hint)
            ok = vector_store.add(doc_id, text, topic=topic)
            if ok is not False:
                added += 1
            if added % batch_size == 0 and added > 0:
                log.info("[QdrantTools] … %d / %d facts added", added, len(facts))
        except Exception as exc:
            log.debug("[QdrantTools] Failed to add fact %d: %s", i, exc)

    log.info("[QdrantTools] Batch population complete: %d / %d facts added to vector store",
             added, len(facts))
    return added


if __name__ == "__main__":
    print('Running qdrant_tools.py')
