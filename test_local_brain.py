#!/usr/bin/env python3
"""Unit tests for modules/local_brain.py."""

import urllib.error

from modules.local_brain import (
    _DEFAULT_LOCAL_COPILOT_SYSTEM_PROMPT,
    QwenLocalBrain,
    _clean_subprocess_output,
)


def test_clean_subprocess_output_strips_llama_banner_and_commands():
    prompt = "<|im_start|>user\nhello<|im_end|>\n<|im_start|>assistant\n"
    raw = (
        "/data/data/com.termux/files/usr/bin/getprop: 3: exec: /system/bin/getprop: Operation not permitted\n"
        "Loading model...\n\n"
        "available commands:\n"
        "  /exit\n"
        "  /glob\n\n"
        f"{prompt}Sure — I can help with that.\n"
    )
    cleaned = _clean_subprocess_output(raw, prompt)
    assert "Operation not permitted" not in cleaned
    assert "available commands" not in cleaned.lower()
    assert "/glob" not in cleaned
    assert cleaned == "Sure — I can help with that."


def test_ask_uses_default_local_copilot_system_prompt():
    brain = QwenLocalBrain(gguf_backend="subprocess")
    captured = {}

    def _fake_generate(prompt, max_new_tokens=None, system_prompt=None):  # noqa: ARG001
        captured["prompt"] = prompt
        captured["system_prompt"] = system_prompt
        return "ok"

    brain.generate = _fake_generate  # type: ignore[method-assign]

    out = brain.ask("write concise python code")
    assert out == "ok"
    assert captured["prompt"] == "write concise python code"
    assert captured["system_prompt"] == _DEFAULT_LOCAL_COPILOT_SYSTEM_PROMPT


def test_check_server_url_falls_back_when_health_missing(monkeypatch):
    brain = QwenLocalBrain(gguf_backend="auto")
    called = []

    class _FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
            return False

    def _fake_urlopen(req, timeout=5):  # noqa: ARG001
        url = req.full_url
        called.append(url)
        if url.endswith("/health"):
            raise urllib.error.HTTPError(url, 404, "Not Found", hdrs=None, fp=None)
        if url.endswith("/v1/models"):
            return _FakeResponse()
        raise AssertionError(f"Unexpected probe URL: {url}")

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    assert brain._check_server_url("http://127.0.0.1:8080") is True
    assert called == [
        "http://127.0.0.1:8080/health",
        "http://127.0.0.1:8080/v1/models",
    ]
