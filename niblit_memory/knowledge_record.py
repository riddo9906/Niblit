#!/usr/bin/env python3
"""
niblit_memory/knowledge_record.py — Structured Knowledge Record for Niblit.

A KnowledgeRecord is the fundamental unit of long-term memory in Niblit.
It stores *what was learned*, not what happened at runtime.

Each completed interaction, research session, or document ingestion should
produce one or more KnowledgeRecords.  Runtime events (loop ticks, object
mutations, session IDs) belong in the operational log, not here.

Usage::

    from niblit_memory.knowledge_record import KnowledgeRecord
    import uuid
    from datetime import datetime, timezone

    record = KnowledgeRecord(
        id=str(uuid.uuid4()),
        topic="Python virtual environments",
        summary="Virtual environments isolate project dependencies so packages "
                "installed for one project do not conflict with another.",
        key_facts=[
            "python -m venv <name> creates a virtual environment.",
            "Activating a venv changes PATH so the local interpreter is first.",
            "requirements.txt pins exact package versions for reproducibility.",
        ],
        concepts_learned=["virtual environment", "dependency isolation", "pip", "venv"],
        relationships=[
            {"from": "virtual environment", "to": "dependency isolation", "type": "enables"},
            {"from": "pip", "to": "virtual environment", "type": "used_within"},
        ],
        confidence=0.9,
        sources=["https://docs.python.org/3/library/venv.html"],
        date_last_verified=datetime.now(timezone.utc).isoformat(),
    )
    print(record.to_dict())
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class KnowledgeRecord:
    """A structured record of what was learned from an interaction, research
    session, or document ingestion.

    Attributes
    ----------
    id : str
        Stable unique identifier (UUID).
    topic : str
        Short human-readable topic label (e.g. "Python virtual environments").
    summary : str
        Concise factual summary in plain language.
    key_facts : list of str
        Extracted factual statements — one discrete fact per item.
    concepts_learned : list of str
        Key concept phrases found in the source material.
    relationships : list of dict
        Semantic relationships between concepts.
        Each entry is ``{"from": str, "to": str, "type": str}``.
    confidence : float
        Confidence in the recorded knowledge, 0.0–1.0.
    sources : list of str
        Original source identifiers (file paths, URLs, session IDs).
    date_last_verified : str
        ISO 8601 timestamp of when this record was last confirmed accurate.
    tags : list of str
        Optional classification tags.
    metadata : dict
        Arbitrary extra fields (page numbers, chunk IDs, section titles, etc.).
    raw_observations : list of str
        The unprocessed inputs this record was built from.
        Kept for audit/debug; not treated as primary long-term memory.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    topic: str = ""
    summary: str = ""
    key_facts: List[str] = field(default_factory=list)
    concepts_learned: List[str] = field(default_factory=list)
    relationships: List[Dict[str, str]] = field(default_factory=list)
    confidence: float = 0.7
    sources: List[str] = field(default_factory=list)
    date_last_verified: str = field(default_factory=_now_iso)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    raw_observations: List[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain-dict representation suitable for JSON serialisation."""
        return {
            "id": self.id,
            "topic": self.topic,
            "summary": self.summary,
            "key_facts": list(self.key_facts),
            "concepts_learned": list(self.concepts_learned),
            "relationships": [dict(r) for r in self.relationships],
            "confidence": self.confidence,
            "sources": list(self.sources),
            "date_last_verified": self.date_last_verified,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> KnowledgeRecord:
        """Reconstruct a KnowledgeRecord from a plain dict."""
        return cls(
            id=str(data.get("id") or uuid.uuid4()),
            topic=str(data.get("topic") or ""),
            summary=str(data.get("summary") or ""),
            key_facts=list(data.get("key_facts") or []),
            concepts_learned=list(data.get("concepts_learned") or []),
            relationships=list(data.get("relationships") or []),
            confidence=float(data.get("confidence") or 0.7),
            sources=list(data.get("sources") or []),
            date_last_verified=str(data.get("date_last_verified") or _now_iso()),
            tags=list(data.get("tags") or []),
            metadata=dict(data.get("metadata") or {}),
            raw_observations=list(data.get("raw_observations") or []),
        )

    def add_relationship(
        self,
        from_concept: str,
        to_concept: str,
        rel_type: str = "related_to",
    ) -> None:
        """Append a relationship entry (deduplicates by from/to/type)."""
        entry = {"from": from_concept, "to": to_concept, "type": rel_type}
        if entry not in self.relationships:
            self.relationships.append(entry)

    def human_readable(self) -> str:
        """Return a multi-line human-readable summary of this record."""
        lines = [
            f"Topic:    {self.topic}",
            f"Summary:  {self.summary}",
        ]
        if self.key_facts:
            lines.append("Key facts:")
            for fact in self.key_facts:
                lines.append(f"  • {fact}")
        if self.concepts_learned:
            lines.append(f"Concepts: {', '.join(self.concepts_learned)}")
        if self.relationships:
            lines.append("Relationships:")
            for rel in self.relationships:
                lines.append(f"  {rel.get('from')} --[{rel.get('type')}]--> {rel.get('to')}")
        lines.append(f"Confidence: {self.confidence:.0%}")
        if self.sources:
            lines.append(f"Sources:  {', '.join(self.sources)}")
        lines.append(f"Verified: {self.date_last_verified}")
        return "\n".join(lines)


def make_knowledge_record(
    topic: str,
    summary: str,
    *,
    key_facts: List[str] | None = None,
    concepts_learned: List[str] | None = None,
    relationships: List[Dict[str, str]] | None = None,
    confidence: float = 0.7,
    sources: List[str] | None = None,
    tags: List[str] | None = None,
    metadata: Dict[str, Any] | None = None,
    raw_observations: List[str] | None = None,
) -> KnowledgeRecord:
    """Convenience factory for creating a KnowledgeRecord."""
    return KnowledgeRecord(
        topic=topic,
        summary=summary,
        key_facts=key_facts or [],
        concepts_learned=concepts_learned or [],
        relationships=relationships or [],
        confidence=confidence,
        sources=sources or [],
        tags=tags or [],
        metadata=metadata or {},
        raw_observations=raw_observations or [],
    )


if __name__ == "__main__":
    print("Running niblit_memory/knowledge_record.py")
