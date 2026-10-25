"""Versioned retrieval records; source documents and audit remain authoritative."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Category = Literal["working", "episodic", "semantic", "procedural"]
CATEGORIES = ("working", "episodic", "semantic", "procedural")


class MemoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_id: UUID
    schema_version: Literal["6.1"] = "6.1"
    category: Category
    namespace: str = Field(min_length=1, max_length=128)
    content: str = Field(min_length=1, max_length=12000)
    structured: dict[str, Any] | None = None
    source_id: str = Field(min_length=1)
    source_location: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    provenance: dict[str, Any]
    created_at: datetime
    observed_at: datetime
    updated_at: datetime
    confidence: float = Field(ge=0, le=1)
    verification: Literal["unverified", "verified", "rejected"] = "unverified"
    importance: float = Field(default=0.5, ge=0, le=1)
    retrieval_relevance: float | None = Field(default=None, ge=0, le=1)
    sensitivity: Literal["public", "internal", "private", "restricted"] = "private"
    access_principals: list[str] = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    embedding_version: str = Field(min_length=1)
    relationships: list[dict[str, str]] = Field(default_factory=list)
    entity_references: list[str] = Field(default_factory=list)
    supersedes: UUID | None = None
    superseded_by: UUID | None = None
    lifecycle: Literal["active", "superseded", "archived", "deleted"] = "active"
    deleted_at: datetime | None = None
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    idempotency_key: str = Field(min_length=1)

    @field_validator("created_at", "observed_at", "updated_at", "deleted_at")
    @classmethod
    def utc_timestamp(cls, value):
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("timestamps must include timezone")
            return value.astimezone(timezone.utc)
        return value

    @field_validator("namespace", "content", "source_id", "source_location",
                     "source_type", "embedding_model", "embedding_version",
                     "idempotency_key")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("blank value")
        return value

    @field_validator("access_principals")
    @classmethod
    def valid_principals(cls, value):
        if any(not p.strip() for p in value):
            raise ValueError("empty access principal")
        return sorted(set(value))

    @model_validator(mode="after")
    def consistent(self):
        import hashlib
        if hashlib.sha256(self.content.encode("utf-8")).hexdigest() != self.content_hash:
            raise ValueError("content hash mismatch")
        if self.updated_at < self.created_at:
            raise ValueError("updated timestamp predates creation")
        if not self.provenance:
            raise ValueError("provenance is required")
        if self.lifecycle == "deleted" and self.deleted_at is None:
            raise ValueError("deleted records require timestamp")
        return self
