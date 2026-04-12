#!/usr/bin/env python3
"""
modules/memory_weighting.py — Niblit Memory Weighting & Decay System (MWDS v2)
===============================================================================
*Not just "store and forget" — adaptive memory evolution.*

Each :class:`MemoryRecord` carries a **dynamic survival score** (``weight``)
that evolves over time based on five independent signals:

1. **Age / decay**   — older memories fade unless regularly used.
2. **Usage**         — accessed memories grow stronger (log scale).
3. **Success ratio** — memories that helped solve things survive longer.
4. **Recency boost** — recently retrieved memories are boosted.
5. **Graph factor**  — memories connected to many others are more important.

Memory lifecycle
----------------
Every record passes through four tiers as its weight changes:

  🔥 HOT   (weight > 0.6) — fast in-memory access
  🌡️ WARM  (0.2 – 0.6)   — normal DB storage
  ❄️ COLD  (0.05 – 0.2)  — compressed / archived
  ☠️ DEAD  (< 0.05)      — pruned

Compression
-----------
Instead of deleting cold memories outright, :meth:`MemoryStore.compress_cold`
groups them and creates a single ``"abstract"`` summary record that carries the
average confidence and a mid-range importance of 0.4.  This converts detailed
noise into condensed knowledge.

Graph-RAG integration
---------------------
:meth:`MemoryStore.retrieve_weighted` combines semantic similarity with MWDS
weight and centrality::

    final_score = similarity * 0.5 + weight * 0.3 + centrality * 0.2

Sync filter
-----------
:meth:`MemoryStore.sync_eligible` returns only records whose weight > 0.1,
keeping cloud sync traffic lean.

Singleton
---------
``get_memory_store()`` returns the process-wide :class:`MemoryStore` instance.

Configuration (environment variables)
--------------------------------------
``NIBLIT_MWDS_PRUNE_DEAD``   — Set to ``0`` to skip pruning dead memories
                               (default: prune enabled).
``NIBLIT_MWDS_COMPRESS``     — Set to ``0`` to skip cold compression
                               (default: compress enabled).
``NIBLIT_MWDS_MAX_RECORDS``  — Maximum total records (default 10 000).
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
_PRUNE_DEAD = os.environ.get("NIBLIT_MWDS_PRUNE_DEAD", "1") != "0"
_COMPRESS_COLD = os.environ.get("NIBLIT_MWDS_COMPRESS", "1") != "0"
_MAX_RECORDS = int(os.environ.get("NIBLIT_MWDS_MAX_RECORDS", "10000"))

# ── Source-based base weights ──────────────────────────────────────────────────
BASE_IMPORTANCE: Dict[str, float] = {
    "user":       1.00,
    "reflection": 0.90,
    "code":       0.85,
    "slsa":       0.80,
    "agent":      0.75,
    "research":   0.60,
    "kernel":     0.70,
    "unknown":    0.50,
}

# ── Source-based decay rates (per-second forgetting speed) ─────────────────────
BASE_DECAY: Dict[str, float] = {
    "user":       0.00001,
    "reflection": 0.00005,
    "code":       0.0001,
    "slsa":       0.0002,
    "agent":      0.0003,
    "research":   0.0006,
    "kernel":     0.00015,
    "unknown":    0.0005,
}

# ── Tier thresholds ────────────────────────────────────────────────────────────
TIER_HOT:  float = 0.60
TIER_WARM: float = 0.20
TIER_COLD: float = 0.05

# ── Initial half-life (seconds) by source ─────────────────────────────────────
BASE_HALF_LIFE: Dict[str, float] = {
    "user":       86_400 * 30,   # 30 days
    "reflection": 86_400 * 14,   # 14 days
    "code":       86_400 * 7,    # 7 days
    "slsa":       86_400 * 5,
    "agent":      86_400 * 3,
    "research":   86_400 * 2,
    "kernel":     86_400 * 7,
    "unknown":    86_400 * 1,
}


# ═════════════════════════════════════════════════════════════════════════════
# MemoryRecord schema
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class MemoryRecord:
    """A single unit of adaptive memory.

    Static fields set at creation time; dynamic fields updated by
    :func:`reinforce`, :func:`compute_weight`, and :func:`update_decay`.

    Attributes
    ----------
    id:            Unique identifier (e.g. content hash).
    content:       The raw text or data being remembered.
    source:        Provenance tag — one of the keys in :data:`BASE_IMPORTANCE`.
    created_at:    UNIX timestamp of insertion.
    confidence:    SECA reward signal ∈ [0, 1].  Updated by RL loop.
    importance:    Initial base weight = ``BASE_IMPORTANCE[source] * confidence``.
    access_count:  Total retrieval count.
    success_count: Retrievals that helped solve something.
    failure_count: Retrievals that didn't help.
    last_accessed: UNIX timestamp of last retrieval.
    connections:   Number of linked memories (graph degree).
    centrality:    Graph centrality = ``connections / total_nodes``.
    decay_rate:    Per-second forgetting factor (adaptive).
    half_life:     Recency boost window in seconds.
    weight:        Current dynamic survival score.
    tier:          Current lifecycle tier: "hot" / "warm" / "cold" / "dead".
    """

    # ── Identity ──────────────────────────────────────────────────────────
    id: str
    content: str
    source: str = "unknown"
    created_at: int = field(default_factory=lambda: int(time.time()))

    # ── Quality signals ───────────────────────────────────────────────────
    confidence: float = 0.5
    importance: float = 0.5

    # ── Dynamic usage signals ─────────────────────────────────────────────
    access_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    last_accessed: int = 0

    # ── Graph signals ─────────────────────────────────────────────────────
    connections: int = 0
    centrality: float = 0.0

    # ── Decay parameters ─────────────────────────────────────────────────
    decay_rate: float = field(init=False)
    half_life: float = field(init=False)

    # ── Final computed score ──────────────────────────────────────────────
    weight: float = field(init=False)
    tier: str = "warm"

    def __post_init__(self) -> None:
        src = self.source if self.source in BASE_DECAY else "unknown"
        self.decay_rate = BASE_DECAY[src]
        self.half_life = BASE_HALF_LIFE[src]
        self.weight = self.importance
        self.tier = assign_tier(self.weight)

    # ── Convenience ──────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict (useful for persistence / sync)."""
        return {
            "id":            self.id,
            "content":       self.content[:200],
            "source":        self.source,
            "created_at":    self.created_at,
            "confidence":    round(self.confidence, 4),
            "importance":    round(self.importance, 4),
            "access_count":  self.access_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "last_accessed": self.last_accessed,
            "connections":   self.connections,
            "centrality":    round(self.centrality, 4),
            "decay_rate":    round(self.decay_rate, 8),
            "half_life":     self.half_life,
            "weight":        round(self.weight, 4),
            "tier":          self.tier,
        }


