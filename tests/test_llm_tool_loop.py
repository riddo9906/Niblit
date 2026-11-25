"""Tests for modules/llm_tool_loop.py — governed Core tool execution loop.
Uses a fake Cloud transport so validation/execution/observation logic is
fully exercised without launching a server.
"""

import json

import pytest

from modules.llm_tool_loop import (
    LlmToolLoop,
    ToolCallError,
    make_runtime_status_tool,
)


class FakeExecutor:
    def __init__(self):
        self.status_calls = 0

    def niblit_status(self):
        self.status_calls += 1
        return {"status": "Core: Ready"}


def _tc(name, args=None, tc_id=None):
    return {
        "id": tc_id or f"call_{name}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args or {})},
    }


def _plan_tool(name, reason="The request requires this registered capability."):
    return {"choices": [{"message": {"role": "assistant", "content": json.dumps({
        "action": "tool", "tool_name": name, "reason": reason, "final_answer": None,
    })}}]}


def _plan_final(answer, reason="No further tool action is required."):
    return {"choices": [{"message": {"role": "assistant", "content": json.dumps({
        "action": "final", "tool_name": None, "reason": reason, "final_answer": answer,
    })}}]}


class FakeLoop(LlmToolLoop):
    """Subclass with a scripted Cloud responder instead of real HTTP."""

    def __init__(self, script):
        super().__init__(executor=FakeExecutor())
        self._script = list(script)
        self.requests = []

    def _cloud_chat(self, messages, model, tools=None, tool_choice=None,
                    response_format=None, max_tokens=512):
        self.requests.append({"messages": list(messages), "tools": tools,
                              "tool_choice": tool_choice,
                              "response_format": response_format})
        entry = self._script.pop(0)
        if isinstance(entry, Exception):
            raise entry
        return entry


def test_validate_rejects_unknown_tool():
    loop = LlmToolLoop(executor=FakeExecutor())
    allowed = {"runtime_status": make_runtime_status_tool()}
    with pytest.raises(ToolCallError):
        loop._validate_call(_tc("totally_unknown"), allowed)


def test_validate_rejects_malformed_arguments():
    loop = LlmToolLoop(executor=FakeExecutor())
    allowed = {"runtime_status": make_runtime_status_tool()}
    call = {"function": {"name": "runtime_status", "arguments": "{not json"}}
    with pytest.raises(ToolCallError):
        loop._validate_call(call, allowed)


def test_validate_rejects_unknown_argument_key():
    loop = LlmToolLoop(executor=FakeExecutor())
    allowed = {"runtime_status": make_runtime_status_tool()}
    with pytest.raises(ToolCallError):
        loop._validate_call(_tc("runtime_status", {"bogus": 1}), allowed)


def test_validate_accepts_empty_args():
    loop = LlmToolLoop(executor=FakeExecutor())
    allowed = {"runtime_status": make_runtime_status_tool()}
    name, args = loop._validate_call(_tc("runtime_status", {}), allowed)
    assert name == "runtime_status" and args == {}


def test_single_tool_turn_executes_and_continuation_receives_observation():
    tool_resp = {
        "choices": [{
            "message": {"role": "assistant", "content": "",
                        "tool_calls": [_tc("runtime_status", {}, "call_rt")]},
        }],
        "niblit_model": {"requested_model": "qwen2.5-coder-3b",
                         "resolved_model": "qwen2.5-coder-3b",
                         "executed_model": "qwen2.5-coder-3b",
                         "fallback": False},
    }
    final_resp = {"choices": [{"message": {"role": "assistant",
                             "content": "Runtime is operational."}}]}
    loop = FakeLoop([_plan_tool("runtime_status"), tool_resp,
                      _plan_final("Runtime is operational.")])
    out = loop.chat([{"role": "user", "content": "What is the runtime status?"}],
                     tools=[make_runtime_status_tool()])
    assert out["text"] == "Runtime is operational."
    assert out["stopped"] == "final_answer"
    assert loop.executor.status_calls == 1
    assert len(out["trace"]) == 1
    t = out["trace"][0]
    assert t["tool"] == "runtime_status" and t["status"] == "success"
    assert t["tool_call_id"] == "call_rt"
    assert {
        "memory_retrieval_ms", "memory_gateway_initialization_ms",
        "capability_retrieval_ms", "decision_inference_ms",
        "tool_selection_inference_ms", "post_tool_decision_inference_ms",
        "structured_argument_inference_ms", "tool_dispatch_ms",
        "final_inference_ms", "total_ms",
    } <= set(out["timings_ms"])
    assert all(value >= 0 for value in out["timings_ms"].values())
    assert out["timings_ms"]["total_ms"] >= out["timings_ms"]["tool_dispatch_ms"]
    assert loop.requests[0]["response_format"]["type"] == "json_schema"
    assert loop.requests[1]["tool_choice"] == {
        "type": "function", "function": {"name": "runtime_status"}}
    assert loop.requests[1]["tools"] == [make_runtime_status_tool()]
    cont = loop.requests[2]["messages"]
    assert "tool" in [m["role"] for m in cont]
    toolmsg = [m for m in cont if m["role"] == "tool"][0]
    assert toolmsg["tool_call_id"] == "call_rt"
    assert '"status"' in toolmsg["content"]


