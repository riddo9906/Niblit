from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from modules.event_bus import EventBus as ModuleEventBus
from modules.governed_document_cognition import ExtractedDocument, GovernedDocumentCognition


class _StubRouter:
    def generate(self, prompt: str, context: str | None = None) -> str:  # noqa: ARG002
        return "Governed synthesis from RouterV2/LocalBrain pathway."


class _StubKnowledgeDB:
    def __init__(self) -> None:
        self.facts: list[tuple[str, object, list[str]]] = []

    def add_fact(self, key: str, value: object, tags: list[str] | None = None) -> None:
        self.facts.append((key, value, list(tags or [])))


class _StubCluster:
    def __init__(self) -> None:
        self.writes: list[tuple[str, str, dict]] = []

    def write_memory(self, text: str, *, memory_type: str = "semantic_memory", payload: dict | None = None) -> dict:
        self.writes.append((text, memory_type, dict(payload or {})))
        return {"stored": True, "memory_id": f"mem-{len(self.writes)}"}

    def compression_candidates(self) -> dict:
        return {"semantic_clusters": [], "governance_required": True}


def test_governed_document_cognition_ingests_and_resumes(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "architecture.pdf").write_bytes(b"%PDF-1.4 fake")
    checkpoint = tmp_path / "doc_checkpoint.json"
    collector = GovernedDocumentCognition(
        checkpoint_path=checkpoint,
        approved_roots=[str(tmp_path)],
    )
    cluster = _StubCluster()
    kb = _StubKnowledgeDB()

    with patch.object(
        collector,
        "_extract_pdf",
        return_value=ExtractedDocument(
            text="RuntimeRouterV2 and LocalBrain coordinate governed inference.",
            pages=1,
            backend="stub",
            needs_ocr=False,
        ),
    ), patch(
        "niblit_memory.governed_qdrant_memory.get_governed_qdrant_memory_cluster",
        return_value=cluster,
    ):
        first = collector.ingest_directory(
            directory=str(docs),
            router=_StubRouter(),
            knowledge_db=kb,
            runtime_id="runtime-test",
        )
        second = collector.ingest_directory(
            directory=str(docs),
            router=_StubRouter(),
            knowledge_db=kb,
            runtime_id="runtime-test",
        )

    assert first["success"] is True
    assert first["ingested"] == 1
    assert first["failed"] == 0
    assert second["ingested"] == 0
    assert second["skipped_unchanged"] == 1
    assert cluster.writes
    assert kb.facts
    assert checkpoint.exists()


def test_governed_document_cognition_emits_events(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "memory.pdf").write_bytes(b"%PDF-1.4 fake")
    collector = GovernedDocumentCognition(
        checkpoint_path=tmp_path / "checkpoint.json",
        approved_roots=[str(tmp_path)],
    )
    cluster = _StubCluster()
    module_bus = ModuleEventBus()
    captured: list[str] = []
    module_bus.subscribe_all(lambda event: captured.append(event.type))

    with patch.object(
        collector,
        "_extract_pdf",
        return_value=ExtractedDocument(
            text="KnowledgeDB and Qdrant memory authority are preserved.",
            pages=1,
            backend="stub",
            needs_ocr=False,
        ),
    ), patch(
        "modules.event_bus.get_event_bus",
        return_value=module_bus,
    ), patch(
        "niblit_memory.governed_qdrant_memory.get_governed_qdrant_memory_cluster",
        return_value=cluster,
    ):
        result = collector.ingest_directory(
            directory=str(docs),
            router=_StubRouter(),
            knowledge_db=_StubKnowledgeDB(),
            runtime_id="runtime-test",
        )

    assert result["success"] is True
    assert "document.ingestion.completed" in captured
    assert "memory.synthesis.created" in captured
    assert "document.ingestion.batch.completed" in captured
