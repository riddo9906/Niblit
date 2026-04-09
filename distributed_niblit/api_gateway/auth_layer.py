"""AuthLayer — API key management for the distributed API gateway.

Usage example::

    auth = AuthLayer()
    key = auth.create_api_key("client-1")
    valid = auth.validate_api_key(key)
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import time
from typing import Dict, List, Optional

log = logging.getLogger("AuthLayer")

# HMAC secret used to derive a keyed digest of each API key before storage.
# A per-deployment secret ensures stored digests cannot be reversed if the
# key table is leaked.  Supply AUTH_KEY_HASH_SECRET via the environment in
# production; a random per-process secret is generated when the variable is
# absent so that security is maintained even without explicit configuration.
_env_secret = os.getenv("AUTH_KEY_HASH_SECRET")
if _env_secret:
    _KEY_HASH_SECRET: bytes = _env_secret.encode()
else:
    _KEY_HASH_SECRET = secrets.token_bytes(32)
    log.warning(
        "AUTH_KEY_HASH_SECRET not set — using a random per-process secret. "
        "API keys will not survive server restarts. Set AUTH_KEY_HASH_SECRET "
        "in the environment for production deployments."
    )


def _hash_api_key(raw_data: str) -> str:
    """Return a keyed HMAC digest of the supplied material for safe storage."""
    return hmac.new(_KEY_HASH_SECRET, raw_data.encode(), "sha256").hexdigest()


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

    def validate_api_key(self, key: str) -> bool:
        """Return True if the supplied key is valid and active."""
        hashed = _hash_api_key(key)
        entry = self._keys.get(hashed)
        return bool(entry and entry.get("active"))

    def revoke_api_key(self, key: str) -> None:
        """Deactivate the supplied key."""
        hashed = _hash_api_key(key)
        if hashed in self._keys:
            self._keys[hashed]["active"] = False
            log.info("AuthLayer: revoked key %s…", key[:8])

    def list_clients(self) -> List[str]:
        """Return list of client_ids with at least one active key."""
        return [
            str(v["client_id"])
            for v in self._keys.values()
            if v.get("active")
        ]


if __name__ == "__main__":
    print('Running auth_layer.py')
