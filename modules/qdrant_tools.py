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

import logging
from typing import Any, Dict, List, Optional

log = logging.getLogger("QdrantTools")

# ── optional VectorStore import ────────────────────────────────────────────────
try:
    from modules.vector_store import VectorStore as _VectorStore
except ImportError:
    _VectorStore = None  # type: ignore[assignment,misc]


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
    """Convert a fact-dict to a searchable string for embedding."""
    key = fact.get("key") or fact.get("topic") or fact.get("id") or ""
    value = fact.get("value") or fact.get("content") or fact.get("text") or ""
    tags = fact.get("tags") or []
    tag_str = " ".join(tags) if isinstance(tags, list) else str(tags)
    parts = [str(p) for p in (key, value, tag_str) if p]
    return " | ".join(parts)[:500]  # keep embedding payload manageable


def _fact_to_id(fact: Dict[str, Any], index: int) -> str:
    """Derive a stable unique ID for a fact."""
    key = fact.get("key") or fact.get("id") or fact.get("topic")
    if key:
        # Sanitise to ASCII-safe slug
        slug = str(key).lower().replace(" ", "_")[:60]
        return f"fact_{slug}"
    return f"fact_{index}"


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
    for i, fact in enumerate(facts):
        try:
            text = _fact_to_text(fact)
            if not text.strip():
                continue
            doc_id = _fact_to_id(fact, i)
            ok = vector_store.add(doc_id, text)
            if ok is not False:
                added += 1
            if added % batch_size == 0 and added > 0:
                log.info("[QdrantTools] … %d / %d facts added", added, len(facts))
        except Exception as exc:
            log.debug("[QdrantTools] Failed to add fact %d: %s", i, exc)

    log.info("[QdrantTools] Batch population complete: %d / %d facts added to vector store",
             added, len(facts))
    return added
