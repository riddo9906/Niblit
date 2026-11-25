"""Small, testable helpers for one-time human approval of agent tool calls."""
from __future__ import annotations

import ipaddress
import time
import uuid
from urllib.parse import urlsplit
from typing import Any


def operator_origin_allowed(request: Any) -> bool:
    """Accept only local UI or a peer inside the user's Tailscale CGNAT range."""
    def trusted_host(value):
        if not value:
            return False
        host = str(value).strip().lower()
        if host in {"localhost", "127.0.0.1", "::1", "tauri.localhost"}:
            return True
        try:
            return ipaddress.ip_address(host) in ipaddress.ip_network("100.64.0.0/10")
        except ValueError:
            return False

    origin = request.headers.get("origin", "")
    host_header = request.headers.get("host", "")
    host = urlsplit("//" + host_header).hostname
    origin_host = urlsplit(origin).hostname if origin else None
    peer = request.client.host if request.client else None
    return bool(origin and trusted_host(host) and trusted_host(origin_host) and trusted_host(peer))


def consume_pending_approval(
    approval_id: str,
    pending: dict[str, dict],
    lock: Any,
    *,
    now: float | None = None,
    ready: Any = None,
) -> tuple[dict | None, str]:
    """Atomically consume a valid approval once; never return it twice.

    The ready callback is checked under the same lock after expiry validation.
    A not-ready Core leaves a valid approval pending, matching the API contract.
    """
    current = time.time() if now is None else float(now)
    with lock:
        item = pending.get(approval_id)
        if item is None:
            return None, "unavailable"
        if item.get("expires_at", 0) <= current:
            pending.pop(approval_id, None)
            return None, "expired"
        if ready is not None and not ready():
            return dict(item), "not_ready"
        consumed = dict(item)
        pending.pop(approval_id, None)
        return consumed, "consumed"


def register_pending_approvals(
    request_id: str,
    trace: list[dict],
    pending: dict[str, dict],
    lock: Any,
    metadata: dict,
    permission_actions: dict,
    ttl_seconds: int = 600,
    max_pending: int = 128,
) -> None:
    now = time.time()
    with lock:
        for key in list(pending):
            if pending[key].get("expires_at", 0) <= now:
                pending.pop(key, None)
        for item in trace:
            if item.get("status") != "authorization_required":
                continue
            tool = item.get("tool")
            tool_metadata = metadata.get(tool, {})
            if not tool_metadata.get("requires_authorization") or not permission_actions.get(tool):
                continue
            approval_id = uuid.uuid4().hex
            pending[approval_id] = {
                "request_id": request_id,
                "tool": tool,
                "arguments": dict(item.get("arguments") or {}),
                "expires_at": now + ttl_seconds,
            }
            item["approval_id"] = approval_id
        while len(pending) > max_pending:
            oldest = min(pending, key=lambda key: pending[key]["expires_at"])
            pending.pop(oldest, None)
