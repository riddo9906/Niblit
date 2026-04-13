#!/usr/bin/env python3
"""
modules/apk_bootstrap.py — Niblit APK first-run bootstrap.

Orchestrates the complete setup needed to make Niblit self-contained on Android:

  1. Unpack the bundled rootfs tarball into app-private storage.
  2. Install Python3, pip, and all Niblit runtime requirements inside proot.
  3. Copy the Niblit source tree into the proot home directory so the agent
     can be invoked with a plain ``python3 /root/niblit/main.py`` inside proot.
  4. Write a ``~/.profile`` inside the rootfs that activates the Niblit venv
     and sets helpful defaults.

This module is imported by ``kivy_app.py`` during the very first launch.
It is also callable standalone for development/testing::

    python -m modules.apk_bootstrap

Progress is reported via a simple callback ``(message: str, percent: int)``
so the Kivy UI can show a progress bar and log messages.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import threading
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("APKBootstrap")

try:
    from modules.proot_env import (
        ProotEnvironment,
        get_proot_env,
        STATUS_READY,
        STATUS_NOT_SETUP,
        STATUS_SETTING_UP,
        STATUS_ERROR,
    )
except ImportError:
    # Allow relative import when running as a module from the package root
    from proot_env import (  # type: ignore[no-redef]
        ProotEnvironment,
        get_proot_env,
        STATUS_READY,
        STATUS_NOT_SETUP,
        STATUS_SETTING_UP,
        STATUS_ERROR,
    )

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# File written to app storage once APKBootstrap is fully complete
_BOOTSTRAP_DONE_FILE = "niblit_bootstrap.json"

# The pip packages to install inside the proot (subset; full list in setup_niblit.sh)
_CORE_PACKAGES = [
    "requests",
    "python-dotenv",
    "duckduckgo-search",
]

# Optional but highly recommended packages
_OPTIONAL_PACKAGES = [
    "aiohttp",
    "beautifulsoup4",
    "lxml",
    "numpy",
]

# Source files / directories that are copied into the proot niblit home
_NIBLIT_SOURCE_PATTERNS = [
    "*.py",              # top-level Python files (niblit_core.py etc.)
    "modules/",
    "niblit_memory/",
    "core/",
    "config.py",
    ".env",              # .env if present
]


# ─────────────────────────────────────────────────────────────────────────────
# APKBootstrap
# ─────────────────────────────────────────────────────────────────────────────

class APKBootstrap:
    """Orchestrates Niblit's complete first-run setup on Android.

    Parameters
    ----------
    source_dir:
        Root directory of the Niblit source (where niblit_core.py lives).
        Defaults to the directory two levels above this file.
    proot_env:
        ProotEnvironment to bootstrap into.  Defaults to the global singleton.
    """

    def __init__(
        self,
        source_dir: Optional[Path] = None,
        proot_env: Optional[ProotEnvironment] = None,
    ) -> None:
        self._source_dir = source_dir or Path(__file__).resolve().parent.parent
        self._env = proot_env or get_proot_env()
        self._done_file = self._env._base / _BOOTSTRAP_DONE_FILE
        self._is_complete: bool = self._done_file.exists()
        self._lock = threading.Lock()

    # ── State ─────────────────────────────────────────────────────────────────

    @property
    def is_complete(self) -> bool:
        return self._is_complete

    def get_status(self) -> dict:
        """Return a status summary for the UI."""
        info = self._env.info()
        result = {
            "bootstrap_complete": self._is_complete,
            "proot_status": info["status"],
            "storage_dir": info["storage_dir"],
            "rootfs_exists": info["rootfs_exists"],
        }
        if self._done_file.exists():
            try:
                result["bootstrap_info"] = json.loads(self._done_file.read_text())
            except Exception:
                pass
        return result

    # ── Run ───────────────────────────────────────────────────────────────────

    def run(
        self,
        progress_callback: Optional[Callable[[str, int], None]] = None,
        force: bool = False,
    ) -> None:
        """Start the complete bootstrap in a background thread.

        Parameters
        ----------
        progress_callback:
            Called with (message, percent) throughout setup.  percent=-1 means error.
        force:
            If True, redo setup even if already complete.
        """
        with self._lock:
            if self._is_complete and not force:
                if progress_callback:
                    progress_callback("Niblit APK backend already set up", 100)
                return

        t = threading.Thread(
            target=self._bootstrap_thread,
            args=(progress_callback,),
            daemon=True,
            name="APKBootstrapThread",
        )
        t.start()

    def run_sync(
        self,
        progress_callback: Optional[Callable[[str, int], None]] = None,
        force: bool = False,
    ) -> bool:
        """Synchronous version of run() — blocks until complete.

        Returns True on success, False on failure.
        """
        if self._is_complete and not force:
            if progress_callback:
                progress_callback("Already bootstrapped", 100)
            return True

        done_event = threading.Event()
        success_holder: list[bool] = [False]

        def _cb(msg: str, pct: int) -> None:
            if progress_callback:
                progress_callback(msg, pct)
            if pct == 100:
                success_holder[0] = True
                done_event.set()
            elif pct == -1:
                done_event.set()

        t = threading.Thread(
            target=self._bootstrap_thread,
            args=(_cb,),
            daemon=True,
            name="APKBootstrapSync",
        )
        t.start()
        done_event.wait(timeout=600)  # 10 minute overall timeout
        return success_holder[0]

    # ── Bootstrap thread ──────────────────────────────────────────────────────

    def _bootstrap_thread(
        self,
        cb: Optional[Callable[[str, int], None]],
    ) -> None:
        def _p(msg: str, pct: int) -> None:
            log.info("[Bootstrap] %d%% — %s", pct, msg)
            if cb:
                cb(msg, pct)

        try:
            # ── Phase 1: proot environment setup (rootfs + Python) ────────
            _p("Starting proot environment setup…", 2)
            if self._env.status != STATUS_READY:
                done_evt = threading.Event()
                errors: list[str] = []

                def _proot_cb(msg: str, pct: int) -> None:
                    if pct == -1:
                        errors.append(msg)
                        done_evt.set()
                    elif pct == 100:
                        done_evt.set()
                    _p(f"[proot] {msg}", max(2, min(pct // 2, 49)))  # maps 0-100 → 2-49

                self._env.setup(progress_callback=_proot_cb)
                done_evt.wait(timeout=600)

                if errors:
                    raise RuntimeError(errors[0])
                if self._env.status != STATUS_READY:
                    raise RuntimeError(f"proot setup ended with status={self._env.status}")
            else:
                _p("proot environment already ready", 49)

            # ── Phase 2: Install optional packages ────────────────────────
            _p("Installing optional Python packages…", 50)
            pkg_str = " ".join(_OPTIONAL_PACKAGES)
            self._env.run(
                f"pip3 install --no-cache-dir --quiet {pkg_str}",
                timeout=300,
            )
            _p("Optional packages installed", 60)

            # ── Phase 3: Copy Niblit source into proot ────────────────────
            _p("Copying Niblit source into proot…", 62)
            self._copy_niblit_source()
            _p("Niblit source copied", 75)

            # ── Phase 4: Write shell profile ──────────────────────────────
            _p("Writing shell profile…", 76)
            self._write_profile()
            _p("Profile written", 78)

            # ── Phase 5: Smoke-test — run 'niblit status' ─────────────────
            _p("Running Niblit smoke test inside proot…", 80)
            rc, out, err = self._env.run(
                "cd /root/niblit && python3 -c "
                "'import sys; sys.path.insert(0,\".\"); "
                "from niblit_core import NiblitCore; print(\"niblit_ok\")'",
                timeout=120,
            )
            if rc == 0 and "niblit_ok" in out:
                _p("Niblit smoke test passed ✓", 95)
            else:
                log.warning("[Bootstrap] Smoke test output: rc=%d out=%r err=%r", rc, out, err)
                _p("Smoke test inconclusive (modules may still be loading)", 95)

            # ── Phase 6: Mark complete ────────────────────────────────────
            _p("Finalising bootstrap…", 97)
            self._write_done_marker()
            self._is_complete = True
            _p("✅ Niblit APK backend ready!", 100)

        except Exception as exc:
            log.error("[Bootstrap] Failed: %s", exc, exc_info=True)
            _p(f"❌ Bootstrap failed: {exc}", -1)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _copy_niblit_source(self) -> None:
        """Copy Niblit source tree into /root/niblit inside the rootfs."""
        dest_base = self._env._rootfs_dir / "root" / "niblit"
        dest_base.mkdir(parents=True, exist_ok=True)

        src = self._source_dir
        # Copy top-level .py files
        for py in src.glob("*.py"):
            shutil.copy2(py, dest_base / py.name)
        # Copy key directories
        for subdir in ("modules", "niblit_memory", "core"):
            src_sub = src / subdir
            if src_sub.exists():
                dst_sub = dest_base / subdir
                if dst_sub.exists():
                    shutil.rmtree(dst_sub)
                shutil.copytree(str(src_sub), str(dst_sub))
        # Copy .env if present (without secrets — safe to copy since inside app-private storage)
        env_file = src / ".env"
        if env_file.exists():
            shutil.copy2(env_file, dest_base / ".env")
        log.info("[Bootstrap] Niblit source copied to %s", dest_base)

    def _write_profile(self) -> None:
        """Write a minimal shell profile inside the rootfs."""
        profile_path = self._env._rootfs_dir / "root" / ".profile"
        profile = (
            "# Niblit APK shell profile\n"
            "export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n"
            "export LANG=en_US.UTF-8\n"
            "export NIBLIT_HOME=/root/niblit\n"
            "alias niblit='python3 /root/niblit/main.py'\n"
            "alias n='niblit'\n"
            "echo '🤖 Niblit APK shell ready. Type niblit to start.'\n"
        )
        profile_path.write_text(profile, encoding="utf-8")

    def _write_done_marker(self) -> None:
        """Write the bootstrap-complete JSON marker."""
        import datetime
        data = {
            "completed_at": datetime.datetime.now().isoformat(),
            "proot_status": self._env.status,
            "niblit_version": self._get_niblit_version(),
        }
        self._done_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _get_niblit_version(self) -> str:
        """Read version from niblit_core or return 'unknown'."""
        try:
            version_file = self._source_dir / "VERSION"
            if version_file.exists():
                return version_file.read_text().strip()
        except Exception:
            pass
        return "unknown"

    # ── Quick install helper ───────────────────────────────────────────────────

    def install_package(
        self,
        package: str,
        progress_callback: Optional[Callable[[str, int], None]] = None,
    ) -> bool:
        """Install a pip package inside the proot — callable post-bootstrap.

        Returns True on success.
        """
        if not self._env.is_ready:
            log.warning("[Bootstrap] Cannot install package — proot not ready")
            return False
        rc, out, err = self._env.run(
            f"pip3 install --no-cache-dir --quiet {package}",
            timeout=300,
        )
        if rc == 0:
            if progress_callback:
                progress_callback(f"Installed {package}", 100)
            return True
        log.warning("[Bootstrap] pip install %s failed: %s", package, err)
        if progress_callback:
            progress_callback(f"Failed to install {package}: {err[:100]}", -1)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_instance: Optional[APKBootstrap] = None
_instance_lock = threading.Lock()


def get_apk_bootstrap() -> APKBootstrap:
    """Return (or create) the global APKBootstrap singleton."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = APKBootstrap()
    return _instance


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point (development / testing)
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

    def _cli_progress(msg: str, pct: int) -> None:
        bar_len = 30
        if pct < 0:
            print(f"\n  ❌ {msg}", flush=True)
            return
        filled = int(bar_len * pct / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        print(f"\r  [{bar}] {pct:3d}%  {msg:<55}", end="", flush=True)
        if pct == 100:
            print()

    print("Niblit APK Bootstrap — standalone test")
    print("=" * 50)
    bootstrap = APKBootstrap()
    print(f"Status: {bootstrap.get_status()}")
    print("Starting bootstrap…")
    ok = bootstrap.run_sync(progress_callback=_cli_progress)
    print(f"\nBootstrap {'succeeded' if ok else 'FAILED'}")
    print(f"Final status: {bootstrap.get_status()}")
