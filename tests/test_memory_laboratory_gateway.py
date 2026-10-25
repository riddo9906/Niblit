import json

import pytest

from modules.memory_laboratory.gateway import MemoryGateway
from modules.memory_laboratory.setup import Config


class Backend:
    def __init__(self):
        self.points = {}
        self.embedder = self
        self.offline = False

    def embed(self, text, **kwargs):
        return [0.5, 0.4, 0.3]

    def close(self):
        pass

    def request(self, method, path, **kwargs):
        if self.offline:
            raise ConnectionError("offline")
        body = kwargs.get("json", {})
        if method == "PUT":
            self.points.update({p["id"]: p for p in body["points"]})
            return True
        if path.endswith("/points"):
            return [self.points[key] for key in body["ids"]]
        if "/payload" in path:
            for key in body["points"]:
                self.points[key]["payload"].update(body["payload"])
            return True
        if "/delete" in path:
            for key in body["points"]:
                self.points.pop(key, None)
            return True
        return {"points": list(self.points.values())}


def gateway(tmp_path, backend, allow=True, revision=None):
    config = Config(url="http://127.0.0.1:6333", **({"revision": revision} if revision else {}))
    return MemoryGateway(config, tmp_path / "ledger.sqlite3", setup=backend,
                         authorize=lambda *args: allow)


def ingest(g, text="The Aurora test code is amber-72.", scope="test", actor="operator"):
    return g.ingest([(text, "fixture.txt:1")], source="fixture.txt",
                    namespace=scope, principal=actor)


def recall(g, scope="test", actor="operator"):
    return g.retrieve("Aurora amber", namespace=scope, principal=actor)


def test_restart_and_idempotence(tmp_path):
    backend = Backend()
    g = gateway(tmp_path, backend)
    first = ingest(g)
    assert first == ingest(g)
    assert len(backend.points) == 1
    reopened = gateway(tmp_path, backend)
    assert recall(reopened)["results"][0]["citation"] == "fixture.txt:1"
    with reopened.db() as db:
        assert db.execute("SELECT count(*) FROM records").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM audit").fetchone()[0] >= 2


def test_namespace_and_principal_isolation_even_if_backend_ignores_filter(tmp_path):
    g = gateway(tmp_path, Backend())
    ingest(g)
    assert not recall(g, scope="other")["results"]
    assert not recall(g, actor="stranger")["results"]


def test_governance_denies_read_and_write(tmp_path):
    g = gateway(tmp_path, Backend(), allow=False)
    with pytest.raises(PermissionError):
        ingest(g)
    with pytest.raises(PermissionError):
        recall(g)


def test_outage_preserves_evidence_and_reports_lexical_degradation(tmp_path):
    backend = Backend()
    g = gateway(tmp_path, backend)
    ingest(g)
    backend.offline = True
    result = recall(g)
    assert result["results"] and result["mode"] == "lexical_degraded"
    with pytest.raises(ConnectionError):
        ingest(g, "A new Aurora source version.")
    assert "amber-72" in recall(g)["results"][0]["content"]
    with g.db() as db:
        assert db.execute("SELECT count(*) FROM records WHERE projection='pending'").fetchone()[0] == 1


def test_correction_and_deletion_keep_original_evidence(tmp_path):
    backend = Backend()
    g = gateway(tmp_path, backend)
    ingest(g)
    ingest(g, "Correction: Aurora test code is amber-73.")
    assert any(p["payload"]["lifecycle"] == "superseded" for p in backend.points.values())
    assert len(recall(g)["results"]) == 1
    assert "amber-73" in recall(g)["results"][0]["content"]
    g.delete_source("fixture.txt", namespace="test", principal="operator")
    assert not recall(g)["results"]
    assert not backend.points
    with g.db() as db:
        rows = db.execute("SELECT payload FROM records").fetchall()
        assert len(rows) == 2
        assert all(json.loads(r[0])["lifecycle"] == "deleted" for r in rows)


def test_delete_during_outage_revokes_retrieval_immediately(tmp_path):
    backend = Backend()
    g = gateway(tmp_path, backend)
    ingest(g)
    backend.offline = True
    with pytest.raises(ConnectionError):
        g.delete_source("fixture.txt", namespace="test", principal="operator")
    assert not recall(g)["results"]


def test_same_dimension_model_change_needs_migration(tmp_path):
    backend = Backend()
    ingest(gateway(tmp_path, backend))
    changed = gateway(tmp_path, backend, revision="b" * 40)
    result = recall(changed)
    assert "embedding_migration_required" in result["issues"]
    assert result["results"]  # only authoritative lexical fallback


def test_credentials_never_ingested(tmp_path):
    backend = Backend()
    with pytest.raises(PermissionError):
        ingest(gateway(tmp_path, backend), "secret hf_" + "A" * 32)
    assert not backend.points


def test_partial_readback_is_not_success(tmp_path):
    backend = Backend()
    original = backend.request
    backend.request = lambda method, path, **kwargs: ([] if method == "POST" and path.endswith("/points")
                                                       else original(method, path, **kwargs))
    g = gateway(tmp_path, backend)
    with pytest.raises(ValueError):
        ingest(g)
    assert not recall(g)["results"]
