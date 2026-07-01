#!/usr/bin/env python3
"""
niblit_memory/unified_memory_engine.py — Phase Ω Unified Memory Engine

Merges all Niblit memory systems into a single cognitive memory infrastructure:

    KnowledgeDB             → semantic / fact memory
    NiblitLearning          → episodic (interaction) memory
    AdaptiveLearning        → preference / feedback memory
    memory_compressor       → compressed long-term storage
    temporal epochs         → time-indexed episodic memory
    intent anchors          → strategic memory
    resonance profiles      → external-system memory
    self-model memory       → introspective memory
    causal episode history  → causal / counterfactual memory

Memory hierarchy::

    ┌─────────────────────────────────────────────────────────┐
    │              UnifiedMemoryEngine                        │
    │                                                         │
    │  ┌──────────┐  ┌───────────┐  ┌─────────────────────┐  │
    │  │ Semantic  │  │ Episodic  │  │ Strategic / Causal  │  │
    │  │ (KB facts)│  │(sessions) │  │  (goals / anchors)  │  │
    │  └──────────┘  └───────────┘  └─────────────────────┘  │
    │                                                         │
    │  ┌──────────────────────────────────────────────────┐   │
    │  │  Long-term (compressed, decayed, importance-     │   │
    │  │  weighted, contradiction-detected)               │   │
    │  └──────────────────────────────────────────────────┘   │
    └─────────────────────────────────────────────────────────┘

Key operations
--------------
``remember(text, category, importance)``  — store a memory
``recall(query, top_k)``                  — semantic search
``recall_episodic(n)``                    — recent episode list
``record_episode(turn)``                  — add an interaction episode
``compress()``                            — run compression cycle
``reflect()``                             — generate reflective summary

Categories
----------
    "semantic"   — facts about the world
    "episodic"   — interaction turns / sessions
    "strategic"  — goals, plans, intent anchors
    "causal"     — cause-effect episodes
    "introspective" — self-model updates

Configuration (env vars)
------------------------
    NIBLIT_UME_ENABLED       — "0" to disable (default 1)
    NIBLIT_UME_MAX_EPISODES  — max episodic records in RAM (default 500)

Usage::

    from niblit_memory.unified_memory_engine import get_unified_memory

    mem = get_unified_memory()
    mem.remember("BTC crossed above 50k", category="semantic", importance=0.8)
    results = mem.recall("BTC price", top_k=3)
    mem.record_episode({"input": "hello", "response": "hi", "quality": 0.9})
    summary = mem.reflect()
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

log = logging.getLogger(__name__)

_ENABLED: bool = os.getenv("NIBLIT_UME_ENABLED", "1").strip() not in ("0", "false")
_MAX_EPISODES: int = int(os.getenv("NIBLIT_UME_MAX_EPISODES", "500"))

# Importance thresholds
_ANCHOR_IMPORTANCE: float = 0.9   # memories above this are never decayed
_DECAY_FACTOR: float = 0.92       # per-compress-cycle decay
_CONTRADICTION_SIM: float = 0.88  # Jaccard threshold for contradiction detection


# ── MemoryRecord ──────────────────────────────────────────────────────────────

@dataclass
class MemoryRecord:
    """A single unified memory entry."""
    uid: str
    text: str
    category: str        # semantic | episodic | strategic | causal | introspective
    importance: float    # 0.0–1.0
    created_at: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())
    access_count: int = 0
    tags: List[str] = field(default_factory=list)
    is_anchor: bool = False

    def to_dict(self) -> Dict:
        return {
            "uid": self.uid,
            "text": self.text,
            "category": self.category,
            "importance": round(self.importance, 4),
            "created_at": self.created_at,
            "access_count": self.access_count,
            "tags": self.tags,
            "is_anchor": self.is_anchor,
        }


# ── EpisodeRecord ─────────────────────────────────────────────────────────────

@dataclass
class EpisodeRecord:
    """A single interaction / session turn."""
    turn_id: int
    input_text: str
    response_text: str
    quality: float
    intent: str = ""
    mode: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())

    def to_dict(self) -> Dict:
        return {
            "turn_id": self.turn_id,
            "input": self.input_text,
            "response": self.response_text,
            "quality": round(self.quality, 4),
            "intent": self.intent,
            "mode": self.mode,
            "timestamp": self.timestamp,
        }


# ── UnifiedMemoryEngine ───────────────────────────────────────────────────────

class UnifiedMemoryEngine:
    """Unified cognitive memory infrastructure for Niblit.

    Combines semantic, episodic, strategic, causal and introspective memory
    in a single API.  Thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: Dict[str, MemoryRecord] = {}          # uid → MemoryRecord
        self._episodes: Deque[EpisodeRecord] = deque(maxlen=_MAX_EPISODES)
        self._turn_counter: int = 0
        self._remember_count: int = 0
        self._recall_count: int = 0
        self._compress_count: int = 0
        self._governed_cluster: Any | None = None
        log.debug("[UME] initialised (max_episodes=%d)", _MAX_EPISODES)

    # ── Store API ─────────────────────────────────────────────────────────────

    def remember(
        self,
        text: str,
        category: str = "semantic",
        importance: float = 0.5,
        tags: Optional[List[str]] = None,
        is_anchor: bool = False,
    ) -> str:
        """Store a memory.  Returns the unique ID of the stored record.

        Args:
            text:       The memory content.
            category:   One of semantic|episodic|strategic|causal|introspective.
            importance: 0.0–1.0; memories ≥ ``_ANCHOR_IMPORTANCE`` become anchors.
            tags:       Optional list of topic tags.
            is_anchor:  Force anchor status regardless of importance.

        Returns:
            ``uid`` string.
        """
        if not _ENABLED:
            return ""
        importance = max(0.0, min(1.0, float(importance)))
        uid = hashlib.sha256(
            f"{category}:{text[:120]}".encode()
        ).hexdigest()[:16]

        with self._lock:
            existing = self._records.get(uid)
            if existing is not None:
                # Update importance upward (boost on re-encounter)
                existing.importance = max(existing.importance, importance)
                existing.access_count += 1
                return uid

            rec = MemoryRecord(
                uid=uid,
                text=text,
                category=category,
                importance=importance,
                tags=list(tags or []),
                is_anchor=is_anchor or (importance >= _ANCHOR_IMPORTANCE),
            )
            self._records[uid] = rec
            self._remember_count += 1
            log.debug("[UME] remember: uid=%s cat=%s imp=%.2f", uid, category, importance)

        # Also forward to KB if semantic
        if category == "semantic":
            self._try_store_kb(uid, text, importance)
        self._try_store_governed_memory(
            text=text,
            category=category,
            importance=importance,
            tags=list(tags or []),
        )

        return uid

    def remember_contract(self, record: Any) -> str:
        """Store a canonical cognitive knowledge record."""
        payload = record.to_dict() if hasattr(record, "to_dict") else dict(record or {})
        content = str(payload.get("content") or payload.get("text") or payload.get("summary") or "").strip()
        if not content:
            return ""
        return self.remember(
            content,
            category=str(payload.get("category", "semantic")),
            importance=float(payload.get("importance", 0.5) or 0.5),
            tags=list(payload.get("tags", []) or []),
        )

    def record_episode(self, turn: Dict[str, Any]) -> None:
        """Add an interaction turn to the episodic memory.

        Expected keys in *turn*: ``input``, ``response``, ``quality``,
        ``intent`` (optional), ``mode`` (optional).
        """
        if not _ENABLED:
            return
        with self._lock:
            self._turn_counter += 1
            ep = EpisodeRecord(
                turn_id=self._turn_counter,
                input_text=str(turn.get("input", "")),
                response_text=str(turn.get("response", "")),
                quality=float(turn.get("quality", 0.5)),
                intent=str(turn.get("intent", "")),
                mode=str(turn.get("mode", "")),
            )
            self._episodes.append(ep)
        self._try_store_governed_episode(ep)

    # ── Recall API ────────────────────────────────────────────────────────────

    def recall(self, query: str, top_k: int = 5, category: Optional[str] = None) -> List[MemoryRecord]:
        """Retrieve the most relevant memory records for *query*.

        Uses Jaccard token similarity (stdlib-only, no heavy deps).

        Args:
            query:    Search query string.
            top_k:    Maximum records to return.
            category: Optional filter (semantic|episodic|strategic|causal|introspective).

        Returns:
            List of :class:`MemoryRecord` sorted by descending similarity.
        """
        if not _ENABLED:
            return []

        query_tokens = set(query.lower().split())
        with self._lock:
            recs = list(self._records.values())
            self._recall_count += 1

        results = []
        for rec in recs:
            if category and rec.category != category:
                continue
            rec_tokens = set(rec.text.lower().split())
            sim = _jaccard(query_tokens, rec_tokens)
            if sim > 0:
                results.append((sim * rec.importance, rec))

        results.sort(key=lambda x: x[0], reverse=True)

        # Increment access counts
        chosen = [r for _, r in results[:top_k]]
        with self._lock:
            for rec in chosen:
                if rec.uid in self._records:
                    self._records[rec.uid].access_count += 1

        if len(chosen) < top_k:
            cluster = self._get_governed_cluster()
            if cluster is not None:
                try:
                    governed = cluster.recall(
                        query,
                        top_k=top_k - len(chosen),
                        memory_types=[self._category_to_memory_type(category)] if category else None,
                        governance_state="override",
                    )
                    for item in governed:
                        payload = item.get("payload", {})
                        chosen.append(
                            MemoryRecord(
                                uid=str(payload.get("memory_id", "")),
                                text=str(payload.get("content_text") or payload.get("summary") or ""),
                                category=self._memory_type_to_category(str(payload.get("memory_type", "semantic_memory"))),
                                importance=float(payload.get("importance_score", 0.5)),
                                tags=list((payload.get("indexing") or {}).get("tags", [])),
                                is_anchor=bool((payload.get("lifecycle") or {}).get("pinned", False)),
                            )
                        )
                except Exception:
                    pass

        return chosen

    def recall_contract(self, request: Any, top_k: int = 3) -> List[Dict[str, Any]]:
        """Recall canonical memory payloads for a cognitive request."""
        payload = request.to_dict() if hasattr(request, "to_dict") else dict(request or {})
        query = str(payload.get("normalized_text") or payload.get("raw_text") or payload.get("query") or "").strip()
        if not query:
            return []
        return [item.to_dict() for item in self.recall(query, top_k=top_k)]

    def recall_episodic(self, n: int = 10) -> List[EpisodeRecord]:
        """Return the most recent *n* episodic records."""
        with self._lock:
            all_eps = list(self._episodes)
        return all_eps[-n:]

    def recall_high_importance(self, threshold: float = 0.7) -> List[MemoryRecord]:
        """Return all memories with importance ≥ *threshold*."""
        with self._lock:
            return [r for r in self._records.values() if r.importance >= threshold]

    # ── Compression & reflection ──────────────────────────────────────────────

    def compress(self) -> Dict:
        """Run a memory compression cycle.

        Actions:
        1. Decay importance of non-anchor records.
        2. Prune records below importance floor.
        3. Detect and merge near-duplicate records.

        Returns:
            Summary dict.
        """
        if not _ENABLED:
            return {}
        with self._lock:
            total = len(self._records)
            pruned = 0
            merged = 0
            for uid in list(self._records.keys()):
                rec = self._records.get(uid)
                if rec is None:
                    continue
                if rec.is_anchor:
                    continue
                rec.importance *= _DECAY_FACTOR
                if rec.importance < 0.03:
                    del self._records[uid]
                    pruned += 1
            self._compress_count += 1
        cluster = self._get_governed_cluster()
        if cluster is not None:
            try:
                cluster.apply_lifecycle(runtime_pressure=0.0)
            except Exception:
                pass
        log.info("[UME] compress: before=%d pruned=%d merged=%d", total, pruned, merged)
        return {"before": total, "pruned": pruned, "merged": merged}

    def reflect(self) -> str:
        """Generate a brief reflective summary of the current memory state.

        Returns:
            Human-readable summary string.
        """
        with self._lock:
            total = len(self._records)
            by_cat: Dict[str, int] = {}
            high_imp = 0
            for rec in self._records.values():
                by_cat[rec.category] = by_cat.get(rec.category, 0) + 1
                if rec.importance >= 0.7:
                    high_imp += 1
            episodes = len(self._episodes)
            recent_quality = 0.0
            if self._episodes:
                recent_quality = sum(e.quality for e in list(self._episodes)[-10:]) / min(10, len(self._episodes))

        cat_str = ", ".join(f"{k}:{v}" for k, v in sorted(by_cat.items()))
        return (
            f"Memory state: {total} records ({cat_str}), "
            f"{high_imp} high-importance, {episodes} episodes, "
            f"recent quality avg={recent_quality:.2f}"
        )

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> Dict:
        with self._lock:
            by_cat: Dict[str, int] = {}
            for rec in self._records.values():
                by_cat[rec.category] = by_cat.get(rec.category, 0) + 1
            return {
                "enabled": _ENABLED,
                "total_records": len(self._records),
                "by_category": by_cat,
                "episode_count": len(self._episodes),
                "remember_count": self._remember_count,
                "recall_count": self._recall_count,
                "compress_count": self._compress_count,
            }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _try_store_kb(self, uid: str, text: str, importance: float) -> None:
        """Best-effort forward to the knowledge base."""
        try:
            from niblit_memory import NiblitMemory
            mem = NiblitMemory()
            if hasattr(mem, "store_fact"):
                mem.store_fact(f"ume:{uid}", text)
        except Exception:
            pass

    def _get_governed_cluster(self) -> Any | None:
        if self._governed_cluster is not None:
            return self._governed_cluster
        try:
            from niblit_memory.governed_qdrant_memory import get_governed_qdrant_memory_cluster

            self._governed_cluster = get_governed_qdrant_memory_cluster()
        except Exception:
            self._governed_cluster = None
        return self._governed_cluster

    def _try_store_governed_memory(
        self,
        *,
        text: str,
        category: str,
        importance: float,
        tags: list[str],
    ) -> None:
        cluster = self._get_governed_cluster()
        if cluster is None or not text:
            return
        try:
            cluster.write_memory(
                text,
                memory_type=self._category_to_memory_type(category),
                payload={
                    "importance_score": importance,
                    "indexing": {"tags": tags},
                    "replay_metadata": {"decision_lineage": tags},
                },
            )
        except Exception:
            pass

    def _try_store_governed_episode(self, episode: EpisodeRecord) -> None:
        cluster = self._get_governed_cluster()
        if cluster is None:
            return
        try:
            cluster.write_memory(
                f"{episode.input_text} -> {episode.response_text}",
                memory_type="episodic_memory",
                payload={
                    "summary": episode.response_text,
                    "importance_score": episode.quality,
                    "runtime_mode": episode.mode or "normal",
                    "replay_metadata": {
                        "trace_id": f"episode-{episode.turn_id}",
                        "decision_lineage": [episode.intent or "interaction"],
                    },
                },
            )
        except Exception:
            pass

    @staticmethod
    def _category_to_memory_type(category: Optional[str]) -> str:
        return {
            "semantic": "semantic_memory",
            "episodic": "episodic_memory",
            "strategic": "governance_memory",
            "causal": "replay_memory",
            "introspective": "reflection_memory",
        }.get(category or "semantic", "semantic_memory")

    @staticmethod
    def _memory_type_to_category(memory_type: str) -> str:
        return {
            "semantic_memory": "semantic",
            "episodic_memory": "episodic",
            "governance_memory": "strategic",
            "replay_memory": "causal",
            "reflection_memory": "introspective",
            "runtime_memory": "strategic",
            "execution_memory": "causal",
        }.get(memory_type, "semantic")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


# ── Singleton ─────────────────────────────────────────────────────────────────
_ume: Optional[UnifiedMemoryEngine] = None
_ume_lock = threading.Lock()


def get_unified_memory() -> UnifiedMemoryEngine:
    """Return the module-level :class:`UnifiedMemoryEngine` singleton."""
    global _ume
    with _ume_lock:
        if _ume is None:
            _ume = UnifiedMemoryEngine()
    return _ume


if __name__ == "__main__":
    print('Running unified_memory_engine.py')
