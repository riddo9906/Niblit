from io import BytesIO
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient

import server


class FakeCloudClient:
    def __init__(self, *, stream_error=False):
        self.payloads = []
        self.stream_error = stream_error

    async def health(self):
        return {"status": "ok"}

    async def list_models(self):
        return {
            "object": "list",
            "data": [{"id": "qwen2.5-coder-3b", "object": "model"}],
        }

    async def chat_completion(self, payload):
        self.payloads.append(payload)
        return {"id": "chat-1", "model": payload["model"], "choices": []}

    async def open_chat_stream(self, payload):
        if self.stream_error:
            raise RuntimeError("cloud_unreachable: refused")
        self.payloads.append(payload)
        return BytesIO(
            b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
            b"data: [DONE]\n\n"
        )

    async def iter_chat_stream(self, response):
        try:
            while line := await __import__("asyncio").to_thread(response.readline):
                yield line
        finally:
            response.close()


def test_core_model_inventory_comes_from_cloud(monkeypatch):
    client = FakeCloudClient()
    monkeypatch.setitem(sys.modules, "niblit_brain", SimpleNamespace(get_niblit_cloud_brain=lambda: client))
    with TestClient(server.app) as api:
        response = api.get("/v1/inference/models")
    assert response.status_code == 200
    assert response.json()["data"][0]["id"] == "qwen2.5-coder-3b"


def test_core_forwards_model_and_messages(monkeypatch):
    client = FakeCloudClient()
    monkeypatch.setitem(sys.modules, "niblit_brain", SimpleNamespace(get_niblit_cloud_brain=lambda: client))
    with TestClient(server.app) as api:
        response = api.post(
            "/v1/inference/chat",
            json={
                "model": "llama3.2-1b",
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 32,
                "temperature": 0.1,
            },
        )
    assert response.status_code == 200
    assert client.payloads[0]["model"] == "llama3.2-1b"
    assert client.payloads[0]["max_tokens"] == 32
    assert client.payloads[0]["metadata"]["source"] == "niblit-core"


def test_core_streams_cloud_sse(monkeypatch):
    client = FakeCloudClient()
    monkeypatch.setitem(sys.modules, "niblit_brain", SimpleNamespace(get_niblit_cloud_brain=lambda: client))
    with TestClient(server.app) as api:
        response = api.post(
            "/v1/inference/chat",
            json={
                "model": "qwen2.5-coder-3b",
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            },
        )
    assert response.status_code == 200
    assert "hello" in response.text
    assert "[DONE]" in response.text


def test_core_returns_structured_error_before_stream(monkeypatch):
    client = FakeCloudClient(stream_error=True)
    monkeypatch.setitem(sys.modules, "niblit_brain", SimpleNamespace(get_niblit_cloud_brain=lambda: client))
    with TestClient(server.app) as api:
        response = api.post(
            "/v1/inference/chat",
            json={
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
            },
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "cloud_unreachable"
