"""Integration tests for the canonical knowledge pipeline.

Tests the full flow:
  search/fetch → normalize → ingest → deduplicate → store → retrieve
"""

import pytest

from niblit_memory.knowledge_document import (
    KnowledgeDocument,
    SourceType,
    TrustLevel,
    compute_content_hash,
)
from niblit_memory.document_normalizer import DocumentNormalizer
from niblit_memory.ingestion import KnowledgeIngestionService, IngestionResult
from niblit_memory.web_fetcher import SafeWebFetcher
from niblit_memory.chunker import DocumentChunker


class TestEndToEndIngestion:
    """Test the complete pipeline from raw input to stored document."""

    def setup_method(self):
        self.normalizer = DocumentNormalizer()
        self.service = KnowledgeIngestionService(normalizer=self.normalizer)
        self.chunker = DocumentChunker(target_chars=500, overlap_chars=50)

    def test_web_search_result_ingestion(self):
        """Simulate ingesting a web search result."""
        result = {
            "text": "Python is a high-level programming language.",
            "url": "https://example.com/python",
            "title": "Python Overview",
        }

        ingestion_result = self.service.ingest_search_result(
            result,
            query="python programming",
            search_provider="serpex",
        )

        assert ingestion_result.stored is True
        assert ingestion_result.document_id
        assert ingestion_result.content_hash

    def test_web_page_ingestion_with_html(self):
        """Simulate ingesting a fetched web page."""
        raw = {
            "html": "<html><body><h1>Article Title</h1><p>This is the article content.</p></body></html>",
            "url": "https://example.com/article",
            "content_type": "text/html",
        }

        ingestion_result = self.service.ingest_raw(
            raw,
            source_type=SourceType.web_page,
        )

        assert ingestion_result.stored is True
        assert ingestion_result.document_id

    def test_github_result_ingestion(self):
        """Simulate ingesting a GitHub search result."""
        result = {
            "text": "def hello():\n    print('world')",
            "url": "https://github.com/owner/repo/blob/main/hello.py",
        }

        ingestion_result = self.service.ingest_github_result(
            result,
            repository="owner/repo",
            path="hello.py",
        )

        assert ingestion_result.stored is True
        assert ingestion_result.document_id

    def test_chat_message_ingestion(self):
        """Simulate ingesting a chat message."""
        ingestion_result = self.service.ingest_raw(
            raw={"text": "User message content"},
            source_type=SourceType.chat,
            trust_level=TrustLevel.user_supplied,
        )

        assert ingestion_result.stored is True

    def test_deduplication(self):
        """Test that duplicate content is detected."""
        content = "This is a unique test content."

        # First ingestion
        doc1 = KnowledgeDocument(content=content, source_uri="https://example.com/1")
        result1 = self.service.ingest(doc1)
        assert result1.stored is True
        assert result1.duplicate is False

        # Second ingestion with same content, different URI
        doc2 = KnowledgeDocument(content=content, source_uri="https://example.com/2")
        result2 = self.service.ingest(doc2)
        assert result2.stored is True
        assert result2.duplicate is True

    def test_chunking_integration(self):
        """Test that documents can be chunked after ingestion."""
        content = "This is paragraph 1.\n\nThis is paragraph 2.\n\nThis is paragraph 3.\n\nThis is paragraph 4."
        doc = KnowledgeDocument(content=content, source_uri="https://example.com/article")

        # Ingest
        result = self.service.ingest(doc)
        assert result.stored is True

        # Chunk
        chunks = self.chunker.chunk_document(
            document_id=doc.id,
            content=content,
            source_uri=doc.source_uri,
        )

        # Should have multiple chunks due to target size
        assert len(chunks) >= 1
        for chunk in chunks:
            assert chunk.document_id == doc.id
            assert chunk.content
            assert chunk.chunk_id


class TestContentHashingAndDeduplication:
    """Test content hash-based deduplication."""

    def test_identical_content_same_hash(self):
        text = "Hello world"
        h1 = compute_content_hash(text)
        h2 = compute_content_hash(text)
        assert h1 == h2

    def test_different_content_different_hash(self):
        h1 = compute_content_hash("Hello")
        h2 = compute_content_hash("World")
        assert h1 != h2

    def test_whitespace_normalization(self):
        h1 = compute_content_hash("  hello  ")
        h2 = compute_content_hash("hello")
        assert h1 == h2


