"""Governed observation client for a verified SSH loopback forward.

No broker adapter methods or mutating HTTP methods are exposed.
"""
from dataclasses import dataclass
import hashlib
import http.client
import json
from pathlib import Path
import threading
import subprocess
import time
from urllib.parse import urlsplit
import uuid

from modules.funded_risk import BINDING


@dataclass(frozen=True)
class GatewayProfile:
    endpoint: str
    token_file: Path
    account: dict
    timeout: float = 3.0
    gateway_id: str | None = None
    ssh_peer: dict | None = None

    @classmethod
    def load(cls, path):
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if (not {"schema_version", "endpoint", "token_file", "account"} <= set(data)
                or set(data) - {"schema_version", "endpoint", "token_file", "account", "gateway_id", "ssh_peer"}
                or data["schema_version"] not in ("0.2","0.3")):
            raise ValueError("Unsupported remote gateway profile")
        url = urlsplit(data["endpoint"])
        if (url.scheme != "http" or url.hostname != "127.0.0.1" or not url.port
                or url.username or url.password or url.path not in ("", "/") or url.query or url.fragment):
            raise ValueError("Remote gateway requires an explicit loopback SSH forward")
        account = data["account"]
        if (set(account) != set(BINDING) or any(not isinstance(v, str) or not v for v in account.values())
                or account["login"] != "100000001" or account["server"] != "XMGlobal-MT5 12"
                or account["environment"] != "live"):
            raise ValueError("Expected bound live XM account")
        token_file = Path(data["token_file"])
        if not token_file.is_absolute():
            raise ValueError("Token file requires absolute path")
        gateway_id = data.get("gateway_id")
        if gateway_id is not None and (not isinstance(gateway_id, str) or len(gateway_id) != 64
                                      or any(c not in "0123456789abcdef" for c in gateway_id)):
            raise ValueError("Invalid pinned gateway identity")
        peer = data.get("ssh_peer")
        if data["schema_version"] == "0.3":
            import re
            if (not gateway_id or not isinstance(peer,dict)
                    or set(peer) != {"host","user","key_file","known_hosts_file"}
                    or not re.fullmatch(r"[A-Za-z0-9.-]+",peer["host"])
                    or not re.fullmatch(r"[A-Za-z0-9_-]+",peer["user"])
                    or not all(Path(peer[k]).is_absolute() for k in ("key_file","known_hosts_file"))):
                raise ValueError("Version 0.3 requires the pinned SSH peer")
        elif peer is not None:
            raise ValueError("SSH peer requires profile version 0.3")
        return cls(data["endpoint"].rstrip("/"), token_file, account, gateway_id=gateway_id,ssh_peer=peer)


