#!/usr/bin/env python3
"""Unit tests for modules/local_brain.py."""

import json
import os
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
    _resolve_portable_model_path,
    acquire_model_lock,
    release_model_lock,
    get_local_brain,
    reset_local_brain,
    set_backend_url,
    swap_local_brain,
)


def test_deprecated_output_cleaner_is_a_compatibility_noop():
    raw = "legacy subprocess output\n"
    assert _clean_subprocess_output(raw, "prompt") == raw



def test_ask_forwards_supplied_system_prompt_to_cloud_runtime(monkeypatch):
    brain = QwenLocalBrain()
    captured = {}
    monkeypatch.setattr(brain, "_call_cloud_runtime", lambda messages, tokens: captured.update(messages=messages, tokens=tokens) or "ok")
    assert brain.ask("write concise python code", system_prompt="Answer briefly") == "ok"
    assert captured["messages"] == [
        {"role": "system", "content": "Answer briefly"},
        {"role": "user", "content": "write concise python code"},
    ]



def test_chat_forwards_short_system_prompt_to_cloud_runtime(monkeypatch):
    brain = QwenLocalBrain()
    captured = {}
    monkeypatch.setattr(brain, "_call_cloud_runtime", lambda messages, tokens: captured.update(messages=messages) or "hi there")
    assert brain.chat("hey", system_prompt=_SHORT_CHAT_SYSTEM_PROMPT) == "hi there"
    assert captured["messages"] == [
        {"role": "system", "content": _SHORT_CHAT_SYSTEM_PROMPT},
        {"role": "user", "content": "hey"},
    ]



def test_gateway_health_check_reports_healthz(monkeypatch):
    from modules.local_brain import LocalBrainGateway
    called = []
    class Response:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
    def fake_urlopen(request, timeout=5):
        called.append((request.full_url, timeout))
        return Response()
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    gateway = LocalBrainGateway()
    assert gateway._check_health("http://127.0.0.1:8000/healthz")
    assert called[0][0].endswith("/healthz")



# ── Llama-3 template tests ────────────────────────────────────────────────────

def test_legacy_gguf_templates_are_not_owned_by_localbrain():
    assert _GGUF_TEMPLATES == {}



def test_legacy_prompt_builder_leaves_templating_to_cloudruntime():
    prompt = "Hello"
    assert _build_gguf_prompt(prompt) == prompt



def test_legacy_prompt_builder_does_not_select_local_templates():
    assert _build_gguf_prompt("hi", "qwen", "sys") == "hi"



# ── Model preset tests ────────────────────────────────────────────────────────

def test_legacy_model_preset_names_are_import_compatibility_only():
    assert _LOCAL_MODEL_PRESETS == ("llama3", "qwen")



def test_swap_local_brain_creates_fresh_instance():
    """swap_local_brain('qwen') must return a new isolated instance each time."""
    reset_local_brain()
    b1 = swap_local_brain("qwen")
    reset_local_brain()
    b2 = swap_local_brain("qwen")
    assert b1 is not b2, "swap_local_brain must produce a fresh instance"


def test_swap_local_brain_returns_cloud_compatibility_shim():
    from modules.local_brain import LocalBrainGateway
    reset_local_brain()
    brain = swap_local_brain("llama3")
    assert isinstance(brain, QwenLocalBrain)
    assert isinstance(brain.gateway, LocalBrainGateway)
    reset_local_brain()



def test_deprecated_swap_does_not_switch_or_validate_local_model():
    brain = swap_local_brain("removed-preset")
    assert isinstance(brain, QwenLocalBrain)
    assert brain._model_name == "cloud-runtime"



def test_get_local_brain_returns_gateway_independent_of_legacy_preset(monkeypatch):
    from modules.local_brain import LocalBrainGateway
    monkeypatch.delenv("NIBLIT_ACTIVE_LOCAL_MODEL", raising=False)
    reset_local_brain()
    assert isinstance(get_local_brain(), LocalBrainGateway)
    reset_local_brain()



def test_get_local_brain_ignores_legacy_preset_environment(monkeypatch):
    from modules.local_brain import LocalBrainGateway
    monkeypatch.setenv("NIBLIT_ACTIVE_LOCAL_MODEL", "invalid-preset")
    reset_local_brain()
    assert isinstance(get_local_brain(), LocalBrainGateway)
    reset_local_brain()



def test_legacy_model_path_resolver_is_disabled(monkeypatch):
    monkeypatch.setenv("NIBLIT_GGUF_MODEL_PATH", "/models/portable.gguf")
    assert _resolve_portable_model_path("qwen") == ""



def test_legacy_named_model_path_is_not_loaded_by_localbrain(monkeypatch):
    monkeypatch.setenv("NIBLIT_MODEL_LLAMA3", "/models/llama3.gguf")
    assert _resolve_portable_model_path("llama3") == ""



def test_legacy_model_paths_are_ignored_by_gateway(monkeypatch):
    monkeypatch.setenv("NIBLIT_GGUF_MODEL_PATH", "/root/models/disallowed.gguf")
    assert _resolve_portable_model_path("qwen") == ""



