from niblit_memory import FusedMemory
from niblit_memory.ingestion import KnowledgeIngestionService
from niblit_memory.knowledge_document import KnowledgeDocument, _normalize_url


def test_existing_pipeline_uses_governed_projection_for_new_duplicate_and_update(tmp_path, monkeypatch):
    from modules.memory_laboratory import context
    monkeypatch.setenv("NIBLIT_MEMORY_LAB_ENABLED", "1")
    calls = []
    class Gateway:
        def ingest(self, chunks, **kwargs):
            calls.append((chunks, kwargs))
            return {"verified": True}
    monkeypatch.setattr(context, "runtime_gateway", lambda: Gateway())
    fused = FusedMemory(sqlite_path=str(tmp_path / "fused.sqlite"), vector_store=object())
    service = KnowledgeIngestionService(fused_memory=fused, enable_legacy_projection=False)
    doc = KnowledgeDocument(content="Original source", source_uri="https://example.com/a", canonical_uri="https://example.com/a")
    try:
        first = service.ingest(doc)
        second = service.ingest(doc)
        correction = KnowledgeDocument(content="Corrected source", source_uri=doc.source_uri, canonical_uri=doc.canonical_uri)
        third = service.ingest(correction)
        assert first.embedding_status == second.embedding_status == third.embedding_status == "embedded_verified_qdrant"
        assert second.duplicate and third.updated
        assert len(calls) == 3
        assert doc.id != correction.id
        assert fused.find_knowledge_document(canonical_uri=doc.canonical_uri)["content"] == "Corrected source"
    finally:
        fused.close()


def test_denied_projection_never_falls_back_to_legacy_vector_write(tmp_path, monkeypatch):
    from modules.memory_laboratory import context
    monkeypatch.setenv("NIBLIT_MEMORY_LAB_ENABLED", "1")
    class Gateway:
        def ingest(self, *args, **kwargs):
            raise PermissionError("denied")
    monkeypatch.setattr(context, "runtime_gateway", lambda: Gateway())
    fused = FusedMemory(sqlite_path=str(tmp_path / "fused.sqlite"), vector_store=object())
    service = KnowledgeIngestionService(fused_memory=fused, enable_legacy_projection=False)
    try:
        result = service.ingest(KnowledgeDocument(content="New source", source_uri="https://example.com/a"))
        assert result.embedding_status == "failed_memory_authorization_required"
    finally:
        fused.close()


def test_deduplication_is_exact_not_the_latest_event(tmp_path):
    fused = FusedMemory(sqlite_path=str(tmp_path / "fused.sqlite"), vector_store=object())
    service = KnowledgeIngestionService(fused_memory=fused, enable_legacy_projection=False, enable_embedding=False)
    try:
        a = KnowledgeDocument(content="Alpha", source_uri="https://example.com/a", canonical_uri="https://example.com/a")
        b = KnowledgeDocument(content="Beta", source_uri="https://example.com/b", canonical_uri="https://example.com/b")
        assert service.ingest(a).stored
        assert not service.ingest(b).duplicate
        assert service.ingest(a).duplicate
        assert a.content_hash != b.content_hash
    finally:
        fused.close()


def test_url_normalizer_handles_ipv6_and_nondefault_scheme_port():
    assert _normalize_url("https://EXAMPLE.com:80/path") == "https://example.com:80/path"
    assert _normalize_url("http://[::1]:8080/path") == "http://[::1]:8080/path"


def test_failed_canonical_write_is_not_reported_as_stored(tmp_path):
    fused = FusedMemory(sqlite_path=str(tmp_path / "fused.sqlite"), vector_store=object())
    service = KnowledgeIngestionService(fused_memory=fused, enable_legacy_projection=False, enable_embedding=False)
    fused.log_event = lambda *args: None  # Existing failure-swallowing legacy contract.
    try:
        result = service.ingest(KnowledgeDocument(content="Must be durable", source_uri="https://example.com/new"))
        assert not result.stored and "storage_failed" in result.errors
    finally:
        fused.close()
