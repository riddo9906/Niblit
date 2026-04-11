#!/usr/bin/env python3
"""
modules/graph_rag_bridge.py — KnowledgeDB ↔ GraphRAGPipeline synchronisation bridge.

This module solves the "cold-start" problem: after each restart Niblit's
GraphRAGPipeline QuadStores are empty, but KnowledgeDB (SQLite) already holds
thousands of facts learned by the Autonomous Learning Engine (ALE), SelfTeacher,
and other information-gathering modules.

The bridge provides three synchronisation channels:

1. **Boot load** (``ingest_from_kb``)
   Called once during ``NiblitCore._init_optional_services()``.  Scans the
   KnowledgeDB and converts every structured fact into SPOC quads that are
   inserted into Tier 1 / Tier 2 of the GraphRAGPipeline.

2. **Real-time hook** (``ingest_single_fact``)
   Wired as an *after-store* callback via ``GraphRAGPipeline.set_kb_hook()``.
   Every time any module writes to KnowledgeDB the fact is immediately
   reflected in the in-memory graph without waiting for the next scan.

3. **Background watch** (``start_watch``)
   A daemon thread that periodically re-runs ``ingest_from_kb()`` so that any
   facts written while the hook was unavailable (e.g. before the bridge was
   created) are eventually absorbed.

Fact → SPOC conversion
-----------------------
KB facts are stored in three broad shapes:

* **ALE research facts** — ``value`` is a dict with ``topic``, ``content``,
  ``tier``, ``source`` keys.  Converted to::

      (topic, source_or_step, content[:150], tier_or_tag)

* **Plain string values** — the key's first colon-segment becomes the subject
  and the value becomes the object::

      (key_prefix, "contains", value[:150], "knowledge")

* **Other dict values** — entity-key pairs inside the dict become separate
  quads with predicate ``"has"``::

      (key_prefix, "has", str(v)[:150], "knowledge")

Documents that are too long to fit in a quad (> 400 chars) are also pushed to
Tier 3 (VectorStore) via ``add_document()`` so semantic search covers them.

Usage::

    from modules.graph_rag_bridge import get_graph_rag_bridge

    bridge = get_graph_rag_bridge(knowledge_db=my_db)
    bridge.start_watch()          # start background sync
    bridge.ingest_from_kb()       # one-time boot load (non-blocking thread)
    bridge.ingest_single_fact(    # real-time feed
        key="ale_research:ai:123",
        value={"topic": "AI", "content": "AI is...", "tier": "Foundation"},
        tags=["ale_step1", "research"],
    )

Singleton via ``get_graph_rag_bridge()``.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("Niblit.GraphRAGBridge")

# How many KB facts to load per sync run.
_DEFAULT_LIMIT = 500

# Background watch interval (seconds).
_DEFAULT_WATCH_INTERVAL = 120


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------

def _clean(text: Any, max_chars: int = 200) -> str:
    """Return a trimmed string, stripping leading/trailing whitespace."""
    return str(text).strip()[:max_chars]


def _kb_fact_to_quads(
    key: str,
    value: Any,
    tags: Optional[List[str]] = None,
) -> List[tuple]:
    """Convert a single KnowledgeDB fact into one or more SPOC quads.

    Parameters
    ----------
    key :
        The KnowledgeDB fact key (e.g. ``"ale_research:python:1712345"``).
    value :
        The stored value — may be a str, dict, or other JSON-serialisable type.
    tags :
        Optional list of tags attached to the fact.

    Returns
    -------
    list of (subject, predicate, object, context) tuples.
    """
    tags = tags or []
    quads: List[tuple] = []

    # ── 1. Structured dict facts (ALE research, tiered knowledge, etc.) ──
    if isinstance(value, dict):
        topic   = value.get("topic", "").strip()
        content = (
            value.get("content") or value.get("summary") or
            value.get("full_text") or value.get("description") or ""
        ).strip()
        tier    = value.get("tier", "")
        source  = value.get("source", "")
        step    = value.get("step", "")
        ctx     = tier or (tags[0] if tags else "knowledge")

        if topic and content:
            predicate = step or source or "contains"
            quads.append((topic, _clean(predicate, 50), _clean(content, 200), _clean(ctx, 60)))

        # Extra structured fields become additional quads (e.g. "results_count")
        for field, fval in value.items():
            if field in ("topic", "content", "summary", "full_text", "description",
                         "tier", "source", "step", "ts"):
                continue
            if fval is not None and str(fval).strip():
                subj = topic or key.split(":")[0]
                quads.append((
                    _clean(subj, 80),
                    _clean(field, 50),
                    _clean(str(fval), 150),
                    _clean(ctx, 60),
                ))
        return quads

    # ── 2. Plain string values ────────────────────────────────────────────
    if isinstance(value, str) and value.strip():
        subj = key.split(":")[0]
        ctx  = tags[0] if tags else "knowledge"
        quads.append((_clean(subj, 80), "contains", _clean(value, 200), _clean(ctx, 60)))
        return quads

    return quads


def _is_stat_fact(key: str, tags: Optional[List[str]]) -> bool:
    """Return True when a fact is better classified as a background stat (Tier 2)."""
    tags = tags or []
    stat_tags = {"statistics", "data", "numeric", "trading", "market", "metric",
                 "performance", "score", "count", "step18", "ale_step18"}
    return bool(stat_tags & set(tags)) or "stat" in key.lower()


# ---------------------------------------------------------------------------
# GraphRAGBridge
# ---------------------------------------------------------------------------

class GraphRAGBridge:
    """Keeps KnowledgeDB and GraphRAGPipeline in sync.

    Parameters
    ----------
    knowledge_db :
        A ``KnowledgeDB`` (or compatible) instance exposing ``list_facts(limit)``.
    graph_rag_pipeline :
        A ``GraphRAGPipeline`` instance.  When ``None`` the singleton is resolved
        lazily on first use.
    watch_interval :
        Seconds between background sync runs.  Set to 0 to disable.
    """

    def __init__(
        self,
        knowledge_db: Any = None,
        graph_rag_pipeline: Any = None,
        watch_interval: float = _DEFAULT_WATCH_INTERVAL,
    ) -> None:
        self.knowledge_db = knowledge_db
        self._grp = graph_rag_pipeline
        self.watch_interval = watch_interval

        self._lock = threading.Lock()
        self._ingested_keys: set = set()   # tracks already-converted KB keys
        self._watch_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Singleton accessors
    # ------------------------------------------------------------------

    def _get_pipeline(self) -> Any:
        if self._grp is not None:
            return self._grp
        try:
            from modules.graph_rag import get_graph_rag_pipeline
            self._grp = get_graph_rag_pipeline()
        except Exception as exc:
            log.debug("[GraphRAGBridge] Pipeline unavailable: %s", exc)
        return self._grp

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest_from_kb(
        self,
        limit: int = _DEFAULT_LIMIT,
        background: bool = False,
    ) -> int:
        """Load (or reload) facts from KnowledgeDB into the GraphRAGPipeline.

        Parameters
        ----------
        limit :
            Maximum number of KB facts to process per call.
        background :
            When ``True``, the work runs in a daemon thread and this method
            returns immediately.

        Returns
        -------
        int
            Number of new quads inserted (0 when background=True).
        """
        if background:
            t = threading.Thread(
                target=self._ingest_worker,
                kwargs={"limit": limit},
                daemon=True,
                name="GraphRAGBridge-Boot",
            )
            t.start()
            return 0
        return self._ingest_worker(limit=limit)

    def ingest_single_fact(
        self,
        key: str,
        value: Any,
        tags: Optional[List[str]] = None,
    ) -> int:
        """Immediately reflect one new KB fact in the GraphRAGPipeline.

        This is called by the hook registered on the KnowledgeDB so that every
        ``add_fact()`` call is automatically forwarded here.

        Returns the number of quads inserted (0 if already seen).
        """
        with self._lock:
            if key in self._ingested_keys:
                return 0

        pipeline = self._get_pipeline()
        if pipeline is None:
            return 0

        quads = _kb_fact_to_quads(key, value, tags)
        is_stat = _is_stat_fact(key, tags)
        inserted = 0
        for quad in quads:
            try:
                s, p, o, c = quad
                if not s or not o:
                    continue
                if is_stat:
                    pipeline.add_stat(s, p, o, c)
                else:
                    pipeline.add_fact(s, p, o, c)
                inserted += 1
            except Exception as exc:
                log.debug("[GraphRAGBridge] quad insert failed: %s", exc)

        # Push long text into Tier 3 (VectorStore) as a document
        if isinstance(value, dict):
            text = (
                value.get("full_text") or value.get("content") or
                value.get("summary") or ""
            ).strip()
            if len(text) > 200:
                try:
                    pipeline.add_document(key, text[:1000])
                except Exception as exc:
                    log.debug("[GraphRAGBridge] doc add failed: %s", exc)

        if inserted > 0:
            with self._lock:
                self._ingested_keys.add(key)
            log.debug(
                "[GraphRAGBridge] Ingested key=%r → %d quads (stat=%s)",
                key[:60], inserted, is_stat,
            )
        return inserted

    def start_watch(self) -> None:
        """Start the background watch thread (no-op if already running or disabled)."""
        if self.watch_interval <= 0:
            return
        if self._watch_thread and self._watch_thread.is_alive():
            return
        self._stop_event.clear()
        self._watch_thread = threading.Thread(
            target=self._watch_worker,
            daemon=True,
            name="GraphRAGBridge-Watch",
        )
        self._watch_thread.start()
        log.info("[GraphRAGBridge] Background watch started (interval=%ss)", self.watch_interval)

    def stop_watch(self) -> None:
        """Signal the background watch thread to stop."""
        self._stop_event.set()

    def status(self) -> Dict[str, Any]:
        """Return a summary dict for CLI / status display."""
        pipeline = self._get_pipeline()
        ps = pipeline.status() if pipeline else {}
        return {
            "kb_available": self.knowledge_db is not None,
            "keys_ingested": len(self._ingested_keys),
            "tier1_quads":   ps.get("tier1_count", 0),
            "tier2_quads":   ps.get("tier2_count", 0),
            "tier3_available": ps.get("tier3_available", False),
            "watch_running": bool(self._watch_thread and self._watch_thread.is_alive()),
        }

    def status_summary(self) -> str:
        """One-line status string."""
        s = self.status()
        watch = "▶" if s["watch_running"] else "■"
        return (
            f"GraphRAGBridge [{watch}] | "
            f"KB keys synced: {s['keys_ingested']} | "
            f"T1: {s['tier1_quads']} | T2: {s['tier2_quads']} | "
            f"T3: {'✅' if s['tier3_available'] else '❌'}"
        )

    # ------------------------------------------------------------------
    # Internal workers
    # ------------------------------------------------------------------

    def _ingest_worker(self, limit: int = _DEFAULT_LIMIT) -> int:
        """Scan KnowledgeDB and push new facts into the pipeline."""
        db = self.knowledge_db
        if db is None:
            log.debug("[GraphRAGBridge] No KnowledgeDB — skipping ingest")
            return 0

        pipeline = self._get_pipeline()
        if pipeline is None:
            log.debug("[GraphRAGBridge] No pipeline — skipping ingest")
            return 0

        facts: List[Any] = []
        try:
            if hasattr(db, "list_facts"):
                facts = db.list_facts(limit) or []
            elif hasattr(db, "get_all"):
                raw = db.get_all() or {}
                facts = [{"key": k, "value": v, "tags": []} for k, v in raw.items()]
        except Exception as exc:
            log.debug("[GraphRAGBridge] list_facts failed: %s", exc)
            return 0

        total_inserted = 0
        for fact in facts:
            try:
                if isinstance(fact, dict):
                    key   = fact.get("key", "")
                    value = fact.get("value", "")
                    tags  = fact.get("tags") or []
                else:
                    key   = str(fact)
                    value = ""
                    tags  = []

                if not key:
                    continue

                total_inserted += self.ingest_single_fact(key, value, tags)
            except Exception as exc:
                log.debug("[GraphRAGBridge] fact processing failed: %s", exc)

        if total_inserted:
            log.info(
                "[GraphRAGBridge] Boot ingest complete: %d new quads from %d KB facts",
                total_inserted, len(facts),
            )
        return total_inserted

    def _watch_worker(self) -> None:
        """Background thread: periodically re-runs _ingest_worker."""
        # Initial delay before first sync to allow the rest of init to settle
        self._stop_event.wait(timeout=30.0)
        while not self._stop_event.is_set():
            try:
                added = self._ingest_worker()
                if added:
                    log.info("[GraphRAGBridge] Watch sync: %d new quads added", added)
            except Exception as exc:
                log.debug("[GraphRAGBridge] Watch error: %s", exc)
            self._stop_event.wait(timeout=self.watch_interval)


# ---------------------------------------------------------------------------
# KnowledgeDB hook integration
# ---------------------------------------------------------------------------

def install_kb_hook(knowledge_db: Any, bridge: "GraphRAGBridge") -> bool:
    """Monkey-patch ``knowledge_db.add_fact`` to also call ``bridge.ingest_single_fact``.

    This ensures every new fact written to KnowledgeDB is immediately reflected
    in the GraphRAGPipeline without waiting for the next background scan.

    Returns ``True`` when the hook was successfully installed.
    """
    if knowledge_db is None or bridge is None:
        return False
    if getattr(knowledge_db, "_graph_rag_bridge_hooked", False):
        return True  # already hooked

    original_add_fact = getattr(knowledge_db, "add_fact", None)
    if original_add_fact is None:
        return False

    def _hooked_add_fact(key: str, value: Any, tags: Optional[List] = None) -> None:
        original_add_fact(key, value, tags)
        try:
            bridge.ingest_single_fact(key, value, tags)
        except Exception as exc:
            log.debug("[GraphRAGBridge] hook callback failed: %s", exc)

    try:
        import types
        knowledge_db.add_fact = types.MethodType(
            lambda self, key, value, tags=None: _hooked_add_fact(key, value, tags),
            knowledge_db,
        )
        knowledge_db._graph_rag_bridge_hooked = True
        log.info("[GraphRAGBridge] KB hook installed on %s", type(knowledge_db).__name__)
        return True
    except Exception as exc:
        log.debug("[GraphRAGBridge] hook install failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[GraphRAGBridge] = None
_singleton_lock = threading.Lock()


def get_graph_rag_bridge(
    knowledge_db: Any = None,
    graph_rag_pipeline: Any = None,
    watch_interval: float = _DEFAULT_WATCH_INTERVAL,
) -> GraphRAGBridge:
    """Return (and lazily create) the process-wide GraphRAGBridge singleton.

    If *knowledge_db* is supplied on the first call it is bound immediately.
    Subsequent calls with a non-None *knowledge_db* will bind it to the existing
    instance if it was previously created without one.
    """
    global _instance
    if _instance is None:
        with _singleton_lock:
            if _instance is None:
                _instance = GraphRAGBridge(
                    knowledge_db=knowledge_db,
                    graph_rag_pipeline=graph_rag_pipeline,
                    watch_interval=watch_interval,
                )
                log.debug("[GraphRAGBridge] Singleton created")
    elif knowledge_db is not None and _instance.knowledge_db is None:
        with _singleton_lock:
            if _instance.knowledge_db is None:
                _instance.knowledge_db = knowledge_db
                log.debug("[GraphRAGBridge] KB bound to existing singleton")
    return _instance


if __name__ == "__main__":
    print("Running graph_rag_bridge.py")
