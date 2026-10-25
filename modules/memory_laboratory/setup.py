"""Read-only preflight and additive, versioned Qdrant collection setup.

This module intentionally does not import legacy vector managers: importing them
can initialize backends. No method recreates or deletes an existing collection.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from .contracts import CATEGORIES

INDEXES = {
    "schema_version": "keyword", "namespace": "keyword", "category": "keyword",
    "source_id": "keyword", "content_hash": "keyword", "lifecycle": "keyword",
    "access_principals": "keyword", "sensitivity": "keyword",
    "verification": "keyword", "updated_at": "datetime",
}


@dataclass(frozen=True)
class Config:
    url: str
    api_key: str = field(default="", repr=False)
    prefix: str = "niblit_lab"
    model: str = "intfloat/multilingual-e5-small"
    revision: str = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
    distance: str = "Cosine"
    allow_download: bool = False

    def __post_init__(self):
        u = urlsplit(self.url)
        if u.scheme not in {"http", "https"} or not u.hostname:
            raise ValueError("Qdrant URL must use HTTP(S)")
        if u.username or u.password or u.query or u.fragment:
            raise ValueError("Qdrant URL cannot contain credentials, query or fragment")
        loopback = u.hostname in {"localhost", "127.0.0.1", "::1"}
        if not loopback and (u.scheme != "https" or not self.api_key):
            raise ValueError("remote Qdrant requires HTTPS and an API key")
        if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_]{0,79}", self.prefix):
            raise ValueError("invalid collection prefix")
        if self.distance not in {"Cosine", "Dot", "Euclid", "Manhattan"}:
            raise ValueError("unsupported distance metric")
        if not self.model.strip() or not re.fullmatch(r"[a-f0-9]{40}", self.revision):
            raise ValueError("embedding revision must be an immutable 40-character commit")

    @classmethod
    def from_env(cls):
        return cls.from_values(os.environ)

    @classmethod
    def from_values(cls, values):
        return cls(
            url=values.get("QDRANT_URL", "http://127.0.0.1:6333"),
            api_key=values.get("QDRANT_API_KEY", ""),
            prefix=values.get("NIBLIT_MEMORY_COLLECTION_PREFIX", "niblit_lab"),
            model=values.get("NIBLIT_MEMORY_EMBEDDING_MODEL", cls.model),
            revision=values.get("NIBLIT_MEMORY_EMBEDDING_REVISION", cls.revision),
            distance=values.get("NIBLIT_MEMORY_DISTANCE", "Cosine"),
            allow_download=values.get("NIBLIT_MEMORY_ALLOW_MODEL_DOWNLOAD", "0") == "1",
        )

    def collection(self, category, dimension):
        if category not in CATEGORIES or dimension < 1:
            raise ValueError("invalid category/dimension")
        identity = ["6.1", self.model, self.revision, dimension, self.distance]
        suffix = hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:16]
        return f"{self.prefix}_s6_{category}_{suffix}"


def validate_vector(vector):
    result = [float(v) for v in vector]
    if not result or len(result) > 65536 or not all(math.isfinite(v) for v in result):
        raise ValueError("invalid embedding")
    norm = math.sqrt(sum(v * v for v in result))
    if norm <= 0:
        raise ValueError("zero embedding is not a semantic embedding")
    return [v / norm for v in result]


class DedicatedEmbedder:
    """Pinned CPU embedding model. No Qwen, fabricated or zero-vector fallback."""
    def __init__(self, config):
        self.config = config
        self._model = None

    def embed(self, text, *, query=False):
        if not text.strip():
            raise ValueError("empty embedding input")
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(
                self.config.model, revision=self.config.revision,
                device="cpu", trust_remote_code=False,
                local_files_only=not self.config.allow_download,
            )
        prefix = ("query: " if query else "passage: ") if "e5" in self.config.model.lower() else ""
        vector = self._model.encode(prefix + text, normalize_embeddings=True,
                                    show_progress_bar=False).tolist()
        return validate_vector(vector)


class QdrantSetup:
    def __init__(self, config, *, client=None, embedder=None):
        self.config = config
        self.client = client or httpx.Client(
            base_url=config.url.rstrip("/"),
            headers={"api-key": config.api_key} if config.api_key else {},
            timeout=10.0, follow_redirects=False,
        )
        self._owns_client = client is None
        self.embedder = embedder or DedicatedEmbedder(config)

    def close(self):
        if self._owns_client:
            self.client.close()

    def request(self, method, path, **kwargs):
        response = self.client.request(method, path, **kwargs)
        response.raise_for_status()
        return response.json().get("result")

    def run(self, *, apply=False):
        report = {"ready": False, "mode": "apply" if apply else "dry-run",
                  "collections": [], "issues": [], "write_permissions_verified": False}
        try:
            root = self.client.get("/")
            root.raise_for_status()
            version = str(root.json().get("version", ""))
            report["server_version"] = version
            match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
            if not match or int(match[1]) != 1 or int(match[2]) < 10:
                raise ValueError("unsupported server; require Qdrant 1.10+ in major version 1")
            # Listing collections verifies read scope before model loading/mutation.
            self.request("GET", "/collections")
            vector = validate_vector(self.embedder.embed("Niblit memory readiness probe"))
            report["embedding"] = {"model": self.config.model,
                                   "revision": self.config.revision, "dimension": len(vector)}
            for category in CATEGORIES:
                name = self.config.collection(category, len(vector))
                path = f"/collections/{name}"
                state = {"name": name, "category": category, "ready": False}
                report["collections"].append(state)
                response = self.client.get(path)
                if response.status_code == 404:
                    if not apply:
                        state["action"] = "create_versioned_collection"
                        continue
                    self.request("PUT", path, json={"vectors": {
                        "size": len(vector), "distance": self.config.distance}})
                    response = self.client.get(path)
                response.raise_for_status()
                info = response.json()["result"]
                params = info["config"]["params"]["vectors"]
                if params.get("size") != len(vector) or params.get("distance") != self.config.distance:
                    state["action"] = "migration_required_preserve_existing"
                    report["issues"].append(f"schema_mismatch:{name}")
                    continue
                indexes = info.get("payload_schema", {})
                missing = [key for key in INDEXES if key not in indexes]
                mismatched = [key for key, kind in INDEXES.items()
                              if key in indexes and indexes[key].get("data_type") != kind]
                if mismatched:
                    state["action"] = "migration_required_preserve_existing"
                    report["issues"].append(f"index_type_mismatch:{name}")
                    continue
                if apply:
                    for key in missing:
                        self.request("PUT", path + "/index?wait=true", json={
                            "field_name": key, "field_schema": INDEXES[key]})
                    refreshed = self.request("GET", path).get("payload_schema", {})
                    missing = [key for key, kind in INDEXES.items()
                               if refreshed.get(key, {}).get("data_type") != kind]
                state["missing_indexes"] = missing
                state["ready"] = not missing
            schema_ready = all(s["ready"] for s in report["collections"])
            if schema_ready and apply:
                # Unique probe in this versioned collection only. Delete ONLY our
                # own probe, never a source point or a collection.
                point_id = str(uuid4())
                path = "/collections/" + report["collections"][0]["name"] + "/points"
                try:
                    self.request("PUT", path + "?wait=true", json={"points": [{
                        "id": point_id, "vector": vector, "payload": {
                            "schema_version": "6.1", "namespace": "_readiness",
                            "category": "working", "lifecycle": "archived",
                            "access_principals": ["setup"], "sensitivity": "internal"}}]})
                    point = self.request("GET", path + "/" + point_id)
                    if point.get("payload", {}).get("namespace") != "_readiness":
                        raise ValueError("probe_readback_mismatch")
                    report["write_permissions_verified"] = True
                finally:
                    self.request("POST", path + "/delete?wait=true", json={"points": [point_id]})
            report["ready"] = schema_ready and (not apply or report["write_permissions_verified"])
        except Exception as exc:
            # Never serialize exception messages: URLs/headers may contain secrets.
            issue = type(exc).__name__
            if isinstance(exc, httpx.HTTPStatusError):
                issue += f":HTTP_{exc.response.status_code}"
            report["issues"].append(issue)
        return report