def test_initial_required_tool_choice_is_released_after_observation():
    tool_resp = {"choices": [{"message": {"role": "assistant", "content": "",
        "tool_calls": [_tc("runtime_status", {}, "call_rt")]}}]}
    final_resp = {"choices": [{"message": {"role": "assistant",
        "content": "Runtime is operational."}}]}
    loop = FakeLoop([tool_resp, _plan_final("Runtime is operational.")])
    loop.chat([{"role": "user", "content": "What is the runtime status?"}],
              tools=[make_runtime_status_tool()], tool_choice="required")
    assert len(loop.requests) == 2
    assert loop.requests[0]["tool_choice"] == {
        "type": "function", "function": {"name": "runtime_status"}}
    assert loop.requests[0]["tools"] == [make_runtime_status_tool()]
    assert loop.requests[1]["response_format"]["type"] == "json_schema"


def test_unknown_tool_is_rejected_by_selection_contract_before_dispatch():
    loop = FakeLoop([_plan_tool("totally_evil_thing")])
    with pytest.raises(ToolCallError, match="unregistered capability"):
        loop.chat([{"role": "user", "content": "do something dangerous"}],
                  tools=[make_runtime_status_tool()])
    assert loop.executor.status_calls == 0
    assert len(loop.requests) == 1


def test_explicit_tool_list_restricts_registered_capabilities():
    write_schema = {"type": "function", "function": {
        "name": "workspace_write", "description": "write",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"}},
                       "required": ["path"]}}}
    read_schema = {"type": "function", "function": {
        "name": "workspace_read", "description": "read",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"}},
                       "required": ["path"]}}}
    writes = []
    loop = FakeLoop([_plan_tool("workspace_write")])
    loop.register_capability("workspace_write", lambda **args: writes.append(args),
                             write_schema)
    loop.register_capability("workspace_read", lambda **args: {"content": "x"},
                             read_schema)

    with pytest.raises(ToolCallError, match="unregistered capability"):
        loop.chat([{"role": "user", "content": "Explain this source"}],
                  tools=[read_schema])

    assert writes == []
    catalog = json.loads(loop.requests[0]["messages"][1]["content"].split(
        "Registered capability catalog (JSON data): ", 1)[1])
    assert [tool["name"] for tool in catalog] == ["workspace_read"]


def test_llm_tool_loop_enforces_mutation_permission(monkeypatch, tmp_path):
    import modules.permission_manager as permission_module

    monkeypatch.setattr(permission_module, "PERM_FILE", str(tmp_path / "perms.json"))
    write_schema = {"type": "function", "function": {
        "name": "workspace_write", "description": "write",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"},
                                      "content": {"type": "string"}},
                       "required": ["path", "content"]}}}
    writes = []
    tool_resp = {"choices": [{"message": {"role": "assistant", "content": "",
        "tool_calls": [_tc("workspace_write", {
            "path": "note.txt", "content": "unapproved"})]}}]}
    loop = FakeLoop([_plan_tool("workspace_write"), tool_resp,
                     _plan_final("The write was not authorized.")])
    loop.register_capability("workspace_write", lambda **args: writes.append(args),
                             write_schema)

    out = loop.chat([{"role": "user", "content": "Save this note"}])

    assert writes == []
    assert out["trace"][0]["status"] == "authorization_required"
    assert out["trace"][0]["tool"] == "workspace_write"
    assert out["trace"][0]["arguments"] == {
        "path": "note.txt", "content": "unapproved"
    }
    assert "command.workspace_write" in out["trace"][0]["error"]
    direct = loop.invoke("workspace_write", {
        "path": "note.txt", "content": "also unapproved"
    })
    assert direct["status"] == "authorization_required"
    assert writes == []


def test_continuation_preserves_assistant_tool_calls_not_flattened():
    tool_resp = {"choices": [{"message": {"role": "assistant", "content": "",
                          "tool_calls": [_tc("runtime_status", {}, "call_2")]}}]}
    final_resp = {"choices": [{"message": {"role": "assistant", "content": "OK"}}]}
    loop = FakeLoop([_plan_tool("runtime_status"), tool_resp,
                     _plan_final("OK")])
    loop.chat([{"role": "user", "content": "go"}], tools=[make_runtime_status_tool()])
    assistant_msgs = [m for m in loop.requests[2]["messages"] if m["role"] == "assistant"]
    assert assistant_msgs and "tool_calls" in assistant_msgs[0]


