"""
env_state.py — Cross-Environment State Portability for Niblit
=============================================================
Provides a serialisable *state envelope* that allows Niblit's session state to
travel between runtimes (Python, Node.js, Rust, browser) without loss.

Design
------
* ``NiblitStateEnvelope`` — a pure-Python dataclass that holds all portable
  state fields.  JSON-serialisable by design; no runtime-specific objects.
* ``EnvStateManager`` — loads/saves the envelope to disk or a shared endpoint,
  merges incoming state from foreign runtimes, and tracks which runtime was
  last active.
* The envelope is keyed to a ``session_id`` so multiple parallel Niblit
  instances never clobber each other.

Runtime contract
----------------
Any foreign runtime (TypeScript, Rust, …) that wants to exchange state with
Niblit **must** read/write the same JSON schema.  The canonical schema is
documented in the ``NIBLIT_STATE_SCHEMA`` dict at the bottom of this file.

Usage
-----
    from modules.env_state import get_env_state_manager

    mgr = get_env_state_manager()
    mgr.update({"last_command": "help", "facts_count": 42})
    envelope = mgr.snapshot()
    mgr.save()                      # write to disk
    payload = mgr.to_json()         # ship across the wire
    mgr.merge_from_json(payload)    # receive from another runtime
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ── State file location (writable path helper mirrors niblit_memory pattern) ─

def _writable_path(filename: str, env_var: str = "") -> Path:
    if env_var:
        candidate = os.environ.get(env_var, "")
        if candidate:
            return Path(candidate)
    for candidate in [Path.cwd(), Path(tempfile.gettempdir())]:
        if os.access(candidate, os.W_OK):
            return candidate / filename
    return Path(tempfile.gettempdir()) / filename


_STATE_FILE = _writable_path("niblit_env_state.json", "NIBLIT_STATE_FILE")


# ── Envelope schema ──────────────────────────────────────────────────────────

@dataclass
class NiblitStateEnvelope:
    """
    Portable state envelope.

    All fields are JSON-primitive so the envelope can be read by any language.
    """
    # Identity
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    niblit_version: str = "1.0"

    # Runtime provenance
    origin_runtime: str = "python"      # python | node | rust | browser | other
    origin_platform: str = ""           # e.g. "linux/aarch64", "win32/x64"
    last_runtime: str = "python"
    runtime_history: List[str] = field(default_factory=list)

    # Session counters
    total_commands: int = 0
    total_facts: int = 0
    total_interactions: int = 0

    # Knowledge snapshot (lightweight — just counts & topic list)
    known_topics: List[str] = field(default_factory=list)
    knowledge_summary: str = ""

    # Last active state
    last_command: str = ""
    last_response_snippet: str = ""  # first 200 chars
    last_active_ts: float = field(default_factory=time.time)

    # Environment capabilities discovered so far
    env_capabilities: Dict[str, Any] = field(default_factory=dict)

    # Arbitrary runtime-specific extras (namespaced by runtime key)
    extras: Dict[str, Any] = field(default_factory=dict)

    # Integrity
    checksum: str = ""

    def compute_checksum(self) -> str:
        """SHA-256 of the stable fields (excludes checksum itself)."""
        stable = {k: v for k, v in asdict(self).items() if k != "checksum"}
        raw = json.dumps(stable, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def seal(self) -> "NiblitStateEnvelope":
        """Compute and store the checksum in-place, return self."""
        self.checksum = self.compute_checksum()
        return self

    def verify(self) -> bool:
        """Return True if the stored checksum matches the recomputed one."""
        return self.checksum == self.compute_checksum()


# ── EnvStateManager ──────────────────────────────────────────────────────────

class EnvStateManager:
    """
    Manages the lifecycle of a ``NiblitStateEnvelope``.

    Thread-safe.  All mutations go through ``update()`` which also refreshes
    the ``last_active_ts`` and records runtime provenance.
    """

    def __init__(
        self,
        state_file: Optional[Path] = None,
        knowledge_db: Optional[Any] = None,
        session_id: Optional[str] = None,
    ) -> None:
        self._file = state_file or _STATE_FILE
        self._knowledge_db = knowledge_db
        self._lock = threading.Lock()
        self._envelope = self._load_or_create(session_id)
        log.info(
            "EnvStateManager ready — session=%s runtime=%s file=%s",
            self._envelope.session_id[:8],
            self._envelope.last_runtime,
            self._file,
        )

    # ── Public API ─────────────────────────────────────────────────────────

    def update(self, changes: Dict[str, Any], runtime: Optional[str] = None) -> None:
        """Apply a dict of field updates to the envelope."""
        with self._lock:
            env = self._envelope
            rt = runtime or env.last_runtime
            # Track runtime transitions
            if rt != env.last_runtime:
                env.runtime_history.append(env.last_runtime)
                env.last_runtime = rt
                log.debug("State: runtime transition %s → %s", env.last_runtime, rt)
            for key, value in changes.items():
                if hasattr(env, key):
                    setattr(env, key, value)
                else:
                    env.extras[key] = value
            env.last_active_ts = time.time()
            env.seal()

    def snapshot(self) -> NiblitStateEnvelope:
        """Return a copy of the current envelope."""
        with self._lock:
            data = asdict(self._envelope)
        return NiblitStateEnvelope(**data)

    def to_json(self, indent: Optional[int] = None) -> str:
        """Serialise the current envelope to a JSON string."""
        with self._lock:
            self._envelope.seal()
            return json.dumps(asdict(self._envelope), indent=indent, default=str)

    def merge_from_json(self, payload: str, trust: bool = False) -> bool:
        """
        Merge state received from another runtime.

        Parameters
        ----------
        payload: JSON string conforming to ``NiblitStateEnvelope`` schema.
        trust:   If False (default), only merge non-sensitive fields.
                 Set True only for trusted peer runtimes.

        Returns True on success.
        """
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning("EnvStateManager.merge_from_json: invalid JSON — %s", exc)
            return False

        incoming = NiblitStateEnvelope(**{
            k: v for k, v in data.items()
            if k in NiblitStateEnvelope.__dataclass_fields__
        })

        if not incoming.verify():
            log.warning("EnvStateManager.merge_from_json: checksum mismatch — rejected")
            return False

        # Fields safe to merge unconditionally
        safe_fields = {
            "total_commands", "total_facts", "total_interactions",
            "known_topics", "knowledge_summary", "last_command",
            "last_response_snippet", "last_active_ts",
            "env_capabilities", "extras", "runtime_history",
        }
        if trust:
            safe_fields |= {"niblit_version", "origin_runtime", "origin_platform"}

        with self._lock:
            env = self._envelope
            incoming_rt = incoming.last_runtime
            for key in safe_fields:
                incoming_val = getattr(incoming, key)
                current_val = getattr(env, key)
                # For numeric counters, take the maximum (don't regress)
                if isinstance(current_val, (int, float)) and isinstance(incoming_val, (int, float)):
                    setattr(env, key, max(current_val, incoming_val))
                elif isinstance(current_val, list) and isinstance(incoming_val, list):
                    # Merge lists without duplicates, preserve order
                    merged = list(dict.fromkeys(current_val + incoming_val))
                    setattr(env, key, merged)
                elif isinstance(current_val, dict) and isinstance(incoming_val, dict):
                    merged_dict = {**current_val, **incoming_val}
                    setattr(env, key, merged_dict)
                else:
                    # String: take the one from the most recently active runtime
                    if incoming.last_active_ts > env.last_active_ts:
                        setattr(env, key, incoming_val)

            if incoming_rt not in env.runtime_history:
                env.runtime_history.append(incoming_rt)
            env.last_active_ts = time.time()
            env.seal()
        log.debug("EnvStateManager: merged state from runtime=%s", incoming_rt)
        return True

    def save(self) -> bool:
        """Write the current envelope to the state file."""
        try:
            with self._lock:
                self._envelope.seal()
                payload = asdict(self._envelope)
            self._file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
            tmp.replace(self._file)
            return True
        except Exception as exc:
            log.warning("EnvStateManager.save failed: %s", exc)
            return False

    def load(self) -> bool:
        """Reload the envelope from the state file (if it exists)."""
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            candidate = NiblitStateEnvelope(**{
                k: v for k, v in data.items()
                if k in NiblitStateEnvelope.__dataclass_fields__
            })
            if candidate.verify():
                with self._lock:
                    self._envelope = candidate
                log.debug("EnvStateManager: loaded state from %s", self._file)
                return True
            log.warning("EnvStateManager: checksum mismatch on load — starting fresh")
        except FileNotFoundError:
            pass
        except Exception as exc:
            log.warning("EnvStateManager.load failed: %s", exc)
        return False

    def status(self) -> Dict[str, Any]:
        """Return a status summary dict."""
        env = self.snapshot()
        return {
            "session_id": env.session_id[:8] + "…",
            "current_runtime": env.last_runtime,
            "runtime_history": env.runtime_history[-5:],
            "total_commands": env.total_commands,
            "total_facts": env.total_facts,
            "known_topics": len(env.known_topics),
            "last_active": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(env.last_active_ts)
            ),
            "state_file": str(self._file),
            "env_capabilities": env.env_capabilities,
        }

    # ── Internal ────────────────────────────────────────────────────────────

    def _load_or_create(self, session_id: Optional[str]) -> NiblitStateEnvelope:
        env = NiblitStateEnvelope(
            session_id=session_id or str(uuid.uuid4()),
            origin_runtime="python",
            origin_platform=f"{platform.system().lower()}/{platform.machine()}",
            last_runtime="python",
        )
        env.seal()
        # Try to restore from disk
        try:
            data = json.loads(self._file.read_text(encoding="utf-8"))
            candidate = NiblitStateEnvelope(**{
                k: v for k, v in data.items()
                if k in NiblitStateEnvelope.__dataclass_fields__
            })
            if candidate.verify():
                # If session_id was provided, only restore if it matches
                if session_id is None or candidate.session_id == session_id:
                    return candidate
        except (FileNotFoundError, Exception):
            pass
        return env


# ── Singleton ──────────────────────────────────────────────────────────────
_manager: Optional[EnvStateManager] = None
_manager_lock = threading.Lock()


def get_env_state_manager(
    knowledge_db: Optional[Any] = None,
    session_id: Optional[str] = None,
) -> EnvStateManager:
    """Return the process-level EnvStateManager singleton."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = EnvStateManager(knowledge_db=knowledge_db, session_id=session_id)
    return _manager


