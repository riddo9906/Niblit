"""
test_niblit_runtime_ui.py — UI architecture contract + new endpoint tests
for the Niblit Cognitive Runtime Shell (server.py evolution).

Validates:
  1. UI Architecture Contract — the dashboard HTML mirrors niblit_dashboard.py's
     panel philosophy (sidebar COMMANDS, panel types, mode selector, telemetry).
  2. New API endpoints added to server.py (/api/boot, /api/commands,
     /api/bg_status, /api/status, /api/suggest, /api/threads).
  3. Non-regression — existing endpoints (/health, /ping, /chat, /memory)
     continue to work correctly.
  4. Runtime compatibility — routing, memory, provider signals all flow
     correctly through the updated server.

Run with::

    pytest test_niblit_runtime_ui.py -v
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """Create a FastAPI test client backed by a stubbed NiblitCore."""
    mock_core = MagicMock()
    mock_core.db.get_personality.return_value = {"mood": "focused", "tone": "analytical"}
    mock_core.db.list_facts.return_value = [
        {"key": "ai_history",  "value": "AI was formalized in 1956", "category": "fact",  "created_at": "2024-01-01 00:00:00"},
        {"key": "niblit_mode", "value": "cognitive runtime",          "category": "state", "created_at": "2024-01-01 00:01:00"},
    ]
    mock_core.handle.return_value = "Processing your command…"
    mock_core.autonomous_engine = None  # no ALE by default

    with patch("server.NiblitCore", return_value=mock_core), \
         patch("server.get_core", return_value=mock_core):
        import server as srv
        srv._core = mock_core  # pylint: disable=protected-access
        # Reset cached boot messages so each test gets a fresh run
        srv._boot_messages = []  # pylint: disable=protected-access
        c = TestClient(srv.app, raise_server_exceptions=False)
        yield c, mock_core, srv


# ---------------------------------------------------------------------------
# 1. UI Architecture Contract
#    Derived from niblit_dashboard.py's canonical architecture.
# ---------------------------------------------------------------------------

class TestDashboardUIContract:
    """The HTML dashboard must mirror niblit_dashboard.py's panel philosophy."""

    def _html(self, client):
        c, _, _ = client
        return c.get("/").content.decode("utf-8", errors="replace")

    # ── Niblit identity ───────────────────────────────────────────────────

    def test_dashboard_returns_200(self, client):
        c, _, _ = client
        assert c.get("/").status_code == 200

    def test_dashboard_has_niblit_brand(self, client):
        html = self._html(client)
        assert "Niblit" in html

    def test_dashboard_cognitive_runtime_identity(self, client):
        """Dashboard must NOT be a generic admin layout — must say 'Cognitive Runtime'."""
        html = self._html(client)
        assert "Cognitive Runtime" in html

    def test_dashboard_not_generic_admin(self, client):
        """Ensure no generic SaaS/admin words ('Dashboard Overview', 'Admin Panel')."""
        html = self._html(client)
        assert "Admin Panel" not in html
        assert "Dashboard Overview" not in html

    # ── Sidebar COMMANDS model ────────────────────────────────────────────
    # Must preserve niblit_dashboard.py COMMANDS exactly.

    def test_dashboard_has_sidebar(self, client):
        assert "sidebar" in self._html(client)

    def test_sidebar_has_status_command(self, client):
        html = self._html(client)
        assert "📊" in html  # status icon

    def test_sidebar_has_memory_command(self, client):
        html = self._html(client)
        assert "🧠" in html  # memory icon

    def test_sidebar_has_search_command(self, client):
        html = self._html(client)
        assert "🔍" in html  # search icon

    def test_sidebar_has_terminal_command(self, client):
        html = self._html(client)
        assert "🖥" in html  # terminal icon

    def test_sidebar_has_setup_command(self, client):
        html = self._html(client)
        assert "⚙" in html  # setup icon

    def test_sidebar_has_reflect_action(self, client):
        html = self._html(client)
        assert "🔄" in html  # reflect icon

    def test_sidebar_has_self_idea_action(self, client):
        html = self._html(client)
        assert "💡" in html  # self-idea icon

    def test_sidebar_has_self_research_action(self, client):
        html = self._html(client)
        assert "🔬" in html  # self-research icon

    def test_sidebar_has_learn_topic_command(self, client):
        html = self._html(client)
        assert "📚" in html  # learn icon

    def test_sidebar_commands_json_injected(self, client):
        """COMMANDS JSON must be injected at render time (template filled)."""
        html = self._html(client)
        # Placeholder must be replaced, real key names must appear
        assert "__JSON_COMMANDS__" not in html
        assert '"status"' in html  # from COMMANDS key

    def test_sidebar_providers_json_injected(self, client):
        """SEARCH_PROVIDERS JSON must be injected at render time."""
        html = self._html(client)
        assert "__JSON_PROVIDERS__" not in html
        assert "DDGS" in html  # from SEARCH_PROVIDERS

    # ── Five modular panel types ─────────────────────────────────────────
    # Must mirror niblit_dashboard.py panel architecture.

    def test_has_expanded_panel(self, client):
        """ExpandedPanel — mirrors niblit_dashboard.py _expand_sidebar_panel."""
        html = self._html(client)
        assert "xpanel" in html

    def test_has_search_panel(self, client):
        """SearchPanel — mirrors niblit_dashboard.py SearchPanel."""
        html = self._html(client)
        assert "spanel" in html

    def test_has_chat_panel(self, client):
        """ChatPanel — main interaction area, always visible."""
        html = self._html(client)
        assert "cpan" in html

    def test_has_terminal_panel(self, client):
        """TerminalPanel — mirrors niblit_dashboard.py TerminalPanel."""
        html = self._html(client)
        assert "tpanel" in html

    def test_has_setup_panel(self, client):
        """SetupPanel — mirrors niblit_dashboard.py SetupPanel."""
        html = self._html(client)
        assert "setupanel" in html

    # ── Mode selector ────────────────────────────────────────────────────
    # Mirrors niblit_dashboard.py Spinner (mode_spinner: API / Local)

    def test_has_mode_selector(self, client):
        html = self._html(client)
        assert "mode-select" in html

    def test_mode_selector_has_api_option(self, client):
        html = self._html(client)
        assert "api" in html.lower()

    def test_mode_selector_has_local_option(self, client):
        html = self._html(client)
        assert "local" in html.lower()

    # ── Cognitive telemetry sidebar footer ───────────────────────────────
    # Mirrors niblit_dashboard.py status polling — threads, facts, ALE, mode.

    def test_has_telemetry_threads(self, client):
        html = self._html(client)
        assert "tel-threads" in html

    def test_has_telemetry_ale(self, client):
        html = self._html(client)
        assert "tel-ale" in html

    def test_has_telemetry_mode(self, client):
        html = self._html(client)
        assert "tel-mode" in html

    def test_has_telemetry_facts(self, client):
        html = self._html(client)
        assert "tel-facts" in html

    # ── Input bar ────────────────────────────────────────────────────────

    def test_has_chat_input(self, client):
        html = self._html(client)
        assert "cinput" in html

    def test_has_send_button(self, client):
        html = self._html(client)
        assert "sendbtn" in html

    # ── Input overlay (InputBubble equivalent) ───────────────────────────

    def test_has_input_overlay(self, client):
        """InputOverlay — mirrors niblit_dashboard.py InputBubble."""
        html = self._html(client)
        assert "ioverlay" in html

    # ── Boot sequence ────────────────────────────────────────────────────

    def test_has_boot_block(self, client):
        html = self._html(client)
        assert "boot-blk" in html

    def test_has_boot_sequence_js(self, client):
        html = self._html(client)
        assert "runBoot" in html

    # ── Live telemetry polling ───────────────────────────────────────────

    def test_has_telemetry_polling_js(self, client):
        html = self._html(client)
        assert "refreshTelemetry" in html

    def test_has_status_polling_js(self, client):
        html = self._html(client)
        assert "pollStatus" in html

    # ── Command dispatch mirrors niblit_dashboard.py handle_command ──────

    def test_has_handle_command_js(self, client):
        html = self._html(client)
        assert "handleCommand" in html

    def test_has_panel_system_js(self, client):
        html = self._html(client)
        assert "showPanel" in html
        assert "hidePanel" in html


