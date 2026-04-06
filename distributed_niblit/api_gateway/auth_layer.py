"""AuthLayer — API key management for the distributed API gateway.

Usage example::

    auth = AuthLayer()
    key = auth.create_api_key("client-1")
    valid = auth.validate_api_key(key)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import time
from typing import Dict, List, Optional

log = logging.getLogger("AuthLayer")

# HMAC secret used to derive a keyed hash of each API key before storage.
# A per-deployment secret ensures the stored digests cannot be reversed even
# if the key table is leaked.  Falls back to a deterministic value in dev;
# set AUTH_KEY_HASH_SECRET in production environments.
_KEY_HASH_SECRET: bytes = os.getenv("AUTH_KEY_HASH_SECRET", "niblit-auth-hmac-secret").encode()


def _hash_api_key(api_key: str) -> str:
    """Return a keyed HMAC-SHA256 digest of *api_key* for safe storage."""
    return hmac.new(_KEY_HASH_SECRET, api_key.encode(), hashlib.sha256).hexdigest()


class AuthLayer:
    """Creates, validates, and revokes API keys."""

    def __init__(self) -> None:
        self._keys: Dict[str, Dict[str, object]] = {}

    # ── public API ──

    def create_api_key(self, client_id: str) -> str:
        """Generate and store a new API key for *client_id*."""
        raw = secrets.token_hex(32)
        hashed = _hash_api_key(raw)
        self._keys[hashed] = {"client_id": client_id, "created_at": time.time(), "active": True}
        log.info("AuthLayer: created key for %s", client_id)
        return raw

    def validate_api_key(self, api_key: str) -> bool:
        """Return True if *api_key* is valid and active."""
        hashed = _hash_api_key(api_key)
        entry = self._keys.get(hashed)
        return bool(entry and entry.get("active"))

    def revoke_api_key(self, api_key: str) -> None:
        """Deactivate *api_key*."""
        hashed = _hash_api_key(api_key)
        if hashed in self._keys:
            self._keys[hashed]["active"] = False
            log.info("AuthLayer: revoked key %s…", api_key[:8])

    def list_clients(self) -> List[str]:
        """Return list of client_ids with at least one active key."""
        return [
            str(v["client_id"])
            for v in self._keys.values()
            if v.get("active")
        ]
