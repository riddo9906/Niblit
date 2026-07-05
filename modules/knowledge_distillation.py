#!/usr/bin/env python3
"""Phase 4 — Knowledge Distillation Layer.

Separates memory from knowledge through a strict, ordered pipeline:

    Raw Runtime Events
        ↓
    Memory  (stores history — what happened, ephemeral)
        ↓
    Reflection  (evaluates correctness — must occur before promotion)
        ↓
    Knowledge  (stores validated facts, persistent)
        ↓
    Understanding  (stores relationships between facts, persistent)
        ↓
    Behaviour  (stores how future decisions should change, persistent)

These layers are *never* conflated.  Raw events never flow directly to
Knowledge or Understanding — they must pass through Memory and Reflection
first.  Confidence thresholds gate each promotion step.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

log = logging.getLogger("Niblit.KnowledgeDistillation")

_CONFIDENCE_THRESHOLD = 0.60


# ── data records ────────────────────────────────────────────────────────────


@dataclass
class MemoryRecord:
    """Raw history entry — what happened.  Ephemeral; not yet validated."""

    memory_id: str
    source: str
    event_type: str
    raw_event: dict[str, Any]
    timestamp: float
    tags: list[str] = field(default_factory=list)
    distilled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class KnowledgeRecord:
    """Validated factual record — what is true.  Persistent."""

    knowledge_id: str
    concept: str
    fact: str
    source_memory_id: str
    confidence: float
    validation_notes: str = ""
    created_at: float = field(default_factory=time.time)
    applied_to_understanding: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class UnderstandingRecord:
    """Relationship between validated facts.  Persistent."""

    understanding_id: str
    primary_concept: str
    related_concepts: list[str]
    relationship: str
    strength: float
    source_knowledge_ids: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    applied_to_behaviour: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BehaviourRecord:
    """Decision rule derived from understanding.  Persistent."""

    rule_id: str
    condition: str
    action: str
    confidence: float
    source_understanding_id: str
    created_at: float = field(default_factory=time.time)
    activated_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── distillation engine ─────────────────────────────────────────────────────


class KnowledgeDistillationLayer:
    """Manages the four-layer distillation pipeline.

    Each layer has a distinct role and promotion criteria.  Objects only
    advance to the next layer after explicit validation, preventing raw
    events from polluting validated knowledge stores.
    """

    CONFIDENCE_THRESHOLD: float = _CONFIDENCE_THRESHOLD

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._memory: list[MemoryRecord] = []
        self._knowledge: list[KnowledgeRecord] = []
        self._understanding: list[UnderstandingRecord] = []
        self._behaviour: list[BehaviourRecord] = []
        self._distillation_count = 0
        self._id_counter = 0

    # ── helpers ─────────────────────────────────────────────────────────────

    def _next_id(self, prefix: str) -> str:
        self._id_counter += 1
        return f"{prefix}-{self._id_counter:06d}"

    # ── Layer 1: Memory ──────────────────────────────────────────────────────

    def ingest_raw_event(self, event: dict[str, Any]) -> MemoryRecord:
        """Stage 1 — Store a raw runtime event as a Memory record."""
        record = MemoryRecord(
            memory_id=self._next_id("mem"),
            source=str(event.get("source", "unknown")),
            event_type=str(event.get("type", "runtime.event")),
            raw_event=event,
            timestamp=float(event.get("timestamp") or time.time()),
            tags=["raw_event", f"source:{event.get('source', 'unknown')}"],
        )
        with self._lock:
            self._memory.append(record)
            if len(self._memory) > 2000:
                self._memory[:] = self._memory[-2000:]
        return record

    # ── Layer 2→3: Memory → Knowledge ──────────────────────────────────────

    def distill_memory_to_knowledge(
        self,
        memory_id: str,
        *,
        concept: str,
        fact: str,
        confidence: float,
        validation_notes: str = "",
    ) -> KnowledgeRecord | None:
        """Stage 2→3 — Promote a validated Memory entry to Knowledge.

        Called *after* Reflection has confirmed the memory is valid.
        Returns ``None`` when confidence is below the threshold.
        """
        if confidence < self.CONFIDENCE_THRESHOLD:
            log.debug(
                "[KnowledgeDistillation] Confidence %.2f below threshold for '%s'",
                confidence,
                concept,
            )
            return None

        with self._lock:
            record = KnowledgeRecord(
                knowledge_id=self._next_id("know"),
                concept=str(concept),
                fact=str(fact)[:480],
                source_memory_id=memory_id,
                confidence=round(min(1.0, max(0.0, confidence)), 3),
                validation_notes=str(validation_notes)[:240],
                created_at=time.time(),
            )
            self._knowledge.append(record)
            for mem in self._memory:
                if mem.memory_id == memory_id:
                    mem.distilled = True
            if len(self._knowledge) > 1000:
                self._knowledge[:] = self._knowledge[-1000:]
            self._distillation_count += 1
        return record

    # ── Layer 3→4: Knowledge → Understanding ───────────────────────────────

    def build_understanding(
        self,
        primary_concept: str,
        *,
        related_concepts: list[str],
        relationship: str,
        strength: float,
        source_knowledge_ids: list[str],
    ) -> UnderstandingRecord:
        """Stage 3→4 — Build an Understanding record from validated Knowledge."""
        with self._lock:
            record = UnderstandingRecord(
                understanding_id=self._next_id("und"),
                primary_concept=str(primary_concept),
                related_concepts=list(related_concepts or []),
                relationship=str(relationship),
                strength=round(min(1.0, max(0.0, strength)), 3),
                source_knowledge_ids=list(source_knowledge_ids or []),
                created_at=time.time(),
            )
            self._understanding.append(record)
            for kid in source_knowledge_ids:
                for k in self._knowledge:
                    if k.knowledge_id == kid:
                        k.applied_to_understanding = True
            if len(self._understanding) > 500:
                self._understanding[:] = self._understanding[-500:]
        return record

    # ── Layer 4→5: Understanding → Behaviour ───────────────────────────────

    def derive_behaviour_rule(
        self,
        understanding_id: str,
        *,
        condition: str,
        action: str,
        confidence: float,
    ) -> BehaviourRecord | None:
        """Stage 4→5 — Derive a Behaviour rule from an Understanding record.

        Returns ``None`` when confidence is below the threshold.
        """
        if confidence < self.CONFIDENCE_THRESHOLD:
            return None
        with self._lock:
            record = BehaviourRecord(
                rule_id=self._next_id("beh"),
                condition=str(condition)[:360],
                action=str(action)[:360],
                confidence=round(min(1.0, max(0.0, confidence)), 3),
                source_understanding_id=understanding_id,
                created_at=time.time(),
            )
            self._behaviour.append(record)
            for u in self._understanding:
                if u.understanding_id == understanding_id:
                    u.applied_to_behaviour = True
            if len(self._behaviour) > 500:
                self._behaviour[:] = self._behaviour[-500:]
        return record

    # ── read access ─────────────────────────────────────────────────────────

    def memory_count(self) -> int:
        with self._lock:
            return len(self._memory)

    def knowledge_count(self) -> int:
        with self._lock:
            return len(self._knowledge)

    def understanding_count(self) -> int:
        with self._lock:
            return len(self._understanding)

    def behaviour_count(self) -> int:
        with self._lock:
            return len(self._behaviour)

    def recent_knowledge(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            return [k.to_dict() for k in self._knowledge[-max(1, limit) :]]

    def recent_understanding(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            return [u.to_dict() for u in self._understanding[-max(1, limit) :]]

    def recent_behaviour_rules(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            return [b.to_dict() for b in self._behaviour[-max(1, limit) :]]

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "layers": {
                    "memory": {
                        "entries": len(self._memory),
                        "persistent": False,
                        "role": "stores_history",
                        "description": "Raw runtime events — what happened",
                    },
                    "knowledge": {
                        "entries": len(self._knowledge),
                        "persistent": True,
                        "role": "stores_validated_facts",
                        "description": "Validated facts — what is true",
                    },
                    "understanding": {
                        "entries": len(self._understanding),
                        "persistent": True,
                        "role": "stores_fact_relationships",
                        "description": "Relationships between validated facts",
                    },
                    "behaviour": {
                        "entries": len(self._behaviour),
                        "persistent": True,
                        "role": "stores_decision_rules",
                        "description": "How future decisions should change",
                    },
                },
                "distillation_count": self._distillation_count,
                "confidence_threshold": self.CONFIDENCE_THRESHOLD,
            }
