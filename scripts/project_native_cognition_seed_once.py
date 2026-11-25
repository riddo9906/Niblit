"""Project only the eight v0.2 native cognition seeds and verify retrieval."""
from __future__ import annotations

import json
import os
from urllib.parse import urlsplit

from dotenv import dotenv_values

from modules.core_tool_runtime import _permission_manager
from modules.memory_laboratory.gateway import MemoryGateway
from modules.memory_laboratory.runtime import MemoryRuntime
from modules.memory_laboratory.setup import Config

TARGETS = {
    "symbols": {
        "source": "native://niblit/foundation/symbols/v0.2.0",
        "query": "Latin reference alphabet uppercase lowercase character position",
    },
    "numbers": {
        "source": "native://niblit/foundation/numbers/v0.2.0",
        "query": "digit values cardinal ordinal fraction percentage number concepts",
    },
    "mathematics": {
        "source": "native://niblit/foundation/mathematics/v0.2.0",
        "query": "operators precedence multiplication addition digits modulo",
    },
    "language": {
        "source": "native://niblit/foundation/language/v0.2.0",
        "query": "function words articles causality comparison language",
    },
    "cognition": {
        "source": "native://niblit/foundation/cognition/v0.2.0",
        "query": "observation claim hypothesis evidence negation modality",
    },
    "memorization": {
        "source": "native://niblit/foundation/memorization/v0.2.0",
        "query": "spaced retrieval practice mastery confidence memory",
    },
    "keyword_structure": {
        "source": "native://niblit/foundation/keyword_structure/v0.2.0",
        "query": "semantic keyword groups morphology phrase offsets",
    },
    "cognitive_scripts": {
        "source": "native://niblit/foundation/cognitive_scripts/v0.2.0",
        "query": "causal reasoning contradiction audit source intake",
    },
}


