"""NodeProtocol — message encoding/decoding for distributed Niblit nodes.

Provides a lightweight wire protocol for inter-node communication.

Usage example::

    proto = NodeProtocol()
    raw = proto.encode_message("TASK", "task-001", {"action": "run"})
    msg_type, task_id, payload = proto.decode_message(raw)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger("NodeProtocol")

_REQUIRED_FIELDS = {"msg_type", "task_id", "payload", "ts", "version"}
_PROTOCOL_VERSION = "1.0"


class NodeProtocol:
    """Encodes and decodes inter-node messages.

    Args:
        version: Protocol version string used in message headers.
    """

    def __init__(self, version: str = _PROTOCOL_VERSION) -> None:
        self._version = version

    # ── public API ──

    def encode_message(
        self, msg_type: str, task_id: str, payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Encode a message dict for transmission."""
        raw: Dict[str, Any] = {
            "msg_type": msg_type,
            "task_id": task_id,
            "payload": payload,
            "ts": time.time(),
            "version": self._version,
        }
        log.debug("NodeProtocol: encoded %s/%s", msg_type, task_id)
        return raw

    def decode_message(
        self, raw: Dict[str, Any]
    ) -> Tuple[str, str, Dict[str, Any]]:
        """Decode a raw message dict → (msg_type, task_id, payload)."""
        if not self.validate_message(raw):
            log.warning("NodeProtocol: invalid message received — %s", list(raw))
            return ("INVALID", "", {})
        return (raw["msg_type"], raw["task_id"], raw["payload"])

    def validate_message(self, raw: Dict[str, Any]) -> bool:
        """Return True when *raw* contains all required protocol fields."""
        return _REQUIRED_FIELDS.issubset(raw.keys())