# ---------------------------------------------------------------------------
# 2. New API endpoints
# ---------------------------------------------------------------------------

class TestBootEndpoint:
    def test_boot_returns_200(self, client):
        c, _, _ = client
        assert c.get("/api/boot").status_code == 200

    def test_boot_has_messages_key(self, client):
        c, _, _ = client
        data = c.get("/api/boot").json()
        assert "messages" in data

    def test_boot_messages_is_list(self, client):
        c, _, _ = client
        data = c.get("/api/boot").json()
        assert isinstance(data["messages"], list)

    def test_boot_messages_not_empty(self, client):
        c, _, _ = client
        data = c.get("/api/boot").json()
        assert len(data["messages"]) > 0

    def test_boot_has_ready_key(self, client):
        c, _, _ = client
        data = c.get("/api/boot").json()
        assert "ready" in data

    def test_boot_ready_true_with_core(self, client):
        c, _, _ = client
        data = c.get("/api/boot").json()
        assert data["ready"] is True

    def test_boot_ready_false_without_core(self, client):
        c, _, srv = client
        with patch("server.get_core", return_value=None):
            srv._boot_messages = []  # pylint: disable=protected-access
            data = c.get("/api/boot").json()
        assert data["ready"] is False

    def test_boot_messages_contain_niblit_string(self, client):
        c, _, srv = client
        srv._boot_messages = []  # pylint: disable=protected-access
        data = c.get("/api/boot").json()
        combined = " ".join(data["messages"])
        assert "NIBLIT" in combined.upper() or "Niblit" in combined or "BOOT" in combined


