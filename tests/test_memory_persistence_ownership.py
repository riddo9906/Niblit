"""Compatibility facades must not overwrite the canonical knowledge snapshot."""
import json
import threading
from pathlib import Path

import pytest

import niblit_memory as memory_module
from niblit_memory.unified_memory_engine import UnifiedMemoryEngine


@pytest.fixture
def knowledge(tmp_path, monkeypatch):
    path = tmp_path / "knowledge.json"
    path.write_text(json.dumps({"facts": [], "preferences": {"theme": "dark"}}), encoding="utf-8")
    database = object.__new__(memory_module.KnowledgeDB)
    database.__init__(path=str(path))
    monkeypatch.setattr(memory_module, "GLOBAL_KNOWLEDGE", database)
    yield database
    database.shutdown()


def make_facade(path, monkeypatch):
    def improvements(self):
        self.metrics = {"loads": 0, "saves": 0, "errors": 0}
        self.telemetry = None

    # No autosave loops or global singletons in these disposable test instances.
    monkeypatch.setattr(memory_module.NiblitMemory, "_init_improvements", improvements)
    monkeypatch.setattr(threading.Thread, "start", lambda self: None)
    facade = object.__new__(memory_module.NiblitMemory)
    facade.__init__(filename=str(path))
    return facade


def test_same_file_has_one_state_and_writer(knowledge, monkeypatch):
    facade = make_facade(knowledge.path, monkeypatch)
    assert facade.state is knowledge.data
    assert facade.lock is knowledge.lock

    with knowledge.lock:
        knowledge.data["facts"].append({"key": "canonical", "value": "Retain this fact"})
    with facade.lock:
        facade.state["preferences"]["language"] = "English"
    facade.save()
    knowledge._save()

    stored = json.loads(Path(knowledge.path).read_text(encoding="utf-8"))
    assert stored["facts"][0]["key"] == "canonical"
    assert stored["preferences"] == {"theme": "dark", "language": "English"}


def test_explicit_separate_file_keeps_independent_state(knowledge, tmp_path, monkeypatch):
    path = tmp_path / "independent.json"
    facade = make_facade(path, monkeypatch)
    assert facade.state is not knowledge.data
    facade.state["preferences"]["language"] = "English"
    facade.save()
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["preferences"]["language"] == "English"
    assert "language" not in knowledge.data["preferences"]


def test_invalid_snapshot_cannot_truncate_existing_file(knowledge, tmp_path, monkeypatch):
    path = tmp_path / "independent.json"
    original = {"preferences": {"language": "English"}}
    path.write_text(json.dumps(original), encoding="utf-8")
    facade = make_facade(path, monkeypatch)
    facade.state["preferences"]["invalid"] = object()
    facade.save()
    assert json.loads(path.read_text(encoding="utf-8")) == original
    assert facade.metrics["errors"] == 1


def test_unified_semantic_memory_reaches_canonical_storage(knowledge, monkeypatch):
    facade = make_facade(knowledge.path, monkeypatch)
    monkeypatch.setattr(memory_module, "NiblitMemory", lambda: facade)
    engine = UnifiedMemoryEngine()
    monkeypatch.setattr(engine, "_get_governed_cluster", lambda: None)
    uid = engine.remember("SQLite stores durable facts for the project memory system.")
    knowledge._save()
    stored = json.loads(Path(knowledge.path).read_text(encoding="utf-8"))
    assert any(fact["key"] == f"ume:{uid}" for fact in stored["facts"])
    assert knowledge.recall("SQLite")


def test_changed_canonical_path_cannot_trigger_a_stale_facade_write(knowledge, tmp_path, monkeypatch):
    facade = make_facade(knowledge.path, monkeypatch)
    original = Path(knowledge.path).read_text(encoding="utf-8")
    with monkeypatch.context() as context:
        context.setattr(knowledge, "path", str(tmp_path / "different.json"))
        facade.save()
        assert facade.metrics["errors"] == 1
        assert not (tmp_path / "different.json").exists()
    assert Path(knowledge.path).read_text(encoding="utf-8") == original