# ═════════════════════════════════════════════════════════════════════════════
# Core computation functions
# ═════════════════════════════════════════════════════════════════════════════

def compute_weight(record: MemoryRecord, now: Optional[float] = None) -> float:
    """Compute the dynamic survival score for *record*.

    Formula::

        weight = importance × confidence × decay × (1 + usage)
                 × (0.5 + success_ratio) × recency_boost × graph_factor

    Components:

    * **decay**         = ``exp(-decay_rate × age)``      — time-based forgetting.
    * **usage**         = ``log(1 + access_count)``         — usage reinforcement.
    * **success_ratio** = ``success / (success + failure)`` — quality filter.
    * **recency_boost** = ``exp(-recency / half_life)``     — freshness boost.
    * **graph_factor**  = ``1 + centrality``                — graph importance.

    Args:
        record: The :class:`MemoryRecord` to score.
        now:    Current UNIX timestamp (defaults to ``time.time()``).

    Returns:
        A non-negative float; values are unbounded above 1 when graph_factor
        and usage compound, but in practice the formula yields ``[0, ~3]``.
    """
    if now is None:
        now = time.time()

    age = max(0.0, now - record.created_at)
    recency = now - record.last_accessed if record.last_accessed > 0 else age

    decay = math.exp(-record.decay_rate * age)
    usage = math.log1p(record.access_count)

    total = record.success_count + record.failure_count
    success_ratio = record.success_count / max(1, total)

    recency_boost = math.exp(-recency / max(1.0, record.half_life))
    graph_factor = 1.0 + record.centrality

    w = (
        record.importance
        * record.confidence
        * decay
        * (1.0 + usage)
        * (0.5 + success_ratio)
        * recency_boost
        * graph_factor
    )
    return max(0.0, w)


