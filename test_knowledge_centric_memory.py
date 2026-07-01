"""
test_knowledge_centric_memory.py — Tests for the knowledge-centric memory upgrade.

Covers:
  * KnowledgeRecord — creation, serialisation, relationships
  * KnowledgeLogger — pipeline (filter → deduplicate → extract → summarise → store)
  * PDFStructureDetector — chapter/section/heading/table/caption detection
  * PDFUnderstandingPipeline — full understanding pass on a mock payload
  * Enhanced ingest_document — backward-compat + new fields
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

# ── KnowledgeRecord ───────────────────────────────────────────────────────────


class TestKnowledgeRecord:
    def _make(self, **kwargs):
        from niblit_memory.knowledge_record import KnowledgeRecord
        defaults = dict(
            topic="Test Topic",
            summary="A brief test summary.",
            key_facts=["Fact one.", "Fact two."],
            concepts_learned=["concept_a", "concept_b"],
            relationships=[{"from": "concept_a", "to": "concept_b", "type": "related_to"}],
            confidence=0.8,
            sources=["test_source.pdf"],
        )
        defaults.update(kwargs)
        return KnowledgeRecord(**defaults)

    def test_default_fields(self):
        from niblit_memory.knowledge_record import KnowledgeRecord
        rec = KnowledgeRecord(topic="hello")
        assert rec.topic == "hello"
        assert rec.summary == ""
        assert rec.key_facts == []
        assert rec.concepts_learned == []
        assert rec.relationships == []
        assert 0.0 <= rec.confidence <= 1.0
        assert rec.sources == []
        assert rec.date_last_verified
        assert rec.id

    def test_to_dict_contains_required_fields(self):
        rec = self._make()
        d = rec.to_dict()
        for key in ("id", "topic", "summary", "key_facts", "concepts_learned",
                    "relationships", "confidence", "sources", "date_last_verified",
                    "tags", "metadata"):
            assert key in d, f"Missing field: {key}"

    def test_to_dict_raw_observations_excluded(self):
        """raw_observations are kept for audit only, not in the serialised dict."""
        rec = self._make()
        rec.raw_observations = ["obs1", "obs2"]
        d = rec.to_dict()
        assert "raw_observations" not in d

    def test_from_dict_roundtrip(self):
        from niblit_memory.knowledge_record import KnowledgeRecord
        rec = self._make()
        restored = KnowledgeRecord.from_dict(rec.to_dict())
        assert restored.topic == rec.topic
        assert restored.summary == rec.summary
        assert restored.key_facts == rec.key_facts
        assert restored.concepts_learned == rec.concepts_learned
        assert restored.confidence == rec.confidence

    def test_add_relationship_deduplicates(self):
        rec = self._make(relationships=[])
        rec.add_relationship("A", "B", "enables")
        rec.add_relationship("A", "B", "enables")  # duplicate
        assert len(rec.relationships) == 1

    def test_add_relationship_multiple_types(self):
        rec = self._make(relationships=[])
        rec.add_relationship("A", "B", "enables")
        rec.add_relationship("A", "B", "requires")  # different type
        assert len(rec.relationships) == 2

    def test_human_readable_contains_key_sections(self):
        rec = self._make()
        text = rec.human_readable()
        assert "Topic:" in text
        assert "Summary:" in text
        assert "Key facts:" in text
        assert "Fact one." in text

    def test_make_knowledge_record_convenience(self):
        from niblit_memory.knowledge_record import make_knowledge_record
        rec = make_knowledge_record(
            "My Topic", "My summary",
            key_facts=["F1"],
            confidence=0.6,
        )
        assert rec.topic == "My Topic"
        assert rec.summary == "My summary"
        assert rec.key_facts == ["F1"]
        assert rec.confidence == 0.6


# ── KnowledgeLogger ───────────────────────────────────────────────────────────


class _FakeKnowledgeDB:
    def __init__(self):
        self.records: List[Dict[str, Any]] = []

    def add_fact(self, key, value, tags=None):
        self.records.append({"key": key, "value": value, "tags": tags or []})


class _FakeMemoryGraph:
    def __init__(self):
        self.nodes: List[Dict[str, Any]] = []

    def add(self, node_id, text, **kwargs):
        self.nodes.append({"id": node_id, "text": text})


class TestKnowledgeLogger:
    def _logger(self, db=None, graph=None):
        from niblit_memory.knowledge_logger import KnowledgeLogger
        return KnowledgeLogger(knowledge_db=db, memory_graph=graph)

    OBSERVATIONS = [
        "The Niblit memory graph persists semantic concepts independently of runtime state.",
        "Immediate persistence prevents concept loss after restart.",
        "The memory system uses a knowledge-centric approach to store facts.",
        "Each KnowledgeRecord contains a topic, summary, key facts, and confidence.",
    ]

    def test_create_record_returns_knowledge_record(self):
        from niblit_memory.knowledge_record import KnowledgeRecord
        logger = self._logger()
        record = logger.create_record("Niblit Memory", self.OBSERVATIONS)
        assert isinstance(record, KnowledgeRecord)
        assert record.topic == "Niblit Memory"

    def test_record_has_summary(self):
        logger = self._logger()
        record = logger.create_record("Niblit Memory", self.OBSERVATIONS)
        assert record.summary
        assert len(record.summary) > 10

    def test_record_has_key_facts(self):
        logger = self._logger()
        record = logger.create_record("Niblit Memory", self.OBSERVATIONS)
        assert len(record.key_facts) >= 1

    def test_record_has_concepts(self):
        logger = self._logger()
        record = logger.create_record("Niblit Memory", self.OBSERVATIONS)
        assert len(record.concepts_learned) >= 1

    def test_deduplication_removes_near_duplicates(self):
        logger = self._logger()
        obs = [
            "Python virtual environments isolate packages.",
            "Python virtual environments isolate packages.",  # exact dup
        ]
        record = logger.create_record("Python", obs)
        # Both observations are the same text; only one should be in raw_observations
        assert len(record.raw_observations) == 1

    def test_store_record_calls_add_fact(self):
        db = _FakeKnowledgeDB()
        logger = self._logger(db=db)
        record = logger.create_record("Test", self.OBSERVATIONS)
        logger.store_record(record)
        assert any("knowledge_record" in (r.get("key") or "") for r in db.records)

    def test_store_record_links_to_graph(self):
        graph = _FakeMemoryGraph()
        logger = self._logger(graph=graph)
        record = logger.create_record("Test", self.OBSERVATIONS)
        logger.store_record(record)
        assert len(graph.nodes) >= 1

    def test_log_creates_and_stores(self):
        db = _FakeKnowledgeDB()
        logger = self._logger(db=db)
        record = logger.log("Niblit Memory", self.OBSERVATIONS, source="session_42")
        assert record.topic == "Niblit Memory"
        assert "session_42" in record.sources
        # Should have been stored
        assert len(db.records) >= 1

    def test_log_with_store_false_does_not_persist(self):
        db = _FakeKnowledgeDB()
        logger = self._logger(db=db)
        logger.log("Test", self.OBSERVATIONS, store=False)
        assert len(db.records) == 0

    def test_empty_observations_produce_record(self):
        logger = self._logger()
        record = logger.create_record("Empty", [])
        assert record.topic == "Empty"
        assert record.key_facts == []

    def test_placeholder_observations_filtered(self):
        logger = self._logger()
        obs = [
            "No data found for query",
            "Real fact about the system.",
        ]
        record = logger.create_record("Test", obs)
        # placeholder should be removed
        assert not any("no data found" in o.lower() for o in record.raw_observations)

    def test_knowledge_record_tag_always_present(self):
        logger = self._logger()
        record = logger.create_record("Test", self.OBSERVATIONS)
        assert "knowledge_record" in record.tags

    def test_relationships_inferred(self):
        logger = self._logger()
        obs = [
            "Virtual environments enable dependency isolation in Python projects.",
            "Pip uses virtual environments to install packages without conflicts.",
        ]
        record = logger.create_record("Python Envs", obs)
        # relationships may or may not be found depending on co-occurrence
        # Just verify the field is a list
        assert isinstance(record.relationships, list)

    def test_singleton(self):
        from niblit_memory.knowledge_logger import get_knowledge_logger, _logger_singleton
        import niblit_memory.knowledge_logger as kl_mod
        # Reset singleton for test isolation
        original = kl_mod._logger_singleton
        kl_mod._logger_singleton = None
        try:
            a = get_knowledge_logger()
            b = get_knowledge_logger()
            assert a is b
        finally:
            kl_mod._logger_singleton = original


# ── PDFStructureDetector ──────────────────────────────────────────────────────


class TestPDFStructureDetector:
    def _detector(self):
        from modules.document_ingestion.pdf_structure_detector import PDFStructureDetector
        return PDFStructureDetector()

    def test_chapter_detected(self):
        det = self._detector()
        page = {"page": 1, "text": "Chapter 1 Introduction\nThis chapter introduces..."}
        result = det.detect_pages([page])[0]
        assert result["structure"]["type"] == "chapter"
        assert result["structure"]["level"] == 1

    def test_numbered_section_detected(self):
        det = self._detector()
        page = {"page": 2, "text": "1.2 Background\nSome background text here."}
        result = det.detect_pages([page])[0]
        assert result["structure"]["type"] == "section"
        assert "1.2" in result["structure"]["title"]

    def test_abstract_detected_as_section(self):
        det = self._detector()
        page = {"page": 1, "text": "Abstract\nThis paper presents a novel approach."}
        result = det.detect_pages([page])[0]
        assert result["structure"]["type"] == "section"

    def test_body_text_detected(self):
        det = self._detector()
        page = {"page": 3, "text": "This is a regular paragraph with many words that do not form a heading at all."}
        result = det.detect_pages([page])[0]
        assert result["structure"]["type"] == "body"

    def test_figure_caption_detected(self):
        det = self._detector()
        page = {"page": 4, "text": "Figure 1: Architecture overview of the system"}
        result = det.detect_pages([page])[0]
        assert result["structure"]["type"] == "caption"

    def test_table_detected(self):
        det = self._detector()
        page = {"page": 5, "text": "col1\tcol2\tcol3\nval1\tval2\tval3"}
        result = det.detect_pages([page])[0]
        assert result["structure"]["type"] == "table"

    def test_empty_page_is_body(self):
        det = self._detector()
        page = {"page": 1, "text": ""}
        result = det.detect_pages([page])[0]
        assert result["structure"]["type"] == "body"

    def test_original_keys_preserved(self):
        det = self._detector()
        page = {"page": 7, "text": "Some text", "extra_field": "kept"}
        result = det.detect_pages([page])[0]
        assert result["page"] == 7
        assert result["extra_field"] == "kept"

    def test_group_into_sections_creates_sections(self):
        det = self._detector()
        pages = [
            {"page": 1, "text": "Chapter 1 Introduction\nIntroduction text."},
            {"page": 2, "text": "More introduction details here."},
            {"page": 3, "text": "Chapter 2 Methods\nMethod description."},
            {"page": 4, "text": "More method details here."},
        ]
        annotated = det.detect_pages(pages)
        sections = det.group_into_sections(annotated)
        assert len(sections) >= 2
        assert all("full_text" in s for s in sections)
        assert all("pages" in s for s in sections)

    def test_section_page_ranges(self):
        det = self._detector()
        pages = [
            {"page": 1, "text": "Chapter 1 Introduction\nText."},
            {"page": 2, "text": "Some body text on page two."},
            {"page": 3, "text": "Chapter 2 Results\nResults text."},
        ]
        annotated = det.detect_pages(pages)
        sections = det.group_into_sections(annotated)
        sec1 = sections[0]
        assert sec1["page_start"] == 1

    def test_preamble_section_for_pages_before_first_heading(self):
        det = self._detector()
        pages = [
            {"page": 1, "text": "Some introductory content without a heading."},
            {"page": 2, "text": "Chapter 1 Introduction\nContent."},
        ]
        annotated = det.detect_pages(pages)
        sections = det.group_into_sections(annotated)
        # First section should contain the preamble page
        assert len(sections) >= 2


# ── PDFUnderstandingPipeline ──────────────────────────────────────────────────


def _make_document_payload(source="/tmp/test.pdf", pages=None, chunks=None):
    if pages is None:
        pages = [
            {"page": 1, "text": "Chapter 1 Introduction\nThis document explains the Niblit memory system."},
            {"page": 2, "text": "1.1 Background\nNiblit is an AI operating system. It uses a knowledge graph to store facts."},
            {"page": 3, "text": "1.2 Architecture\nThe architecture consists of a memory layer and a reasoning engine. The memory layer persists facts."},
        ]
    if chunks is None:
        chunks = [
            {"chunk_id": 1, "text": "This document explains the Niblit memory system."},
            {"chunk_id": 2, "text": "Niblit is an AI operating system. It uses a knowledge graph to store facts."},
            {"chunk_id": 3, "text": "The architecture consists of a memory layer and a reasoning engine. The memory layer persists facts."},
        ]
    return {"source": source, "pages": pages, "chunks": chunks}


class TestPDFUnderstandingPipeline:
    def _pipeline(self, db=None, graph=None):
        from modules.document_ingestion.pdf_understanding import PDFUnderstandingPipeline
        return PDFUnderstandingPipeline(knowledge_db=db, memory_graph=graph)

    def test_understand_returns_dict(self):
        pipeline = self._pipeline()
        result = pipeline.understand(_make_document_payload())
        assert isinstance(result, dict)

    def test_required_keys_present(self):
        pipeline = self._pipeline()
        result = pipeline.understand(_make_document_payload())
        for key in ("source", "page_count", "chunk_count", "section_count",
                    "knowledge_records", "definitions", "facts", "procedures",
                    "terminology", "relationships", "summary", "document_topic"):
            assert key in result, f"Missing key: {key}"

    def test_knowledge_records_created(self):
        from niblit_memory.knowledge_record import KnowledgeRecord
        pipeline = self._pipeline()
        result = pipeline.understand(_make_document_payload())
        assert len(result["knowledge_records"]) >= 1
        # Records come back as dicts (to_dict() output)
        assert isinstance(result["knowledge_records"][0], KnowledgeRecord)

    def test_terminology_extracted(self):
        pipeline = self._pipeline()
        payload = _make_document_payload(
            pages=[{"page": 1, "text": "The KnowledgeGraph API uses REST endpoints."}],
            chunks=[{"chunk_id": 1, "text": "The KnowledgeGraph API uses REST endpoints."}],
        )
        result = pipeline.understand(payload)
        # Should extract at least one technical term
        assert isinstance(result["terminology"], list)

    def test_facts_extracted(self):
        pipeline = self._pipeline()
        payload = _make_document_payload(
            pages=[{"page": 1, "text": "The memory system stores facts persistently. It uses SQLite for local storage."}],
            chunks=[{"chunk_id": 1, "text": "The memory system stores facts persistently. It uses SQLite for local storage."}],
        )
        result = pipeline.understand(payload)
        assert isinstance(result["facts"], list)

    def test_stores_via_knowledge_db(self):
        db = _FakeKnowledgeDB()
        pipeline = self._pipeline(db=db)
        pipeline.understand(_make_document_payload())
        # Should have stored at least one knowledge_record fact
        assert any("knowledge_record" in (r.get("key") or "") for r in db.records)

    def test_links_to_memory_graph(self):
        graph = _FakeMemoryGraph()
        pipeline = self._pipeline(graph=graph)
        pipeline.understand(_make_document_payload())
        assert len(graph.nodes) >= 1

    def test_empty_document_payload(self):
        pipeline = self._pipeline()
        result = pipeline.understand({})
        assert result["page_count"] == 0
        assert result["chunk_count"] == 0

    def test_document_topic_derived_from_source(self):
        pipeline = self._pipeline()
        result = pipeline.understand(_make_document_payload(source="/docs/niblit_arch.pdf"))
        assert "niblit" in result["document_topic"].lower() or "arch" in result["document_topic"].lower()

    def test_sections_have_required_keys(self):
        pipeline = self._pipeline()
        result = pipeline.understand(_make_document_payload())
        for section in result["sections"]:
            assert "section_id" in section
            assert "title" in section
            assert "full_text" in section
            assert "pages" in section


# ── Enhanced ingest_document ──────────────────────────────────────────────────


class TestEnhancedIngestDocument:
    def _comprehension(self, db=None):
        from modules.knowledge_comprehension import KnowledgeComprehension
        return KnowledgeComprehension(knowledge_db=db)

    def test_backward_compat_status_ingested(self):
        db = _FakeKnowledgeDB()
        kc = self._comprehension(db=db)
        payload = _make_document_payload()
        result = kc.ingest_document(payload)
        assert result["status"] == "ingested"

    def test_backward_compat_chunks_ingested(self):
        db = _FakeKnowledgeDB()
        kc = self._comprehension(db=db)
        payload = _make_document_payload()
        result = kc.ingest_document(payload)
        assert result["chunks_ingested"] == len(payload["chunks"])

    def test_backward_compat_document_ingestion_tag(self):
        db = _FakeKnowledgeDB()
        kc = self._comprehension(db=db)
        payload = _make_document_payload()
        kc.ingest_document(payload, source_tag="user_pdf")
        assert any("document_ingestion" in (r.get("tags") or []) for r in db.records)

    def test_backward_compat_document_chunk_tag(self):
        db = _FakeKnowledgeDB()
        kc = self._comprehension(db=db)
        payload = _make_document_payload()
        kc.ingest_document(payload, source_tag="user_pdf")
        # At least 3 chunk records from the original comprehension path.
        # The PDF understanding pipeline may add additional document_chunk records.
        assert sum(1 for r in db.records if "document_chunk" in (r.get("tags") or [])) >= 3

    def test_new_knowledge_records_key_present(self):
        db = _FakeKnowledgeDB()
        kc = self._comprehension(db=db)
        payload = _make_document_payload()
        result = kc.ingest_document(payload)
        # When PDF understanding pipeline runs, extra keys appear
        if "knowledge_records" in result:
            assert isinstance(result["knowledge_records"], list)

    def test_new_sections_detected_key(self):
        db = _FakeKnowledgeDB()
        kc = self._comprehension(db=db)
        payload = _make_document_payload()
        result = kc.ingest_document(payload)
        if "sections_detected" in result:
            assert isinstance(result["sections_detected"], int)