def test_cloud_failure_fallback_is_recorded_not_silent():
    """H1: when Cloud fails and LocalBrain answers, the swap must be
    recorded on brain_router.last_fallback with a real reason."""
    from modules.brain_router import BrainRouter

    class FakeLocal:
        def is_available(self):
            return True

        model_name = "local-test"

    def bad_cloud(_prompt):
        raise RuntimeError("cloud down")

    router = BrainRouter(local_brain=FakeLocal(), cloud_brain=bad_cloud)
    # Route via cloud path directly to exercise escalation.
    out = router._cloud_escalation("hello")
    assert router.last_fallback is not None
    fb = router.last_fallback
    assert fb["fallback"] is True
    assert "cloud error" in fb["fallback_reason"] or "cloud" in fb["fallback_reason"]
    assert fb["backend"] == "local_brain"
    assert isinstance(out, str)  # resilience preserved


def test_no_fallback_when_cloud_succeeds():
    from modules.brain_router import BrainRouter

    class FakeLocal:
        def is_available(self):
            return True

    def good_cloud(_prompt):
        return "cloud answer"

    router = BrainRouter(local_brain=FakeLocal(), cloud_brain=good_cloud)
    out = router._cloud_escalation("hi")
    assert out == "cloud answer"
    assert router.last_fallback is None


def test_tool_calls_above_limit_rejected():
    calls = [_tc("runtime_status", {}, f"call_{i}") for i in range(20)]
    resp_single = {"choices": [{"message": {"role": "assistant",
                             "content": "", "tool_calls": calls}}]}
    loop = FakeLoop([_plan_tool("runtime_status"), resp_single])
    with pytest.raises(ToolCallError):
        loop.chat([{"role": "user", "content": "go"}], tools=[make_runtime_status_tool()])


def test_identical_call_repetition_triggers_guard_and_forces_answer():
    """A model stuck re-requesting the same read-only call must not burn the
    whole loop budget and return silence: after MAX_IDENTICAL_TOOL_CALLS
    repeats, the guard removes the tool surface and the next turn MUST be a
    text answer built from the observations already collected."""
    tool_resp = {"choices": [{"message": {"role": "assistant", "content": "",
                            "tool_calls": [_tc("runtime_status", {}, "call_rt")]}}],
                 "niblit_model": {"requested_model": "qwen2.5-coder-3b",
                                  "resolved_model": "qwen2.5-coder-3b",
                                  "executed_model": "qwen2.5-coder-3b",
                                  "fallback": False}}
    final_resp = {"choices": [{"message": {"role": "assistant",
                             "content": "Core status: Ready."}}]}
    loop = FakeLoop([
        _plan_tool("runtime_status"), tool_resp,
        _plan_tool("runtime_status"), tool_resp,
        _plan_tool("runtime_status"), tool_resp,
        final_resp,
    ])
    out = loop.chat([{"role": "user", "content": "status?"}],
                    tools=[make_runtime_status_tool()])
    assert out["text"] == "Core status: Ready."
    assert out["stopped"] == "repetition_guard"
    # read-only calls were truthfully executed (not faked away)
    assert loop.executor.status_calls == 3
    # the post-guard turn was sent WITHOUT the tool surface
    assert loop.requests[-1]["tools"] is None
    statuses = [t["status"] for t in out["trace"]]
    assert statuses.count("success") == 3
    assert "guard" in statuses
    guard_entry = [t for t in out["trace"] if t["status"] == "guard"][0]
    assert guard_entry["tool_call_id"] == "loop_guard"


def test_budget_exhausted_forces_one_final_no_tools_turn():
    """Distinct tool calls each turn never trip the repetition guard; when
    the loop budget is exhausted the loop performs exactly one forced
    no-tools turn so the interaction ends in an answer, not silence."""
    echo_schema = {"type": "function", "function": {
        "name": "echo_tool", "description": "echo test capability",
        "parameters": {"type": "object",
                       "properties": {"q": {"type": "string"}},
                       "required": ["q"], "additionalProperties": False}}}

    def _tc_echo(q, cid):
        return {"id": cid, "type": "function",
                "function": {"name": "echo_tool",
                             "arguments": json.dumps({"q": q})}}

    def resp_with(q):
        return {"choices": [{"message": {"role": "assistant", "content": "",
                                "tool_calls": [_tc_echo(q, f"call_{q}")]}}]}

    final_resp = {"choices": [{"message": {"role": "assistant",
                             "content": "Answer from observations."}}]}
    loop = FakeLoop([
        _plan_tool("echo_tool"), resp_with("a"),
        _plan_tool("echo_tool"), resp_with("b"),
        final_resp,
    ])
    loop.max_loop_calls = 2  # exhaust the budget while still tool-calling
    loop.register_capability("echo_tool", lambda **kw: {"echo": kw.get("q", "")},
                             echo_schema)
    out = loop.chat([{"role": "user", "content": "go"}])
    assert out["text"] == "Answer from observations."
    assert out["stopped"] == "forced_final_answer"
    assert loop.requests[-1]["tools"] is None
    statuses = [t["status"] for t in out["trace"]]
    assert statuses.count("success") == 2


