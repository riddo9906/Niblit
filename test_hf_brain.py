"""Unit tests for modules/hf_brain.py."""

from types import SimpleNamespace

from modules.hf_brain import HFBrain


class _StubDB:
    def list_facts(self, _limit=200):
        return []

    def add_interaction(self, _role, _text):
        return None


def test_hf_402_disables_hfbrain(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test_token")
    brain = HFBrain(db=_StubDB())
    brain.chat_memory = None

    def _fake_post(*_args, **_kwargs):
        return SimpleNamespace(status_code=402, text='{"error":"credits depleted"}')

    monkeypatch.setattr("modules.hf_brain.requests.post", _fake_post)

    result = brain.ask_single("hello")

    assert result is None
    assert brain.enabled is False


def test_kb_snapshot_uses_cache(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test_token")

    class CountingDB:
        def __init__(self):
            self.calls = 0

        def list_facts(self, _limit=200):
            self.calls += 1
            return [{"key": "topic_knowledge:python", "value": "Python is powerful"}]

    db = CountingDB()
    brain = HFBrain(db=db)
    brain.chat_memory = None

    first = brain._build_kb_snapshot()
    second = brain._build_kb_snapshot()

    assert first == "NIBLIT CURRENT KNOWLEDGE TOPICS (from KB ledger):\n• python: Python is powerful"
    assert second == first
    assert db.calls == 1
