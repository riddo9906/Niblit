"""Unit tests for modules/hf_brain.py."""

from types import SimpleNamespace

from modules.hf_brain import HFBrain


class _StubDB:
    def list_facts(self, limit=200):
        _ = limit
        return []

    def add_interaction(self, role, text):
        _ = (role, text)


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

