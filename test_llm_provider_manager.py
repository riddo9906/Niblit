"""Unit tests for modules/llm_provider_manager.py."""

from modules.llm_provider_manager import LLMProviderManager


class _StubLocalBrain:
    model_name = "Qwen/Qwen2.5-0.5B-Instruct"

    def __init__(self, response="local answer"):
        self._response = response

    def generate(self, prompt, max_new_tokens=500, system_prompt=None):
        _ = (prompt, max_new_tokens, system_prompt)
        return self._response


class _StubHFBrain:
    enabled = True
    token = "hf_x"
    model = "hf-model"

    def ask_single(self, prompt):
        _ = prompt
        return "hf fallback answer"


class _StubRuflo:
    model = "ruflo-qwen"

    def __init__(self, response="ruflo answer", available=True):
        self._response = response
        self._available = available

    def is_available(self):
        return self._available

    def generate(self, prompt, system="", max_tokens=500):
        _ = (prompt, system, max_tokens)
        return self._response


class TestLLMProviderManagerQwen:
    def test_switch_to_qwen_and_ask(self):
        mgr = LLMProviderManager()
        mgr.wire(local_brain=_StubLocalBrain("qwen answer"))

        msg = mgr.switch("qwen")
        assert "qwen" in msg.lower()
        assert mgr.ask("hello") == "qwen answer"

    def test_status_includes_qwen(self):
        mgr = LLMProviderManager()
        mgr.wire(local_brain=_StubLocalBrain())
        s = mgr.status()

        assert "qwen" in s
        assert "qwen_model" in s
        assert s["qwen"] is True

    def test_qwen_falls_back_to_hf_when_local_unavailable(self):
        mgr = LLMProviderManager()
        mgr.wire(
            local_brain=_StubLocalBrain("[LocalBrain unavailable - model missing]"),
            hf_brain=_StubHFBrain(),
        )
        mgr.switch("qwen")

        assert mgr.ask("hello") == "hf fallback answer"

    def test_switch_to_ruflo_and_ask(self):
        mgr = LLMProviderManager()
        mgr._ruflo = _StubRuflo("ruflo answer")

        msg = mgr.switch("ruflo")
        assert "ruflo" in msg.lower()
        assert mgr.ask("hello") == "ruflo answer"

    def test_status_includes_ruflo(self):
        mgr = LLMProviderManager()
        mgr._ruflo = _StubRuflo()
        s = mgr.status()

        assert "ruflo" in s
        assert "ruflo_model" in s
        assert s["ruflo"] is True

    def test_ruflo_falls_back_to_hf_when_unavailable(self):
        mgr = LLMProviderManager()
        mgr._ruflo = _StubRuflo(available=False)
        mgr.wire(hf_brain=_StubHFBrain())
        mgr.switch("ruflo")

        assert mgr.ask("hello") == "hf fallback answer"


if __name__ == "__main__":
    print('Running test_llm_provider_manager.py')
