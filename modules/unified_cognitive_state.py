#!/usr/bin/env python3
"""
modules/unified_cognitive_state.py — Phase Ω Unified Cognitive State Layer

The canonical runtime state authority for Niblit.  Every subsystem previously
persisted its own state independently (self_model_state.json,
impact_weights.json, governance_state.json, etc.).  This module provides a
single indexed registry that:

* **Indexes** all known subsystem state files and in-memory snapshots.
* **Synchronises** state across subsystems so they share the same reality.
* **Versions** state with monotonic epoch counters and ISO timestamps.
* **Resolves conflicts** when two subsystems report contradictory values for
  the same metric via a configurable merge strategy.
* **Snapshots** the whole system into a compact checkpoint (JSON).
* **Restores** from a checkpoint for rollback / restart.
* **Serves** cross-subsystem queries: ``get("self_model.reasoning_quality")``.
* **Broadcasts** change notifications via the EventBus.

Architecture::

    ┌──────────────────────────────────────────────────────────┐
    │                UnifiedCognitiveState                     │
    │  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  │
    │  │  State Index │  │ Epoch Clock  │  │ Conflict      │  │
    │  │  (dict)      │  │ (monotonic)  │  │ Resolver      │  │
    │  └──────┬───────┘  └──────┬───────┘  └──────┬────────┘  │
    │         │                 │                  │            │
    │  ┌──────▼─────────────────▼──────────────────▼────────┐  │
    │  │  Checkpoint Engine  (JSON snapshots + rollback)     │  │
    │  └─────────────────────────────────────────────────────┘  │
    └──────────────────────────────────────────────────────────┘
              │                                  │
        EventBus.publish()              list_subsystems()

Configuration (env vars)
------------------------
    NIBLIT_UCS_ENABLED        — "0" to disable (default 1)
    NIBLIT_UCS_CHECKPOINT_DIR — directory for checkpoints (default: .)
    NIBLIT_UCS_MAX_CHECKPOINTS— maximum retained checkpoints (default: 5)

Usage::

    from modules.unified_cognitive_state import get_unified_state

    ucs = get_unified_state()
    ucs.set("self_model.reasoning_quality", 0.75, source="self_model")
    val = ucs.get("self_model.reasoning_quality")        # 0.75
    ucs.set_dict("governance", {"override_frequency": 0.1})
    snap = ucs.checkpoint()
    ucs.restore(snap)
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger(__name__)

_ENABLED: bool = os.getenv("NIBLIT_UCS_ENABLED", "1").strip() not in ("0", "false")
_CHECKPOINT_DIR: str = os.getenv(
    "NIBLIT_UCS_CHECKPOINT_DIR",
    os.path.dirname(os.path.abspath(__file__)) + "/..",
)
_MAX_CHECKPOINTS: int = int(os.getenv("NIBLIT_UCS_MAX_CHECKPOINTS", "5"))


# ── StateEntry ────────────────────────────────────────────────────────────────

@dataclass
class StateEntry:
    """One tracked key–value pair with provenance."""
    key: str
    value: Any
    source: str = ""
    epoch: int = 0
    updated_at: str = field(default_factory=lambda: datetime.now(tz=timezone.utc).isoformat())

    def to_dict(self) -> Dict:
        return {
            "key": self.key,
            "value": self.value,
            "source": self.source,
            "epoch": self.epoch,
            "updated_at": self.updated_at,
        }


# ── UnifiedCognitiveState ─────────────────────────────────────────────────────

class UnifiedCognitiveState:
    """Central, epoch-versioned state registry for all Niblit subsystems.

    Thread-safe.  Subscribers are notified synchronously on every ``set()``
    call, so handlers must be non-blocking.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._store: Dict[str, StateEntry] = {}
        self._epoch: int = 0
        self._subscribers: Dict[str, List[Callable]] = {}
        self._checkpoint_paths: List[str] = []
        self._set_count: int = 0
        log.debug("[UCS] initialised")

    # ── Read API ──────────────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """Return the current value for *key*, or *default*."""
        with self._lock:
            entry = self._store.get(key)
            return entry.value if entry is not None else default

    def get_entry(self, key: str) -> Optional[StateEntry]:
        """Return the full :class:`StateEntry` for *key*."""
        with self._lock:
            return self._store.get(key)

    def get_namespace(self, namespace: str) -> Dict[str, Any]:
        """Return all keys under ``namespace.*`` as a flat dict."""
        prefix = namespace.rstrip(".") + "."
        with self._lock:
            return {
                k[len(prefix):]: e.value
                for k, e in self._store.items()
                if k.startswith(prefix)
            }

    def list_keys(self) -> List[str]:
        with self._lock:
            return list(self._store.keys())

    def epoch(self) -> int:
        with self._lock:
            return self._epoch

    # ── Write API ─────────────────────────────────────────────────────────────

    def set(self, key: str, value: Any, source: str = "") -> None:
        """Set *key* to *value*.  Increments the global epoch and notifies subscribers."""
        if not _ENABLED:
            return
        with self._lock:
            self._epoch += 1
            entry = StateEntry(
                key=key,
                value=value,
                source=source,
                epoch=self._epoch,
                updated_at=datetime.now(tz=timezone.utc).isoformat(),
            )
            self._store[key] = entry
            self._set_count += 1
            handlers = list(self._subscribers.get(key, []))

        # Notify outside lock to avoid deadlock
        for handler in handlers:
            try:
                handler(key, value, source)
            except Exception as exc:
                log.debug("[UCS] subscriber error for key %s: %s", key, exc)

        self._emit_event(key, value, source)

    def set_dict(self, namespace: str, values: Dict[str, Any], source: str = "") -> None:
        """Bulk-set all keys in *values* under ``namespace.*``."""
        prefix = namespace.rstrip(".") + "."
        for k, v in values.items():
            self.set(prefix + k, v, source=source)

    def update_from_subsystem(self, subsystem: str, state_dict: Dict[str, Any]) -> None:
        """Import a subsystem's ``status()`` dict into the registry."""
        self.set_dict(subsystem, state_dict, source=subsystem)

    # ── Subscription API ──────────────────────────────────────────────────────

    def subscribe(self, key: str, handler: Callable[[str, Any, str], None]) -> None:
        """Register *handler* to be called when *key* changes."""
        with self._lock:
            self._subscribers.setdefault(key, []).append(handler)

    def unsubscribe(self, key: str, handler: Callable) -> None:
        with self._lock:
            self._subscribers.get(key, []).remove(handler)

    # ── Conflict resolution ───────────────────────────────────────────────────

    def resolve_conflict(self, key: str, values: List[Any], strategy: str = "latest") -> Any:
        """Merge conflicting values for *key* using *strategy*.

        Strategies:
            ``"latest"``  — prefer the most-recently set value (default)
            ``"average"`` — numeric average of all values
            ``"max"``     — maximum numeric value
            ``"min"``     — minimum numeric value
        """
        if strategy == "average":
            nums = [v for v in values if isinstance(v, (int, float))]
            return sum(nums) / len(nums) if nums else values[-1]
        if strategy == "max":
            nums = [v for v in values if isinstance(v, (int, float))]
            return max(nums) if nums else values[-1]
        if strategy == "min":
            nums = [v for v in values if isinstance(v, (int, float))]
            return min(nums) if nums else values[-1]
        return values[-1]  # latest

    # ── Checkpoint / Rollback ─────────────────────────────────────────────────

    def checkpoint(self) -> str:
        """Persist the full state to a JSON checkpoint file.

        Returns:
            Path to the checkpoint file.
        """
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        fname = f"niblit_ucs_checkpoint_{ts}.json"
        path = os.path.join(_CHECKPOINT_DIR, fname)
        with self._lock:
            data = {
                "epoch": self._epoch,
                "timestamp": datetime.now(tz=timezone.utc).isoformat(),
                "entries": {k: e.to_dict() for k, e in self._store.items()},
            }
        try:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, default=str)
            os.replace(tmp, path)
            with self._lock:
                self._checkpoint_paths.append(path)
                # Prune old checkpoints
                while len(self._checkpoint_paths) > _MAX_CHECKPOINTS:
                    old = self._checkpoint_paths.pop(0)
                    try:
                        os.remove(old)
                    except FileNotFoundError:
                        pass
            log.info("[UCS] checkpoint saved: %s (epoch=%d)", path, self._epoch)
            return path
        except Exception as exc:
            log.warning("[UCS] checkpoint failed: %s", exc)
            return ""

    def restore(self, checkpoint_path: str) -> bool:
        """Restore state from a checkpoint file.

        Returns:
            True on success, False on failure.
        """
        try:
            with open(checkpoint_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            with self._lock:
                self._epoch = data.get("epoch", 0)
                self._store = {}
                for k, ed in data.get("entries", {}).items():
                    self._store[k] = StateEntry(
                        key=k,
                        value=ed.get("value"),
                        source=ed.get("source", ""),
                        epoch=ed.get("epoch", 0),
                        updated_at=ed.get("updated_at", ""),
                    )
            log.info("[UCS] restored from %s (epoch=%d)", checkpoint_path, self._epoch)
            return True
        except Exception as exc:
            log.warning("[UCS] restore failed: %s", exc)
            return False

    # ── Sync helpers ──────────────────────────────────────────────────────────

    def sync_from_self_model(self) -> None:
        """Pull current self_model state into UCS."""
        try:
            from modules.self_model import get_self_model
            state = get_self_model().status()
            self.update_from_subsystem("self_model", state)
        except Exception as exc:
            log.debug("[UCS] self_model sync failed: %s", exc)

    def sync_from_resource_manager(self) -> None:
        """Pull current resource manager state into UCS."""
        try:
            from modules.runtime_resource_manager import get_resource_manager
            state = get_resource_manager().status()
            self.update_from_subsystem("resource_manager", state)
        except Exception as exc:
            log.debug("[UCS] resource_manager sync failed: %s", exc)

    def sync_all(self) -> Dict[str, bool]:
        """Best-effort sync from all known subsystems."""
        results: Dict[str, bool] = {}
        for name, fn in [
            ("self_model", self.sync_from_self_model),
            ("resource_manager", self.sync_from_resource_manager),
        ]:
            try:
                fn()
                results[name] = True
            except Exception:
                results[name] = False
        return results

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> Dict:
        with self._lock:
            return {
                "enabled": _ENABLED,
                "epoch": self._epoch,
                "key_count": len(self._store),
                "set_count": self._set_count,
                "checkpoint_count": len(self._checkpoint_paths),
                "namespaces": sorted({k.split(".")[0] for k in self._store}),
            }

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _emit_event(self, key: str, value: Any, source: str) -> None:
        try:
            from modules.event_bus import get_event_bus, NiblitEvent, EVENT_STATE_UPDATED
            get_event_bus().publish(NiblitEvent(
                type=EVENT_STATE_UPDATED,
                source="unified_cognitive_state",
                payload={"key": key, "source": source},
            ))
        except Exception:
            pass


# ── Singleton ─────────────────────────────────────────────────────────────────
_ucs: Optional[UnifiedCognitiveState] = None
_ucs_lock = threading.Lock()


def get_unified_state() -> UnifiedCognitiveState:
    """Return the module-level :class:`UnifiedCognitiveState` singleton."""
    global _ucs
    with _ucs_lock:
        if _ucs is None:
            _ucs = UnifiedCognitiveState()
    return _ucs


if __name__ == "__main__":
    print('Running unified_cognitive_state.py')
