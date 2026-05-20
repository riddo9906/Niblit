from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def app_client():
    mock_core = MagicMock()
    mock_core.memory.get_personality.return_value = {"mood": "stable"}
    mock_core.memory.list_facts.return_value = [{"key": "k", "value": "v"}]

    runtime = MagicMock()
    runtime.boot.return_value = {"ok": True}
    runtime.state.return_value = {
        "state": {
            "runtime_mode": "api",
            "active_provider": "qwen",
            "deployment": {"environment": "local"},
        },
        "providers": {"health": {}},
        "telemetry": {"threads": 3, "facts_count": 1},
        "events": {"event_counts": {"boot.sequence": 1}},
    }
    runtime.events.return_value = [{"id": 1, "type": "boot.sequence", "source": "runtime", "payload": {}}]
    runtime.stream_frame.return_value = {
        "stream_format": "niblit.runtime.stream.v1",
        "type": "runtime.frame",
        "state": {"runtime_mode": "api", "active_provider": "qwen"},
        "telemetry": {"threads": 3, "facts_count": 1},
        "events": [{"id": 1, "type": "telemetry.update", "source": "runtime", "payload": {}}],
        "provider": {"active_provider": "qwen"},
    }

    with patch("app.get_core", return_value=mock_core), patch("app.get_unified_runtime", return_value=runtime), patch(
        "app.rate_limited", return_value=False
    ):
        import app as niblit_app

        client = TestClient(niblit_app.app, raise_server_exceptions=False)
        yield client, runtime


def test_app_runtime_state_endpoint(app_client) -> None:
    client, _ = app_client
    resp = client.get("/api/runtime/state")
    assert resp.status_code == 200
    data = resp.json()
    assert "state" in data
    assert data["state"]["active_provider"] == "qwen"


def test_app_runtime_events_endpoint(app_client) -> None:
    client, _ = app_client
    resp = client.get("/api/runtime/events?since=0&limit=20")
    assert resp.status_code == 200
    data = resp.json()
    assert "events" in data
    assert isinstance(data["events"], list)


def test_app_runtime_websocket_stream(app_client) -> None:
    client, _ = app_client
    with client.websocket_connect("/ws/runtime") as ws:
        msg = ws.receive_json()
        assert msg["stream_format"] == "niblit.runtime.stream.v1"
        assert msg["type"] == "runtime.frame"

