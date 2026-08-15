"""KnowledgeIngestionService — canonical ingestion pipeline for Niblit.

This module provides the authoritative write path for external information
into Niblit long-term memory.

Flow:
    raw source/result
        ↓
    DocumentNormalizer
        ↓
    Deduplicator
        ↓
    canonical storage (FusedMemory)
        ↓
    optional legacy projection (KnowledgeDB)
        ↓
    optional embedding/indexing
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from niblit_memory.knowledge_document import (
    ContentFormat,
    KnowledgeDocument,
    SourceType,
    TrustLevel,
    compute_content_hash,
)
from niblit_memory.document_normalizer import DocumentNormalizer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Ingestion result
# ---------------------------------------------------------------------------

@dataclass
class IngestionResult:
    """Structured result of an ingestion attempt."""
    document_id: str = ""
    stored: bool = False
    duplicate: bool = False
    updated: bool = False
    content_hash: str = ""
    storage_backend: str = ""
    embedding_status: str = "skipped"
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "stored": self.stored,
            "duplicate": self.duplicate,
            "updated": self.updated,
            "content_hash": self.content_hash,
            "storage_backend": self.storage_backend,
            "embedding_status": self.embedding_status,
            "warnings": self.warnings,
            "errors": self.errors,
        }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_fused_memory():
    """Lazily import and return the global FusedMemory instance."""
    try:
        from niblit_memory import get_fused_memory
        return get_fused_memory()
    except Exception as exc:
        logger.debug("[Ingestion] FusedMemory unavailable: %s", exc)
        return None

def _get_knowledge_db():
    """Lazily import and return the global KnowledgeDB instance."""
    try:
        from niblit_memory import GLOBAL_KNOWLEDGE
        return GLOBAL_KNOWLEDGE
    except Exception as exc:
        logger.debug("[Ingestion] KnowledgeDB unavailable: %s", exc)
        return None

# ---------------------------------------------------------------------------
# KnowledgeIngestionService
# ---------------------------------------------------------------------------

class KnowledgeIngestionService:
    """Canonical ingestion service for Niblit knowledge documents.

    This service owns the write path for all newly ingested external
    information.  It ensures:
      - deterministic normalization via DocumentNormalizer
      - exact-content deduplication via content hash
      - canonical URI deduplication
      - versioning for updated documents
      - authoritative storage in FusedMemory
      - optional legacy projection to KnowledgeDB
      - optional embedding/indexing

    Usage:
        service = KnowledgeIngestionService()
        result = await service.ingest_raw(
            raw={"text": "...", "url": "https://example.com"},
            source_type=SourceType.web_page,
        )
    """

    def __init__(
        self,
        *,
        normalizer: Optional[DocumentNormalizer] = None,
        fused_memory: Any = None,
        knowledge_db: Any = None,
        enable_legacy_projection: bool = True,
        enable_embedding: bool = True,
    ):
        self.normalizer = normalizer or DocumentNormalizer()
        self._fused_memory = fused_memory
        self._knowledge_db = knowledge_db
        self.enable_legacy_projection = enable_legacy_projection
        self.enable_embedding = enable_embedding

    @property
    def fused_memory(self):
        if self._fused_memory is None:
            self._fused_memory = _get_fused_memory()
        return self._fused_memory

    @property
    def knowledge_db(self):
        if self._knowledge_db is None:
            self._knowledge_db = _get_knowledge_db()
        return self._knowledge_db

    def ingest(
        self,
        document: KnowledgeDocument,
        *,
        allow_update: bool = True,
    ) -> IngestionResult:
        """Ingest a canonical KnowledgeDocument.

        Args:
            document: The normalized document to ingest.
            allow_update: If True, a document with the same canonical URI
                          but different content hash is stored as a new version.

        Returns:
            IngestionResult with status and diagnostics.
        """
        result = IngestionResult()
        result.document_id = document.id
        result.content_hash = document.content_hash

        # --- Validation ---
        if not document.content and not document.source_uri:
            result.errors.append("empty_content_and_no_uri")
            return result

        # --- Deduplication ---
        existing = self._find_existing(document)
        if existing:
            existing_hash = existing.get("provenance", {}).get("content_hash", "")
            if existing_hash == document.content_hash:
                # Exact duplicate
                result.duplicate = True
                result.stored = True
                result.storage_backend = "existing"
                logger.debug("[Ingestion] Duplicate skipped: %s", document.id)
                return result
            elif allow_update and document.canonical_uri:
                # Same URI, different content — version/update
                result.updated = True
                result.stored = True
                result.storage_backend = "fused_memory"
                # Store with version metadata
                self._store_document(document, version_of=existing.get("id"))
                logger.debug("[Ingestion] Updated: %s (prev=%s)", document.id, existing.get("id"))
                return result
            else:
                # Same URI, different content, but updates not allowed
                result.duplicate = True
                result.stored = False
                result.warnings.append("same_uri_different_hash_update_not_allowed")
                return result

        # --- Store ---
        stored = self._store_document(document)
        result.stored = stored
        result.storage_backend = "fused_memory" if stored else "none"

        if not stored:
            result.errors.append("storage_failed")
            return result

        # --- Legacy projection ---
        if self.enable_legacy_projection:
            self._project_to_legacy(document)

        # --- Embedding ---
        if self.enable_embedding:
            embed_status = self._embed_document(document)
            result.embedding_status = embed_status

        logger.debug("[Ingestion] Stored: %s (backend=%s)", document.id, result.storage_backend)
        return result

    def ingest_raw(
        self,
        raw: Any,
        *,
        source_type: SourceType,
        trust_level: Optional[TrustLevel] = None,
        provenance: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        allow_update: bool = True,
    ) -> IngestionResult:
        """Normalize and ingest a raw source.

        Args:
            raw: Raw input (dict or str).
            source_type: The type of source.
            trust_level: Trust classification.
            provenance: Optional pre-built provenance.
            metadata: Optional extra metadata.
            allow_update: Whether to allow versioning for updated content.

        Returns:
            IngestionResult.
        """
        doc = self.normalizer.normalize(
            raw,
            source_type=source_type,
            trust_level=trust_level,
            provenance=provenance,
            metadata=metadata,
        )
        return self.ingest(doc, allow_update=allow_update)

    def ingest_search_result(
        self,
        result: Dict[str, Any],
        *,
        query: str = "",
        search_provider: str = "",
        allow_update: bool = True,
    ) -> IngestionResult:
        """Normalize and ingest a search result snippet."""
        doc = self.normalizer.normalize_search_result(
            result,
            query=query,
            search_provider=search_provider,
        )
        return self.ingest(doc, allow_update=allow_update)

    def ingest_github_result(
        self,
        result: Dict[str, Any],
        *,
        repository: str = "",
        path: str = "",
        commit: str = "",
        allow_update: bool = True,
    ) -> IngestionResult:
        """Normalize and ingest a GitHub search result."""
        doc = self.normalizer.normalize_github_result(
            result,
            repository=repository,
            path=path,
            commit=commit,
        )
        return self.ingest(doc, allow_update=allow_update)

    # ------------------------------------------------------------------
    # Internal storage helpers
    # ------------------------------------------------------------------

    def _find_existing(self, document: KnowledgeDocument) -> Optional[Dict[str, Any]]:
        """Find an existing document by canonical URI or content hash."""
        fm = self.fused_memory
        if fm is None:
            return None

        # Try canonical URI first
        if document.canonical_uri:
            try:
                existing = fm.retrieve(query=document.canonical_uri, event_type="knowledge_document", top_k=1)
                if existing and existing.get("events"):
                    return existing["events"][0]
            except Exception as exc:
                logger.debug("[Ingestion] FusedMemory lookup failed: %s", exc)

        # Try content hash
        try:
            existing = fm.retrieve(query=document.content_hash, event_type="knowledge_document", top_k=1)
            if existing and existing.get("events"):
                return existing["events"][0]
        except Exception as exc:
            logger.debug("[Ingestion] FusedMemory hash lookup failed: %s", exc)

        return None

    def _store_document(self, document: KnowledgeDocument, *, version_of: str = "") -> bool:
        """Store document to FusedMemory."""
        fm = self.fused_memory
        if fm is None:
            return False

        try:
            payload = document.to_dict()
            if version_of:
                payload["version_of"] = version_of
                payload["version_number"] = int(time.time())

            # Store as knowledge event with document metadata
            event_payload = {
                "type": "knowledge_document",
                "document_id": document.id,
                "content": document.content,
                "title": document.title,
                "source_uri": document.source_uri,
                "canonical_uri": document.canonical_uri,
                "source_type": document.source_type,
                "content_format": document.content_format,
                "content_hash": document.content_hash,
                "trust_level": document.get_trust_level().value,
                "confidence": document.confidence,
                "retrieved_at": document.retrieved_at,
                "published_at": document.published_at,
                "updated_at": document.updated_at,
                "author": document.author,
                "language": document.language,
                "topics": document.topics,
                "entities": document.entities,
                "embedding_ids": document.embedding_ids,
                "provenance": document.provenance,
                "metadata": document.metadata,
                "schema_version": document.schema_version,
            }

            if version_of:
                event_payload["version_of"] = version_of

            fm.log_event("knowledge_document", event_payload)
            return True
        except Exception as exc:
            logger.warning("[Ingestion] FusedMemory store failed: %s", exc)
            return False

    def _project_to_legacy(self, document: KnowledgeDocument) -> None:
        """Optionally project document to legacy KnowledgeDB for compatibility."""
        kdb = self.knowledge_db
        if kdb is None:
            return

        try:
            # Project as a research fact with trust metadata
            tags = [document.source_type, "canonical_ingest"]
            if document.topics:
                tags.extend(document.topics[:5])

            kdb.store_research(
                key=f"doc:{document.id}",
                text=document.content[:2000],
                tags=tags,
                source="canonical_ingestion",
                confidence=document.confidence,
            )
        except Exception as exc:
            logger.debug("[Ingestion] Legacy projection failed: %s", exc)

    def _embed_document(self, document: KnowledgeDocument) -> str:
        """Attempt to embed document content in vector store."""
        fm = self.fused_memory
        if fm is None:
            return "skipped_no_fused_memory"

        try:
            # Use FusedMemory's embedding capability if available
            if hasattr(fm, "add_embedding"):
                text = document.content[:2000]
                metadata = {
                    "document_id": document.id,
                    "source_type": document.source_type,
                    "source_uri": document.source_uri,
                    "domain": document.provenance.get("domain", ""),
                    "trust_level": document.get_trust_level().value,
                    "retrieved_at": document.retrieved_at,
                    "published_at": document.published_at,
                    "topics": document.topics[:10] if document.topics else [],
                }
                fm.add_embedding(text, metadata=metadata)
                return "embedded"
            return "no_embedding_api"
        except Exception as exc:
            logger.warning("[Ingestion] Embedding failed for %s: %s", document.id, exc)
            return f"failed:{exc}"