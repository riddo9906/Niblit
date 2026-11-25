from threading import RLock
from types import SimpleNamespace

from modules.agent_tool_approval import consume_pending_approval, operator_origin_allowed, register_pending_approvals


def test_authorization_trace_gets_one_time_approval_capability():
    name = "mcp_desktop_commander_write_file"
    pending = {}
    trace = [{
        "tool_call_id": "call-write-1",
        "tool": name,
        "arguments": {"path": "notes.txt", "content": "hello"},
        "status": "authorization_required",
    }]
    register_pending_approvals(
        "request-r16-1",
        trace,
        pending,
        RLock(),
        {name: {"requires_authorization": True}},
        {name: "command.mcp.desktop_commander.write_file"},
    )
    approval_id = trace[0].get("approval_id")
    assert isinstance(approval_id, str) and len(approval_id) == 32
    assert pending[approval_id]["request_id"] == "request-r16-1"
    assert pending[approval_id]["tool"] == name
    assert pending[approval_id]["arguments"]["path"] == "notes.txt"


def test_approval_registry_ignores_unprotected_and_unknown_tools():
    pending = {}
    trace = [
        {"tool": "safe_read", "arguments": {}, "status": "authorization_required"},
        {"tool": "unknown_write", "arguments": {}, "status": "authorization_required"},
        {"tool": "approved_tool", "arguments": {}, "status": "success"},
    ]
    register_pending_approvals(
        "request",
        trace,
        pending,
        RLock(),
        {"safe_read": {"requires_authorization": False}},
        {"unknown_write": "command.unknown"},
    )
    assert pending == {}
    assert all("approval_id" not in item for item in trace)


def test_pending_approval_is_consumed_exactly_once():
    pending = {"a" * 32: {"tool": "write_file", "arguments": {"path": "safe.txt"}, "expires_at": 200}}
    lock = RLock()
    first, state = consume_pending_approval("a" * 32, pending, lock, now=100)
    second, second_state = consume_pending_approval("a" * 32, pending, lock, now=100)
    assert state == "consumed"
    assert first["tool"] == "write_file"
    assert second is None and second_state == "unavailable"
    assert pending == {}


def test_expired_approval_is_removed_without_execution():
    pending = {"b" * 32: {"tool": "write_file", "arguments": {}, "expires_at": 100}}
    item, state = consume_pending_approval("b" * 32, pending, RLock(), now=100)
    assert item is None and state == "expired"
    assert pending == {}


def test_core_not_ready_keeps_valid_approval_pending():
    pending = {"c" * 32: {"tool": "write_file", "arguments": {}, "expires_at": 200}}
    item, state = consume_pending_approval(
        "c" * 32, pending, RLock(), now=100, ready=lambda: False,
    )
    assert state == "not_ready"
    assert item["tool"] == "write_file"
    assert "c" * 32 in pending


def test_operator_origin_accepts_local_and_tailscale_clients_only():
    local = SimpleNamespace(
        headers={"origin": "tauri://localhost", "host": "127.0.0.1:5310"},
        client=SimpleNamespace(host="127.0.0.1"),
    )
    tailscale = SimpleNamespace(
        headers={"origin": "http://100.100.20.30:5202", "host": "100.100.20.30:5310"},
        client=SimpleNamespace(host="100.100.20.30"),
    )
    external = SimpleNamespace(
        headers={"origin": "https://example.com", "host": "203.0.113.10:5310"},
        client=SimpleNamespace(host="203.0.113.10"),
    )
    assert operator_origin_allowed(local)
    assert operator_origin_allowed(tailscale)
    assert not operator_origin_allowed(external)
