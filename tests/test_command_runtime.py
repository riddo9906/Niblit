"""Phase 5E tests: governed command surface for the Command tab.

Covers: registry discovery with truthful states; real execution through the
SAME governed dispatch as the LLM (LlmToolLoop.invoke); rejection of unknown
commands and malformed arguments; authorization gate for mutation commands
(existing PermissionManager store); unavailable dependency handling;
EventBus command.* events; endpoint envelopes; security invariants.
"""
from __future__ import annotations

import json

import pytest

import modules.core_tool_runtime as ctr
import modules.permission_manager as pmod
from modules.core_tool_runtime import (
    COMMAND_PERMISSION_ACTIONS,
    GOVERNED_COMMAND_METADATA,
    HARD_CAP_FETCHES,
    HARD_CAP_ROUNDS,
    HARD_CAP_SEARCHES,
    ORIGINAL_READONLY_PROMOTIONS,
    execute_governed_command,
    list_governed_commands,
    reset_governed_tool_loop,
)
from modules.event_bus import get_event_bus
from modules.trading_read_tools import FORBIDDEN_EXECUTION_NAMES

EXPECTED_COMMANDS = {
    "runtime_status", "web_search", "web_fetch", "run_research",
    "trading_runtime_status", "workspace_list", "workspace_search",
    "workspace_read", "workspace_read_pdf", "workspace_inspect_python", "workspace_write",
    "workspace_edit", "run_tests",
    # Phase 5F: restored ORIGINAL knowledge commands (niblit_core.py)
    "recall", "acquired_data", "knowledge_stats", "memory",
    # Phase 5G: evidence-traced ORIGINAL read-only commands (niblit_core.py)
} | {spec["canonical_id"] for spec in ORIGINAL_READONLY_PROMOTIONS.values()}


class FakeCore:
    def __init__(self, runtime=None):
        self.db = None
        self.trading_runtime_manager = runtime


