"""Unit tests for KnowledgeIngestionService."""

import pytest

from niblit_memory.ingestion import IngestionResult, KnowledgeIngestionService
from niblit_memory.knowledge_document import KnowledgeDocument, SourceType, TrustLevel
from niblit_memory.document_normalizer import DocumentNormalizer


class TestIngestionResult:
    def test_empty_defaults(self):
        result = IngestionResult()
        assert result.document_id == ""
        assert result.stored is False
        assert result.duplicate is False
        assert result.updated is False

    def test_to_dict(self):
        result = IngestionResult(
            document_id="doc_123",
            stored=True,
            duplicate=False,
            content_hash="abc123",
        )
        data = result.to_dict()
        assert data["document_id"] == "doc_123"
        assert data["stored"] is True
        assert data["duplicate"] is False
        assert data["content_hash"] == "abc123"


class TestKnowledgeIngestionService:
    def setup_method(self):
        self.normalizer = DocumentNormalizer()
        self.service = KnowledgeIngestionService(normalizer=self.normalizer)

    def test_ingest_new_document(self):
        doc = KnowledgeDocument(
            content="New unique content",
            source_uri="https://example.com/page1",
        )
        result = self.service.ingest(doc)
        assert result.stored is True
        assert result.duplicate is False
        assert result.content_hash == doc.content_hash
        assert result.storage_backend == "fused_memory"

    def test_ingest_duplicate_content(self):
        content = "Same content here"
        doc1 = KnowledgeDocument(content=content, source_uri="https://example.com/page")
        doc2 = KnowledgeDocument(content=content, source_uri="https://example.com/other-url")

        result1 = self.service.ingest(doc1)
        assert result1.stored is True

        result2 = self.service.ingest(doc2)
        assert result2.duplicate is True
        assert result2.stored is True
        assert result2.storage_backend == "existing"

    def test_ingest_empty_content_no_uri(self):
        doc = KnowledgeDocument(content="", source_uri="")
        result = self.service.ingest(doc)
        assert result.stored is False
        assert "empty_content_and_no_uri" in result.errors

    def test_ingest_raw_web_page(self):
        result = self.service.ingest_raw(
            raw={"text": "Web page content", "url": "https://example.com/article"},
            source_type=SourceType.web_page,
        )
        assert result.stored is True
        assert result.document_id

    def test_ingest_raw_with_trust_level(self):
        result = self.service.ingest_raw(
            raw={"text": "User provided info"},
            source_type=SourceType.file,
            trust_level=TrustLevel.user_supplied,
        )
        assert result.stored is True

    def test_ingest_search_result(self):
        result = self.service.ingest_search_result(
            {"text": "Search snippet", "url": "https://example.com"},
            query="test query",
            search_provider="serpex",
        )
        assert result.stored is True
        assert result.document_id

    def test_ingest_github_result(self):
        result = self.service.ingest_github_result(
            {"text": "code snippet", "url": "https://github.com/owner/repo"},
            repository="owner/repo",
            path="src/main.py",
        )
        assert result.stored is True
        assert result.document_id

    def test_versioning_same_uri_different_content(self):
        # First ingest
        doc1 = KnowledgeDocument(
            content="Original content",
            source_uri="https://example.com/page",
            canonical_uri="https://example.com/page",
        )
        result1 = self.service.ingest(doc1)
        assert result1.stored is True
        assert result1.updated is False

        # Second ingest with same URI but different content
        doc2 = KnowledgeDocument(
            content="Updated content",
            source_uri="https://example.com/page",
            canonical_uri="https://example.com/page",
        )
        result2 = self.service.ingest(doc2, allow_update=True)
        assert result2.stored is True
        assert result2.updated is True

    def test_legacy_projection_disabled(self):
        service = KnowledgeIngestionService(
            normalizer=self.normalizer,
            enable_legacy_projection=False,
        )
        doc = KnowledgeDocument(content="test")
        result = service.ingest(doc)
        assert result.stored is True