#!/usr/bin/env python3
"""
modules/parameter_manager.py — Hybrid dynamic parameter management for Niblit.

:class:`ParameterManager` provides a unified key-value parameter store that
can load parameters from multiple sources:

1. **Environment variables** — always checked first (highest precedence).
2. **Local JSON file** — persisted parameters that survive restarts.
3. **Remote URL** — optional HTTP endpoint returning a JSON object.
4. **In-memory overrides** — set via :meth:`set` at runtime.

A background daemon thread (started via :meth:`start_background_sync`) can
periodically poll the remote URL and the local file for changes.  When
parameters change, a notification is pushed to
:data:`~core.notification_queue.notif_queue` — **never** printed directly to
stdout/stderr, so the interactive shell is never interrupted.

Usage::

    from modules.parameter_manager import parameter_manager

    # Read a parameter (checks env → memory → file → defaults in order)
    val = parameter_manager.get("QDRANT_URL", default="")

    # Override at runtime
    parameter_manager.set("MAX_TOPICS", "20")

    # Reload from file + env immediately (e.g. after config edit)
    parameter_manager.reload()

    # Start background sync (call once at boot)
    parameter_manager.start_background_sync(interval=60)

The module-level :data:`parameter_manager` singleton is process-wide so all
modules share the same parameters without circular imports.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Dict, Optional

# ── notification queue ─────────────────────────────────────────────────────────
try:
    from core.notification_queue import notif_queue as _notif_queue
except ImportError:
    class _NopQueue:  # type: ignore[no-redef]
        def push(self, msg: str) -> None:
            pass
    _notif_queue = _NopQueue()  # type: ignore[assignment]

# ── optional requests library ──────────────────────────────────────────────────
try:
    import requests as _requests  # type: ignore[import]
    _REQUESTS_AVAILABLE = True
except ImportError:
    _requests = None  # type: ignore[assignment]
    _REQUESTS_AVAILABLE = False

log = logging.getLogger("ParameterManager")

# Default path for the local parameter store file
try:
    from niblit_memory import _writable_path as _mem_writable_path
except Exception:
    import tempfile as _tempfile
    def _mem_writable_path(fn, env_var=None):  # type: ignore[misc]
        if env_var:
            v = os.environ.get(env_var, "").strip()
            if v:
                return v
        cwd = os.getcwd()
        return os.path.join(cwd, fn) if os.access(cwd, os.W_OK) else os.path.join(_tempfile.gettempdir(), fn)

_DEFAULT_PARAMS_FILE = _mem_writable_path("niblit_params.json", "NIBLIT_PARAMS_FILE")

# ─────────────────────────────────────────────────────────────────────────────
# ParameterManager
# ─────────────────────────────────────────────────────────────────────────────

class ParameterManager:
    """Unified parameter store with env / file / remote / runtime layers.

    Priority (highest → lowest):
    1. In-memory overrides (set via :meth:`set`)
    2. Environment variables
    3. Local JSON file (*params_file*)
    4. Default values passed to :meth:`get`

    Parameters
    ----------
    params_file:
        Path to the local JSON parameter file.  Created automatically on
        first :meth:`save`.
    remote_url:
        Optional HTTP URL that returns a JSON object of key-value pairs.
        Fetched periodically by the background sync thread.
    remote_timeout:
        HTTP request timeout in seconds for remote fetches.
    """

    def __init__(
        self,
        params_file: str = _DEFAULT_PARAMS_FILE,
        remote_url: Optional[str] = None,
        remote_timeout: float = 5.0,
    ) -> None:
        self._params_file = params_file
        self._remote_url = remote_url
        self._remote_timeout = remote_timeout

        # In-memory store: populated from file on init, updated via set()
        # NOTE: _file_store holds values loaded from file/remote.
        #       _runtime_overrides holds values set via set() at runtime.
        #       get() gives runtime overrides highest priority (after env vars).
        self._file_store: Dict[str, str] = {}
        self._runtime_overrides: Dict[str, str] = {}
        self._lock = threading.RLock()

        # Background sync state
        self._sync_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_file_mtime: float = 0.0

        # Load persisted parameters from the local file
        self._load_file(silent=True)

    # ── read API ────────────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for *key*, following the priority chain.

        Priority (highest → lowest):
        1. Runtime overrides (set via :meth:`set`)
        2. Environment variable (exact key name)
        3. File/remote loaded values
        4. *default*
        """
        with self._lock:
            # 1 — runtime overrides (never overwritten by file/remote reloads)
            if key in self._runtime_overrides:
                return self._runtime_overrides[key]
        # 2 — environment variable
        env_val = os.environ.get(key)
        if env_val is not None:
            return env_val
        # 3 — file/remote values
        with self._lock:
            if key in self._file_store:
                return self._file_store[key]
        # 4 — default
        return default

    def get_all(self) -> Dict[str, str]:
        """Return a snapshot of all parameters (merged: file store + runtime overrides)."""
        with self._lock:
            merged = dict(self._file_store)
            merged.update(self._runtime_overrides)  # runtime overrides win
            return merged

    # ── write API ───────────────────────────────────────────────────────────

    def set(self, key: str, value: str, persist: bool = False) -> None:
        """Set a runtime parameter override.

        Runtime overrides take precedence over file/remote values and are
        **never** silently overwritten by background syncs or :meth:`reload`.

        Parameters
        ----------
        key:
            Parameter name.
        value:
            String value.
        persist:
            If ``True``, also write the updated file store to the local JSON
            file (the runtime override is still kept separate).
        """
        with self._lock:
            self._runtime_overrides[key] = str(value)
        if persist:
            self._save_file()

    # ── reload (on-demand) ──────────────────────────────────────────────────

    def reload(self) -> str:
        """Re-read parameters from the local file and optionally remote URL.

        Returns a human-readable summary of what changed.  Pushes a
        notification to :data:`~core.notification_queue.notif_queue`.
        """
        old = self.get_all()
        self._load_file(silent=False)
        remote_changed = self._fetch_remote(silent=False)
        new = self.get_all()

        changed_keys = [k for k in set(list(old) + list(new)) if old.get(k) != new.get(k)]
        if changed_keys:
            summary = f"ParameterManager reloaded — {len(changed_keys)} key(s) changed: {changed_keys[:5]}"
        else:
            summary = "ParameterManager reloaded — no changes detected"

        _notif_queue.push(summary)
        log.info("[ParameterManager] %s", summary)
        return summary

    # ── background sync ──────────────────────────────────────────────────────

    def start_background_sync(
        self,
        interval: float = 60.0,
        initial_delay: float = 30.0,
    ) -> threading.Thread:
        """Start a daemon thread that periodically reloads parameters.

        Parameters
        ----------
        interval:
            Seconds between sync cycles.  Default: 60 s.
        initial_delay:
            Seconds to wait before the first sync (let the system boot first).

        Returns
        -------
        threading.Thread
            The started daemon thread.
        """
        if self._sync_thread is not None and self._sync_thread.is_alive():
            log.debug("[ParameterManager] Background sync thread already running")
            return self._sync_thread

        self._stop_event.clear()

        def _loop() -> None:
            log.debug(
                "[ParameterManager] Sync thread started (interval=%.0fs, delay=%.0fs)",
                interval, initial_delay,
            )
            # Initial delay
            if initial_delay > 0 and self._stop_event.wait(timeout=initial_delay):
                return

            while not self._stop_event.is_set():
                try:
                    old = self.get_all()
                    self._load_file(silent=True)
                    self._fetch_remote(silent=True)
                    new = self.get_all()
                    changed = [k for k in set(list(old) + list(new)) if old.get(k) != new.get(k)]
                    if changed:
                        msg = f"[ParameterManager] Auto-sync: {len(changed)} parameter(s) updated: {changed[:5]}"
                        _notif_queue.push(msg)
                        log.debug(msg)
                except Exception as exc:
                    _notif_queue.push(f"[ParameterManager] Sync error: {exc}")
                    log.debug("[ParameterManager] Sync error: %s", exc)

                # Sleep in small chunks for responsive stop_event check
                remaining = interval
                chunk = min(10.0, remaining)
                while remaining > 0 and not self._stop_event.is_set():
                    self._stop_event.wait(timeout=chunk)
                    remaining -= chunk
                    chunk = min(10.0, remaining)

        self._sync_thread = threading.Thread(
            target=_loop, daemon=True, name="ParameterManagerSync"
        )
        self._sync_thread.start()
        log.debug("[ParameterManager] Background sync thread launched")
        return self._sync_thread

    def stop_background_sync(self) -> None:
        """Signal the background sync thread to stop."""
        self._stop_event.set()

    # ── persistence helpers ──────────────────────────────────────────────────

    def _load_file(self, silent: bool = True) -> None:
        """Load parameters from the local JSON file (if it exists)."""
        try:
            mtime = os.path.getmtime(self._params_file)
        except OSError:
            return  # file doesn't exist yet — that's fine

        if mtime <= self._last_file_mtime:
            return  # file hasn't changed since last load

        try:
            with open(self._params_file, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                with self._lock:
                    # Write to _file_store only; runtime overrides are preserved
                    for k, v in data.items():
                        self._file_store[str(k)] = str(v)
                self._last_file_mtime = mtime
                if not silent:
                    log.debug("[ParameterManager] Loaded %d params from %s", len(data), self._params_file)
        except Exception as exc:
            if not silent:
                log.warning("[ParameterManager] Failed to load %s: %s", self._params_file, exc)

    def _save_file(self) -> None:
        """Persist current file-store parameters to the local JSON file."""
        try:
            with self._lock:
                snapshot = dict(self._file_store)
            with open(self._params_file, "w", encoding="utf-8") as fh:
                json.dump(snapshot, fh, indent=2)
            self._last_file_mtime = os.path.getmtime(self._params_file)
        except Exception as exc:
            log.warning("[ParameterManager] Failed to save %s: %s", self._params_file, exc)

    def _fetch_remote(self, silent: bool = True) -> bool:
        """Fetch parameters from *remote_url* (if configured).

        Remote values are written to *_file_store* and will NOT overwrite
        runtime overrides set via :meth:`set`.

        Returns ``True`` if any file-store parameters changed, ``False``
        otherwise.
        """
        if not self._remote_url:
            return False
        if not _REQUESTS_AVAILABLE:
            if not silent:
                log.debug("[ParameterManager] requests not installed — skipping remote fetch")
            return False
        try:
            resp = _requests.get(
                self._remote_url, timeout=self._remote_timeout
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                return False
            changed = False
            with self._lock:
                for k, v in data.items():
                    sk, sv = str(k), str(v)
                    # Only update _file_store; runtime overrides are never touched
                    if self._file_store.get(sk) != sv:
                        self._file_store[sk] = sv
                        changed = True
            return changed
        except Exception as exc:
            if not silent:
                log.debug("[ParameterManager] Remote fetch failed: %s", exc)
            return False

    # ── introspection ────────────────────────────────────────────────────────

    def status_summary(self) -> str:
        """Return a human-readable status string."""
        with self._lock:
            n_file = len(self._file_store)
            n_runtime = len(self._runtime_overrides)
        thread_alive = self._sync_thread is not None and self._sync_thread.is_alive()
        remote = self._remote_url or "(none)"
        return (
            f"ParameterManager: {n_file} file param(s), {n_runtime} runtime override(s) | "
            f"file={self._params_file} | "
            f"remote={remote} | "
            f"sync_thread={'alive ✅' if thread_alive else 'stopped ⏹️'}"
        )

# ─────────────────────────────────────────────────────────────────────────────
# Module-level singleton
# ─────────────────────────────────────────────────────────────────────────────

#: Global ParameterManager singleton.  Import and use this everywhere.
parameter_manager: ParameterManager = ParameterManager(
    params_file=_DEFAULT_PARAMS_FILE,
    # remote_url can be set later via parameter_manager._remote_url = "..."
    # or by passing a config at startup
)


if __name__ == "__main__":
    print('Running parameter_manager.py')
