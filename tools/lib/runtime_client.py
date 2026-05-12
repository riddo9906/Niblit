#!/usr/bin/env python3
"""Schema/governance-aware runtime client for local/cloud Niblit runtime surfaces."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from shared.governance_contract import compatibility_metadata, validate_compatibility


@dataclass
class RuntimeClientResponse:
    ok: bool
    status_code: int
    data: dict[str, Any]
    error: str = ""


class RuntimeClient:
    """HTTP client for Niblit runtime contract/federation endpoints."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000", timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def runtime_contract(self) -> RuntimeClientResponse:
        return self._get("/niblit/runtime")

    def cluster_status(self) -> RuntimeClientResponse:
        return self._get("/cluster/status")

    def federation_peers(self) -> RuntimeClientResponse:
        return self._get("/federation/peers")

    def diagnostics(self) -> dict[str, Any]:
        runtime = self.runtime_contract()
        cluster = self.cluster_status()
        peers = self.federation_peers()

        contract = runtime.data if runtime.ok else {}
        compatibility = dict((contract or {}).get("compatibility") or compatibility_metadata())
        compat_check = validate_compatibility(compatibility)

        return {
            "runtime": runtime.data if runtime.ok else {"error": runtime.error},
            "cluster": cluster.data if cluster.ok else {"error": cluster.error},
            "peers": peers.data if peers.ok else {"error": peers.error},
            "compatibility": compatibility,
            "compatibility_check": compat_check,
        }

    def _get(self, path: str) -> RuntimeClientResponse:
        url = f"{self.base_url}{path}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8") or "{}")
                if not isinstance(data, dict):
                    data = {"data": data}
                return RuntimeClientResponse(ok=True, status_code=int(getattr(resp, "status", 200)), data=data)
        except urllib.error.HTTPError as exc:
            try:
                data = json.loads(exc.read().decode("utf-8") or "{}")
                if not isinstance(data, dict):
                    data = {"data": data}
            except Exception:
                data = {}
            return RuntimeClientResponse(ok=False, status_code=int(exc.code), data=data, error=str(exc))
        except Exception as exc:
            return RuntimeClientResponse(ok=False, status_code=0, data={}, error=str(exc))


if __name__ == "__main__":
    print('Running runtime_client.py')
