#!/usr/bin/env python3
"""Unit tests for modules/local_brain.py."""

import json
from types import TracebackType
from typing import Optional, Type
import urllib.error

from modules.local_brain import (
    _DEFAULT_LOCAL_COPILOT_SYSTEM_PROMPT,
    _GGUF_TEMPLATES,
    _LocalBrainConfig,
    _LOCAL_MODEL_PRESETS,
    _NIBLIT_FULL_STRUCTURAL_CONTEXT,
    _SHORT_CHAT_SYSTEM_PROMPT,
    _SLIM_SYSTEM_PROMPT,
    _TOOL_CALL_SYSTEM_PROMPT,
    NIBLIT_ALL_TOOLS,
    NIBLIT_KB_TOOLS,
    NIBLIT_SLIM_TOOLS,
    QwenLocalBrain,
    _build_gguf_prompt,
    _clean_subprocess_output,
    get_local_brain,
    reset_local_brain,
    set_backend_url,
    swap_local_brain,
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


def test_chat_uses_short_system_prompt():
    """chat() must use _SHORT_CHAT_SYSTEM_PROMPT, not the full copilot prompt."""
    brain = QwenLocalBrain(gguf_backend="subprocess")
    captured = {}

    def _fake_generate(prompt, max_new_tokens=None, system_prompt=None):  # noqa: ARG001
        captured["prompt"] = prompt
        captured["system_prompt"] = system_prompt
        return "hi there"

    brain.generate = _fake_generate  # type: ignore[method-assign]

    out = brain.chat("hey")
    assert out == "hi there"
    assert captured["system_prompt"] == _SHORT_CHAT_SYSTEM_PROMPT
    # Must NOT inject the heavy structural context
    assert captured["system_prompt"] != _DEFAULT_LOCAL_COPILOT_SYSTEM_PROMPT
    assert len(captured["system_prompt"]) < len(_DEFAULT_LOCAL_COPILOT_SYSTEM_PROMPT)


def test_check_server_url_falls_back_when_health_missing(monkeypatch):
    brain = QwenLocalBrain(gguf_backend="auto")
    called = []

    class _FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(
            self,
            exc_type: Optional[Type[BaseException]],
            exc: Optional[BaseException],
            tb: Optional[TracebackType],
        ) -> bool:
            return False

    def _fake_urlopen(request, timeout=5):  # noqa: ARG001
        url = request.full_url
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


# ── Llama-3 template tests ────────────────────────────────────────────────────

def test_llama3_template_present():
    """llama3 template must exist in _GGUF_TEMPLATES."""
    assert "llama3" in _GGUF_TEMPLATES
    tmpl = _GGUF_TEMPLATES["llama3"]
    assert "<|begin_of_text|>" in tmpl["system_start"]
    assert "<|eot_id|>" in tmpl["stop"]
    assert "<|end_of_text|>" in tmpl["stop"]


def test_llama3_prompt_format():
    """_build_gguf_prompt with llama3 template must use Llama-3 header tokens."""
    prompt, stop = _build_gguf_prompt("Hello", "You are Niblit.", "llama3")
    assert "<|begin_of_text|>" in prompt
    assert "<|start_header_id|>system<|end_header_id|>" in prompt
    assert "<|start_header_id|>user<|end_header_id|>" in prompt
    assert "<|start_header_id|>assistant<|end_header_id|>" in prompt
    assert "<|eot_id|>" in stop


def test_qwen_template_unaffected():
    """qwen template must still use ChatML tokens after adding llama3."""
    prompt, stop = _build_gguf_prompt("hi", "sys", "qwen")
    assert "<|im_start|>system" in prompt
    assert "<|im_end|>" in stop


# ── Model preset tests ────────────────────────────────────────────────────────

def test_local_model_presets_contain_qwen_and_llama3():
    assert "qwen" in _LOCAL_MODEL_PRESETS
    assert "llama3" in _LOCAL_MODEL_PRESETS
    for name, cfg in _LOCAL_MODEL_PRESETS.items():
        assert "model_path" in cfg, f"preset {name!r} missing model_path"
        assert "chat_template" in cfg, f"preset {name!r} missing chat_template"
        assert "description" in cfg, f"preset {name!r} missing description"

    assert _LOCAL_MODEL_PRESETS["qwen"]["chat_template"] == "qwen"
    assert _LOCAL_MODEL_PRESETS["llama3"]["chat_template"] == "llama3"


def test_swap_local_brain_creates_fresh_instance():
    """swap_local_brain('qwen') must return a new isolated instance each time."""
    reset_local_brain()
    b1 = swap_local_brain("qwen")
    reset_local_brain()
    b2 = swap_local_brain("qwen")
    assert b1 is not b2, "swap_local_brain must produce a fresh instance"


def test_swap_local_brain_sets_correct_template():
    """swap_local_brain('llama3') must use the llama3 chat template."""
    reset_local_brain()
    lb = swap_local_brain("llama3")
    assert lb.gguf_chat_template == "llama3"
    reset_local_brain()  # cleanup


def test_swap_local_brain_invalid_preset():
    """swap_local_brain with unknown preset must raise ValueError."""
    import pytest
    with pytest.raises(ValueError, match="Unknown local model preset"):
        swap_local_brain("nonexistent-model")


def test_get_local_brain_defaults_to_qwen_when_active_preset_unset(monkeypatch):
    monkeypatch.delenv("NIBLIT_ACTIVE_LOCAL_MODEL", raising=False)
    reset_local_brain()
    lb = get_local_brain()
    assert lb.gguf_chat_template == "qwen"
    reset_local_brain()


def test_get_local_brain_invalid_active_preset_falls_back_to_qwen(monkeypatch):
    monkeypatch.setenv("NIBLIT_ACTIVE_LOCAL_MODEL", "invalid-preset")
    reset_local_brain()
    lb = get_local_brain()
    assert lb.gguf_chat_template == "qwen"
    reset_local_brain()


def test_set_backend_url_keeps_active_local_preset(monkeypatch):
    monkeypatch.setenv("NIBLIT_ACTIVE_LOCAL_MODEL", "llama3")
    reset_local_brain()
    lb = set_backend_url("http://127.0.0.1:8080", backend="http")
    assert lb.gguf_chat_template == "llama3"
    reset_local_brain()


def test_local_brain_config_builds_server_url_from_host_port(monkeypatch):
    monkeypatch.delenv("NIBLIT_LLAMA_SERVER_URL", raising=False)
    monkeypatch.setenv("NIBLIT_LLAMA_SERVER_HOST", "127.0.0.1")
    monkeypatch.setenv("NIBLIT_LLAMA_SERVER_PORT", "8080")
    cfg = _LocalBrainConfig()
    assert cfg.llama_server_url == "http://127.0.0.1:8080"


def test_set_backend_url_normalizes_host_port_without_scheme(monkeypatch):
    monkeypatch.setenv("NIBLIT_ACTIVE_LOCAL_MODEL", "qwen")
    reset_local_brain()
    lb = set_backend_url("127.0.0.1:8080", backend="http")
    assert lb.llama_server_url == "http://127.0.0.1:8080"
    reset_local_brain()


def test_reset_local_brain_clears_singleton():
    """reset_local_brain must allow a fresh singleton to be created."""
    reset_local_brain()
    b1 = get_local_brain()
    reset_local_brain()
    b2 = get_local_brain()
    assert b1 is not b2


# ── NIBLIT_KB_TOOLS schema tests ──────────────────────────────────────────────

def test_niblit_kb_tools_schema():
    """NIBLIT_KB_TOOLS must define exactly the four expected tools."""
    names = {t["function"]["name"] for t in NIBLIT_KB_TOOLS}
    assert names == {"list_kb_facts", "read_kb_fact", "delete_kb_fact", "complete_slsa_artifact"}


def test_niblit_kb_tools_required_fields():
    for tool in NIBLIT_KB_TOOLS:
        assert tool["type"] == "function"
        fn = tool["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn


# ── generate_with_tools tests ─────────────────────────────────────────────────

def test_generate_with_tools_non_http_falls_back(monkeypatch):
    """generate_with_tools on subprocess backend falls back to plain generate()."""
    brain = QwenLocalBrain(gguf_backend="subprocess")
    brain._backend_in_use = "subprocess"
    brain._subprocess_bin = object()  # simulate loaded

    def _fake_generate(prompt, max_new_tokens=None, system_prompt=None):  # noqa: ARG001
        return "fallback text"

    monkeypatch.setattr(brain, "generate", _fake_generate)
    text, tool_calls = brain.generate_with_tools("hello", tools=NIBLIT_KB_TOOLS)
    assert text == "fallback text"
    assert tool_calls == []


def test_generate_with_tools_http_parses_tool_calls(monkeypatch):
    """generate_with_tools on http backend must parse and normalise tool_calls."""
    brain = QwenLocalBrain(gguf_backend="http")
    brain._backend_in_use = "http"
    brain._server_url = "http://127.0.0.1:8080"

    # Mock connectivity check
    monkeypatch.setattr(brain, "_check_server_url", lambda url: True)

    # Simulated llama-server response with tool_calls
    fake_response = {
        "choices": [{
            "message": {
                "content": "",
                "tool_calls": [{
                    "id": "call_1",
                    "function": {
                        "name": "list_kb_facts",
                        "arguments": json.dumps({"limit": 10}),
                    },
                }],
            },
        }],
    }

    class _FakeHTTPResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return json.dumps(fake_response).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=None: _FakeHTTPResp())
    text, tool_calls = brain.generate_with_tools("list facts", tools=NIBLIT_KB_TOOLS)
    assert text == ""
    assert len(tool_calls) == 1
    assert tool_calls[0]["function"]["name"] == "list_kb_facts"
    assert isinstance(tool_calls[0]["function"]["arguments"], str)
    parsed_args = json.loads(tool_calls[0]["function"]["arguments"])
    assert parsed_args["limit"] == 10


# ── NIBLIT_ALL_TOOLS / full tool suite tests ──────────────────────────────────

def test_niblit_all_tools_is_superset_of_kb_tools():
    """NIBLIT_ALL_TOOLS must contain all NIBLIT_KB_TOOLS entries."""
    kb_names = {t["function"]["name"] for t in NIBLIT_KB_TOOLS}
    all_names = {t["function"]["name"] for t in NIBLIT_ALL_TOOLS}
    assert kb_names.issubset(all_names), f"KB tools missing from ALL_TOOLS: {kb_names - all_names}"


def test_niblit_all_tools_has_expected_tools():
    """NIBLIT_ALL_TOOLS must cover all major command categories."""
    expected = {
        # System
        "niblit_status", "niblit_exec", "niblit_list_commands",
        # Brain
        "set_brain_mode", "toggle_llm",
        # Model
        "switch_local_model", "local_model_status",
        # Memory/KB (from KB tools + extended)
        "list_kb_facts", "read_kb_fact", "delete_kb_fact",
        "complete_slsa_artifact", "search_memory", "store_kb_fact",
        # Learning
        "self_research", "self_teach", "reflect",
        # Code
        "run_code", "fix_code",
        # ALE
        "ale_status", "autonomous_learn",
        # Healing
        "run_selfheal",
        # Awareness
        "niblit_structure",
    }
    all_names = {t["function"]["name"] for t in NIBLIT_ALL_TOOLS}
    missing = expected - all_names
    assert not missing, f"Expected tools missing from NIBLIT_ALL_TOOLS: {missing}"


def test_niblit_all_tools_required_fields():
    """Every tool in NIBLIT_ALL_TOOLS must have type, function, name, description."""
    for tool in NIBLIT_ALL_TOOLS:
        assert tool["type"] == "function"
        fn = tool["function"]
        assert "name" in fn, f"Tool missing 'name': {tool}"
        assert "description" in fn, f"Tool {fn.get('name')} missing 'description'"
        assert "parameters" in fn, f"Tool {fn.get('name')} missing 'parameters'"
        assert isinstance(fn["description"], str) and fn["description"], \
            f"Tool {fn['name']} has empty description"


def test_niblit_all_tools_no_duplicate_names():
    """NIBLIT_ALL_TOOLS must not contain duplicate tool names."""
    names = [t["function"]["name"] for t in NIBLIT_ALL_TOOLS]
    seen: set = set()
    for n in names:
        assert n not in seen, f"Duplicate tool name: {n!r}"
        seen.add(n)


def test_niblit_all_tools_niblit_exec_has_required_command_param():
    """niblit_exec must require a 'command' string parameter."""
    tool = next(t for t in NIBLIT_ALL_TOOLS if t["function"]["name"] == "niblit_exec")
    params = tool["function"]["parameters"]
    assert "command" in params["properties"]
    assert "command" in params.get("required", [])


# ── Full structural context tests ─────────────────────────────────────────────

def test_niblit_full_structural_context_covers_all_categories():
    """_NIBLIT_FULL_STRUCTURAL_CONTEXT must mention all major command categories."""
    ctx = _NIBLIT_FULL_STRUCTURAL_CONTEXT
    for keyword in [
        "ENTRY POINTS", "CORE ORCHESTRATION", "MEMORY LAYERS",
        "BRAIN", "ALE", "SELF-IMPROVEMENT", "KNOWLEDGE",
        "SECURITY", "PLATFORM", "TRADING", "ROUTER COMMANDS",
    ]:
        assert keyword.lower() in ctx.lower(), \
            f"Full structural context missing section: {keyword!r}"


def test_tool_call_system_prompt_includes_full_context():
    """_TOOL_CALL_SYSTEM_PROMPT must include the full structural context."""
    assert _NIBLIT_FULL_STRUCTURAL_CONTEXT in _TOOL_CALL_SYSTEM_PROMPT
    # Must mention tool-calling rules
    assert "delete_kb_fact" in _TOOL_CALL_SYSTEM_PROMPT
    assert "niblit_exec" in _TOOL_CALL_SYSTEM_PROMPT


# ── NiblitToolExecutor tests ──────────────────────────────────────────────────

def test_niblit_tool_executor_inherits_kb_tools():
    """NiblitToolExecutor must be a subclass of KBToolExecutor."""
    from modules.niblit_tool_executor import NiblitToolExecutor
    from modules.kb_tool_executor import KBToolExecutor
    assert issubclass(NiblitToolExecutor, KBToolExecutor)


def test_niblit_tool_executor_dispatch_niblit_exec(monkeypatch):
    """niblit_exec tool must call _exec() and return structured output."""
    from modules.niblit_tool_executor import NiblitToolExecutor
    executor = NiblitToolExecutor(core=None)
    monkeypatch.setattr(executor, "_exec", lambda cmd: f"output of: {cmd}")
    result = executor._dispatch("niblit_exec", {"command": "brain status"})
    assert result["command"] == "brain status"
    assert "output of: brain status" in result["output"]


def test_niblit_tool_executor_dispatch_set_brain_mode_invalid():
    """set_brain_mode with unknown mode must return error dict."""
    from modules.niblit_tool_executor import NiblitToolExecutor
    executor = NiblitToolExecutor(core=None)
    result = executor._dispatch("set_brain_mode", {"mode": "quantum"})
    assert "error" in result


def test_niblit_tool_executor_dispatch_toggle_llm_invalid():
    """toggle_llm with unknown action must return error dict."""
    from modules.niblit_tool_executor import NiblitToolExecutor
    executor = NiblitToolExecutor(core=None)
    result = executor._dispatch("toggle_llm", {"action": "maybe"})
    assert "error" in result


def test_niblit_tool_executor_dispatch_unknown_tool_falls_back(monkeypatch):
    """Unknown tool names must fall back to niblit_exec."""
    from modules.niblit_tool_executor import NiblitToolExecutor
    executor = NiblitToolExecutor(core=None)
    calls = []
    monkeypatch.setattr(executor, "_exec", lambda cmd: calls.append(cmd) or "ok")
    executor._dispatch("some_unknown_tool", {"arg": "val"})
    assert calls, "Fallback to niblit_exec was not called"


def test_niblit_tool_executor_execute_tool_calls_returns_list():
    """execute_tool_calls must return a list of result dicts."""
    from modules.niblit_tool_executor import NiblitToolExecutor
    executor = NiblitToolExecutor(core=None)
    tool_calls = [
        {"function": {"name": "niblit_status", "arguments": "{}"}},
    ]
    # Patch _exec to avoid actual core dependency
    executor._core = type("FakeCore", (), {"process": lambda self, cmd: f"mocked: {cmd}"})()
    results = executor.execute_tool_calls(tool_calls)
    assert isinstance(results, list)
    assert len(results) == 1
    assert results[0]["tool"] == "niblit_status"


# ── NIBLIT_SLIM_TOOLS / slim 2-tool suite tests ───────────────────────────────

def test_niblit_slim_tools_has_exactly_two_tools():
    """NIBLIT_SLIM_TOOLS must contain exactly 2 tool schemas."""
    assert len(NIBLIT_SLIM_TOOLS) == 2
    names = [t["function"]["name"] for t in NIBLIT_SLIM_TOOLS]
    assert "niblit_structural_info" in names
    assert "niblit_run_command" in names


def test_niblit_slim_tools_required_fields():
    """Every slim tool must have type, function, name, description, parameters."""
    for tool in NIBLIT_SLIM_TOOLS:
        assert tool["type"] == "function"
        fn = tool["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn
        assert isinstance(fn["description"], str) and fn["description"]


def test_niblit_run_command_requires_command_and_reason():
    """niblit_run_command must require both 'command' and 'reason' parameters."""
    tool = next(t for t in NIBLIT_SLIM_TOOLS if t["function"]["name"] == "niblit_run_command")
    params = tool["function"]["parameters"]
    assert "command" in params["properties"]
    assert "reason" in params["properties"]
    required = params.get("required", [])
    assert "command" in required
    assert "reason" in required


def test_niblit_structural_info_section_enum():
    """niblit_structural_info section param must mention expected sections."""
    tool = next(t for t in NIBLIT_SLIM_TOOLS if t["function"]["name"] == "niblit_structural_info")
    section_desc = tool["function"]["parameters"]["properties"]["section"]["description"]
    for expected in ("all", "commands", "memory", "brain", "ale", "kernel"):
        assert expected in section_desc, f"Section {expected!r} missing from niblit_structural_info description"


def test_slim_system_prompt_token_budget():
    """_SLIM_SYSTEM_PROMPT should be < 1000 chars to leave room for context."""
    assert len(_SLIM_SYSTEM_PROMPT) < 1000, (
        f"_SLIM_SYSTEM_PROMPT is {len(_SLIM_SYSTEM_PROMPT)} chars; "
        "should be <1000 for Llama 1B context budget"
    )


def test_slim_system_prompt_mentions_both_tools():
    """_SLIM_SYSTEM_PROMPT must reference both slim tool names."""
    assert "niblit_structural_info" in _SLIM_SYSTEM_PROMPT
    assert "niblit_run_command" in _SLIM_SYSTEM_PROMPT


def test_slim_system_prompt_mentions_max_tool_calls():
    """_SLIM_SYSTEM_PROMPT must mention the 5-call turn limit."""
    assert "5" in _SLIM_SYSTEM_PROMPT


# ── NiblitToolExecutor slim execution tests ───────────────────────────────────

def test_execute_slim_tool_calls_structural_info(monkeypatch):
    """execute_slim_tool_calls with niblit_structural_info must call get_structural_info."""
    from modules.niblit_tool_executor import NiblitToolExecutor
    executor = NiblitToolExecutor(core=None)
    calls = []

    def _fake_structural(section="all"):
        calls.append(section)
        return {"section": section, "modules": {}, "state": {}}

    monkeypatch.setattr(executor, "get_structural_info", _fake_structural)
    tool_calls = [
        {"function": {"name": "niblit_structural_info", "arguments": '{"section": "commands"}'}},
    ]
    results = executor.execute_slim_tool_calls(tool_calls)
    assert results[0]["tool"] == "niblit_structural_info"
    assert "result" in results[0]
    assert calls == ["commands"]


def test_execute_slim_tool_calls_run_command(monkeypatch):
    """execute_slim_tool_calls with niblit_run_command must call execute_niblit_run_command."""
    from modules.niblit_tool_executor import NiblitToolExecutor
    executor = NiblitToolExecutor(core=None)
    calls = []

    def _fake_run(command, reason):
        calls.append((command, reason))
        return {"command": command, "reason": reason, "output": "ok"}

    monkeypatch.setattr(executor, "execute_niblit_run_command", _fake_run)
    tool_calls = [
        {"function": {
            "name": "niblit_run_command",
            "arguments": '{"command": "status", "reason": "health check"}',
        }},
    ]
    results = executor.execute_slim_tool_calls(tool_calls)
    assert results[0]["tool"] == "niblit_run_command"
    assert calls == [("status", "health check")]


def test_execute_slim_tool_calls_max_tool_calls():
    """execute_slim_tool_calls must enforce MAX_TOOL_CALLS_PER_TURN limit."""
    from modules.niblit_tool_executor import NiblitToolExecutor, MAX_TOOL_CALLS_PER_TURN
    executor = NiblitToolExecutor(core=None)
    # Patch run_command so it doesn't need a real core
    executor._core = type("FakeCore", (), {"process": lambda self, cmd: "ok"})()

    # Submit MAX+2 calls
    n = MAX_TOOL_CALLS_PER_TURN + 2
    tool_calls = [
        {"function": {
            "name": "niblit_run_command",
            "arguments": json.dumps({"command": "status", "reason": "loop test"}),
        }}
    ] * n

    results = executor.execute_slim_tool_calls(tool_calls)
    assert len(results) == n
    # First MAX calls succeed (have "result"), remainder have "error" about limit
    limit_errors = [r for r in results if "error" in r and "max_tool_calls" in r.get("error", "")]
    assert len(limit_errors) == 2


def test_execute_niblit_run_command_blocks_destructive():
    """execute_niblit_run_command must block shutdown/exit/quit without confirm_mode."""
    from modules.niblit_tool_executor import NiblitToolExecutor
    executor = NiblitToolExecutor(core=None, confirm_mode=False)
    for cmd in ("shutdown", "exit", "quit"):
        result = executor.execute_niblit_run_command(cmd, "test")
        assert "error" in result, f"Destructive command {cmd!r} was not blocked"
        assert "blocked" in result["error"].lower()


def test_execute_niblit_run_command_allows_destructive_with_confirm():
    """execute_niblit_run_command must allow destructive cmds when confirm_mode=True."""
    from modules.niblit_tool_executor import NiblitToolExecutor
    executor = NiblitToolExecutor(core=None, confirm_mode=True)
    executor._core = type("FakeCore", (), {"process": lambda self, cmd: f"ran: {cmd}"})()
    result = executor.execute_niblit_run_command("shutdown", "user confirmed")
    assert "output" in result


def test_execute_niblit_run_command_logs_reason(monkeypatch):
    """execute_niblit_run_command must pass command to _exec."""
    from modules.niblit_tool_executor import NiblitToolExecutor
    executor = NiblitToolExecutor(core=None)
    executed = []
    monkeypatch.setattr(executor, "_exec", lambda cmd: executed.append(cmd) or "ok")
    result = executor.execute_niblit_run_command("brain status", "health check")
    assert executed == ["brain status"]
    assert result["command"] == "brain status"
    assert result["reason"] == "health check"


def test_get_structural_info_all_section(monkeypatch):
    """get_structural_info(section='all') must return modules, state, commands_tip keys."""
    from modules.niblit_tool_executor import NiblitToolExecutor
    executor = NiblitToolExecutor(core=None)
    # Patch _exec to avoid core dependency
    monkeypatch.setattr(executor, "_exec", lambda cmd: "mocked")
    result = executor.get_structural_info("all")
    assert result["section"] == "all"
    assert "modules" in result
    assert "state" in result
    assert "commands_tip" in result


def test_get_structural_info_brain_section():
    """get_structural_info(section='brain') must return brain section."""
    from modules.niblit_tool_executor import NiblitToolExecutor
    executor = NiblitToolExecutor(core=None)
    result = executor.get_structural_info("brain")
    assert result["section"] == "brain"
    assert "mode" in result or "local_backend" in result


def test_get_structural_info_commands_section(monkeypatch):
    """get_structural_info(section='commands') must return a commands list."""
    from modules.niblit_tool_executor import NiblitToolExecutor
    executor = NiblitToolExecutor(core=None)
    result = executor.get_structural_info("commands")
    assert result["section"] == "commands"
    assert isinstance(result.get("commands"), list)
    assert len(result["commands"]) > 0


if __name__ == "__main__":
    print('Running test_local_brain.py')
