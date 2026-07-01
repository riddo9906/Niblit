#!/usr/bin/env python3
"""
modules/document_ingestion/pdf_understanding.py — PDF Understanding Pipeline.

Transforms a raw PDFReader payload into structured knowledge by:

1. Detecting document structure (chapters, sections, headings, tables, captions).
2. Grouping pages into logical sections.
3. Per-section/chunk: extracting definitions, facts, procedures, relationships,
   and terminology.
4. Generating a human-readable summary for each section.
5. Building semantic concepts and optionally linking them into the MemoryGraph.
6. Creating KnowledgeRecords for each section.
7. Returning a comprehensive understanding result.

After ingestion, Niblit can answer questions from the stored KnowledgeRecords
without re-reading the PDF every time.

Usage::

    from modules.document_ingestion.pdf_reader import PDFReader
    from modules.document_ingestion.pdf_understanding import PDFUnderstandingPipeline

    pipeline = PDFUnderstandingPipeline(knowledge_db=my_db)
    result = pipeline.understand(PDFReader().read("/path/to/doc.pdf"))

    print(result["summary"])
    for rec in result["knowledge_records"]:
        print(rec.human_readable())
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from modules.document_ingestion.pdf_structure_detector import PDFStructureDetector
from niblit_memory.knowledge_logger import KnowledgeLogger
from niblit_memory.knowledge_record import KnowledgeRecord

log = logging.getLogger("PDFUnderstandingPipeline")

# ── Extraction constants ──────────────────────────────────────────────────────

# Patterns for definition extraction.
# Matches: "X is defined as …", "X refers to …", "X: …", "X means …"
_DEF_RE = re.compile(
    r"([A-Z][a-zA-Z\s\-]{2,40}?)\s+(?:is|are|refers? to|means?|denotes?|"
    r"describes?|defined? as|stands? for)\s+([^.!?]{10,200}[.!?])",
    re.IGNORECASE,
)

# Patterns for procedure/step extraction.
# Matches ordered steps: "1. Do this", "Step 1:", "First, …"
_PROC_RE = re.compile(
    r"(?:^|\n)\s*(?:[0-9]+[\.\)]\s+|step\s+[0-9]+\s*:\s*|"
    r"(?:first|second|third|fourth|fifth|then|next|finally)[,\s]+)([^.\n]{10,200})",
    re.IGNORECASE,
)

# Factual assertion pattern.
_FACT_MARKERS_RE = re.compile(
    r"\b(is|are|was|were|can|will|does|allows|enables|requires|provides|"
    r"supports|prevents|stores|persists|returns|creates|builds|uses|defines)\b",
    re.IGNORECASE,
)

# Sentence boundary.
_SENT_END_RE = re.compile(r"(?<=[.!?])\s+")

# Technical terminology: CamelCase, ALL_CAPS, or hyphenated.
_TECH_TERM_RE = re.compile(
    r"\b([A-Z][a-z]+[A-Z][A-Za-z]+|[A-Z]{2,8}|[a-z]+-[a-z]+(?:-[a-z]+)*)\b"
)

# Maximum chars of a section's text fed into extraction routines.
_MAX_TEXT_CHARS: int = 4_000

# Maximum items returned per extraction type.
_MAX_FACTS: int = 8
_MAX_DEFS: int = 6
_MAX_PROCS: int = 6
_MAX_TERMS: int = 12

# Minimum sentence length to be considered a key fact.
_MIN_FACT_LEN: int = 20


class PDFUnderstandingPipeline:
    """Full understanding pipeline for PDF documents.

    Args:
        knowledge_db:  Optional KnowledgeDB.  When provided, KnowledgeRecords
                       are persisted via :meth:`KnowledgeLogger.store_record`.
        memory_graph:  Optional MemoryGraph.  When provided, each section
                       summary is embedded as a graph node.
        knowledge_logger: Optional pre-built KnowledgeLogger.  When omitted,
                          one is created from *knowledge_db* and *memory_graph*.
    """

    def __init__(
        self,
        knowledge_db: Any | None = None,
        memory_graph: Any | None = None,
        knowledge_logger: KnowledgeLogger | None = None,
    ) -> None:
        self.knowledge_db = knowledge_db
        self.memory_graph = memory_graph
        self._structure_detector = PDFStructureDetector()
        self._logger: KnowledgeLogger = knowledge_logger or KnowledgeLogger(
            knowledge_db=knowledge_db,
            memory_graph=memory_graph,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def understand(self, document_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Transform a PDFReader payload into structured knowledge.

        Args:
            document_payload: Output of :meth:`PDFReader.read` — a dict with
                ``"source"``, ``"pages"``, and ``"chunks"`` keys.

        Returns:
            A dict with::

                {
                    "source":              str,
                    "page_count":          int,
                    "chunk_count":         int,
                    "section_count":       int,
                    "sections":            list[dict],  # annotated sections
                    "knowledge_records":   list[KnowledgeRecord],
                    "definitions":         list[str],
                    "facts":               list[str],
                    "procedures":          list[str],
                    "terminology":         list[str],
                    "relationships":       list[dict],
                    "summary":             str,  # document-level summary
                    "document_topic":      str,
                }
        """
        payload = dict(document_payload or {})
        source = str(payload.get("source") or "").strip()
        raw_pages: List[Dict[str, Any]] = [
            p for p in list(payload.get("pages") or [])
            if str((p or {}).get("text") or "").strip()
        ]
        chunks: List[Dict[str, Any]] = [
            c for c in list(payload.get("chunks") or [])
            if str((c or {}).get("text") or "").strip()
        ]

        document_topic = self._derive_topic(source, raw_pages)

        # 1. Detect structure
        annotated_pages = self._structure_detector.detect_pages(raw_pages)

        # 2. Group into sections
        sections = self._structure_detector.group_into_sections(annotated_pages)

        # 3. Extract knowledge per section
        all_definitions: List[str] = []
        all_facts: List[str] = []
        all_procedures: List[str] = []
        all_terminology: List[str] = []
        all_relationships: List[Dict[str, str]] = []
        knowledge_records: List[KnowledgeRecord] = []

        for section in sections:
            sec_text = section.get("full_text") or ""
            sec_title = section.get("title") or document_topic
            section_topic = f"{document_topic} — {sec_title}" if sec_title != document_topic else document_topic

            defs = self._extract_definitions(sec_text)
            facts = self._extract_facts(sec_text)
            procs = self._extract_procedures(sec_text)
            terms = self._extract_terminology(sec_text)
            rels = self._extract_relationships(sec_text)

            all_definitions.extend(defs)
            all_facts.extend(facts)
            all_procedures.extend(procs)
            all_terminology.extend(terms)
            all_relationships.extend(rels)

            # Store section metadata on the section dict
            section["definitions"] = defs
            section["facts"] = facts
            section["procedures"] = procs
            section["terminology"] = terms

            if not sec_text.strip():
                continue

            # 4. Build KnowledgeRecord for this section
            observations = self._build_observations(sec_text, facts, defs)
            record = self._logger.create_record(
                topic=section_topic,
                observations=observations,
                source=source,
                confidence=0.8,
                tags=["pdf_understanding", "knowledge_chunk", document_topic.lower()[:30]],
                metadata={
                    "section_id": section.get("section_id"),
                    "section_title": sec_title,
                    "page_start": section.get("page_start"),
                    "page_end": section.get("page_end"),
                    "document_source": source,
                    "terminology": terms,
                    "definitions": defs,
                    "procedures": procs,
                },
            )
            self._logger.store_record(record)
            knowledge_records.append(record)

        # 5. Build document-level summary record
        doc_summary = self._build_document_summary(
            document_topic, source, all_facts, all_definitions, sections
        )
        doc_record = self._logger.create_record(
            topic=document_topic,
            observations=self._build_observations(
                "\n".join(all_facts[:10]), all_facts[:10], all_definitions[:5]
            ),
            source=source,
            confidence=0.85,
            tags=["pdf_understanding", "document_summary", document_topic.lower()[:30]],
            metadata={
                "document_source": source,
                "section_count": len(sections),
                "page_count": len(raw_pages),
                "chunk_count": len(chunks),
            },
        )
        self._logger.store_record(doc_record)
        knowledge_records.insert(0, doc_record)

        return {
            "source": source,
            "document_topic": document_topic,
            "page_count": len(raw_pages),
            "chunk_count": len(chunks),
            "section_count": len(sections),
            "sections": sections,
            "knowledge_records": knowledge_records,
            "definitions": self._deduplicate_list(all_definitions)[:_MAX_DEFS],
            "facts": self._deduplicate_list(all_facts)[:_MAX_FACTS],
            "procedures": self._deduplicate_list(all_procedures)[:_MAX_PROCS],
            "terminology": self._deduplicate_list(all_terminology)[:_MAX_TERMS],
            "relationships": all_relationships,
            "summary": doc_summary,
        }

    # ── Extraction helpers ────────────────────────────────────────────────────

    def _extract_definitions(self, text: str) -> List[str]:
        """Extract definition sentences from *text*."""
        results: List[str] = []
        seen: set = set()
        for m in _DEF_RE.finditer(text[:_MAX_TEXT_CHARS]):
            full = m.group(0).strip()
            norm = full.lower()
            if norm not in seen:
                seen.add(norm)
                results.append(full)
            if len(results) >= _MAX_DEFS:
                break
        return results

    def _extract_facts(self, text: str) -> List[str]:
        """Extract factual assertion sentences from *text*."""
        facts: List[str] = []
        seen: set = set()
        for sent in _SENT_END_RE.split(text[:_MAX_TEXT_CHARS]):
            sent = sent.strip()
            if len(sent) < _MIN_FACT_LEN:
                continue
            if not _FACT_MARKERS_RE.search(sent):
                continue
            norm = sent.lower()
            if norm in seen:
                continue
            seen.add(norm)
            facts.append(sent)
            if len(facts) >= _MAX_FACTS:
                break
        return facts

    def _extract_procedures(self, text: str) -> List[str]:
        """Extract procedural/step sentences from *text*."""
        results: List[str] = []
        seen: set = set()
        for m in _PROC_RE.finditer(text[:_MAX_TEXT_CHARS]):
            step = m.group(1).strip()
            if len(step) < _MIN_FACT_LEN:
                continue
            norm = step.lower()
            if norm not in seen:
                seen.add(norm)
                results.append(step)
            if len(results) >= _MAX_PROCS:
                break
        return results

    def _extract_terminology(self, text: str) -> List[str]:
        """Extract technical terms from *text*."""
        seen: set = set()
        terms: List[str] = []
        for m in _TECH_TERM_RE.finditer(text[:_MAX_TEXT_CHARS]):
            term = m.group(1)
            lower = term.lower()
            if lower not in seen and len(term) >= 3:
                seen.add(lower)
                terms.append(term)
            if len(terms) >= _MAX_TERMS:
                break
        return terms

    def _extract_relationships(self, text: str) -> List[Dict[str, str]]:
        """Extract concept relationships from *text*."""
        terms = set(self._extract_terminology(text))
        relationships: List[Dict[str, str]] = []
        seen_pairs: set = set()

        for sent in _SENT_END_RE.split(text[:_MAX_TEXT_CHARS]):
            lower = sent.lower()
            present = [t for t in terms if t.lower() in lower]
            if len(present) < 2:
                continue
            for i in range(len(present)):
                for j in range(i + 1, len(present)):
                    a, b = present[i], present[j]
                    pair = (min(a, b), max(a, b))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    rel_type = self._classify_rel(sent)
                    relationships.append({"from": a, "to": b, "type": rel_type})
        return relationships

    @staticmethod
    def _classify_rel(sentence: str) -> str:
        lower = sentence.lower()
        if re.search(r"\b(enables?|allows?)\b", lower):
            return "enables"
        if re.search(r"\b(requires?|depends?)\b", lower):
            return "requires"
        if re.search(r"\b(is a|are a|type of|kind of)\b", lower):
            return "is_a"
        if re.search(r"\b(uses?|utilises?|employs?)\b", lower):
            return "uses"
        if re.search(r"\b(contains?|includes?|consists? of)\b", lower):
            return "contains"
        return "related_to"

    # ── Summary helpers ───────────────────────────────────────────────────────

    def _build_observations(
        self,
        text: str,
        facts: List[str],
        definitions: List[str],
    ) -> List[str]:
        """Build a list of observation strings for KnowledgeLogger."""
        obs: List[str] = []
        obs.extend(facts[:5])
        obs.extend(definitions[:3])
        # Add leading sentences of raw text as fallback
        if not obs and text.strip():
            for sent in _SENT_END_RE.split(text[:1000]):
                sent = sent.strip()
                if len(sent) >= _MIN_FACT_LEN:
                    obs.append(sent)
                if len(obs) >= 5:
                    break
        return obs

    def _build_document_summary(
        self,
        topic: str,
        source: str,
        all_facts: List[str],
        all_definitions: List[str],
        sections: List[Dict[str, Any]],
    ) -> str:
        """Build a human-readable document-level summary."""
        parts: List[str] = []
        if all_facts:
            parts.append(all_facts[0])
        elif all_definitions:
            parts.append(all_definitions[0])

        section_titles = [
            s.get("title") for s in sections
            if s.get("title") and s.get("type") in ("chapter", "section")
        ]
        if section_titles:
            joined = "; ".join(section_titles[:5])
            parts.append(f"Covers: {joined}.")

        return " ".join(parts)[:500] if parts else f"Document: {topic}"

    @staticmethod
    def _derive_topic(source: str, pages: List[Dict[str, Any]]) -> str:
        """Derive a short topic name from the source path or first page text."""
        if source:
            stem = re.sub(r"[^a-zA-Z0-9_\- ]+", " ", source.rsplit("/", 1)[-1])
            stem = re.sub(r"\.(pdf|PDF)$", "", stem).strip()
            if stem:
                return stem
        if pages:
            first_text = str(pages[0].get("text") or "").strip()
            first_line = first_text.splitlines()[0][:80].strip() if first_text else ""
            if first_line:
                return first_line
        return "Unknown Document"

    @staticmethod
    def _deduplicate_list(items: List[str]) -> List[str]:
        seen: set = set()
        result: List[str] = []
        for item in items:
            norm = item.strip().lower()
            if norm and norm not in seen:
                seen.add(norm)
                result.append(item.strip())
        return result


if __name__ == "__main__":
    print("Running modules/document_ingestion/pdf_understanding.py")