def update_decay(record: MemoryRecord) -> None:
    """Adjust *record*'s ``decay_rate`` based on its current strength.

    Stronger memories (high confidence × importance) decay slower.
    The base decay is scaled by ``(1 - strength)`` so:

    * A perfect memory (strength = 1.0) → near-zero decay.
    * A weak memory (strength ≈ 0) → full base decay.

    Args:
        record: The :class:`MemoryRecord` to update in-place.
    """
    src = record.source if record.source in BASE_DECAY else "unknown"
    strength = float(max(0.0, min(1.0, record.confidence * record.importance)))
    record.decay_rate = BASE_DECAY[src] * (1.0 - strength)
    # Prevent decay_rate from hitting exactly 0 (would freeze the memory forever)
    record.decay_rate = max(record.decay_rate, BASE_DECAY[src] * 0.001)


def reinforce(record: MemoryRecord, success: bool = True) -> None:
    """RL-style reinforcement loop — update *record* based on retrieval outcome.

    On **success**:

    * ``access_count`` incremented.
    * ``success_count`` incremented.
    * ``confidence`` nudged up by +0.02 (capped at 1.0).

    On **failure**:

    * ``access_count`` incremented.
    * ``failure_count`` incremented.
    * ``confidence`` multiplied by 0.98 (soft decay).

    In both cases:

    * ``last_accessed`` is updated to now.
    * ``decay_rate`` is recomputed via :func:`update_decay`.
    * ``weight`` is recomputed via :func:`compute_weight`.
    * ``tier`` is reassigned via :func:`assign_tier`.

    Args:
        record:  The :class:`MemoryRecord` to update in-place.
        success: Whether this retrieval was useful.
    """
    now = int(time.time())
    record.access_count += 1
    record.last_accessed = now

    if success:
        record.success_count += 1
        record.confidence = min(1.0, record.confidence + 0.02)
    else:
        record.failure_count += 1
        record.confidence = record.confidence * 0.98

    update_decay(record)
    record.weight = compute_weight(record)
    record.tier = assign_tier(record.weight)


def assign_tier(weight: float) -> str:
    """Map a computed *weight* value to a tier name.

    Args:
        weight: The ``weight`` field from :func:`compute_weight`.

    Returns:
        ``"hot"`` | ``"warm"`` | ``"cold"`` | ``"dead"``
    """
    if weight >= TIER_HOT:
        return "hot"
    if weight >= TIER_WARM:
        return "warm"
    if weight >= TIER_COLD:
        return "cold"
    return "dead"


def update_centrality(record: MemoryRecord, total_nodes: int) -> None:
    """Recompute *record*'s centrality from current connection count.

    Args:
        record:      The :class:`MemoryRecord` to update in-place.
        total_nodes: Total number of nodes in the memory graph.
    """
    record.centrality = record.connections / max(1, total_nodes)


def make_record(
    record_id: str,
    content: str,
    source: str = "unknown",
    confidence: float = 0.5,
) -> MemoryRecord:
    """Factory: create a :class:`MemoryRecord` with correct initial ``importance``.

    ``importance = BASE_IMPORTANCE[source] * confidence``

    Args:
        record_id:  Unique string identifier (typically a content hash).
        content:    The raw text or data.
        source:     Provenance tag; keys are validated against :data:`BASE_IMPORTANCE`.
        confidence: Initial confidence ∈ [0, 1].

    Returns:
        A fully initialised :class:`MemoryRecord`.
    """
    src = source if source in BASE_IMPORTANCE else "unknown"
    importance = BASE_IMPORTANCE[src] * float(max(0.0, min(1.0, confidence)))
    rec = MemoryRecord(
        id=record_id,
        content=content,
        source=src,
        confidence=float(max(0.0, min(1.0, confidence))),
        importance=importance,
    )
    update_decay(rec)
    rec.weight = compute_weight(rec)
    rec.tier = assign_tier(rec.weight)
    return rec


