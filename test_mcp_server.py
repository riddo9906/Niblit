"""
test_mcp_server.py — Unit tests for modules/mcp_server.py

All transport-level I/O is avoided; tests exercise the JSON-RPC handler
directly (no live Niblit core, no network calls).

Run with::

    pytest test_mcp_server.py -v
"""

from unittest.mock import MagicMock, patch
import json
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_handler():
    """Return a fresh NiblitMCPHandler (no core attached)."""
    from modules.mcp_server import NiblitMCPHandler
    return NiblitMCPHandler()


def _rpc(method, params=None, msg_id=1):
    return {"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params or {}}


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------

class TestInitialize:
    def test_returns_protocol_version(self):
        h = _make_handler()
        resp = h.handle(_rpc("initialize"))
        assert resp is not None
        assert resp["id"] == 1
        result = resp["result"]
        assert "protocolVersion" in result
        assert result["protocolVersion"] == "2024-11-05"

    def test_returns_server_info(self):
        h = _make_handler()
        resp = h.handle(_rpc("initialize"))
        info = resp["result"]["serverInfo"]
        assert info["name"] == "niblit"
        assert "version" in info

    def test_returns_capabilities(self):
        h = _make_handler()
        resp = h.handle(_rpc("initialize"))
        caps = resp["result"]["capabilities"]
        assert "tools" in caps
        assert "resources" in caps
        assert "prompts" in caps


# ---------------------------------------------------------------------------
# ping
# ---------------------------------------------------------------------------

class TestPing:
    def test_ping_returns_empty_result(self):
        h = _make_handler()
        resp = h.handle(_rpc("ping"))
        assert resp["result"] == {}


# ---------------------------------------------------------------------------
# tools/list
# ---------------------------------------------------------------------------

class TestToolsList:
    def test_returns_tools_list(self):
        h = _make_handler()
        resp = h.handle(_rpc("tools/list"))
        tools = resp["result"]["tools"]
        assert isinstance(tools, list)
        assert len(tools) > 0

    def test_niblit_chat_tool_present(self):
        h = _make_handler()
        resp = h.handle(_rpc("tools/list"))
        names = [t["name"] for t in resp["result"]["tools"]]
        assert "niblit_chat" in names

    def test_all_expected_tools_present(self):
        h = _make_handler()
        resp = h.handle(_rpc("tools/list"))
        names = {t["name"] for t in resp["result"]["tools"]}
        expected = {
            "niblit_chat", "niblit_search", "niblit_status",
            "niblit_learn", "niblit_remember", "niblit_recall",
            "niblit_generate_code", "niblit_serpex_search",
            "niblit_searchcode",
        }
        assert expected.issubset(names)

    def test_each_tool_has_required_fields(self):
        h = _make_handler()
        tools = h.handle(_rpc("tools/list"))["result"]["tools"]
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool


# ---------------------------------------------------------------------------
# tools/call — without core
# ---------------------------------------------------------------------------

class TestToolsCallWithoutCore:
    """All tools should degrade gracefully when no core is attached."""

    def _call(self, tool_name, arguments=None):
        h = _make_handler()
        return h.handle(_rpc("tools/call", {"name": tool_name, "arguments": arguments or {}}))

    def test_niblit_chat_graceful(self):
        resp = self._call("niblit_chat", {"message": "hello"})
        assert resp["result"]["content"][0]["type"] == "text"

    def test_niblit_status_graceful(self):
        resp = self._call("niblit_status")
        text = resp["result"]["content"][0]["text"]
        data = json.loads(text)
        assert "status" in data

    def test_niblit_search_graceful(self):
        resp = self._call("niblit_search", {"query": "python asyncio"})
        assert resp["result"]["content"][0]["type"] == "text"

    def test_niblit_learn_graceful(self):
        resp = self._call("niblit_learn")
        assert resp["result"]["content"][0]["type"] == "text"

    def test_niblit_remember_no_key_returns_error(self):
        resp = self._call("niblit_remember", {"value": "foo"})
        text = resp["result"]["content"][0]["text"]
        assert "error" in text.lower() or "required" in text.lower()

    def test_niblit_recall_graceful(self):
        resp = self._call("niblit_recall", {"query": "foo"})
        assert resp["result"]["content"][0]["type"] == "text"

    def test_niblit_generate_code_graceful(self):
        resp = self._call("niblit_generate_code", {"language": "python", "purpose": "hello world"})
        assert resp["result"]["content"][0]["type"] == "text"

    def test_niblit_serpex_graceful(self):
        resp = self._call("niblit_serpex_search", {"query": "asyncio"})
        assert resp["result"]["content"][0]["type"] == "text"

    def test_niblit_searchcode_graceful(self):
        """niblit_searchcode should degrade gracefully (no core, no network)."""
        from unittest.mock import patch
        # SearchcodeSearch will fall back to REST but requests will fail — still no exception
        with patch("modules.searchcode_search.requests.get", side_effect=Exception("offline")):
            with patch("modules.searchcode_search.requests.post", side_effect=Exception("offline")):
                resp = self._call("niblit_searchcode", {"query": "asyncio python"})
        text = resp["result"]["content"][0]["text"]
        assert isinstance(text, str)

    def test_niblit_searchcode_empty_query_returns_error(self):
        resp = self._call("niblit_searchcode", {"query": ""})
        text = resp["result"]["content"][0]["text"]
        assert "error" in text.lower()


# ---------------------------------------------------------------------------
# tools/call — with mocked core
# ---------------------------------------------------------------------------

class TestToolsCallWithCore:
    def _handler_with_core(self):
        h = _make_handler()
        core = MagicMock()
        core.handle.return_value = "Hello from Niblit!"
        core.internet = None
        core.db = None
        core.llm = None
        core.code_generator = None
        core.serpex_research_agent = None
        core.autonomous_engine = None
        h.set_core(core)
        return h

    def test_niblit_chat_calls_core_handle(self):
        h = self._handler_with_core()
        resp = h.handle(_rpc("tools/call", {"name": "niblit_chat", "arguments": {"message": "hi"}}))
        text = resp["result"]["content"][0]["text"]
        assert "Hello from Niblit!" in text

    def test_niblit_status_with_core(self):
        h = self._handler_with_core()
        # Remove auto-MagicMock get_status so the fallback status dict path runs
        del h._core.get_status
        resp = h.handle(_rpc("tools/call", {"name": "niblit_status", "arguments": {}}))
        text = resp["result"]["content"][0]["text"]
        data = json.loads(text)
        assert data["status"] == "online"
        assert "modules" in data

    def test_niblit_remember_stores_in_db(self):
        h = self._handler_with_core()
        mock_db = MagicMock()
        h._core.db = mock_db
        resp = h.handle(_rpc("tools/call", {
            "name": "niblit_remember",
            "arguments": {"key": "test-key", "value": "test-value"},
        }))
        mock_db.add_fact.assert_called()
        text = resp["result"]["content"][0]["text"]
        assert "test-key" in text

    def test_niblit_learn_adds_topic(self):
        h = self._handler_with_core()
        mock_ae = MagicMock()
        mock_ae._autonomous_research.return_value = "research done"
        h._core.autonomous_engine = mock_ae
        resp = h.handle(_rpc("tools/call", {
            "name": "niblit_learn",
            "arguments": {"topic": "quantum computing"},
        }))
        mock_ae.add_research_topic.assert_called_with("quantum computing")
        text = resp["result"]["content"][0]["text"]
        assert isinstance(text, str)

    def test_niblit_searchcode_with_mocked_sc(self):
        """niblit_searchcode tool uses core.searchcode_search when available."""
        h = self._handler_with_core()
        mock_sc = MagicMock()
        mock_sc.search_code.return_value = [
            {"filename": "util.py", "language": "Python", "text": "def helper(): pass", "url": "http://sc.test/u.py"},
        ]
        h._core.searchcode_search = mock_sc
        resp = h.handle(_rpc("tools/call", {
            "name": "niblit_searchcode",
            "arguments": {"query": "helper function python", "language": "python", "max_results": 3},
        }))
        mock_sc.search_code.assert_called_once_with("helper function python", language="python", max_results=3)
        text = resp["result"]["content"][0]["text"]
        assert "util.py" in text
        assert "helper" in text


# ---------------------------------------------------------------------------
# resources
# ---------------------------------------------------------------------------

class TestResources:
    def test_resources_list_returns_resources(self):
        h = _make_handler()
        resp = h.handle(_rpc("resources/list"))
        resources = resp["result"]["resources"]
        assert isinstance(resources, list)
        uris = {r["uri"] for r in resources}
        assert "niblit://status" in uris
        assert "niblit://knowledge" in uris

    def test_read_status_resource(self):
        h = _make_handler()
        resp = h.handle(_rpc("resources/read", {"uri": "niblit://status"}))
        contents = resp["result"]["contents"]
        assert len(contents) == 1
        assert contents[0]["uri"] == "niblit://status"
        data = json.loads(contents[0]["text"])
        assert "status" in data

    def test_read_knowledge_resource(self):
        h = _make_handler()
        resp = h.handle(_rpc("resources/read", {"uri": "niblit://knowledge"}))
        contents = resp["result"]["contents"]
        data = json.loads(contents[0]["text"])
        assert "entries" in data

    def test_unknown_resource_returns_error(self):
        h = _make_handler()
        resp = h.handle(_rpc("resources/read", {"uri": "niblit://nonexistent"}))
        assert "error" in resp


# ---------------------------------------------------------------------------
# prompts
# ---------------------------------------------------------------------------

class TestPrompts:
    def test_prompts_list_returns_prompts(self):
        h = _make_handler()
        resp = h.handle(_rpc("prompts/list"))
        prompts = resp["result"]["prompts"]
        names = [p["name"] for p in prompts]
        assert "niblit_assistant" in names

    def test_get_assistant_prompt(self):
        h = _make_handler()
        resp = h.handle(_rpc("prompts/get", {"name": "niblit_assistant", "arguments": {"task": "code review"}}))
        result = resp["result"]
        assert "messages" in result
        assert len(result["messages"]) > 0
        text = result["messages"][0]["content"]["text"]
        assert "code review" in text

    def test_unknown_prompt_returns_error(self):
        h = _make_handler()
        resp = h.handle(_rpc("prompts/get", {"name": "no_such_prompt"}))
        assert "error" in resp


# ---------------------------------------------------------------------------
# Notifications (no id — no response expected)
# ---------------------------------------------------------------------------

class TestNotifications:
    def test_notification_returns_none(self):
        h = _make_handler()
        # Notification has no "id" field
        msg = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        result = h.handle(msg)
        assert result is None


# ---------------------------------------------------------------------------
# Unknown method
# ---------------------------------------------------------------------------

class TestUnknownMethod:
    def test_unknown_method_returns_error(self):
        h = _make_handler()
        resp = h.handle(_rpc("some/unknown/method"))
        assert "error" in resp
        assert resp["error"]["code"] == -32601


# ---------------------------------------------------------------------------
# SSE subscription
# ---------------------------------------------------------------------------

class TestSSE:
    def test_subscribe_returns_queue(self):
        from queue import Queue
        h = _make_handler()
        q = h.subscribe_sse("test-session")
        assert isinstance(q, Queue)

    def test_broadcast_reaches_subscriber(self):
        h = _make_handler()
        q = h.subscribe_sse("s1")
        h.broadcast({"type": "test", "data": "hello"})
        item = q.get_nowait()
        data = json.loads(item)
        assert data["type"] == "test"

    def test_unsubscribe_removes_queue(self):
        h = _make_handler()
        h.subscribe_sse("s2")
        h.unsubscribe_sse("s2")
        # After unsubscribe, broadcast should not raise
        h.broadcast({"type": "test"})


# ---------------------------------------------------------------------------
# Singleton helpers
# ---------------------------------------------------------------------------

class TestSingletonHelpers:
    def test_get_handler_returns_handler(self):
        from modules.mcp_server import get_handler, NiblitMCPHandler
        h = get_handler()
        assert isinstance(h, NiblitMCPHandler)

    def test_get_handler_is_singleton(self):
        from modules.mcp_server import get_handler
        assert get_handler() is get_handler()

    def test_attach_core(self):
        from modules.mcp_server import attach_core, get_handler
        mock_core = MagicMock()
        attach_core(mock_core)
        assert get_handler()._core is mock_core


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