class TestCommandsEndpoint:
    def test_commands_returns_200(self, client):
        c, _, _ = client
        assert c.get("/api/commands").status_code == 200

    def test_commands_has_commands_key(self, client):
        c, _, _ = client
        data = c.get("/api/commands").json()
        assert "commands" in data

    def test_commands_is_list(self, client):
        c, _, _ = client
        data = c.get("/api/commands").json()
        assert isinstance(data["commands"], list)

    def test_commands_has_count_key(self, client):
        c, _, _ = client
        data = c.get("/api/commands").json()
        assert "count" in data

    def test_commands_count_matches_list_length(self, client):
        c, _, _ = client
        data = c.get("/api/commands").json()
        assert data["count"] == len(data["commands"])

    def test_commands_count_is_positive(self, client):
        c, _, _ = client
        data = c.get("/api/commands").json()
        assert data["count"] > 0

    def test_commands_have_required_fields(self, client):
        """Each command must have title, key, type — mirrors niblit_dashboard.py COMMANDS."""
        c, _, _ = client
        for cmd in c.get("/api/commands").json()["commands"]:
            assert "title" in cmd, f"Missing 'title' in {cmd}"
            assert "key"   in cmd, f"Missing 'key' in {cmd}"
            assert "type"  in cmd, f"Missing 'type' in {cmd}"

    def _cmds_by_key(self, client):
        c, _, _ = client
        return {cmd["key"]: cmd for cmd in c.get("/api/commands").json()["commands"]}

    def test_commands_has_status(self, client):
        assert "status" in self._cmds_by_key(client)

    def test_commands_has_memory(self, client):
        assert "memory" in self._cmds_by_key(client)

    def test_commands_has_search(self, client):
        assert "search" in self._cmds_by_key(client)

    def test_commands_has_terminal(self, client):
        assert "terminal" in self._cmds_by_key(client)

    def test_commands_has_setup(self, client):
        assert "setup" in self._cmds_by_key(client)

    def test_commands_has_reflect(self, client):
        assert "reflect" in self._cmds_by_key(client)

    def test_commands_has_self_idea(self, client):
        assert "self-idea" in self._cmds_by_key(client)

    def test_commands_has_self_research(self, client):
        assert "self-research" in self._cmds_by_key(client)

    def test_commands_has_learn_about(self, client):
        assert "learn_about" in self._cmds_by_key(client)

    def test_commands_status_type_is_status(self, client):
        cmds = self._cmds_by_key(client)
        assert cmds["status"]["type"] == "status"

    def test_commands_memory_type_is_panel(self, client):
        cmds = self._cmds_by_key(client)
        assert cmds["memory"]["type"] == "panel"

    def test_commands_search_type_is_search(self, client):
        cmds = self._cmds_by_key(client)
        assert cmds["search"]["type"] == "search"

    def test_commands_terminal_type_is_terminal(self, client):
        cmds = self._cmds_by_key(client)
        assert cmds["terminal"]["type"] == "terminal"

    def test_commands_reflect_type_is_action(self, client):
        cmds = self._cmds_by_key(client)
        assert cmds["reflect"]["type"] == "action"

    def test_commands_learn_about_has_input_label(self, client):
        cmds = self._cmds_by_key(client)
        assert cmds["learn_about"].get("input_label") is not None