def test_distinct_calls_do_not_trip_repetition_guard():
    """Two different calls interleaved (A, B, A) stay under the per-signature
    threshold; the loop must behave exactly as before the guard existed."""
    echo_schema = {"type": "function", "function": {
        "name": "echo_tool", "description": "echo test capability",
        "parameters": {"type": "object",
                       "properties": {"q": {"type": "string"}},
                       "required": ["q"], "additionalProperties": False}}}

    def _tc_echo(q, cid):
        return {"id": cid, "type": "function",
                "function": {"name": "echo_tool",
                             "arguments": json.dumps({"q": q})}}

    ra = {"choices": [{"message": {"role": "assistant", "content": "",
                      "tool_calls": [_tc_echo("a", "c1")]}}]}
    rb = {"choices": [{"message": {"role": "assistant", "content": "",
                      "tool_calls": [_tc_echo("b", "c2")]}}]}
    final_resp = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
    loop = FakeLoop([
        _plan_tool("echo_tool"), ra,
        _plan_tool("echo_tool"), rb,
        _plan_tool("echo_tool"), ra,
        _plan_final("ok"),
    ])
    loop.register_capability("echo_tool", lambda **kw: {"echo": kw.get("q", "")},
                             echo_schema)
    out = loop.chat([{"role": "user", "content": "go"}])
    assert out["text"] == "ok"
    assert out["stopped"] == "final_answer"
    assert all(t["status"] == "success" for t in out["trace"])

def test_invoke_reports_structured_capability_errors_as_errors():
    schema = {"type": "function", "function": {
        "name": "guarded_read",
        "description": "Read through a guarded adapter",
        "parameters": {"type": "object", "properties": {}, "required": []},
    }}
    loop = LlmToolLoop(executor=FakeExecutor())
    loop.register_capability(
        "guarded_read",
        lambda **kwargs: {"error": "blocked_by_niblit_secret_file_policy"},
        schema,
    )
    result = loop.invoke("guarded_read", {})
    assert result["status"] == "error"
    assert result["error"] == "blocked_by_niblit_secret_file_policy"

def test_one_time_permission_grant_executes_without_persisting_authority():
    import uuid
    from modules import core_tool_runtime
    from modules.permission_manager import permission_grant_once

    action = "command.mcp.test.once." + uuid.uuid4().hex
    name = "mcp_test_one_time_write_" + uuid.uuid4().hex[:8]
    schema = {"type": "function", "function": {
        "name": name,
        "description": "Test one-time permission",
        "parameters": {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
    }}
    calls = []
    loop = LlmToolLoop(executor=FakeExecutor())
    loop.register_capability(name, lambda **args: calls.append(args) or {"written": True}, schema)
    old_meta = core_tool_runtime.GOVERNED_COMMAND_METADATA.get(name)
    old_action = core_tool_runtime.COMMAND_PERMISSION_ACTIONS.get(name)
    core_tool_runtime.GOVERNED_COMMAND_METADATA[name] = {"requires_authorization": True}
    core_tool_runtime.COMMAND_PERMISSION_ACTIONS[name] = action
    try:
        denied = loop.invoke(name, {"value": "one"})
        assert denied["status"] == "authorization_required"
        with permission_grant_once(action):
            approved = loop.invoke(name, {"value": "one"})
        assert approved["status"] == "success"
        assert calls == [{"value": "one"}]
        from modules.core_tool_runtime import _permission_manager
        assert not _permission_manager().check(action)
    finally:
        if old_meta is None:
            core_tool_runtime.GOVERNED_COMMAND_METADATA.pop(name, None)
        else:
            core_tool_runtime.GOVERNED_COMMAND_METADATA[name] = old_meta
        if old_action is None:
            core_tool_runtime.COMMAND_PERMISSION_ACTIONS.pop(name, None)
        else:
            core_tool_runtime.COMMAND_PERMISSION_ACTIONS[name] = old_action
