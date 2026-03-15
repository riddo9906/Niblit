"""
test_server.py — Unit tests for the Niblit Flask API (server.py).

Run with::

    pytest test_server.py -v

The NiblitCore is stubbed out so no heavy model loading occurs.
"""

import json
import unittest
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    """Create a Flask test client with NiblitCore stubbed."""
    mock_core = MagicMock()
    mock_core.db.get_personality.return_value = {"mood": "neutral", "tone": "calm"}
    mock_core.db.list_facts.return_value = [
        {"key": "greeting", "value": "hello", "category": "", "created_at": "2024-01-01 00:00:00"}
    ]
    mock_core.handle.return_value = "Hello! I'm Niblit."

    with patch("server.NiblitCore", return_value=mock_core), \
         patch("server.get_core", return_value=mock_core):
        import server as srv
        srv._core = mock_core  # pylint: disable=protected-access
        srv.app.config["TESTING"] = True
        with srv.app.test_client() as c:
            yield c, mock_core


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_200(self, client):
        c, _ = client
        resp = c.get("/health")
        assert resp.status_code == 200

    def test_health_returns_ok_status(self, client):
        c, _ = client
        resp = c.get("/health")
        data = resp.get_json()
        assert data["status"] == "ok"

    def test_health_returns_service_name(self, client):
        c, _ = client
        resp = c.get("/health")
        data = resp.get_json()
        assert data["service"] == "niblit"

    def test_health_has_security_headers(self, client):
        c, _ = client
        resp = c.get("/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"


# ---------------------------------------------------------------------------
# /ping
# ---------------------------------------------------------------------------

class TestPing:
    def test_ping_returns_200(self, client):
        c, _ = client
        resp = c.get("/ping")
        assert resp.status_code == 200

    def test_ping_returns_status_ok(self, client):
        c, _ = client
        resp = c.get("/ping")
        data = resp.get_json()
        assert data["status"] == "ok"

    def test_ping_returns_personality(self, client):
        c, _ = client
        resp = c.get("/ping")
        data = resp.get_json()
        assert "personality" in data

    def test_ping_personality_has_mood(self, client):
        c, _ = client
        resp = c.get("/ping")
        data = resp.get_json()
        assert "mood" in data["personality"]


# ---------------------------------------------------------------------------
# /chat
# ---------------------------------------------------------------------------

class TestChat:
    def test_chat_valid_message_returns_200(self, client):
        c, _ = client
        resp = c.post("/chat", json={"text": "hello"})
        assert resp.status_code == 200

    def test_chat_returns_reply(self, client):
        c, _ = client
        resp = c.post("/chat", json={"text": "hello"})
        data = resp.get_json()
        assert "reply" in data

    def test_chat_reply_is_string(self, client):
        c, _ = client
        resp = c.post("/chat", json={"text": "hello"})
        data = resp.get_json()
        assert isinstance(data["reply"], str)

    def test_chat_empty_text_returns_400(self, client):
        c, _ = client
        resp = c.post("/chat", json={"text": ""})
        assert resp.status_code == 400

    def test_chat_missing_text_returns_400(self, client):
        c, _ = client
        resp = c.post("/chat", json={})
        assert resp.status_code == 400

    def test_chat_whitespace_only_returns_400(self, client):
        c, _ = client
        resp = c.post("/chat", json={"text": "   "})
        assert resp.status_code == 400

    def test_chat_passes_text_to_core(self, client):
        c, mock_core = client
        c.post("/chat", json={"text": "what time is it"})
        mock_core.handle.assert_called_once_with("what time is it")

    def test_chat_non_json_body_returns_400(self, client):
        c, _ = client
        resp = c.post(
            "/chat",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 400

    def test_chat_core_unavailable_returns_500(self, client):
        c, _ = client
        import server as srv
        original = srv._core  # pylint: disable=protected-access
        srv._core = None
        try:
            with patch("server.get_core", return_value=None):
                resp = c.post("/chat", json={"text": "hello"})
            assert resp.status_code == 500
        finally:
            srv._core = original


# ---------------------------------------------------------------------------
# /memory
# ---------------------------------------------------------------------------

class TestMemory:
    def test_memory_returns_200(self, client):
        c, _ = client
        resp = c.get("/memory")
        assert resp.status_code == 200

    def test_memory_returns_facts_list(self, client):
        c, _ = client
        resp = c.get("/memory")
        data = resp.get_json()
        assert "facts" in data
        assert isinstance(data["facts"], list)

    def test_memory_facts_have_key_field(self, client):
        c, _ = client
        resp = c.get("/memory")
        data = resp.get_json()
        for fact in data["facts"]:
            assert "key" in fact

    def test_memory_core_unavailable_returns_empty(self, client):
        c, _ = client
        import server as srv
        original = srv._core  # pylint: disable=protected-access
        srv._core = None
        try:
            with patch("server.get_core", return_value=None):
                resp = c.get("/memory")
            data = resp.get_json()
            assert data["facts"] == []
        finally:
            srv._core = original


# ---------------------------------------------------------------------------
# Dashboard route
# ---------------------------------------------------------------------------

class TestDashboard:
    def test_dashboard_returns_200(self, client):
        c, _ = client
        resp = c.get("/")
        assert resp.status_code == 200

    def test_dashboard_returns_html(self, client):
        c, _ = client
        resp = c.get("/")
        assert b"Niblit" in resp.data


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