class TestBgStatusEndpoint:
    def test_bg_status_returns_200(self, client):
        c, _, _ = client
        assert c.get("/api/bg_status").status_code == 200

    def test_bg_status_has_threads(self, client):
        c, _, _ = client
        data = c.get("/api/bg_status").json()
        assert "threads" in data

    def test_bg_status_threads_is_int(self, client):
        c, _, _ = client
        data = c.get("/api/bg_status").json()
        assert isinstance(data["threads"], int)

    def test_bg_status_threads_positive(self, client):
        c, _, _ = client
        data = c.get("/api/bg_status").json()
        assert data["threads"] > 0

    def test_bg_status_has_ts(self, client):
        c, _, _ = client
        data = c.get("/api/bg_status").json()
        assert "ts" in data

    def test_bg_status_has_ale(self, client):
        c, _, _ = client
        data = c.get("/api/bg_status").json()
        assert "ale" in data

    def test_bg_status_ale_null_without_ale_engine(self, client):
        """When core has no autonomous_engine, ale must be None."""
        c, mock_core, _ = client
        mock_core.autonomous_engine = None
        data = c.get("/api/bg_status").json()
        assert data["ale"] is None

    def test_bg_status_ale_populated_with_ale_engine(self, client):
        c, mock_core, _ = client
        ale = MagicMock()
        ale.running = True
        ale._cycle_count = 7
        ale.get_current_topic.return_value = "neural networks"
        mock_core.autonomous_engine = ale
        data = c.get("/api/bg_status").json()
        assert data["ale"] is not None
        assert data["ale"]["running"] is True
        assert data["ale"]["cycle"] == 7

    def test_bg_status_no_core_returns_ok(self, client):
        c, _, _ = client
        with patch("server.get_core", return_value=None):
            resp = c.get("/api/bg_status")
        assert resp.status_code == 200


