import sys
import types

from modules.document_ingestion.pdf_reader import PDFReader
from modules.knowledge_comprehension import KnowledgeComprehension


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
    monkeypatch.delitem(sys.modules, "pypdf", raising=False)
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