def compress_memories(records: List[MemoryRecord]) -> Optional[MemoryRecord]:
    """Compress a list of cold/dead records into a single abstract knowledge record.

    Instead of discarding the information entirely, the content is summarised
    (truncated concatenation) and stored with moderate importance.  The result
    has ``source="reflection"`` and represents condensed knowledge.

    Args:
        records: List of :class:`MemoryRecord` to compress.

    Returns:
        A new abstract :class:`MemoryRecord`, or ``None`` if *records* is empty.
    """
    if not records:
        return None

    # Summarise by taking the first 80 chars of each, joining with "; "
    summary_parts = [r.content[:80].strip() for r in records if r.content]
    summary = "; ".join(summary_parts)[:500]

    avg_conf = sum(r.confidence for r in records) / len(records)
    record_id = "abstract_" + str(int(time.time())) + "_" + str(len(records))

    compressed = make_record(
        record_id=record_id,
        content=f"[Abstract] {summary}",
        source="reflection",
        confidence=float(avg_conf),
    )
    compressed.importance = 0.4
    compressed.weight = compute_weight(compressed)
    compressed.tier = assign_tier(compressed.weight)
    return compressed


# ═════════════════════════════════════════════════════════════════════════════
# MemoryStore
# ═════════════════════════════════════════════════════════════════════════════

