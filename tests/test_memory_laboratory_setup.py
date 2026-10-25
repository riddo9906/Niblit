"""Non-destructive setup contract tests. Mock transport is NOT live acceptance."""
import hashlib
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from modules.memory_laboratory.contracts import MemoryRecord
from modules.memory_laboratory.setup import Config, INDEXES, QdrantSetup, validate_vector


class Embedder:
    def embed(self, text):
        return [0.2, 0.3, 0.4]


class Server:
    def __init__(self):
        self.collections = {}
        self.points = {}
        self.calls = []
        self.version = "1.18.0"

    def __call__(self, req):
        import json
        method, path = req.method, req.url.path
        self.calls.append((method, path))
        body = json.loads(req.content) if req.content else {}
        if path == "/":
            return httpx.Response(200, json={"version": self.version})
        if path == "/collections":
            return httpx.Response(200, json={"result": {"collections": []}})
        parts = path.split("/")
        name = parts[2]
        result = True
        if len(parts) == 3:
            if method == "PUT":
                self.collections[name] = {"config": {"params": body}, "payload_schema": {}}
            elif name not in self.collections:
                return httpx.Response(404, json={"status": "not found"})
            else:
                result = self.collections[name]
        elif parts[3] == "index":
            self.collections[name]["payload_schema"][body["field_name"]] = {"data_type": body["field_schema"]}
        elif parts[3] == "points":
            if method == "PUT":
                self.points.update({x["id"]: x for x in body["points"]})
            elif method == "GET":
                result = self.points[parts[4]]
            else:
                for key in body["points"]:
                    self.points.pop(key, None)
        return httpx.Response(200, json={"result": result})


def setup(server):
    config = Config(url="http://127.0.0.1:6333")
    client = httpx.Client(base_url=config.url, transport=httpx.MockTransport(server))
    return QdrantSetup(config, client=client, embedder=Embedder())


def test_dry_run_is_read_only():
    server = Server()
    result = setup(server).run()
    assert not result["ready"]
    assert len(result["collections"]) == 4
    assert all(method == "GET" for method, _ in server.calls)
    assert not server.collections


def test_apply_adds_versioned_collections_and_indexes_verifies_permissions():
    server = Server()
    service = setup(server)
    first = service.run(apply=True)
    assert first["ready"] and first["write_permissions_verified"]
    assert len(server.collections) == 4
    assert all(len(v["payload_schema"]) == len(INDEXES) for v in server.collections.values())
    assert not server.points  # only its own probe removed
    server.calls.clear()
    second = service.run(apply=True)
    assert second["ready"]
    assert not any(method == "DELETE" for method, _ in server.calls)
    assert not any(method == "PUT" and len(path.split("/")) == 3 for method, path in server.calls)


def test_schema_mismatch_never_recreates_populated_collection():
    server = Server()
    service = setup(server)
    name = service.config.collection("semantic", 3)
    server.collections[name] = {"points_count": 45, "config": {"params": {
        "vectors": {"size": 384, "distance": "Cosine"}}}, "payload_schema": {}}
    result = service.run(apply=True)
    assert not result["ready"]
    assert server.collections[name]["points_count"] == 45
    assert not any(method != "GET" and path == "/collections/" + name for method, path in server.calls)


def test_wrong_payload_index_requires_new_version():
    server = Server()
    service = setup(server)
    assert service.run(apply=True)["ready"]
    name = service.config.collection("semantic", 3)
    server.collections[name]["payload_schema"]["namespace"] = {"data_type": "integer"}
    assert not service.run(apply=True)["ready"]
    assert server.collections[name]["payload_schema"]["namespace"]["data_type"] == "integer"


@pytest.mark.parametrize("version", ["0.9.0", "1.9.9", "2.0.0", "unknown"])
def test_unsupported_server_does_not_mutate(version):
    server = Server()
    server.version = version
    assert not setup(server).run(apply=True)["ready"]
    assert not server.collections


def test_outage_does_not_disclose_credentials():
    def failure(req):
        raise httpx.ConnectError("secret key: do-not-print", request=req)
    result = setup(failure).run(apply=True)
    assert result["issues"] == ["ConnectError"]
    assert "do-not-print" not in str(result)


def test_auth_denial_and_redirect_never_claim_ready():
    for code in [401, 403, 302]:
        result = setup(lambda req: httpx.Response(code, json={})).run(apply=True)
        assert not result["ready"]
        assert not result["write_permissions_verified"]


@pytest.mark.parametrize("url,key", [("http://public.example", ""),
    ("https://public.example", ""), ("http://public.example", "key"),
    ("https://user:secret@example.com", "key")])
def test_unsafe_remote_configuration_rejected(url, key):
    with pytest.raises(ValueError):
        Config(url=url, api_key=key)


def test_embedding_identity_versions_same_dimension_models():
    a = Config(url="http://localhost:6333")
    b = Config(url=a.url, revision="a" * 40)
    assert a.collection("semantic", 384) != b.collection("semantic", 384)
    assert a.collection("semantic", 384) != a.collection("semantic", 768)
    assert "secret" not in repr(Config(url=a.url, api_key="secret"))


def test_private_profile_mapping_preserves_embedding_and_distance_settings():
    config = Config.from_values({"QDRANT_URL": "http://127.0.0.1:6333",
        "NIBLIT_MEMORY_DISTANCE": "Dot", "NIBLIT_MEMORY_ALLOW_MODEL_DOWNLOAD": "1",
        "NIBLIT_MEMORY_COLLECTION_PREFIX": "isolated_lab"})
    assert config.distance == "Dot" and config.allow_download
    assert config.collection("semantic", 384).startswith("isolated_lab_")


@pytest.mark.parametrize("vector", [[], [0, 0], [float("nan")], [float("inf")]])
def test_invalid_vectors_rejected(vector):
    with pytest.raises(ValueError):
        validate_vector(vector)


def record(**kwargs):
    content = "A permitted source fact."
    now = datetime.now(timezone.utc)
    fields = dict(memory_id=uuid4(), category="semantic", namespace="test",
        content=content, source_id="doc1", source_location="test.txt:1",
        source_type="text", provenance={"actor": "operator"}, created_at=now,
        observed_at=now, updated_at=now, confidence=0.8, access_principals=["user"],
        embedding_model="e5-small", embedding_version="a" * 40,
        content_hash=hashlib.sha256(content.encode()).hexdigest(), idempotency_key="doc1:v1:chunk1")
    return MemoryRecord(**(fields | kwargs))


def test_record_requires_provenance_hash_acl_and_aware_timestamps():
    assert record().schema_version == "6.1"
    for override in [{"content_hash": "0" * 64}, {"provenance": {}},
                     {"access_principals": []}, {"created_at": datetime.now()},
                     {"lifecycle": "deleted"}, {"confidence": 1.5}]:
        with pytest.raises(ValidationError):
            record(**override)