def test_gateway_discovers_cloud_managed_llama_binary(monkeypatch, tmp_path):
    from modules.local_brain import LocalBrainGateway
    root = tmp_path / "llama.cpp"
    binary = root / "build" / "bin" / "llama-server.exe"
    binary.parent.mkdir(parents=True)
    binary.write_text("test binary", encoding="utf-8")
    monkeypatch.setattr("modules.local_brain._WINDOWS_LLAMA_CPP_ROOT", str(root))
    assert LocalBrainGateway()._discover_llama_server()["path"] == str(binary)



def test_deprecated_backend_url_does_not_reconfigure_local_inference(monkeypatch):
    monkeypatch.setenv("NIBLIT_ACTIVE_LOCAL_MODEL", "llama3")
    brain = set_backend_url("http://127.0.0.1:8080", backend="http")
    assert isinstance(brain, QwenLocalBrain)
    assert brain._model_name == "cloud-runtime"



def test_legacy_config_retains_only_generic_key_value_compatibility():
    cfg = _LocalBrainConfig()
    cfg.set("legacy", "value")
    assert cfg.get("legacy") == "value"
    assert "llama_server_url" not in cfg.as_dict()



def test_deprecated_backend_url_does_not_normalize_or_store_url():
    brain = set_backend_url("127.0.0.1:8080", backend="http")
    assert isinstance(brain, QwenLocalBrain)
    assert not hasattr(brain, "llama_server_url")



def test_reset_local_brain_clears_singleton():
    """reset_local_brain must allow a fresh singleton to be created."""
    reset_local_brain()
    b1 = get_local_brain()
    reset_local_brain()
    b2 = get_local_brain()
    assert b1 is not b2


# ── NIBLIT_KB_TOOLS schema tests ──────────────────────────────────────────────

def test_local_brain_does_not_export_legacy_kb_tool_schemas():
    from modules.llm_tool_loop import LlmToolLoop, make_runtime_status_tool
    assert NIBLIT_KB_TOOLS == []
    loop = LlmToolLoop()
    assert loop.prevalidate("runtime_status", {}) is None
    assert make_runtime_status_tool()["function"]["name"] == "runtime_status"



