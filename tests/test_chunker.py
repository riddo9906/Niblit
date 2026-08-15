"""Unit tests for DocumentChunker."""

import pytest

from niblit_memory.chunker import DocumentChunker, DocumentChunk, DEFAULT_TARGET_CHARS, DEFAULT_OVERLAP_CHARS


class TestDocumentChunker:
    def setup_method(self):
        self.chunker = DocumentChunker()

    def test_empty_content(self):
        chunks = self.chunker.chunk_document(
            document_id="doc_1",
            content="",
        )
        assert chunks == []

    def test_short_document_single_chunk(self):
        text = "This is a short document."
        chunks = self.chunker.chunk_document(
            document_id="doc_1",
            content=text,
        )
        assert len(chunks) == 1
        assert chunks[0].content == text
        assert chunks[0].chunk_index == 0
        assert chunks[0].document_id == "doc_1"

    def test_chunk_id_generation(self):
        chunks = self.chunker.chunk_document(
            document_id="doc_1",
            content="Hello world",
        )
        assert chunks[0].chunk_id
        assert chunks[0].chunk_id.startswith("chunk_")

    def test_content_hash_computed(self):
        chunks = self.chunker.chunk_document(
            document_id="doc_1",
            content="Hello world",
        )
        assert chunks[0].content_hash
        assert len(chunks[0].content_hash) == 64

    def test_provenance_preserved(self):
        provenance = {"source_uri": "https://example.com", "trust_level": "external_untrusted"}
        chunks = self.chunker.chunk_document(
            document_id="doc_1",
            content="Hello world",
            provenance=provenance,
        )
        assert chunks[0].provenance == provenance

    def test_metadata_preserved(self):
        metadata = {"author": "Test Author"}
        chunks = self.chunker.chunk_document(
            document_id="doc_1",
            content="Hello world",
            metadata=metadata,
        )
        assert chunks[0].metadata == metadata

    def test_multiple_chunks(self):
        # Create content longer than target
        text = "Paragraph 1\n\nParagraph 2\n\nParagraph 3\n\nParagraph 4"
        # Target 20 chars to force multiple chunks
        chunker = DocumentChunker(target_chars=20, overlap_chars=5)
        chunks = chunker.chunk_document(
            document_id="doc_1",
            content=text,
        )
        assert len(chunks) > 1

    def test_chunk_indices_incremented(self):
        text = "A" * 1000
        chunker = DocumentChunker(target_chars=100, overlap_chars=10)
        chunks = chunker.chunk_document(
            document_id="doc_1",
            content=text,
        )
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_source_uri_attached(self):
        chunks = self.chunker.chunk_document(
            document_id="doc_1",
            content="Hello world",
            source_uri="https://example.com",
        )
        assert chunks[0].source_uri == "https://example.com"

    def test_to_dict(self):
        chunks = self.chunker.chunk_document(
            document_id="doc_1",
            content="Hello world",
        )
        data = chunks[0].to_dict()
        assert "chunk_id" in data
        assert "document_id" in data
        assert "content" in data
        assert data["document_id"] == "doc_1"

    def test_custom_target_chars(self):
        text = "A" * 5000
        chunker = DocumentChunker(target_chars=1000, overlap_chars=100)
        chunks = chunker.chunk_document(
            document_id="doc_1",
            content=text,
        )
        # All chunks except possibly the last should be close to target
        for chunk in chunks[:-1]:
            assert len(chunk.content) <= 1200  # allow some overflow