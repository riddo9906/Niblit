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


class FakeLoop(LlmToolLoop):
    """Subclass with a scripted Cloud responder instead of real HTTP."""

    def __init__(self, script):
        super().__init__(executor=FakeExecutor())
        self._script = list(script)
        self.requests = []

    def _cloud_chat(self, messages, model, tools=None, tool_choice=None, max_tokens=512):
        self.requests.append({"messages": list(messages), "tools": tools,
                              "tool_choice": tool_choice})
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
    loop = FakeLoop([tool_resp, final_resp])
    out = loop.chat([{"role": "user", "content": "What is the runtime status?"}],
                     tools=[make_runtime_status_tool()])
    assert out["text"] == "Runtime is operational."
    assert out["stopped"] == "final_answer"
    assert loop.executor.status_calls == 1
    assert len(out["trace"]) == 1
    t = out["trace"][0]
    assert t["tool"] == "runtime_status" and t["status"] == "success"
    assert t["tool_call_id"] == "call_rt"
    cont = loop.requests[1]["messages"]
    assert "tool" in [m["role"] for m in cont]
    toolmsg = [m for m in cont if m["role"] == "tool"][0]
    assert toolmsg["tool_call_id"] == "call_rt"
    assert '"status"' in toolmsg["content"]


def test_initial_required_tool_choice_is_released_after_observation():
    tool_resp = {"choices": [{"message": {"role": "assistant", "content": "",
        "tool_calls": [_tc("runtime_status", {}, "call_rt")]}}]}
    final_resp = {"choices": [{"message": {"role": "assistant",
        "content": "Runtime is operational."}}]}
    loop = FakeLoop([tool_resp, final_resp])
    loop.chat([{"role": "user", "content": "What is the runtime status?"}],
              tools=[make_runtime_status_tool()], tool_choice="required")
    assert loop.requests[0]["tool_choice"] == "required"
    assert loop.requests[1]["tool_choice"] is None


def test_unknown_tool_is_rejected_as_observation_not_executed():
    tool_resp = {"choices": [{"message": {"role": "assistant", "content": "",
                          "tool_calls": [_tc("totally_evil_thing", {}, "call_bad")]}}]}
    final_resp = {"choices": [{"message": {"role": "assistant",
                          "content": "Tool not permitted."}}]}
    loop = FakeLoop([tool_resp, final_resp])
    out = loop.chat([{"role": "user", "content": "do something dangerous"}],
                   tools=[make_runtime_status_tool()])
    assert loop.executor.status_calls == 0
    assert out["trace"][0]["status"] == "rejected"
    assert "unknown tool" in out["trace"][0].get("error", "")


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
    loop = FakeLoop([
        {"choices": [{"message": {"role": "assistant", "content": "",
          "tool_calls": [_tc("workspace_write", {"path": "note.txt"})]}}]},
        {"choices": [{"message": {"role": "assistant",
                                   "content": "Write was denied."}}]},
    ])
    loop.register_capability("workspace_write", lambda **args: writes.append(args),
                             write_schema)
    loop.register_capability("workspace_read", lambda **args: {"content": "x"},
                             read_schema)

    out = loop.chat([{"role": "user", "content": "Explain this source"}],
                    tools=[read_schema])

    assert writes == []
    assert out["trace"][0]["status"] == "rejected"
    assert "unknown tool" in out["trace"][0]["error"]
    assert [tool["function"]["name"] for tool in loop.requests[0]["tools"]] == [
        "workspace_read"]


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
    loop = FakeLoop([
        {"choices": [{"message": {"role": "assistant", "content": "",
          "tool_calls": [_tc("workspace_write", {
              "path": "note.txt", "content": "unapproved"})]}}]},
        {"choices": [{"message": {"role": "assistant",
                                   "content": "The write was not authorized."}}]},
    ])
    loop.register_capability("workspace_write", lambda **args: writes.append(args),
                             write_schema)

    out = loop.chat([{"role": "user", "content": "Save this note"}])

    assert writes == []
    assert out["trace"][0]["status"] == "authorization_required"
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
    loop = FakeLoop([tool_resp, final_resp])
    loop.chat([{"role": "user", "content": "go"}], tools=[make_runtime_status_tool()])
    assistant_msgs = [m for m in loop.requests[1]["messages"] if m["role"] == "assistant"]
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
    loop = FakeLoop([resp_single])
    with pytest.raises(ToolCallError):
        loop.chat([{"role": "user", "content": "go"}], tools=[make_runtime_status_tool()])
def test_tool_calls_above_limit_rejected():
    calls = [_tc("runtime_status", {}, f"call_{i}") for i in range(20)]
    resp_single = {"choices": [{"message": {"role": "assistant",
                             "content": "", "tool_calls": calls}}]}
    loop = FakeLoop([resp_single])
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
    loop = FakeLoop([tool_resp, tool_resp, tool_resp, final_resp])
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
    loop = FakeLoop([resp_with("a"), resp_with("b"), final_resp])
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
    loop = FakeLoop([ra, rb, ra, final_resp])
    loop.register_capability("echo_tool", lambda **kw: {"echo": kw.get("q", "")},
                             echo_schema)
    out = loop.chat([{"role": "user", "content": "go"}])
    assert out["text"] == "ok"
    assert out["stopped"] == "final_answer"
    assert all(t["status"] == "success" for t in out["trace"])