# ── Schema documentation ──────────────────────────────────────────────────
NIBLIT_STATE_SCHEMA: Dict[str, Any] = {
    "$schema": "niblit-env-state/1.0",
    "description": (
        "Portable state envelope shared across all Niblit runtime nodes. "
        "Any runtime that implements this schema can exchange state with the Python core."
    ),
    "fields": {
        "session_id": "string (UUID4) — unique per session",
        "niblit_version": "string — Niblit protocol version",
        "origin_runtime": "string — 'python' | 'node' | 'rust' | 'browser' | 'other'",
        "origin_platform": "string — '<os>/<arch>'",
        "last_runtime": "string — most recent runtime that wrote this envelope",
        "runtime_history": "list[string] — ordered list of runtimes that have touched this state",
        "total_commands": "integer",
        "total_facts": "integer",
        "total_interactions": "integer",
        "known_topics": "list[string]",
        "knowledge_summary": "string",
        "last_command": "string",
        "last_response_snippet": "string (≤200 chars)",
        "last_active_ts": "float (UNIX timestamp)",
        "env_capabilities": "object — runtime-reported capabilities",
        "extras": "object — namespaced extras per runtime",
        "checksum": "string (SHA-256[:16] of all other fields)",
    },
}


if __name__ == "__main__":
    print('Running env_state.py')