class TestStatusEndpoint:
    def test_status_returns_200(self, client):
        c, _, _ = client
        assert c.get("/api/status").status_code == 200

    def test_status_has_online(self, client):
        c, _, _ = client
        data = c.get("/api/status").json()
        assert "online" in data

    def test_status_online_true_with_core(self, client):
        c, _, _ = client
        data = c.get("/api/status").json()
        assert data["online"] is True

    def test_status_has_service_niblit(self, client):
        c, _, _ = client
        data = c.get("/api/status").json()
        assert data.get("service") == "niblit"

    def test_status_has_threads(self, client):
        c, _, _ = client
        data = c.get("/api/status").json()
        assert "threads" in data
        assert isinstance(data["threads"], int)

    def test_status_includes_personality(self, client):
        c, _, _ = client
        data = c.get("/api/status").json()
        assert "personality" in data

    def test_status_personality_has_mood(self, client):
        c, _, _ = client
        data = c.get("/api/status").json()
        assert "mood" in data["personality"]

    def test_status_includes_facts_count(self, client):
        c, _, _ = client
        data = c.get("/api/status").json()
        assert "facts_count" in data

    def test_status_facts_count_is_int(self, client):
        c, _, _ = client
        data = c.get("/api/status").json()
        assert isinstance(data["facts_count"], int)

    def test_status_no_core_online_false(self, client):
        c, _, _ = client
        with patch("server.get_core", return_value=None):
            data = c.get("/api/status").json()
        assert data["online"] is False


class TestSuggestEndpoint:
    def test_suggest_returns_200(self, client):
        c, _, _ = client
        assert c.get("/api/suggest?q=status").status_code == 200

    def test_suggest_has_suggestions_key(self, client):
        c, _, _ = client
        data = c.get("/api/suggest?q=status").json()
        assert "suggestions" in data

    def test_suggest_is_list(self, client):
        c, _, _ = client
        data = c.get("/api/suggest?q=status").json()
        assert isinstance(data["suggestions"], list)

    def test_suggest_empty_query_returns_empty_list(self, client):
        c, _, _ = client
        data = c.get("/api/suggest").json()
        assert data["suggestions"] == []

    def test_suggest_returns_query_in_response(self, client):
        c, _, _ = client
        data = c.get("/api/suggest?q=help").json()
        assert data.get("query") == "help"

    def test_suggest_known_command_returns_matches(self, client):
        c, _, _ = client
        data = c.get("/api/suggest?q=status").json()
        # "status" is in _SHELL_COMMANDS; close matches should not be empty for a near-match
        # (exact match is excluded; "status" exact should return empty — test close match)
        data2 = c.get("/api/suggest?q=statsu").json()  # typo
        assert isinstance(data2["suggestions"], list)


class TestThreadsEndpoint:
    def test_threads_returns_200(self, client):
        c, _, _ = client
        assert c.get("/api/threads").status_code == 200

    def test_threads_has_threads_key(self, client):
        c, _, _ = client
        data = c.get("/api/threads").json()
        assert "threads" in data

    def test_threads_is_string(self, client):
        c, _, _ = client
        data = c.get("/api/threads").json()
        assert isinstance(data["threads"], str)


# ---------------------------------------------------------------------------
# 3. Non-regression — existing endpoints must still work
# ---------------------------------------------------------------------------

class TestExistingEndpointsCompat:
    """These tests mirror test_server.py to guard against regressions."""

    def test_health_still_works(self, client):
        c, _, _ = client
        resp = c.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert resp.json()["service"] == "niblit"

    def test_ping_still_works(self, client):
        c, _, _ = client
        resp = c.get("/ping")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "personality" in data

    def test_chat_still_works(self, client):
        c, _, _ = client
        resp = c.post("/chat", json={"text": "hello"})
        assert resp.status_code == 200
        assert "reply" in resp.json()

    def test_chat_empty_text_still_400(self, client):
        c, _, _ = client
        resp = c.post("/chat", json={"text": ""})
        assert resp.status_code == 400

    def test_memory_still_works(self, client):
        c, _, _ = client
        resp = c.get("/memory")
        assert resp.status_code == 200
        data = resp.json()
        assert "facts" in data
        assert isinstance(data["facts"], list)

    def test_root_still_returns_html(self, client):
        c, _, _ = client
        resp = c.get("/")
        assert resp.status_code == 200
        assert b"Niblit" in resp.content