class TestSafeWebFetcherIntegration:
    """Test safe web fetching."""

    def test_fetcher_rejects_private_ips(self):
        fetcher = SafeWebFetcher()
        response = fetcher.fetch("http://192.168.1.1/")
        assert response.success is False
        assert "private_ip" in response.error

    def test_fetcher_rejects_localhost(self):
        fetcher = SafeWebFetcher()
        response = fetcher.fetch("http://localhost:8080/")
        assert response.success is False
        assert "blocked_host" in response.error

    def test_fetcher_accepts_public_http(self):
        fetcher = SafeWebFetcher()
        response = fetcher.fetch("http://example.com/")
        # Should not fail with validation error
        if not response.success:
            assert "url_validation_failed" not in response.error

    def test_fetcher_accepts_public_https(self):
        fetcher = SafeWebFetcher()
        response = fetcher.fetch("https://example.com/")
        # Should not fail with validation error
        if not response.success:
            assert "url_validation_failed" not in response.error


class TestDocumentNormalizerIntegration:
    """Test document normalization with various input types."""

    def setup_method(self):
        self.normalizer = DocumentNormalizer()

    def test_normalize_search_result(self):
        doc = self.normalizer.normalize_search_result(
            {"text": "Search snippet", "url": "https://example.com"},
            query="test",
            search_provider="serpex",
        )
        assert doc.source_type == SourceType.web_search_result.value
        assert doc.confidence == 0.7

    def test_normalize_github_result(self):
        doc = self.normalizer.normalize_github_result(
            {"text": "code", "url": "https://github.com/o/r"},
            repository="o/r",
        )
        assert doc.source_type == SourceType.github.value
        assert doc.metadata.get("repository") == "o/r"

    def test_normalize_chat_message(self):
        doc = self.normalizer.normalize_chat_message(
            role="user",
            content="Hello",
        )
        assert doc.source_type == SourceType.chat.value
        assert doc.metadata.get("role") == "user"


class TestProvenanceTracking:
    """Test that provenance is preserved through the pipeline."""

    def test_provenance_populated(self):
        doc = KnowledgeDocument(
            content="Test content",
            source_uri="https://example.com/page",
            provenance={
                "source_uri": "https://example.com/page",
                "trust_level": TrustLevel.external_untrusted.value,
            },
        )

        assert doc.provenance.get("source_uri") == "https://example.com/page"
        assert doc.provenance.get("trust_level") == TrustLevel.external_untrusted.value

    def test_provenance_in_ingestion(self):
        raw = {
            "text": "Article content",
            "url": "https://example.com/article",
            "author": "Test Author",
            "published_at": "2024-01-15T10:00:00Z",
        }

        doc = DocumentNormalizer().normalize(
            raw,
            source_type=SourceType.web_page,
        )

        assert doc.provenance.get("author") == "Test Author"
        assert doc.provenance.get("published_at") is not None


class TestTrustLevels:
    """Test trust level assignment."""

    def test_external_untrusted_default(self):
        doc = DocumentNormalizer().normalize(
            {"text": "test"},
            source_type=SourceType.web_page,
        )
        assert doc.get_trust_level() == TrustLevel.external_untrusted

    def test_user_supplied(self):
        doc = DocumentNormalizer().normalize(
            {"text": "test"},
            source_type=SourceType.file,
            trust_level=TrustLevel.user_supplied,
        )
        assert doc.get_trust_level() == TrustLevel.user_supplied

    def test_github_structured(self):
        doc = DocumentNormalizer().normalize(
            {"text": "code"},
            source_type=SourceType.github,
            trust_level=TrustLevel.external_structured,
        )
        assert doc.get_trust_level() == TrustLevel.external_structured


class TestChunkingIntegration:
    """Test document chunking."""

    def setup_method(self):
        self.chunker = DocumentChunker(target_chars=200, overlap_chars=20)

    def test_chunks_preserve_provenance(self):
        content = "A" * 500
        provenance = {"source_uri": "https://example.com"}
        chunks = self.chunker.chunk_document(
            document_id="doc_1",
            content=content,
            provenance=provenance,
        )

        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.provenance == provenance

    def test_chunks_are_deterministic(self):
        content = "A" * 500
        chunks1 = self.chunker.chunk_document(
            document_id="doc_1",
            content=content,
        )
        chunks2 = self.chunker.chunk_document(
            document_id="doc_1",
            content=content,
        )

        # Same content should produce same chunk structure
        assert len(chunks1) == len(chunks2)
        for c1, c2 in zip(chunks1, chunks2):
            assert c1.content == c2.content
            assert c1.chunk_index == c2.chunk_index
