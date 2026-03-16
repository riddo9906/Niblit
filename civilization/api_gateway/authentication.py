"""Authentication — token-based auth for the civilisation API gateway.

Usage example::

    auth = Authentication()
    token = auth.create_token("agent-1")
    valid = auth.validate_token(token)
"""

from __future__ import annotations

import hashlib
import logging
import secrets
import time
from typing import Dict, List

log = logging.getLogger("CivilizationAuth")


class Authentication:
    """Issues and validates bearer tokens for agents."""

    def __init__(self) -> None:
        self._tokens: Dict[str, Dict[str, object]] = {}

    # ── public API ──

    def create_token(self, agent_id: str) -> str:
        """Generate a token for *agent_id*."""
        raw = secrets.token_hex(32)
        hashed = hashlib.sha256(raw.encode()).hexdigest()
        self._tokens[hashed] = {"agent_id": agent_id, "created_at": time.time(), "active": True}
        log.info("Authentication: token created for %s", agent_id)
        return raw

    def validate_token(self, token: str) -> bool:
        """Return True if *token* is valid and active."""
        hashed = hashlib.sha256(token.encode()).hexdigest()
        entry = self._tokens.get(hashed)
        return bool(entry and entry.get("active"))

    def revoke_token(self, token: str) -> None:
        """Deactivate *token*."""
        hashed = hashlib.sha256(token.encode()).hexdigest()
        if hashed in self._tokens:
            self._tokens[hashed]["active"] = False
            log.info("Authentication: token revoked")

    def list_active_tokens(self) -> List[str]:
        """Return agent_ids with active tokens."""
        return [str(v["agent_id"]) for v in self._tokens.values() if v.get("active")]
