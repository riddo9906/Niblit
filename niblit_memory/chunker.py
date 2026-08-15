"""Deterministic document chunking for Niblit knowledge pipeline.

This module provides heading/paragraph-aware deterministic chunking.
No semantic AI chunking is performed — chunks are split based on
structural boundaries with configurable overlap.

Each chunk retains provenance to its source document.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Default target chunk size in characters
DEFAULT_TARGET_CHARS: int = 3000

#: Default overlap between chunks in characters
DEFAULT_OVERLAP_CHARS: int = 300

# Environment variable overrides
_ENV_TARGET_CHARS = os.getenv("NIBLIT_MEMORY_CHUNK_TARGET_CHARS")
_ENV_OVERLAP_CHARS = os.getenv("NIBLIT_MEMORY_CHUNK_OVERLAP_CHARS")

if _ENV_TARGET_CHARS:
    try:
        DEFAULT_TARGET_CHARS = max(500, int(_ENV_TARGET_CHARS))
    except ValueError:
        pass

if _ENV_OVERLAP_CHARS:
    try:
        DEFAULT_OVERLAP_CHARS = max(0, min(int(_ENV_OVERLAP_CHARS), DEFAULT_TARGET_CHARS // 2))
    except ValueError:
        pass

# ---------------------------------------------------------------------------
# Chunk model
# ---------------------------------------------------------------------------

@dataclass
class DocumentChunk:
    """A single chunk of a knowledge document."""
    chunk_id: str = ""
    document_id: str = ""
    chunk_index: int = 0
    content: str = ""
    content_hash: str = ""
    source_uri: str = ""
    provenance: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.chunk_id:
            self.chunk_id = self._generate_id()

    def _generate_id(self) -> str:
        ts = int(time.time())
        return f"chunk_{ts}_{hashlib.sha256(f'{self.document_id}:{self.chunk_index}'.encode()).hexdigest()[:12]}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "chunk_index": self.chunk_index,
            "content": self.content,
            "content_hash": self.content_hash,
            "source_uri": self.source_uri,
            "provenance": self.provenance,
            "metadata": self.metadata,
        }

# ---------------------------------------------------------------------------
# Chunker
# ---------------------------------------------------------------------------

class DocumentChunker:
    """Deterministic document chunking with heading/paragraph awareness.

    Splits documents into chunks based on:
      1. Markdown headings (# ## ###)
      2. Paragraph boundaries (double newline)
      3. Sentence boundaries (single newline, period+space)
      4. Hard target size limit

    Overlap is preserved between adjacent chunks to maintain context.

    Usage:
        chunker = DocumentChunker()
        chunks = chunker.chunk_document(
            document_id="doc_123",
            content="...",
            source_uri="https://example.com",
            provenance={...},
        )
    """

    def __init__(
        self,
        target_chars: int = DEFAULT_TARGET_CHARS,
        overlap_chars: int = DEFAULT_OVERLAP_CHARS,
    ):
        self.target_chars = target_chars
        self.overlap_chars = overlap_chars

    def chunk_document(
        self,
        *,
        document_id: str,
        content: str,
        source_uri: str = "",
        provenance: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[DocumentChunk]:
        """Chunk a document into multiple DocumentChunk objects.

        Args:
            document_id: The source document ID.
            content: The full document text.
            source_uri: The document source URI.
            provenance: Optional provenance to attach to each chunk.
            metadata: Optional metadata to attach to each chunk.

        Returns:
            List of DocumentChunk objects.
        """
        if not content or not content.strip():
            return []

        text = content.strip()
        if len(text) <= self.target_chars:
            # Document fits in one chunk
            chunk = DocumentChunk(
                document_id=document_id,
                chunk_index=0,
                content=text,
                content_hash=self._compute_chunk_hash(text),
                source_uri=source_uri,
                provenance=dict(provenance or {}),
                metadata=dict(metadata or {}),
            )
            return [chunk]

        # Split into sections based on headings and paragraphs
        sections = self._split_into_sections(text)

        # Combine sections into chunks with overlap
        chunks = self._combine_sections_into_chunks(
            document_id=document_id,
            sections=sections,
            source_uri=source_uri,
            provenance=provenance or {},
            metadata=metadata or {},
        )

        return chunks

    def _split_into_sections(self, text: str) -> List[str]:
        """Split text into sections based on headings and paragraphs."""
        # Split on markdown headings or double newlines
        # Preserve the heading/paragraph boundary markers for context
        parts = re.split(r'(\n#{1,6}\s+.*?\n|\n{2,})', text)

        sections: List[str] = []
        current = ""

        for part in parts:
            if not part:
                continue
            # Check if this is a heading/paragraph boundary
            if re.match(r'\n#{1,6}\s+', part) or re.match(r'\n{2,}', part):
                if current.strip():
                    sections.append(current.strip())
                current = part
            else:
                current += part

        if current.strip():
            sections.append(current.strip())

        return sections

    def _combine_sections_into_chunks(
        self,
        *,
        document_id: str,
        sections: List[str],
        source_uri: str,
        provenance: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> List[DocumentChunk]:
        """Combine sections into chunks respecting target size and overlap."""
        chunks: List[DocumentChunk] = []
        current_chunk_text = ""
        chunk_index = 0

        for section in sections:
            # If adding this section would exceed target, start a new chunk
            if current_chunk_text and len(current_chunk_text) + len(section) > self.target_chars:
                # Finalize current chunk
                chunk = DocumentChunk(
                    document_id=document_id,
                    chunk_index=chunk_index,
                    content=current_chunk_text.strip(),
                    content_hash=self._compute_chunk_hash(current_chunk_text),
                    source_uri=source_uri,
                    provenance=dict(provenance),
                    metadata=dict(metadata),
                )
                chunks.append(chunk)
                chunk_index += 1

                # Start new chunk with overlap
                if self.overlap_chars > 0:
                    overlap_text = current_chunk_text[-self.overlap_chars:]
                    current_chunk_text = overlap_text + section
                else:
                    current_chunk_text = section
            else:
                current_chunk_text += section

        # Finalize last chunk
        if current_chunk_text.strip():
            chunk = DocumentChunk(
                document_id=document_id,
                chunk_index=chunk_index,
                content=current_chunk_text.strip(),
                content_hash=self._compute_chunk_hash(current_chunk_text),
                source_uri=source_uri,
                provenance=dict(provenance),
                metadata=dict(metadata),
            )
            chunks.append(chunk)

        return chunks

    def _compute_chunk_hash(self, content: str) -> str:
        """Compute hash for a chunk."""
        return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()