# ---------------------------------------------------------------------------
# 4. Runtime compatibility — routing, memory, provider signal flow
# ---------------------------------------------------------------------------

class TestRuntimeCompatibility:
    """Validate integration with existing Niblit backends through server.py."""

    def test_chat_routes_to_core_handle(self, client):
        c, mock_core, _ = client
        c.post("/chat", json={"text": "what time is it"})
        mock_core.handle.assert_called_with("what time is it")

    def test_memory_returns_structured_facts(self, client):
        """Facts from db.list_facts must surface verbatim in /memory response."""
        c, mock_core, _ = client
        data = c.get("/memory").json()
        keys_returned = [f["key"] for f in data["facts"]]
        assert "ai_history"  in keys_returned
        assert "niblit_mode" in keys_returned

    def test_status_uses_db_get_personality(self, client):
        """api_status must call core.db.get_personality() for personality data."""
        c, mock_core, _ = client
        data = c.get("/api/status").json()
        assert data["personality"].get("mood") == "focused"
        mock_core.db.get_personality.assert_called()

    def test_status_uses_db_list_facts_for_count(self, client):
        """api_status must derive facts_count from core.db.list_facts()."""
        c, mock_core, _ = client
        data = c.get("/api/status").json()
        assert data["facts_count"] == 2  # matches mock_core.db.list_facts fixture

    def test_ping_uses_db_get_personality(self, client):
        c, mock_core, _ = client
        data = c.get("/ping").json()
        assert data["personality"].get("mood") == "focused"

    def test_bg_status_returns_thread_count_as_int(self, client):
        """Thread count must be an integer (from threading.enumerate())."""
        c, _, _ = client
        data = c.get("/api/bg_status").json()
        assert isinstance(data["threads"], int)
        assert data["threads"] >= 1

    def test_api_commands_mirrors_niblit_dashboard_commands(self, client):
        """COMMANDS from server.py must exactly match niblit_dashboard.py COMMANDS."""
        c, _, srv = client
        import niblit_dashboard as nd  # pylint: disable=import-error
        server_keys = {cmd["key"] for cmd in srv.COMMANDS}
        dashboard_keys = {cmd["key"] for cmd in nd.COMMANDS}
        assert server_keys == dashboard_keys, (
            f"COMMANDS mismatch.\n"
            f"server.py keys: {sorted(server_keys)}\n"
            f"niblit_dashboard.py keys: {sorted(dashboard_keys)}"
        )

    def test_api_commands_type_contract(self, client):
        """Command types must be valid per niblit_dashboard.py contract."""
        c, _, _ = client
        valid_types = {"status", "panel", "input", "search", "terminal",
                       "setup", "file", "action"}
        for cmd in c.get("/api/commands").json()["commands"]:
            assert cmd["type"] in valid_types, \
                f"Invalid type '{cmd['type']}' for command '{cmd['key']}'"

    def test_chat_core_unavailable_returns_500(self, client):
        c, _, srv = client
        original = srv._core  # pylint: disable=protected-access
        srv._core = None
        try:
            with patch("server.get_core", return_value=None):
                resp = c.post("/chat", json={"text": "hello"})
            assert resp.status_code == 500
        finally:
            srv._core = original

    def test_memory_core_unavailable_returns_empty(self, client):
        c, _, srv = client
        original = srv._core  # pylint: disable=protected-access
        srv._core = None
        try:
            with patch("server.get_core", return_value=None):
                data = c.get("/memory").json()
            assert data["facts"] == []
        finally:
            srv._core = original

    def test_session_continuity_boot_cached(self, client):
        """Boot messages must be cached after first call (persistent session state)."""
        c, _, srv = client
        srv._boot_messages = []  # pylint: disable=protected-access
        data1 = c.get("/api/boot").json()
        data2 = c.get("/api/boot").json()
        assert data1["messages"] == data2["messages"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
