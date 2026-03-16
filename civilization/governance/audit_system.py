"""AuditSystem — immutable audit log for civilisation agent actions.

Usage example::

    audit = AuditSystem()
    audit.record("execute_code", "agent-1", {"task": "build"})
    log = audit.get_audit_log(agent_id="agent-1")
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger("AuditSystem")


class AuditSystem:
    """Append-only audit trail for agent actions."""

    def __init__(self) -> None:
        self._log: List[Dict[str, Any]] = []

    # ── public API ──

    def record(
        self,
        action_type: str,
        agent_id: str,
        details: Dict[str, Any],
    ) -> None:
        """Append an audit entry."""
        entry: Dict[str, Any] = {
            "action_type": action_type,
            "agent_id": agent_id,
            "details": details,
            "ts": time.time(),
        }
        self._log.append(entry)
        log.debug("AuditSystem: %s by %s", action_type, agent_id)

    def get_audit_log(
        self, agent_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return audit entries, optionally filtered by *agent_id*."""
        if agent_id is None:
            return list(self._log)
        return [e for e in self._log if e["agent_id"] == agent_id]

    def export(self) -> List[Dict[str, Any]]:
        """Return full audit log."""
        return list(self._log)

    def clear(self) -> None:
        """Clear audit log (use with caution)."""
        self._log.clear()
        log.warning("AuditSystem: log cleared")
