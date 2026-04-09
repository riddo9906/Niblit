"""AgentProtocol — message encoding for agent-to-agent communication.

Usage example::

    proto = AgentProtocol()
    msg = proto.encode("agent-1", "agent-2", {"action": "share_knowledge"})
    sender, recipient, content = proto.decode(msg)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Tuple

log = logging.getLogger("AgentProtocol")

_REQUIRED = {"sender_id", "recipient_id", "content", "ts"}


class AgentProtocol:
    """Encodes and decodes agent-to-agent messages."""

    # ── public API ──

    def encode(
        self, sender_id: str, recipient_id: str, content: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Return encoded message dict."""
        return {
            "sender_id": sender_id,
            "recipient_id": recipient_id,
            "content": content,
            "ts": time.time(),
        }

    def decode(
        self, message: Dict[str, Any]
    ) -> Tuple[str, str, Dict[str, Any]]:
        """Return (sender_id, recipient_id, content) tuple."""
        if not self.validate(message):
            return ("", "", {})
        return (
            str(message["sender_id"]),
            str(message["recipient_id"]),
            dict(message["content"]),
        )

    def validate(self, message: Dict[str, Any]) -> bool:
        """Return True if *message* has all required fields."""
        return _REQUIRED.issubset(message.keys())


if __name__ == "__main__":
    print('Running agent_protocol.py')
