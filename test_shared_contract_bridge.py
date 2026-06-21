import json
import urllib.request
from unittest.mock import patch

from niblit_brain import NiblitCloudBrain


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_niblit_cloud_brain_uses_shared_contract_bridge():
    brain = NiblitCloudBrain(base_url="http://example.test")
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["data"] = json.loads(req.data.decode("utf-8"))
        if req.full_url.endswith("/v1/bridge/inference"):
            return _FakeResponse(
                {
                    "message_type": "ai.inference.completed",
                    "correlation_id": "corr-123",
                    "payload": {"response_text": "Bridge response: hello", "model_id": "demo-model"},
                }
            )
        raise RuntimeError("unexpected endpoint")

    with patch.object(urllib.request, "urlopen", side_effect=fake_urlopen):
        result = brain.chat("hello")

    assert result == "Bridge response: hello"
    assert captured["url"].endswith("/v1/bridge/inference")
    assert captured["data"]["message_type"] == "ai.inference.requested"
    assert captured["data"]["payload"]["prompt"] == "hello"
