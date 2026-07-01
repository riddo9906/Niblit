#!/usr/bin/env python3
"""
modules/document_ingestion/pdf_structure_detector.py — PDF Structure Detection.

Analyses the raw text of PDF pages to identify structural elements:

* Chapters  — lines beginning with "Chapter N" or similar patterns
* Sections  — numbered headings like "1.2 Overview", "2. Methods"
* Headings  — short ALL-CAPS or title-case lines that are likely headings
* Tables    — lines with tab or consistent column spacing
* Captions  — lines beginning with "Figure N", "Table N", "Fig.", etc.
* Body      — regular paragraph text

The detector operates entirely in pure Python (no external dependencies) and
annotates each page dict with a ``structure`` key describing its dominant
element type and an optional extracted title.

Usage::

    from modules.document_ingestion.pdf_structure_detector import PDFStructureDetector

    detector = PDFStructureDetector()
    annotated = detector.detect_pages([
        {"page": 1, "text": "Chapter 1 Introduction\\nThis document..."},
        {"page": 2, "text": "1.1 Background\\nSome background text here."},
    ])
    sections = detector.group_into_sections(annotated)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

# ── Heading / structural patterns ─────────────────────────────────────────────

# "Chapter 1", "CHAPTER ONE", "Chapter I" etc.
_CHAPTER_RE = re.compile(
    r"^(?:chapter|appendix)\s+(?:[0-9]+|[ivxlcdm]+|one|two|three|four|five|"
    r"six|seven|eight|nine|ten)[\.\:\s]",
    re.IGNORECASE,
)

# Numbered section heading: "1.", "1.2", "2.3.4", optionally followed by a title
_SECTION_RE = re.compile(r"^([0-9]{1,2}(?:\.[0-9]{1,2}){0,3})[\.\s]\s*(\S.{0,80})$")

# Abstract, Introduction, Conclusion, References, etc. (common standalone headings)
_NAMED_SECTION_RE = re.compile(
    r"^(abstract|introduction|conclusion|conclusions|summary|references?"
    r"|bibliography|acknowledgements?|methodology|methods?|results?|"
    r"discussion|background|related work|future work|overview|appendix)[\.\:\s]*$",
    re.IGNORECASE,
)

# Figure / table captions
_CAPTION_RE = re.compile(
    r"^(?:fig(?:ure)?|table|exhibit|listing|algorithm)\s*[0-9]+",
    re.IGNORECASE,
)

# ALL-CAPS heading (at least 3 words, each ≥2 chars)
_ALL_CAPS_RE = re.compile(r"^([A-Z][A-Z\s\-]{4,80})$")

# Table-like line: contains multiple tabs or pipe characters
_TABLE_ROW_RE = re.compile(r"(\t.*\t|\|.*\|)")

# Minimum word count for a line to be considered body text (not a heading)
_BODY_MIN_WORDS: int = 8

# Maximum word count for a line to be considered a heading
_HEADING_MAX_WORDS: int = 12


class PDFStructureDetector:
    """Detect structural elements within PDF page text.

    The detector operates on per-page text strings and returns annotated
    page dicts augmented with a ``structure`` field.

    Structure field schema::

        {
            "type":  "chapter" | "section" | "heading" | "caption" |
                     "table" | "body",
            "level": int,    # heading depth (1=chapter, 2=section, 3=subsection)
            "title": str,    # extracted title string (may be empty for body/table)
        }
    """

    # ── Public API ────────────────────────────────────────────────────────────

    def detect_pages(self, pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Annotate each page dict with a ``structure`` key.

        Args:
            pages: List of ``{"page": int, "text": str}`` dicts (as produced
                   by :class:`PDFReader`).

        Returns:
            New list of dicts with an added ``"structure"`` key.
        """
        return [self._annotate_page(page) for page in pages]

    def group_into_sections(
        self, annotated_pages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Group annotated pages into logical document sections.

        A new section begins whenever a chapter- or section-level heading is
        encountered.  All subsequent pages are grouped under that heading until
        the next heading appears.

        Args:
            annotated_pages: Output of :meth:`detect_pages`.

        Returns:
            List of section dicts::

                {
                    "section_id":   int,
                    "title":        str,
                    "level":        int,
                    "type":         str,
                    "page_start":   int,
                    "page_end":     int,
                    "pages":        [{"page": int, "text": str, "structure": {...}}, ...],
                    "full_text":    str,  # concatenated page text
                }
        """
        sections: List[Dict[str, Any]] = []
        current: Dict[str, Any] | None = None

        for page in annotated_pages:
            struct = page.get("structure", {})
            stype = struct.get("type", "body")
            is_heading = stype in ("chapter", "section", "heading")

            if is_heading:
                if current is not None:
                    current["full_text"] = "\n".join(
                        p.get("text", "") for p in current["pages"]
                    )
                    sections.append(current)
                current = {
                    "section_id": len(sections) + 1,
                    "title": struct.get("title") or page.get("text", "")[:80].strip(),
                    "level": struct.get("level", 2),
                    "type": stype,
                    "page_start": page.get("page", 0),
                    "page_end": page.get("page", 0),
                    "pages": [page],
                }
            else:
                if current is None:
                    # Pages before the first heading go into a preamble section
                    current = {
                        "section_id": 1,
                        "title": "Preamble",
                        "level": 0,
                        "type": "body",
                        "page_start": page.get("page", 0),
                        "page_end": page.get("page", 0),
                        "pages": [],
                    }
                current["pages"].append(page)
                current["page_end"] = page.get("page", current["page_end"])

        if current is not None:
            current["full_text"] = "\n".join(
                p.get("text", "") for p in current["pages"]
            )
            sections.append(current)

        # Re-assign sequential IDs
        for idx, section in enumerate(sections, start=1):
            section["section_id"] = idx

        return sections

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _annotate_page(self, page: Dict[str, Any]) -> Dict[str, Any]:
        """Return a copy of *page* with a ``structure`` key added."""
        text = str(page.get("text") or "").strip()
        structure = self._detect_structure(text)
        result = dict(page)
        result["structure"] = structure
        return result

    def _detect_structure(self, text: str) -> Dict[str, Any]:
        """Classify the dominant structural element in *text*.

        Inspects the first significant line of the page text to determine
        whether it is a chapter heading, section heading, caption, table, or
        body paragraph.
        """
        if not text:
            return {"type": "body", "level": 0, "title": ""}

        # Check for table-like content first (can appear anywhere)
        if _TABLE_ROW_RE.search(text):
            return {"type": "table", "level": 0, "title": ""}

        # Inspect leading lines only (headings appear at the top of a page)
        leading = self._leading_line(text)
        if not leading:
            return {"type": "body", "level": 0, "title": ""}

        # Chapter
        if _CHAPTER_RE.match(leading):
            title = leading.strip()
            return {"type": "chapter", "level": 1, "title": title}

        # Caption
        if _CAPTION_RE.match(leading):
            return {"type": "caption", "level": 0, "title": leading[:80]}

        # Named standalone section (Abstract, Introduction, …)
        if _NAMED_SECTION_RE.match(leading):
            return {"type": "section", "level": 1, "title": leading.title()}

        # Numbered section
        m = _SECTION_RE.match(leading)
        if m:
            number = m.group(1)
            title_part = m.group(2).strip()
            level = min(3, number.count(".") + 2)
            return {"type": "section", "level": level, "title": f"{number} {title_part}"}

        # ALL-CAPS heading (short line)
        if _ALL_CAPS_RE.match(leading):
            word_count = len(leading.split())
            if word_count <= _HEADING_MAX_WORDS:
                return {"type": "heading", "level": 2, "title": leading.title()}

        # Default: body
        return {"type": "body", "level": 0, "title": ""}

    @staticmethod
    def _leading_line(text: str) -> str:
        """Return the first non-empty line of *text*."""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
        return ""


if __name__ == "__main__":
    print("Running modules/document_ingestion/pdf_structure_detector.py")
