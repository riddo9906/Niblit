from __future__ import annotations

import json
from unittest.mock import patch

from tools.lib.runtime_client import RuntimeClient


class _FakeResponse:
    def __init__(self, status: int, payload: dict):
        self.status = status
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _fake_urlopen(req, timeout=0):
    url = req.full_url
    if url.endswith("/niblit/runtime"):
        return _FakeResponse(200, {"runtime": {"mode": "cautious"}, "compatibility": {"schema_version": "2.x", "event_contract_version": "omega-7", "governance_contract_version": "1.x", "advisor_protocol_version": "2.x", "runtime_mode_contract": "2026.05"}})
    if url.endswith("/cluster/status"):
        return _FakeResponse(200, {"status": "standalone_with_federation_readiness"})
    if url.endswith("/federation/peers"):
        return _FakeResponse(200, {"peers": []})
    return _FakeResponse(404, {})


@patch("urllib.request.urlopen", side_effect=_fake_urlopen)
def test_runtime_client_diagnostics(_mock_urlopen) -> None:
    client = RuntimeClient(base_url="http://example")
    diag = client.diagnostics()
    assert diag["runtime"]["runtime"]["mode"] == "cautious"
    assert diag["cluster"]["status"] == "standalone_with_federation_readiness"
    assert diag["compatibility_check"]["compatible"] is True


if __name__ == "__main__":
    print('Running test_runtime_client_phase_omega_8.py')
