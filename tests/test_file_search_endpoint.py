"""Tests for the implemented /api/file/search endpoint (Phase 5D)."""
import pytest


def _client():
    testclient = pytest.importorskip("fastapi.testclient")
    import server as server_module
    return testclient.TestClient(server_module.app)


def test_file_search_returns_real_matches(tmp_path):
    client = _client()
    target = tmp_path / "sample.py"
    target.write_text("alpha one\nbeta two\nalpha three\n", encoding="utf-8")
    resp = client.post("/api/file/search",
                       json={"path": str(target), "query": "alpha"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    assert [m["line_number"] for m in body["matches"]] == [1, 3]
    assert body["truncated"] is False


def test_file_search_requires_query(tmp_path):
    client = _client()
    target = tmp_path / "sample.py"
    target.write_text("data\n", encoding="utf-8")
    resp = client.post("/api/file/search",
                       json={"path": str(target), "query": "  "})
    assert resp.status_code == 200
    assert resp.json()["error"] == "query is required"


def test_file_search_rejects_missing_file():
    client = _client()
    resp = client.post("/api/file/search",
                       json={"path": "does/not/exist.py", "query": "x"})
    assert resp.json()["error"] == "File not found"


def test_file_search_rejects_binary(tmp_path):
    client = _client()
    target = tmp_path / "blob.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\n")
    resp = client.post("/api/file/search",
                       json={"path": str(target), "query": "x"})
    assert resp.json()["error"] == "Cannot search binary files"