def test_niblit_kb_tools_required_fields():
    for tool in NIBLIT_KB_TOOLS:
        assert tool["type"] == "function"
        fn = tool["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn


# ── generate_with_tools tests ─────────────────────────────────────────────────

def test_legacy_generate_with_tools_delegates_text_only(monkeypatch):
    brain = QwenLocalBrain()
    calls = []
    monkeypatch.setattr(brain, "_call_cloud_runtime", lambda messages, tokens: calls.append((messages, tokens)) or "text answer")
    result = brain.generate_with_tools("hello", tools=[])
    assert result == "text answer"
    assert len(calls) == 1



def test_legacy_generate_with_tools_does_not_execute_tool_calls(monkeypatch):
    brain = QwenLocalBrain()
    calls = []
    monkeypatch.setattr(brain, "_call_cloud_runtime", lambda messages, tokens: calls.append(messages) or "cloud text")
    result = brain.generate_with_tools("list facts", tools=NIBLIT_KB_TOOLS)
    assert result == "cloud text"
    assert len(calls) == 1



# ── NIBLIT_ALL_TOOLS / full tool suite tests ──────────────────────────────────

def test_niblit_all_tools_is_superset_of_kb_tools():
    """NIBLIT_ALL_TOOLS must contain all NIBLIT_KB_TOOLS entries."""
    kb_names = {t["function"]["name"] for t in NIBLIT_KB_TOOLS}
    all_names = {t["function"]["name"] for t in NIBLIT_ALL_TOOLS}
    assert kb_names.issubset(all_names), f"KB tools missing from ALL_TOOLS: {kb_names - all_names}"


def test_legacy_all_tools_export_is_empty_and_governed_loop_is_narrow():
    from modules.llm_tool_loop import LlmToolLoop
    assert NIBLIT_ALL_TOOLS == []
    loop = LlmToolLoop()
    assert loop.allowed_tool_names() == ["runtime_status"]
    assert loop.prevalidate("niblit_exec", {"command": "status"})



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


def test_legacy_niblit_exec_is_not_registered_with_governed_loop():
    from modules.llm_tool_loop import LlmToolLoop
    assert LlmToolLoop().prevalidate("niblit_exec", {"command": "status"})



# ── Full structural context tests ─────────────────────────────────────────────

def test_structural_context_describes_current_gateway_architecture():
    for term in ("CloudRuntime", "LocalBrain", "NiblitBrain", "MEMORY", "TRADING"):
        assert term.lower() in _NIBLIT_FULL_STRUCTURAL_CONTEXT.lower()



def test_legacy_tool_prompt_includes_architecture_without_owning_tools():
    assert _NIBLIT_FULL_STRUCTURAL_CONTEXT in _TOOL_CALL_SYSTEM_PROMPT
    assert NIBLIT_ALL_TOOLS == []



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

def test_local_brain_does_not_export_legacy_slim_tool_schemas():
    from modules.llm_tool_loop import LlmToolLoop
    assert NIBLIT_SLIM_TOOLS == []
    assert LlmToolLoop().prevalidate("niblit_run_command", {"command": "status", "reason": "test"})



def test_niblit_slim_tools_required_fields():
    """Every slim tool must have type, function, name, description, parameters."""
    for tool in NIBLIT_SLIM_TOOLS:
        assert tool["type"] == "function"
        fn = tool["function"]
        assert "name" in fn
        assert "description" in fn
        assert "parameters" in fn
        assert isinstance(fn["description"], str) and fn["description"]


def test_legacy_command_schema_is_not_a_governed_capability():
    from modules.llm_tool_loop import LlmToolLoop
    assert LlmToolLoop().prevalidate("niblit_run_command", {"command": "status", "reason": "test"})



def test_legacy_structural_tool_schema_is_not_exported():
    from modules.llm_tool_loop import LlmToolLoop
    assert NIBLIT_SLIM_TOOLS == []
    assert LlmToolLoop().prevalidate("niblit_structural_info", {"section": "all"})



def test_slim_system_prompt_token_budget():
    """_SLIM_SYSTEM_PROMPT should be < 1000 chars to leave room for context."""
    assert len(_SLIM_SYSTEM_PROMPT) < 1000, (
        f"_SLIM_SYSTEM_PROMPT is {len(_SLIM_SYSTEM_PROMPT)} chars; "
        "should be <1000 for Llama 1B context budget"
    )


def test_legacy_slim_prompt_does_not_advertise_removed_command_tools():
    assert "niblit_structural_info" not in _SLIM_SYSTEM_PROMPT
    assert "niblit_run_command" not in _SLIM_SYSTEM_PROMPT



def test_governed_tool_loop_owns_call_limit_not_localbrain_prompt():
    from modules.llm_tool_loop import LlmToolLoop
    assert LlmToolLoop().max_loop_calls == 15



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


# ── route_inference() tests ───────────────────────────────────────────────────

def test_legacy_shim_exposes_cloud_text_api_not_route_inference():
    brain = QwenLocalBrain()
    assert callable(brain.chat)
    assert callable(brain.generate)
    assert not hasattr(brain, "route_inference")



def test_legacy_shim_does_not_select_an_inference_backend():
    brain = QwenLocalBrain()
    assert brain._model_name == "cloud-runtime"
    assert not hasattr(brain, "_backend_in_use")



def test_cloud_text_call_reports_unavailable_service_without_fabrication(monkeypatch):
    import urllib.error
    brain = QwenLocalBrain()
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")))
    assert brain._call_cloud_runtime([{"role": "user", "content": "hi"}], 8) == "[LocalBrain error: CloudRuntime unreachable]"



def test_gateway_owns_runtime_status_not_inference_routing():
    from modules.local_brain import LocalBrainGateway
    assert not hasattr(LocalBrainGateway(), "route_inference")



# ── acquire_model_lock / release_model_lock tests ─────────────────────────────

def test_acquire_and_release_model_lock():
    """acquire_model_lock must return True and release must not raise."""
    # Ensure the lock is free before we test
    import modules.local_brain as lb_mod
    if lb_mod._MODEL_SWITCH_LOCK.locked():
        lb_mod._MODEL_SWITCH_LOCK.release()

    assert acquire_model_lock(timeout=5.0) is True
    release_model_lock()  # should not raise


def test_acquire_model_lock_timeout_when_held():
    """acquire_model_lock must return False when lock is already held."""
    import modules.local_brain as lb_mod
    if lb_mod._MODEL_SWITCH_LOCK.locked():
        lb_mod._MODEL_SWITCH_LOCK.release()

    # Acquire and hold
    assert lb_mod._MODEL_SWITCH_LOCK.acquire(timeout=1.0) is True
    try:
        # Second acquire with short timeout must fail
        result = acquire_model_lock(timeout=0.05)
        assert result is False
    finally:
        lb_mod._MODEL_SWITCH_LOCK.release()


def test_deprecated_swap_does_not_mutate_model_switch_lock(monkeypatch):
    class Lock:
        calls = 0
        def acquire(self, **kwargs):
            self.calls += 1
        def release(self):
            pass
    lock = Lock()
    monkeypatch.setattr("modules.local_brain._MODEL_SWITCH_LOCK", lock)
    assert isinstance(swap_local_brain("qwen"), QwenLocalBrain)
    assert lock.calls == 0



# ── TTL health cache tests ────────────────────────────────────────────────────

def test_gateway_monitor_reports_unhealthy_runtime(monkeypatch):
    from modules.local_brain import LocalBrainGateway
    gateway = LocalBrainGateway()
    monkeypatch.setattr(gateway, "_check_health", lambda _url: False)
    result = gateway.monitor()
    assert result["healthy"] is False
    assert result["running"] is False



def test_gateway_health_check_truthfully_handles_unavailable_service(monkeypatch):
    import urllib.error
    from modules.local_brain import LocalBrainGateway
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")))
    assert LocalBrainGateway()._check_health("http://127.0.0.1:8000/healthz") is False



if __name__ == "__main__":
    print('Running test_local_brain.py')
