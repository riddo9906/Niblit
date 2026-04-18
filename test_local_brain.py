#!/usr/bin/env python3
"""Unit tests for modules/local_brain.py."""

from modules.local_brain import (
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
    assert "local copilot for Niblit" in (captured["system_prompt"] or "")