class RemoteBrokerGateway:
    def __init__(self, profile, *, clock=time.monotonic):
        self.profile, self.clock = profile, clock
        self.lock = threading.Lock()
        self.cached = None
        self.last_attempt = None
        self.failures = 0
        self.last_success = None
        self.last_verified = None
        self.received_at = None

    def status(self):
        with self.lock:
            now = self.clock()
            delay = min(30, 2 ** min(self.failures, 5)) if self.failures else 2
            if self.last_attempt is not None and now - self.last_attempt < delay:
                cached_age = (self.cached or {}).get("observation", {}).get("observation_age_seconds", 30) if (self.cached or {}).get("observation") else 30
                if not (self.cached or {}).get("broker_verified") or cached_age + now - self.last_attempt < 30:
                    return self.normalized_status()
            self.last_attempt = now
            started = time.monotonic()
            request_id = str(uuid.uuid4())
            try:
                url = urlsplit(self.profile.endpoint)
                connection = http.client.HTTPConnection(url.hostname, url.port, timeout=self.profile.timeout)
                try:
                    connection.connect()
                    peer_verified = None
                    if self.profile.ssh_peer is not None:
                        from modules.ssh_forward_identity import verify_peer
                        peer_verified = verify_peer(self.profile.ssh_peer, url.port)
                    token = self.profile.token_file.read_text(encoding="ascii").strip()
                    if len(token) != 64 or any(ch not in "0123456789abcdef" for ch in token):
                        raise ValueError("Invalid observation credential")
                    connection.request("GET", "/status", headers={"Authorization": "Bearer " + token,
                                                                  "X-Request-Id": request_id})
                    response = connection.getresponse()
                    if response.status not in (200, 503):
                        raise ValueError("Gateway rejected observation")
                    body = response.read(2_000_001)
                    if len(body) > 2_000_000:
                        raise ValueError("Gateway response too large")
                    payload = json.loads(body)
                finally:
                    connection.close()
                if (payload.get("schema_version") != "0.2" or payload.get("execution_enabled") is not False
                        or payload.get("effective_config", {}).get("account") != self.profile.account
                        or any(value is not False for value in payload.get("operations", {}).values())
                        or set(payload.get("operations", {})) != {"open", "modify", "close", "cancel", "switch_account"}):
                    raise ValueError("Incompatible gateway identity or authority")
                if self.profile.gateway_id is not None and payload.get("gateway_id") != self.profile.gateway_id:
                    raise ValueError("Gateway identity mismatch")
                reported = payload.get("reported_at")
                age = payload.get("observation_age_seconds")
                if not isinstance(reported, (int, float)) or not 0 <= time.time() - reported < 30:
                    raise ValueError("Stale gateway response")
                source_at = (payload.get("account_observation") or {}).get("observed_at")
                fresh = (payload.get("broker_fresh") is True
                         and type(source_at) in (int,float) and 0 <= time.time()-source_at < 30
                         and payload.get("account_observation", {}).get("account") == self.profile.account
                         and isinstance(age, (int, float)) and 0 <= age < 30)
                self.failures = 0
                if fresh:
                    self.last_success = time.time()
                    observed = payload.get("account_observation") or {}
                    self.last_verified = {k: observed.get(k) for k in
                        ("account", "balance", "equity", "margin", "free_margin", "positions", "orders", "observed_at")}
                    self.last_verified.update(breaker=payload.get("breaker"), gateway_id=payload.get("gateway_id"),
                                              gateway_version=payload.get("gateway_version"))
                self.received_at = time.time()
                self.cached = {
                    "schema_version": "0.2", "configured": True, "gateway_reachable": True,
                    "broker_verified": fresh, "observation_enabled": fresh,
                    "execution_enabled": False, "request_id": request_id,
                    "gateway_version": payload.get("gateway_version"), "breaker": payload.get("breaker"),
                    "ssh_peer_verified": peer_verified,
                    "last_success_at": self.last_success,
                    "latency_ms": round((time.monotonic() - started) * 1000, 2),
                    "observation": payload if fresh else None,
                    "last_probe_reasons": payload.get("last_probe_reasons", []),
                    "transport_requirement": "operator_verified_ssh_forward",
                }
            except (OSError, ValueError, TypeError, AttributeError, http.client.HTTPException, subprocess.SubprocessError):
                self.failures += 1
                self.cached = {
                    "schema_version": "0.2", "configured": True, "gateway_reachable": False,
                    "broker_verified": False, "observation_enabled": False, "execution_enabled": False,
                    "observation": None, "error": "remote_observation_unavailable",
                    "last_success_at": self.last_success, "request_id": request_id,
                    "retry_after_seconds": min(30, 2 ** min(self.failures, 5)),
                }
            return self.normalized_status()


    def normalized_status(self):
        from modules.broker_observation import normalize
        result = dict(self.cached or {})
        result["broker_observation"] = normalize(result, now=time.time(),
            received_at=self.received_at, last_verified=self.last_verified)
        return result


def configured_gateway():
    import os
    profile = os.environ.get("NIBLIT_VPS_GATEWAY_PROFILE", "").strip()
    return RemoteBrokerGateway(GatewayProfile.load(profile)) if profile else None