@pytest.fixture()
def isolated(tmp_path, monkeypatch):
    """Isolated workspace root + permission store + fresh loop singleton."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "README.md").write_text("# smoke\n governed line\n", encoding="utf-8")
    monkeypatch.setenv("NIBLIT_WORKSPACE_ROOT", str(ws))
    monkeypatch.setattr(pmod, "PERM_FILE", str(tmp_path / "perms.json"))
    reset_governed_tool_loop()
    yield ws
    reset_governed_tool_loop()


def _no_core():
    return None


def _find(registry, name):
    for command in registry["commands"]:
        if command["name"] == name:
            return command
    raise AssertionError(name)


# ---------------------------------------------------------------------------
# Discovery (§16 command discovery)
# ---------------------------------------------------------------------------

def test_registry_lists_exactly_the_governed_capabilities(isolated):
    reg = list_governed_commands(_no_core)
    names = {c["name"] for c in reg["commands"]}
    assert names == EXPECTED_COMMANDS
    assert reg["count"] == len(EXPECTED_COMMANDS)
    assert reg["source"] == "core_tool_runtime.governed_registry"
    for command in reg["commands"]:
        for field in ("description", "category", "input_schema", "state",
                      "risk_class", "side_effect_level",
                      "requires_authorization", "execution_enabled"):
            assert field in command, (command["name"], field)
        assert command["input_schema"].get("type") == "object"


def test_registry_states_are_truthful(isolated):
    reg = list_governed_commands(_no_core)
    states = {c["name"]: c["state"] for c in reg["commands"]}
    # Trading runtime missing -> registered but UNAVAILABLE (never EXECUTABLE).
    assert states["trading_runtime_status"] == "UNAVAILABLE"
    assert not _find(reg, "trading_runtime_status")["execution_enabled"]
    # Mutations need an explicit operator grant.
    for name in ("workspace_write", "workspace_edit", "run_tests"):
        assert states[name] == "REQUIRES_AUTHORIZATION", name
    # Read-only surface is executable right now.
    for name in ("runtime_status", "workspace_read", "workspace_search"):
        assert states[name] == "EXECUTABLE", name


def test_trading_becomes_executable_with_real_runtime(isolated):
    reg = list_governed_commands(lambda: FakeCore(runtime=object()))
    states = {c["name"]: c["state"] for c in reg["commands"]}
    assert states["trading_runtime_status"] == "EXECUTABLE"


def test_grant_flips_mutation_state_to_executable(isolated):
    mgr = pmod.PermissionManager()
    mgr.perms = {"command.workspace_write": True}
    mgr.save()
    reg = list_governed_commands(_no_core)
    states = {c["name"]: c["state"] for c in reg["commands"]}
    assert states["workspace_write"] == "EXECUTABLE"
    assert states["workspace_edit"] == "REQUIRES_AUTHORIZATION"  # untouched


def test_research_budgets_are_structural_not_ui_raisable(isolated):
    reg = list_governed_commands(_no_core)
    budgets = reg["research_budgets"]
    assert budgets == {"max_searches": HARD_CAP_SEARCHES,
                       "max_fetches": HARD_CAP_FETCHES,
                       "max_rounds": HARD_CAP_ROUNDS,
                       "ui_can_raise": False}


# ---------------------------------------------------------------------------
# Execution (§16 command execution) - real results only
# ---------------------------------------------------------------------------

def test_execute_returns_real_file_content(isolated):
    out = execute_governed_command(_no_core, "workspace_read",
                                   {"path": "README.md"}, "t-read")
    assert out["status"] == "success", out
    assert "governed line" in out["result"]["content"]
    assert out["governance"]["executor"] == "core_tool_runtime.LlmToolLoop.invoke"
    assert out["governance"]["schema_validated"] is True


def test_execute_runtime_status_real_dispatch(isolated):
    out = execute_governed_command(_no_core, "runtime_status", {}, "t-status")
    assert out["status"] == "success", out
    assert isinstance(out["result"], dict) and "status" in out["result"]


def test_unknown_command_rejected_never_substituted(isolated):
    for name in ("import os", "__import__", "trading_execute", "workspace_delete"):
        out = execute_governed_command(_no_core, name, {}, "t-unknown")
        assert out["status"] == "rejected", (name, out)
        assert "unknown_command" in out["error"]
        assert out["result"] is None


def test_missing_required_argument_rejected(isolated):
    out = execute_governed_command(_no_core, "workspace_read", {}, "t-missing")
    assert out["status"] == "rejected"
    assert "missing" in out["error"]


def test_unknown_argument_rejected(isolated):
    out = execute_governed_command(_no_core, "runtime_status",
                                   {"payload": "evil"}, "t-extra")
    assert out["status"] == "rejected"
    assert "unknown keys" in out["error"]


def test_non_object_arguments_rejected(isolated):
    out = execute_governed_command(_no_core, "runtime_status", ["x"], "t-type")
    assert out["status"] == "rejected"


def test_unavailable_capability_is_not_dispatched(isolated):
    out = execute_governed_command(_no_core, "trading_runtime_status", {},
                                   "t-unavail")
    assert out["status"] == "unavailable"
    assert out["result"] is None


def test_mutation_blocked_then_executes_after_grant(isolated):
    blocked = execute_governed_command(
        _no_core, "workspace_write",
        {"path": "made_by_command.txt", "content": "real"}, "t-auth1")
    assert blocked["status"] == "authorization_required"
    assert blocked["result"] is None
    assert blocked["authorization_action"] == "command.workspace_write"
    assert not (isolated / "made_by_command.txt").exists()

    mgr = pmod.PermissionManager()
    mgr.perms = {"command.workspace_write": True}
    mgr.save()
    allowed = execute_governed_command(
        _no_core, "workspace_write",
        {"path": "made_by_command.txt", "content": "real"}, "t-auth2")
    assert allowed["status"] == "success", allowed
    assert (isolated / "made_by_command.txt").read_text(encoding="utf-8") == "real"


# ---------------------------------------------------------------------------
# Security (§16 security)
# ---------------------------------------------------------------------------

def test_no_trading_execution_surface_registered(isolated):
    reg = list_governed_commands(_no_core)
    dumped = json.dumps(reg)
    for forbidden in FORBIDDEN_EXECUTION_NAMES:
        assert forbidden not in dumped, forbidden
    assert "place_order" not in {c["name"] for c in reg["commands"]}


def test_cannot_invoke_arbitrary_python(isolated):
    out = execute_governed_command(_no_core, "os.system", {"cmd": "dir"}, "t-py")
    assert out["status"] == "rejected"


def test_workspace_escape_answered_truthfully_not_followed(isolated):
    for bad_path in ("../outside.txt", "C:\\Windows\\win.ini", "/etc/passwd"):
        out = execute_governed_command(_no_core, "workspace_read",
                                       {"path": bad_path}, "t-escape")
        # Dispatch happens (schema valid); the GOVERNED TOOL rejects the
        # escape and answers with an error - it never reads outside files.
        assert out["status"] == "success", bad_path
        assert "error" in out["result"], bad_path


def test_cannot_self_authorize_via_arguments(isolated):
    out = execute_governed_command(
        _no_core, "workspace_write",
        {"path": "x.txt", "content": "y",
         "command.workspace_write": True},  # sneaked permission flag
        "t-selfauth")
    assert out["status"] == "rejected"  # unknown keys -> schema rejection
    assert not (isolated / "x.txt").exists()


def test_command_metadata_matches_declared_permissions(isolated):
    for name, meta in GOVERNED_COMMAND_METADATA.items():
        if meta["requires_authorization"]:
            assert name in COMMAND_PERMISSION_ACTIONS, name


def test_non_serializable_result_is_json_safe(isolated):
    """Regression (found live): a capability result embedding a runtime object
    (e.g. a market-data provider) must not 500 the command endpoint; the
    command boundary coerces non-JSON leaves to str, like the LLM loop does."""
    loop = ctr.get_governed_tool_loop(lambda: None)
    ctr.GOVERNED_COMMAND_METADATA["p5e_weird"] = {
        "category": "Test", "risk_class": "none",
        "side_effect_level": "read_only", "requires_authorization": False,
        "availability": lambda core: True,
    }
    loop.register_capability(
        "p5e_weird",
        lambda **a: {"provider": object()},
        {"type": "function",
         "function": {
             "name": "p5e_weird",
             "description": "x",
             "parameters": {"type": "object", "properties": {},
                            "additionalProperties": False}}})
    out = execute_governed_command(lambda: None, "p5e_weird", {})
    assert out["status"] == "success", out
    assert isinstance(out["result"]["provider"], str)
    json.dumps(out)  # fully serializable


# ---------------------------------------------------------------------------
# Events (§15)
# ---------------------------------------------------------------------------

def test_events_record_lifecycle(isolated):
    events: list = []
    bus = get_event_bus()
    bus.subscribe_all(events.append)
    try:
        execute_governed_command(_no_core, "workspace_read",
                                 {"path": "README.md"}, "ev-1")
        execute_governed_command(_no_core, "nope", {}, "ev-2")
        execute_governed_command(_no_core, "workspace_write",
                                 {"path": "a.txt", "content": "b"}, "ev-3")
    finally:
        try:
            bus._wildcard_handlers.remove(events.append)  # test isolation
        except ValueError:  # pragma: no cover
            pass

    types = [e.type for e in events]
    assert "command.execution.started" in types
    assert "command.execution.completed" in types
    assert "command.execution.rejected" in types  # unknown command
    assert "command.authorization.requested" in types  # workspace_write
    started = [e for e in events if e.type == "command.execution.started"]
    assert started[0].payload["command"] == "workspace_read"
    assert started[0].source == "core_tool_runtime"


# ---------------------------------------------------------------------------
# Endpoints (§5 command execution endpoint)
# ---------------------------------------------------------------------------

def _client():
    testclient = pytest.importorskip("fastapi.testclient")
    import server as server_module
    return testclient.TestClient(server_module.app), server_module


def test_api_governed_registry(isolated):
    client, _ = _client()
    resp = client.get("/api/commands/governed")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == len(EXPECTED_COMMANDS)
    assert {c["name"] for c in body["commands"]} == EXPECTED_COMMANDS


def test_api_execute_real_result(isolated):
    client, _ = _client()
    resp = client.post("/api/commands/execute", json={
        "command": "workspace_read",
        "arguments": {"path": "README.md"},
        "request_id": "api-1",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["command"] == "workspace_read"
    assert body["status"] == "success"
    assert "governed line" in body["result"]["content"]
    assert body["request_id"] == "api-1"
    assert body["governance"]["schema_validated"] is True


def test_api_execute_unknown_rejected(isolated):
    client, _ = _client()
    resp = client.post("/api/commands/execute", json={
        "command": "shutdown_everything", "arguments": {}})
    body = resp.json()
    assert body["status"] == "rejected"
    assert "unknown_command" in body["error"]


def test_api_execute_authorization_required(isolated):
    client, _ = _client()
    resp = client.post("/api/commands/execute", json={
        "command": "workspace_edit",
        "arguments": {"path": "README.md", "old_text": "a", "new_text": "b"}})
    body = resp.json()
    assert body["status"] == "authorization_required"
    assert body["result"] is None


def test_api_static_catalogue_untouched(isolated):
    """The dashboard nav contract (GET /api/commands) is preserved."""
    client, server_module = _client()
    resp = client.get("/api/commands")
    assert resp.status_code == 200
    body = resp.json()
    assert body["commands"] == server_module.COMMANDS


# ---------------------------------------------------------------------------
# Phase 5F: restored ORIGINAL Niblit knowledge commands
# (source: niblit_core.py _cmd_recall / _cmd_acquired_data /
#  _cmd_knowledge_stats / register("memory", ...); implementation:
#  niblit_memory.KnowledgeDB.recall / get_acquired_data /
#  get_knowledge_summary / recent_interactions)
# ---------------------------------------------------------------------------

RESTORED = ("recall", "acquired_data", "knowledge_stats", "memory")

EXPECTED_ALIASES = {
    "recall": {"original_name": "recall", "aliases": []},
    "acquired_data": {"original_name": "acquired data",
                      "aliases": ["acquired data"]},
    "knowledge_stats": {"original_name": "knowledge stats",
                        "aliases": ["knowledge stats"]},
    "memory": {"original_name": "memory", "aliases": []},
}


@pytest.fixture()
def real_kb(tmp_path):
    """A REAL KnowledgeDB instance (singleton reset) backed by tmp_path."""
    import niblit_memory
    from niblit_memory import KnowledgeDB

    niblit_memory.KnowledgeDB._instance = None  # singleton isolation
    kb = KnowledgeDB(str(tmp_path / "niblit_memory.json"))
    kb.add_fact("p5f_e5_embedding",
                "Niblit uses intfloat/multilingual-e5-small for embeddings",
                tags=["phase5f", "research"])
    kb.add_fact("p5f_recall_note",
                "the original recall command searches KnowledgeDB facts",
                tags=["phase5f", "restore"])
    kb.add_interaction("what did phase 5F restore?",
                       "the original niblit knowledge commands",
                       source="p5f_test")
    kb.store_learning({"topic": "phase5f", "note": "commands restored"})
    yield kb
    try:
        kb.shutdown()
    except Exception:
        pass
    niblit_memory.KnowledgeDB._instance = None


def test_restored_commands_are_registered(isolated):
    reg = list_governed_commands(_no_core)
    by_name = {c["name"]: c for c in reg["commands"]}
    for name in RESTORED:
        assert name in by_name, name
        meta = by_name[name]
        assert meta["category"] == "Knowledge"
        assert meta["side_effect_level"] == "read_only"
        assert meta["requires_authorization"] is False
        assert meta["risk_class"] == "none"


def test_original_names_preserved_as_aliases(isolated):
    from modules.core_tool_runtime import ORIGINAL_COMMAND_ALIASES, resolve_command_alias

    for name in RESTORED:
        assert ORIGINAL_COMMAND_ALIASES[name] == EXPECTED_ALIASES[name]

    # Verbal original names resolve to the canonical governed tool names.
    assert resolve_command_alias("knowledge stats") == "knowledge_stats"
    assert resolve_command_alias("acquired data") == "acquired_data"
    assert resolve_command_alias("recall") == "recall"
    assert resolve_command_alias("memory") == "memory"
    # Unknown names pass through and stay rejected downstream.
    assert resolve_command_alias("not_a_command") == "not_a_command"


def test_registry_reports_original_names_and_aliases(isolated):
    reg = list_governed_commands(_no_core)
    by_name = {c["name"]: c for c in reg["commands"]}
    for name in RESTORED:
        assert by_name[name]["original_name"] == EXPECTED_ALIASES[name]["original_name"]
        assert by_name[name]["aliases"] == EXPECTED_ALIASES[name]["aliases"]


def test_restored_commands_unavailable_without_db(isolated):
    """Truthful UNAVAILABLE — no fake success when core.db is missing."""
    out = execute_governed_command(_no_core, "knowledge_stats", {}, "p5f-u1")
    assert out["status"] == "unavailable"
    assert out["result"] is None
    assert "not available" in out["error"]


def test_alias_execution_reaches_real_knowledge_db(isolated, real_kb):
    """'knowledge stats' (original verbal alias) executes the REAL
    KnowledgeDB.get_knowledge_summary through the governed path."""
    from types import SimpleNamespace

    core = SimpleNamespace(db=real_kb)
    out = execute_governed_command(lambda: core, "knowledge stats", {},
                                   "p5f-alias-1")
    assert out["command"] == "knowledge stats"          # truthful identity
    assert out["alias_of"] == "knowledge_stats"         # canonical target
    assert out["status"] == "success"
    summary = out["result"]["summary"]
    assert isinstance(summary, str) and "NIBLIT KNOWLEDGE BASE SUMMARY" in summary


def test_recall_returns_real_fact(isolated, real_kb):
    from types import SimpleNamespace

    core = SimpleNamespace(db=real_kb)
    out = execute_governed_command(
        lambda: core, "recall", {"query": "multilingual-e5-small", "limit": 5},
        "p5f-recall-1")
    assert out["status"] == "success"
    result = out["result"]
    assert result["query"] == "multilingual-e5-small"
    assert result["count"] >= 1
    flat = json.dumps(result["entries"], default=str).lower()
    assert "multilingual-e5-small" in flat


def test_memory_returns_real_interactions(isolated, real_kb):
    from types import SimpleNamespace

    core = SimpleNamespace(db=real_kb)
    out = execute_governed_command(lambda: core, "memory", {"limit": 5},
                                   "p5f-mem-1")
    assert out["status"] == "success"
    assert out["result"]["count"] >= 1
    flat = json.dumps(out["result"]["entries"], default=str).lower()
    assert "phase 5f restore" in flat


def test_acquired_data_alias_executes(isolated, real_kb):
    from types import SimpleNamespace

    core = SimpleNamespace(db=real_kb)
    out = execute_governed_command(lambda: core, "acquired data",
                                   {"limit": 5}, "p5f-acq-1")
    assert out["command"] == "acquired data"
    assert out["alias_of"] == "acquired_data"
    assert out["status"] == "success"
    assert "count" in out["result"] and "entries" in out["result"]


def test_recall_requires_query(isolated, real_kb):
    from types import SimpleNamespace

    core = SimpleNamespace(db=real_kb)
    out = execute_governed_command(lambda: core, "recall", {"limit": 3},
                                   "p5f-recall-bad")
    # Schema requires "query" -> rejected BEFORE dispatch (§6).
    assert out["status"] == "rejected"
    assert "query" in str(out["error"]).lower()


def test_restored_commands_reject_unknown_arguments(isolated, real_kb):
    from types import SimpleNamespace

    core = SimpleNamespace(db=real_kb)
    out = execute_governed_command(lambda: core, "memory",
                                   {"bogus": 1}, "p5f-mem-bad")
    assert out["status"] == "rejected"


def test_restored_events_flow(isolated, real_kb):
    """EventBus records started/completed for a restored command by alias."""
    from types import SimpleNamespace

    events: list = []
    bus = get_event_bus()
    bus.subscribe_all(events.append)
    try:
        core = SimpleNamespace(db=real_kb)
        execute_governed_command(lambda: core, "knowledge stats", {},
                                 "p5f-ev-1")
    finally:
        try:
            bus._wildcard_handlers.remove(events.append)
        except ValueError:  # pragma: no cover
            pass

    started = [e for e in events if e.type == "command.execution.started"]
    completed = [e for e in events if e.type == "command.execution.completed"]
    assert started and completed
    assert started[0].payload["command"] == "knowledge stats"
    assert started[0].payload["alias_of"] == "knowledge_stats"
    assert completed[0].payload["status"] == "success"
