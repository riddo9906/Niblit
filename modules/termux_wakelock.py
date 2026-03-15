#!/usr/bin/env python3
"""
modules/termux_wakelock.py — Termux CPU Wake-Lock + Persistent Notification

Purpose
-------
On Android, when the screen turns off or another app moves to the foreground,
the OS enters Doze mode and can freeze or throttle background Python threads.
This means Niblit's autonomous-learning loops (ALE, ResearchLoop, HealLoop,
etc.) stop making progress until the screen is turned on again — causing the
"locks after a certain time" issue.

This module solves that by:

  1. **CPU wake-lock** (`termux-wake-lock`)
     Acquired when Niblit starts its background loops.  Prevents the CPU from
     sleeping even when the screen is off and Termux is in the background.
     Released when Niblit shuts down (`termux-wake-unlock`).

  2. **Persistent foreground notification** (`termux-notification --ongoing`)
     Creates a visible notification that acts as a soft "foreground service"
     signal.  Android is much less aggressive about killing processes that
     have an ongoing notification.  Removed on shutdown.

Requirements (Termux only)
--------------------------
  pkg install termux-api
  # …and install the matching Termux:API companion app from F-Droid

On non-Termux platforms (Linux desktop, CI, Windows) the module detects that
the commands are unavailable and silently becomes a no-op, so the rest of
Niblit is unaffected.

Usage
-----
    from modules.termux_wakelock import TermuxWakeLock

    wl = TermuxWakeLock()
    wl.acquire()   # call once at startup
    ...
    wl.release()   # call on shutdown
"""

import logging
import os
import shutil
import subprocess
import threading
import time
from typing import Optional

log = logging.getLogger("TermuxWakeLock")

# Notification ID used for the persistent Niblit notification.
# Keep it fixed so we can remove the exact same notification on shutdown.
_NOTIFICATION_ID = "niblit_bg"


def _is_termux() -> bool:
    """Return True when running inside a Termux environment."""
    return (
        os.path.isdir("/data/data/com.termux")
        or "com.termux" in os.environ.get("PREFIX", "")
        or "TERMUX_VERSION" in os.environ
        or shutil.which("termux-wake-lock") is not None
    )


def _run(cmd: list, *, timeout: int = 10) -> bool:
    """Run a shell command.  Return True on success, False on any error."""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False


class TermuxWakeLock:
    """
    Manages a Termux CPU wake-lock and an ongoing notification so that
    Niblit's background loops continue running when:

      • The phone screen turns off while Termux is open.
      • The user switches to another app while Termux runs in the background.

    The class is safe to instantiate on non-Termux systems; all public
    methods become silent no-ops when the required CLI tools are absent.

    Thread-safety: acquire()/release() are idempotent and protected by a lock.
    """

    def __init__(
        self,
        notification_title: str = "Niblit AIOS",
        notification_text: str = "Autonomous learning is running in the background.",
        enable_notification: bool = True,
    ):
        self._lock = threading.Lock()
        self._acquired = False
        self._notification_title = notification_title
        self._notification_text = notification_text
        self._enable_notification = enable_notification
        self._available: Optional[bool] = None  # lazily set

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire(self) -> bool:
        """
        Acquire the CPU wake-lock and show the persistent notification.

        Returns True if the wake-lock was successfully acquired, False if
        it was already held or the commands are unavailable.

        Safe to call multiple times — only acts on the first call.
        """
        with self._lock:
            if self._acquired:
                return False

            if not self._check_available():
                log.debug("[WakeLock] Not on Termux or termux-api not installed — skipping.")
                return False

            ok = _run(["termux-wake-lock"])
            if ok:
                self._acquired = True
                log.info("🔒 [WakeLock] CPU wake-lock acquired — loops will run while screen is off.")
            else:
                log.warning(
                    "[WakeLock] termux-wake-lock failed. "
                    "Is termux-api installed? (pkg install termux-api)"
                )

            if self._enable_notification and shutil.which("termux-notification"):
                _run([
                    "termux-notification",
                    "--id",       _NOTIFICATION_ID,
                    "--title",    self._notification_title,
                    "--content",  self._notification_text,
                    "--ongoing",
                ])
                log.debug("[WakeLock] Persistent notification posted.")

            return ok

    def release(self) -> bool:
        """
        Release the CPU wake-lock and remove the persistent notification.

        Returns True if the wake-lock was held and is now released, False
        if it was not held or the commands are unavailable.

        Safe to call multiple times — only acts when the lock is held.
        """
        with self._lock:
            if not self._acquired:
                return False

            ok = _run(["termux-wake-unlock"])
            self._acquired = False  # mark released even if the command failed

            if ok:
                log.info("🔓 [WakeLock] CPU wake-lock released.")
            else:
                log.warning("[WakeLock] termux-wake-unlock failed (lock may still be held).")

            if self._enable_notification and shutil.which("termux-notification-remove"):
                _run(["termux-notification-remove", _NOTIFICATION_ID])
                log.debug("[WakeLock] Persistent notification removed.")

            return ok

    @property
    def is_acquired(self) -> bool:
        """True if the wake-lock is currently held."""
        return self._acquired

    @property
    def available(self) -> bool:
        """True if termux-wake-lock is present on this system."""
        return self._check_available()

    def status(self) -> str:
        """Return a one-line human-readable status string."""
        if not self._check_available():
            return "⚪ Wake-lock: not available (non-Termux environment)"
        if self._acquired:
            return "🟢 Wake-lock: ACTIVE — loops run while screen is off"
        return "🔴 Wake-lock: INACTIVE — loops may pause when screen turns off"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_available(self) -> bool:
        """Cache and return whether termux-wake-lock exists on this system."""
        if self._available is None:
            self._available = _is_termux() and shutil.which("termux-wake-lock") is not None
        return self._available


# ──────────────────────────────────────────────────────────────────────────────
# Module-level singleton — imported by niblit_core
# ──────────────────────────────────────────────────────────────────────────────

_global_wakelock: Optional[TermuxWakeLock] = None


def get_wakelock() -> TermuxWakeLock:
    """Return (or lazily create) the process-wide TermuxWakeLock instance."""
    global _global_wakelock
    if _global_wakelock is None:
        _global_wakelock = TermuxWakeLock()
    return _global_wakelock


if __name__ == "__main__":
    print("Running termux_wakelock.py")
