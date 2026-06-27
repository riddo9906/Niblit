import sys
import types

import modules.memory_graph as memory_graph_module
import modules.reasoning_engine as reasoning_engine_module
from core.runtime_manager import RuntimeManager
from modules.document_ingestion.pdf_reader import PDFReader
from modules.knowledge_comprehension import KnowledgeComprehension
from modules.memory_graph import get_memory_graph
from modules.reasoning_engine import get_reasoning_engine


def _install_fake_pypdf(monkeypatch, page_texts):
    fake_module = types.ModuleType("pypdf")

    class _FakePage:
        def __init__(self, text):
            self._text = text

        def extract_text(self):
            return self._text

    class _FakePdfReader:
        def __init__(self, _path):
            self.pages = [_FakePage(text) for text in page_texts]

    fake_module.PdfReader = _FakePdfReader
    monkeypatch.setitem(sys.modules, "pypdf", fake_module)


def _install_fake_pdfminer(monkeypatch, extract_text_value):
    pdfminer_module = types.ModuleType("pdfminer")
    high_level_module = types.ModuleType("pdfminer.high_level")

    def _fake_extract_text(_path):
        return extract_text_value

    high_level_module.extract_text = _fake_extract_text
    monkeypatch.setitem(sys.modules, "pdfminer", pdfminer_module)
    monkeypatch.setitem(sys.modules, "pdfminer.high_level", high_level_module)


def test_pdf_reader_reads_pages_and_chunks_with_pypdf(tmp_path, monkeypatch):
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"fake")
    _install_fake_pypdf(monkeypatch, ["alpha " * 700, "beta " * 700])

    result = PDFReader().read(str(pdf_path))

    assert result["source"] == str(pdf_path.resolve())
    assert [page["page"] for page in result["pages"]] == [1, 2]
    assert len(result["chunks"]) >= 1
    assert result["chunks"][0]["chunk_id"] == 1


def test_pdf_reader_falls_back_to_pdfminer(tmp_path, monkeypatch):
    pdf_path = tmp_path / "fallback.pdf"
    pdf_path.write_bytes(b"fake")
    monkeypatch.setitem(sys.modules, "pypdf", None)
    _install_fake_pdfminer(monkeypatch, "page one text\fpage two text")

    result = PDFReader().read(str(pdf_path))

    assert len(result["pages"]) == 2
    assert result["pages"][0]["text"] == "page one text"
    assert result["pages"][1]["text"] == "page two text"


class _FakeKnowledgeDB:
    def __init__(self):
        self.records = []

    def add_fact(self, key, value, tags=None):
        self.records.append({"key": key, "value": value, "tags": tags or []})


def test_knowledge_comprehension_ingest_document_preserves_chunks():
    db = _FakeKnowledgeDB()
    kc = KnowledgeComprehension(knowledge_db=db)
    payload = {
        "source": "/tmp/example.pdf",
        "pages": [{"page": 1, "text": "hello page"}],
        "chunks": [{"chunk_id": 1, "text": "chunk one"}, {"chunk_id": 2, "text": "chunk two"}],
    }

    result = kc.ingest_document(payload, source_tag="user_pdf")

    assert result["status"] == "ingested"
    assert result["chunks_ingested"] == 2
    assert any("document_ingestion" in record["tags"] for record in db.records)
    assert sum(1 for record in db.records if "document_chunk" in record["tags"]) == 2


def test_reasoning_engine_uses_shared_memory_graph_when_facts_are_empty(tmp_path):
    old_graph_singleton = getattr(memory_graph_module, "_graph_singleton", None)
    old_reasoning_instance = getattr(reasoning_engine_module, "_INSTANCE", None)
    try:
        setattr(memory_graph_module, "_graph_singleton", None)
        setattr(reasoning_engine_module, "_INSTANCE", None)

        graph = get_memory_graph(persist_path=str(tmp_path / "memory_graph.pkl"))
        graph.add("snip:1", "The router manages traffic", embedding=[1.0, 0.0])

        engine = get_reasoning_engine(knowledge_db=_FakeKnowledgeDB())
        engine.memory_graph = graph

        cot = engine.chain_of_thought("What does the router manage?", facts=[])

        assert cot.source == "graph"
        assert "Insufficient knowledge graph data" not in cot.conclusion
        assert cot.confidence >= 0.0
    finally:
        setattr(memory_graph_module, "_graph_singleton", old_graph_singleton)
        setattr(reasoning_engine_module, "_INSTANCE", old_reasoning_instance)


def test_runtime_manager_registry_exposes_shared_services():
    runtime = RuntimeManager()

    knowledge_db = runtime.get_knowledge_db()
    memory_graph = runtime.get_memory_graph()
    reasoning_engine = runtime.get_reasoning_engine()
    knowledge_comprehension = runtime.get_knowledge_comprehension()

    assert runtime.get_knowledge_db() is knowledge_db
    assert runtime.get_memory_graph() is memory_graph
    assert runtime.get_reasoning_engine() is reasoning_engine
    assert runtime.get_knowledge_comprehension() is knowledge_comprehension
    assert reasoning_engine.db is knowledge_db
    assert knowledge_comprehension.knowledge_db is knowledge_db
    assert knowledge_comprehension.memory_graph is memory_graph

    diagnostics = runtime.get_diagnostics()
    assert diagnostics["runtime_id"] == runtime.runtime_id
    assert "knowledge_db" in diagnostics["services"]
    assert diagnostics["services"]["knowledge_db"]["status"] == "ready"


def test_runtime_manager_exposes_lifecycle_state_and_extension_points():
    runtime = RuntimeManager()
    runtime.register_extension_point("memory_manager", {"status": "planned"})

    diagnostics = runtime.get_diagnostics()

    assert diagnostics["runtime_state"] == "ready"
    assert diagnostics["service_lifecycle_states"]["knowledge_db"] == "ready"
    assert diagnostics["extension_points"]["memory_manager"] == {"status": "planned"}
    assert runtime.get_extension_point("memory_manager") == {"status": "planned"}


def test_runtime_manager_reports_architecture_snapshot():
    runtime = RuntimeManager()
    runtime.register_extension_point("memory_manager", {"status": "planned"})

    report = runtime.get_runtime_report()

    assert report["runtime_state"] == "ready"
    assert report["lifecycle_model"]["current"] == "ready"
    assert report["boot_sequence"][0]["name"] == "runtime_manager_init"
    assert report["event_bridge"]["module_bridge_installed"] is True
    assert report["extension_points"]["memory_manager"] == {"status": "planned"}
