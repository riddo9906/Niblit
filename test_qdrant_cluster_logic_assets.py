from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parent / "qdrant_cluster_logic"


def test_collection_blueprints_have_matching_api_payloads() -> None:
    collections = sorted((ROOT / "collections").glob("*.json"))
    assert collections
    for blueprint_path in collections:
        blueprint = json.loads(blueprint_path.read_text(encoding="utf-8"))
        payload_path = ROOT / "deployment" / "api_payloads" / f"{blueprint['collection_name']}.json"
        assert payload_path.exists()
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        assert payload["vectors"]["size"] == blueprint["vector_policy"]["size"]
        assert payload["vectors"]["distance"] == blueprint["vector_policy"]["distance"]
        assert payload["strict_mode_config"]["enabled"] is True
        assert blueprint["payload_indexes"]


def test_required_payload_schemas_exist() -> None:
    required = {
        "schema_v2_memory_payload.json",
        "governance_payload.json",
        "replay_payload.json",
        "federation_payload.json",
    }
    found = {path.name for path in (ROOT / "payload_schemas").glob("*.json")}
    assert required.issubset(found)


def test_deployment_scripts_reference_ui_ready_payloads() -> None:
    script = (ROOT / "deployment" / "initialize_cluster.sh").read_text(encoding="utf-8")
    assert "deployment/api_payloads" in script
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "deployment/api_payloads" in readme


if __name__ == "__main__":
    print('Running test_qdrant_cluster_logic_assets.py')