def main():
    env_file = ".env"
    values = dotenv_values(env_file)
    os.environ.update({key: str(value) for key, value in values.items() if value is not None})
    namespace = os.getenv("NIBLIT_MEMORY_LAB_NAMESPACE", "desktop")
    principal = os.getenv("NIBLIT_MEMORY_LAB_PRINCIPAL", "desktop_operator")
    for action in ("ingest", "read"):
        if not _permission_manager().check(f"memory.{action}.{namespace}"):
            raise PermissionError(f"Existing memory {action} grant required.")

    ledger = os.getenv("NIBLIT_MEMORY_LAB_LEDGER", "runtime/memory-framework/ledger.sqlite3")
    config = Config.from_values(os.environ)
    qdrant_host = urlsplit(config.url).hostname
    qdrant_remote = qdrant_host not in {"localhost", "127.0.0.1", "::1"}
    # Config enforces HTTPS plus a configured API key for remote Qdrant.
    # The operator has already selected this Qdrant Cloud endpoint for Niblit's
    # memory backend; this pass sends only the eight public cognitive seed packs.
    gateway = MemoryGateway(config, ledger)
    runtime = MemoryRuntime(gateway, scope={"namespace": namespace, "principal": principal})
    try:
        gateway.require("ingest", namespace, principal)
        gateway.require("read", namespace, principal)

        # Preflight the configured Qdrant and pinned, locally cached embedder
        # before claiming any outbox rows. No model download is permitted.
        try:
            collections = gateway.backend.request("GET", "/collections").get("collections", [])
        except Exception as exc:
            print(json.dumps({
                "projection_status": "blocked_preflight",
                "stage": "qdrant_connectivity",
                "error_type": type(exc).__name__,
                "outbox_claimed": False,
                "qdrant_host": qdrant_host,
                "qdrant_remote": qdrant_remote,
            }, indent=2))
            return 3
        try:
            vector = gateway.backend.embedder.embed(
                "Niblit native cognition projection preflight"
            )
        except Exception as exc:
            print(json.dumps({
                "projection_status": "blocked_preflight",
                "stage": "local_embedding_model",
                "error_type": type(exc).__name__,
                "outbox_claimed": False,
                "qdrant_host": qdrant_host,
                "model_download_allowed": config.allow_download,
            }, indent=2))
            return 3
        dimension = len(vector)
        available = {item.get("name") for item in collections}
        required = {
            config.collection("semantic", dimension),
            config.collection("procedural", dimension),
        }
        missing_collections = sorted(required - available)
        if missing_collections:
            raise RuntimeError(
                "Required configured Qdrant collections are missing; no outbox rows claimed: "
                + ", ".join(missing_collections)
            )

        sources = [item["source"] for item in TARGETS.values()]
        placeholders = ",".join("?" for _ in sources)
        with gateway.db() as db:
            queued = db.execute(
                f"SELECT source, state, attempts, next_attempt FROM ingestion_outbox "
                f"WHERE source IN ({placeholders}) ORDER BY source",
                sources,
            ).fetchall()
        if len(queued) != len(sources):
            raise RuntimeError(
                f"Expected exactly {len(sources)} v0.2 seed records; found {len(queued)}."
            )
        blocked = [
            dict(row) for row in queued
            if row["state"] not in {"pending", "complete"}
        ]
        if blocked:
            raise RuntimeError(
                "A target source is already leased or not retryable; no projection started: "
                + json.dumps(blocked, ensure_ascii=False)
            )

        projection = runtime.tick(limit=8, sources=sources)

        with gateway.db() as db:
            states = db.execute(
                f"SELECT source, state, attempts, error FROM ingestion_outbox "
                f"WHERE source IN ({placeholders}) ORDER BY source",
                sources,
            ).fetchall()
            record_rows = db.execute(
                f"SELECT source, COUNT(*) AS count, MIN(active) AS min_active, "
                f"MIN(projection) AS projection FROM records "
                f"WHERE namespace=? AND principal=? AND source IN ({placeholders}) "
                f"GROUP BY source",
                [namespace, principal, *sources],
            ).fetchall()

        state_by_source = {row["source"]: dict(row) for row in states}
        record_by_source = {row["source"]: dict(row) for row in record_rows}
        missing_projection = [
            source for source in sources
            if state_by_source.get(source, {}).get("state") != "complete"
            or source not in record_by_source
            or record_by_source[source]["min_active"] != 1
            or record_by_source[source]["projection"] != "verified"
        ]
        if missing_projection:
            raise RuntimeError(
                "Targeted projection did not verify all eight records: "
                + json.dumps({
                    "missing": missing_projection,
                    "projection": projection,
                    "states": state_by_source,
                    "records": record_by_source,
                }, ensure_ascii=False)
            )

        retrieval = []
        for domain, item in TARGETS.items():
            result = gateway.retrieve(
                item["query"], namespace=namespace, principal=principal, limit=20
            )
            hit = next(
                (candidate for candidate in result["results"]
                 if candidate["citation"].startswith(item["source"])),
                None,
            )
            retrieval.append({
                "domain": domain,
                "retrieved": hit is not None,
                "record_id": hit["id"] if hit else None,
                "citation": hit["citation"] if hit else None,
                "retrieval_mode": result["mode"],
                "issues": result["issues"],
                "excerpt": hit["content"][:180] if hit else None,
            })

        failed = [item for item in retrieval if not item["retrieved"]]
        report = {
            "target_count": len(sources),
            "target_sources": sources,
            "projection_pass": projection,
            "outbox_states": state_by_source,
            "verified_record_rows": record_by_source,
            "retrieval_checks": retrieval,
            "retrieved_count": len(retrieval) - len(failed),
            "worker_thread_started": False,
            "existing_ledger": ledger,
            "qdrant_host": qdrant_host,
            "qdrant_remote": qdrant_remote,
            "qdrant_collection_count": len(collections),
            "embedding_model": config.model,
            "embedding_revision": config.revision,
            "model_download_allowed": config.allow_download,
        }
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if not failed and projection.get("failed", 0) == 0 else 2
    finally:
        gateway.close()


if __name__ == "__main__":
    raise SystemExit(main())