class MemoryStore:
    """Thread-safe in-memory store that manages :class:`MemoryRecord` lifecycle.

    Responsibilities
    ----------------
    * **store()** — insert or upsert a record; compute initial weight.
    * **retrieve_weighted()** — re-rank text candidates using MWDS weight + centrality.
    * **reinforce_by_id()** — update a record's RL state by ID.
    * **update_all_weights()** — recompute every record's weight in one pass.
    * **prune()** — remove dead records (weight < :data:`TIER_COLD`).
    * **compress_cold()** — compress cold-tier records into abstract knowledge.
    * **sync_eligible()** — return records with weight > 0.1 for cloud sync.
    * **run_maintenance()** — combined update + prune + compress pass.
    * **tier_breakdown()** — count records per tier.

    Args:
        max_records:  Hard cap on the total number of records (default 10 000).
        prune_dead:   Whether to delete dead records during maintenance.
        compress:     Whether to compress cold records during maintenance.
    """

    def __init__(
        self,
        max_records: int = _MAX_RECORDS,
        prune_dead: bool = _PRUNE_DEAD,
        compress: bool = _COMPRESS_COLD,
    ) -> None:
        self._records: Dict[str, MemoryRecord] = {}
        self._lock = threading.Lock()
        self._max_records = max_records
        self._prune_dead = prune_dead
        self._compress = compress
        self._maintenance_count: int = 0
        log.info("[MemoryStore] MWDS v2 initialised (max=%d)", max_records)

    # ── Store ─────────────────────────────────────────────────────────────────

    def store(
        self,
        record_id: str,
        content: str,
        source: str = "unknown",
        confidence: float = 0.5,
    ) -> MemoryRecord:
        """Insert or upsert a :class:`MemoryRecord`.

        If *record_id* already exists, its ``content`` and ``confidence`` are
        updated and the weight is recomputed.  Otherwise a new record is created
        via :func:`make_record`.

        When the store is at capacity, the lowest-weight record is evicted to
        make room.

        Args:
            record_id:  Unique identifier.
            content:    Raw text content.
            source:     Provenance tag.
            confidence: Initial quality signal ∈ [0, 1].

        Returns:
            The inserted or updated :class:`MemoryRecord`.
        """
        with self._lock:
            if record_id in self._records:
                rec = self._records[record_id]
                rec.content = content[:500]
                rec.confidence = float(max(0.0, min(1.0, confidence)))
                update_decay(rec)
                rec.weight = compute_weight(rec)
                rec.tier = assign_tier(rec.weight)
                return rec

            # Evict lowest-weight record if at capacity
            if len(self._records) >= self._max_records:
                self._evict_one_unsafe()

            rec = make_record(record_id, content, source, confidence)
            self._records[record_id] = rec
            return rec

    def _evict_one_unsafe(self) -> None:
        """Evict the single lowest-weight record.  Caller must hold *_lock*."""
        if not self._records:
            return
        worst_id = min(self._records, key=lambda k: self._records[k].weight)
        del self._records[worst_id]
        log.debug("[MemoryStore] Evicted record '%s' (at capacity)", worst_id)

    # ── Retrieve ──────────────────────────────────────────────────────────────

    def retrieve_weighted(
        self,
        candidates: List[str],
        similarity_scores: Optional[List[float]] = None,
        top_k: int = 5,
    ) -> List[str]:
        """Re-rank *candidates* using MWDS weight and centrality.

        For each candidate text, a matching :class:`MemoryRecord` is looked up
        by searching for a record whose ``content`` starts with the same 60
        characters.  If a match is found, its contribution to the final ranking
        score is::

            final_score = similarity × 0.5 + weight × 0.3 + centrality × 0.2

        Unmatched candidates receive a baseline score of ``similarity × 0.5``.

        Args:
            candidates:        Ordered list of text strings (typically from
                               short-term memory + MemoryGraph search).
            similarity_scores: Optional parallel list of similarity values ∈ [0, 1].
                               Defaults to decreasing values (1.0, 0.9, …) if
                               not provided.
            top_k:             Maximum results to return.

        Returns:
            Up to *top_k* text strings, highest final_score first.
        """
        if not candidates:
            return []

        if similarity_scores is None or len(similarity_scores) != len(candidates):
            similarity_scores = [
                max(0.0, 1.0 - i * 0.1) for i in range(len(candidates))
            ]

        with self._lock:
            records_snapshot = dict(self._records)

        scored: List[Tuple[float, str]] = []
        for text, sim in zip(candidates, similarity_scores):
            rec = self._find_by_content(text, records_snapshot)
            if rec is not None:
                score = sim * 0.5 + rec.weight * 0.3 + rec.centrality * 0.2
            else:
                score = sim * 0.5
            scored.append((score, text))

        scored.sort(key=lambda t: t[0], reverse=True)
        return [t[1] for t in scored[:top_k]]

    @staticmethod
    def _find_by_content(
        text: str, records: Dict[str, MemoryRecord]
    ) -> Optional[MemoryRecord]:
        """Look up the first record whose content prefix matches *text*."""
        prefix = text[:60].strip()
        for rec in records.values():
            if rec.content[:60].strip() == prefix:
                return rec
        return None

    # ── Reinforce ─────────────────────────────────────────────────────────────

    def reinforce_by_id(self, record_id: str, success: bool = True) -> bool:
        """Apply RL reinforcement to the record with *record_id*.

        Args:
            record_id: Identifier of the target record.
            success:   Whether the retrieval was useful.

        Returns:
            ``True`` if the record was found and updated, ``False`` otherwise.
        """
        with self._lock:
            rec = self._records.get(record_id)
            if rec is None:
                return False
            reinforce(rec, success=success)
        return True

    def reinforce_by_content(self, text: str, success: bool = True) -> int:
        """Apply RL reinforcement to records matching *text*.

        Matches by comparing the first 60 characters of ``content``.

        Returns:
            Number of records updated.
        """
        prefix = text[:60].strip()
        count = 0
        with self._lock:
            for rec in self._records.values():
                if rec.content[:60].strip() == prefix:
                    reinforce(rec, success=success)
                    count += 1
        return count

    # ── Weight refresh ────────────────────────────────────────────────────────

    def update_all_weights(self, total_nodes: Optional[int] = None) -> int:
        """Recompute ``weight`` and ``tier`` for every record.

        Also updates ``centrality`` if *total_nodes* is provided.

        Args:
            total_nodes: Total graph node count for centrality normalisation.

        Returns:
            Number of records updated.
        """
        now = time.time()
        count = 0
        with self._lock:
            n = total_nodes or len(self._records)
            for rec in self._records.values():
                if total_nodes is not None:
                    update_centrality(rec, n)
                update_decay(rec)
                rec.weight = compute_weight(rec, now=now)
                rec.tier = assign_tier(rec.weight)
                count += 1
        return count

    # ── Pruning ───────────────────────────────────────────────────────────────

    def prune(self, dead_threshold: float = TIER_COLD) -> int:
        """Remove records whose weight has fallen below *dead_threshold*.

        Args:
            dead_threshold: Weight threshold below which a record is dead.

        Returns:
            Number of records removed.
        """
        with self._lock:
            to_remove = [
                rid for rid, rec in self._records.items()
                if rec.weight < dead_threshold and rec.access_count == 0
            ]
            for rid in to_remove:
                del self._records[rid]
        if to_remove:
            log.debug("[MemoryStore] Pruned %d dead records", len(to_remove))
        return len(to_remove)

    # ── Compression ───────────────────────────────────────────────────────────

    def compress_cold(self) -> int:
        """Compress cold-tier records into abstract knowledge.

        Cold records (``weight`` ∈ [TIER_COLD, TIER_WARM)) are grouped and
        replaced by a single abstract :class:`MemoryRecord` via
        :func:`compress_memories`.

        Returns:
            Number of original records compressed (removed).
        """
        with self._lock:
            cold = [
                rec for rec in self._records.values()
                if TIER_COLD <= rec.weight < TIER_WARM
            ]

        if len(cold) < 2:
            return 0

        abstract = compress_memories(cold)
        if abstract is None:
            return 0

        with self._lock:
            for rec in cold:
                self._records.pop(rec.id, None)
            self._records[abstract.id] = abstract

        log.debug(
            "[MemoryStore] Compressed %d cold records → '%s'",
            len(cold), abstract.id,
        )
        return len(cold)

    # ── Sync ──────────────────────────────────────────────────────────────────

    def sync_eligible(self, min_weight: float = 0.1) -> List[MemoryRecord]:
        """Return records with weight above *min_weight* for cloud sync.

        Args:
            min_weight: Weight threshold (default 0.1).

        Returns:
            List of :class:`MemoryRecord` instances.
        """
        with self._lock:
            return [r for r in self._records.values() if r.weight >= min_weight]

    # ── Maintenance ───────────────────────────────────────────────────────────

    def run_maintenance(
        self,
        total_nodes: Optional[int] = None,
    ) -> Dict[str, int]:
        """Full maintenance pass: refresh weights → prune → compress.

        Steps:

        1. :meth:`update_all_weights` — recompute every record's survival score.
        2. :meth:`prune`              — delete dead records (if enabled).
        3. :meth:`compress_cold`      — compress cold-tier records (if enabled).

        Args:
            total_nodes: Optional graph size for centrality normalisation.

        Returns:
            Dict ``{"updated": N, "pruned": N, "compressed": N}``.
        """
        self._maintenance_count += 1
        updated = self.update_all_weights(total_nodes=total_nodes)
        pruned = self.prune() if self._prune_dead else 0
        compressed = self.compress_cold() if self._compress else 0
        log.info(
            "[MemoryStore] Maintenance #%d: updated=%d pruned=%d compressed=%d",
            self._maintenance_count, updated, pruned, compressed,
        )
        return {"updated": updated, "pruned": pruned, "compressed": compressed}

    # ── Analytics ─────────────────────────────────────────────────────────────

    def tier_breakdown(self) -> Dict[str, int]:
        """Count records by tier.

        Returns:
            ``{"hot": N, "warm": N, "cold": N, "dead": N, "total": N}``
        """
        counts: Dict[str, int] = {"hot": 0, "warm": 0, "cold": 0, "dead": 0}
        with self._lock:
            for rec in self._records.values():
                counts[rec.tier] = counts.get(rec.tier, 0) + 1
        counts["total"] = sum(counts.values())
        return counts

    def top_records(self, n: int = 10) -> List[MemoryRecord]:
        """Return the *n* highest-weight records.

        Args:
            n: Number of top records to return.

        Returns:
            Sorted list (highest weight first).
        """
        with self._lock:
            recs = list(self._records.values())
        recs.sort(key=lambda r: r.weight, reverse=True)
        return recs[:n]

    def get_record(self, record_id: str) -> Optional[MemoryRecord]:
        """Look up a :class:`MemoryRecord` by *record_id*.

        Returns ``None`` if not found.
        """
        with self._lock:
            return self._records.get(record_id)

    def stats(self) -> Dict[str, Any]:
        """Return a summary of store health and composition."""
        with self._lock:
            n = len(self._records)
            if n:
                avg_w = sum(r.weight for r in self._records.values()) / n
                avg_c = sum(r.confidence for r in self._records.values()) / n
            else:
                avg_w = avg_c = 0.0
        tb = self.tier_breakdown()
        return {
            "total_records": n,
            "avg_weight": round(avg_w, 4),
            "avg_confidence": round(avg_c, 4),
            "tier_breakdown": tb,
            "maintenance_runs": self._maintenance_count,
        }

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)


# ═════════════════════════════════════════════════════════════════════════════
# Singleton
# ═════════════════════════════════════════════════════════════════════════════

_store: Optional[MemoryStore] = None
_store_lock = threading.Lock()


def get_memory_store(**kwargs) -> MemoryStore:
    """Return the process-level :class:`MemoryStore` singleton.

    Thread-safe, lazily created on first call.  Any keyword arguments are
    forwarded to the constructor **only** on the first call.
    """
    global _store  # pylint: disable=global-statement
    with _store_lock:
        if _store is None:
            _store = MemoryStore(**kwargs)
        return _store


if __name__ == "__main__":
    print('Running memory_weighting.py')
