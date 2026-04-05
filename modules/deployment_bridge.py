"""
modules/deployment_bridge.py — Cross-deployment checkpoint bridge for Niblit.

Persists a compact deployment snapshot (ALE cycles, trained facts, KB
digest, learned topics) to a location that survives Vercel re-deploys
(configurable via NIBLIT_BRIDGE_PATH env var, defaults to writable CWD or
/tmp).  On next startup the bridge merges the previous snapshot into the
live system so that every deployment "inherits" the work of its
predecessor.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("DeploymentBridge")

# ─── writable-path helper ────────────────────────────────────────────────────

try:
    from niblit_memory import _writable_path as _mem_writable_path  # type: ignore[import]
except Exception:
    def _mem_writable_path(fn: str, env_var: Optional[str] = None) -> str:  # type: ignore[misc]
        if env_var:
            v = os.environ.get(env_var, "").strip()
            if v:
                return v
        cwd = os.getcwd()
        return os.path.join(cwd, fn) if os.access(cwd, os.W_OK) else os.path.join(tempfile.gettempdir(), fn)

_BRIDGE_FILE = _mem_writable_path("niblit_deployment_bridge.json", "NIBLIT_BRIDGE_PATH")
_BRIDGE_LOCK = threading.Lock()

# ─────────────────────────────────────────────────────────────────────────────

class DeploymentBridge:
    """Persist and restore Niblit's learned state across deployments.

    Usage::

        bridge = DeploymentBridge()
        bridge.load(core)          # called at startup — merges previous state
        bridge.save(core)          # called at shutdown / on a timer
        bridge.start_autosave(core, interval=120)  # background autosave
    """

    SCHEMA_VERSION = 2
    _AUTOSAVE_INTERVAL_SECS = int(os.getenv("NIBLIT_BRIDGE_INTERVAL", "120"))

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = Path(path or _BRIDGE_FILE)
        self._autosave_thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._last_save: Optional[datetime] = None

    # ── snapshot I/O ─────────────────────────────────────────────────────────

    def _read_snapshot(self) -> Optional[Dict[str, Any]]:
        """Load and return the on-disk snapshot, or None if absent/corrupt."""
        try:
            if self.path.exists():
                with open(self.path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
        except Exception as exc:
            log.warning("[Bridge] Could not read snapshot %s: %s", self.path, exc)
        return None

    def _write_snapshot(self, snap: Dict[str, Any]) -> None:
        """Atomically write snapshot to disk."""
        tmp = str(self.path) + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(snap, fh, indent=2, ensure_ascii=False, default=str)
            shutil.move(tmp, str(self.path))
        except Exception as exc:
            log.warning("[Bridge] Snapshot write failed: %s", exc)

    # ── public API ────────────────────────────────────────────────────────────

    def save(self, core: Any) -> str:
        """Capture a snapshot of ``core`` and persist it."""
        snap: Dict[str, Any] = {
            "schema": self.SCHEMA_VERSION,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "ale_cycles": 0,
            "ale_state": {},
            "topics": [],
            "facts_count": 0,
            "interactions_count": 0,
            "memory_meta": {},
            "learned_knowledge": [],
        }

        # ALE state
        ale = getattr(core, "autonomous_engine", None)
        if ale is not None:
            snap["ale_cycles"] = getattr(ale, "_cycle_count", 0)
            snap["ale_state"] = getattr(ale, "state", {}) or {}
            snap["topics"] = list(getattr(ale, "research_topics", []))

        # Memory / KnowledgeDB
        db = getattr(core, "db", None)
        if db is not None:
            try:
                facts = list(getattr(db, "data", {}).get("facts", []))
                snap["facts_count"] = len(facts)
                # Ship up to the 200 most recent facts
                snap["learned_knowledge"] = facts[-200:]
                interactions = getattr(db, "data", {}).get("interactions", [])
                snap["interactions_count"] = len(interactions)
                snap["memory_meta"] = getattr(db, "data", {}).get("meta", {})
            except Exception as exc:
                log.debug("[Bridge] DB snapshot partial: %s", exc)

        with _BRIDGE_LOCK:
            self._write_snapshot(snap)
        self._last_save = datetime.now(timezone.utc)
        log.info("[Bridge] Snapshot saved → %s (%d facts, %d ALE cycles)",
                 self.path, snap["facts_count"], snap["ale_cycles"])
        return (f"✅ Deployment snapshot saved: {snap['facts_count']} facts, "
                f"{snap['ale_cycles']} ALE cycles @ {snap['saved_at']}")

    def load(self, core: Any) -> str:
        """Restore a previous deployment snapshot into ``core``."""
        snap = self._read_snapshot()
        if snap is None:
            return "ℹ️ No previous deployment snapshot found — starting fresh."

        merged_facts = merged_topics = 0

        db = getattr(core, "db", None)
        ale = getattr(core, "autonomous_engine", None)

        # Merge topics
        if ale is not None and snap.get("topics"):
            current: List[str] = list(getattr(ale, "research_topics", []))
            for t in snap["topics"]:
                if t not in current:
                    current.append(t)
                    merged_topics += 1
            try:
                ale.research_topics = current
            except Exception:
                pass

        # Merge learned knowledge / facts
        if db is not None and snap.get("learned_knowledge"):
            existing_keys = {f.get("key") for f in getattr(db, "data", {}).get("facts", [])}
            for fact in snap["learned_knowledge"]:
                key = fact.get("key")
                if key and key not in existing_keys:
                    try:
                        db.add_fact(key=key, value=fact.get("value"), tags=fact.get("tags", ["bridge"]))
                        merged_facts += 1
                        existing_keys.add(key)
                    except Exception:
                        pass

        saved_at = snap.get("saved_at", "unknown")
        msg = (f"✅ Deployment bridge loaded: +{merged_facts} facts, "
               f"+{merged_topics} topics from snapshot @ {saved_at}")
        log.info("[Bridge] %s", msg)
        return msg

    def status(self) -> str:
        snap = self._read_snapshot()
        if snap is None:
            return "⚫ DeploymentBridge: no snapshot on disk"
        lines = [
            f"🔗 **DeploymentBridge** ({self.path}):",
            f"  Saved at   : {snap.get('saved_at', '?')}",
            f"  ALE cycles : {snap.get('ale_cycles', 0)}",
            f"  Facts      : {snap.get('facts_count', 0)}",
            f"  Topics     : {len(snap.get('topics', []))}",
            f"  Schema     : v{snap.get('schema', '?')}",
        ]
        if self._last_save:
            lines.append(f"  Last save  : {self._last_save.isoformat()}")
        return "\n".join(lines)

    # ── background autosave ───────────────────────────────────────────────────

    def start_autosave(self, core: Any, interval: Optional[int] = None) -> None:
        """Start a background daemon thread that saves snapshots periodically."""
        iv = interval or self._AUTOSAVE_INTERVAL_SECS
        if self._autosave_thread and self._autosave_thread.is_alive():
            return

        def _loop() -> None:
            log.info("[Bridge] Autosave thread started (interval=%ds)", iv)
            while not self._stop.wait(iv):
                try:
                    self.save(core)
                except Exception as exc:
                    log.debug("[Bridge] Autosave error: %s", exc)
            log.info("[Bridge] Autosave thread stopped")

        self._stop.clear()
        self._autosave_thread = threading.Thread(target=_loop, daemon=True,
                                                  name="NiblitDeploymentBridgeAutosave")
        self._autosave_thread.start()

    def stop_autosave(self) -> None:
        self._stop.set()

# ── module-level singleton ────────────────────────────────────────────────────

_bridge: Optional[DeploymentBridge] = None

def get_deployment_bridge(path: Optional[str] = None) -> DeploymentBridge:
    global _bridge
    if _bridge is None:
        _bridge = DeploymentBridge(path=path)
    return _bridge

if __name__ == "__main__":
    print("Running deployment_bridge.py")
    b = get_deployment_bridge()
    print(b.status())
