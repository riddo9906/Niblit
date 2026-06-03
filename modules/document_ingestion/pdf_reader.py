#!/usr/bin/env python3
"""Offline PDF reader with lazy parser imports."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any


class PDFReader:
    """Read local PDFs and return page/chunk payloads for ingestion."""

    def read(self, file_path: str) -> dict[str, Any]:
        """Read *file_path* and return normalized pages/chunks."""
        path = Path(file_path).expanduser().resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"PDF not found: {file_path}")
        if path.suffix.lower() != ".pdf":
            raise ValueError(f"Only PDF files are supported: {file_path}")

        pages = self._read_pages_with_pypdf(path)
        if not pages:
            pages = self._read_pages_with_pdfminer(path)
        pages = [page for page in pages if page.get("text", "").strip()]
        chunks = self._chunk_pages(pages)
        return {
            "source": str(path),
            "pages": pages,
            "chunks": chunks,
        }

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()

    def _read_pages_with_pypdf(self, path: Path) -> list[dict[str, Any]]:
        try:
            from pypdf import PdfReader  # type: ignore[import-not-found]
        except Exception:
            return []

        try:
            reader = PdfReader(str(path))
        except Exception:
            return []

        pages: list[dict[str, Any]] = []
        for idx, page in enumerate(reader.pages, start=1):
            text = self._normalize_text(page.extract_text() or "")
            if text:
                pages.append({"page": idx, "text": text})
        return pages

    def _read_pages_with_pdfminer(self, path: Path) -> list[dict[str, Any]]:
        try:
            from pdfminer.high_level import extract_text  # type: ignore[import-not-found]
        except Exception as exc:
            raise RuntimeError("PDF parsing requires pypdf or pdfminer.six") from exc

        text = extract_text(str(path)) or ""
        if not str(text).strip():
            return []
        raw_pages = [self._normalize_text(part) for part in str(text).split("\f")]
        return [
            {"page": idx, "text": page_text}
            for idx, page_text in enumerate(raw_pages, start=1)
            if page_text
        ]

    def _chunk_pages(self, pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not pages:
            return []
        # ~1 token ~= 0.75 words; 800-1500 tokens ≈ 600-1125 words.
        target_words = 900
        max_words = 1125
        chunks: list[dict[str, Any]] = []
        bucket: list[str] = []
        bucket_words = 0
        chunk_id = 1

        for page in pages:
            words = str(page.get("text", "")).split()
            if not words:
                continue
            cursor = 0
            while cursor < len(words):
                remaining_capacity = max_words - bucket_words
                if remaining_capacity <= 0:
                    chunk_text = " ".join(bucket).strip()
                    if chunk_text:
                        chunks.append({"chunk_id": chunk_id, "text": chunk_text})
                        chunk_id += 1
                    bucket = []
                    bucket_words = 0
                    remaining_capacity = max_words

                take = min(remaining_capacity, len(words) - cursor)
                if take <= 0:
                    break
                segment = words[cursor:cursor + take]
                bucket.append(" ".join(segment))
                bucket_words += len(segment)
                cursor += take

                if bucket_words >= target_words:
                    chunk_text = " ".join(bucket).strip()
                    if chunk_text:
                        chunks.append({"chunk_id": chunk_id, "text": chunk_text})
                        chunk_id += 1
                    bucket = []
                    bucket_words = 0

        trailing = " ".join(bucket).strip()
        if trailing:
            chunks.append({"chunk_id": chunk_id, "text": trailing})
        return chunks


if __name__ == "__main__":
    print("Running pdf_reader.py")
