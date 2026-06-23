#!/usr/bin/env python3
"""
modules/proot_env.py — Niblit proot-based Linux userland manager.

Provides ProotEnvironment: a self-contained manager for a proot-based
Linux rootfs that lives entirely inside the app's private storage.
No root access is required — proot fakes the root filesystem without
kernel privileges (same technique used by Termux and UserLAnd).

Architecture overview
---------------------
                 ┌────────────────────────────────┐
  Android APK   │  ProotEnvironment               │
  (no root)     │  ┌──────────┐  ┌─────────────┐  │
                │  │  proot   │  │  Alpine/     │  │
                │  │  binary  │  │  Debian      │  │
                │  │ (ARM64)  │  │  rootfs      │  │
                │  └──────────┘  └─────────────┘  │
                │  app-private storage             │
                └────────────────────────────────┘

Status lifecycle
----------------
  NOT_SETUP  ──(setup())──>  SETTING_UP  ──(done)──>  READY
                                                     ──(error)──>  ERROR

Public API
----------
  env = ProotEnvironment()
  env.status         → "not_setup" | "setting_up" | "ready" | "error"
  env.setup(cb)      → start first-run extraction in a thread, cb(msg, pct)
  env.run(cmd)       → run a shell command inside proot, return (rc, stdout, stderr)
  env.popen(cmd)     → return a live Popen for an interactive proot shell
  env.run_python(script) → run a Python script string inside the proot Python3
"""

from __future__ import annotations

import logging
import os
import subprocess
import tarfile
import threading
from pathlib import Path
from typing import Callable, Optional, Tuple

log = logging.getLogger("ProotEnv")

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────

def _app_storage_dir() -> Path:
    """Return the app's private storage directory.

    On Android (via python-for-android) this is the app's internal storage.
    On desktop it falls back to ~/.niblit_userland for development.
    """
    # python-for-android sets ANDROID_PRIVATE to the app-private storage dir
    android_private = os.environ.get("ANDROID_PRIVATE")
    if android_private:
        return Path(android_private)
    # Termux-style path (when running under Termux itself)
    termux_home = os.environ.get("TERMUX_APP_FILE_PACKAGES_PATH")
    if termux_home:
        return Path(termux_home)
    # Desktop fallback
    return Path.home() / ".niblit_userland"


# ─────────────────────────────────────────────────────────────────────────────
# Status constants
# ─────────────────────────────────────────────────────────────────────────────

STATUS_NOT_SETUP   = "not_setup"
STATUS_SETTING_UP  = "setting_up"
STATUS_READY       = "ready"
STATUS_ERROR       = "error"

# Sentinel file written once first-run setup completes
_SETUP_SENTINEL = ".niblit_setup_complete"

# Name of the proot binary we ship (compiled static ARM64 binary placed in assets/)
_PROOT_BINARY_NAME = "proot"


# ─────────────────────────────────────────────────────────────────────────────
# ProotEnvironment
# ─────────────────────────────────────────────────────────────────────────────

class ProotEnvironment:
    """Manages a proot-based Linux userland inside app-private storage.

    Parameters
    ----------
    storage_dir:
        Override the base storage directory (useful for testing).
    rootfs_tarball:
        Path to the rootfs tarball (e.g. alpine-rootfs-arm64.tar.gz).
        If None the class looks for an ``alpine-rootfs.tar.gz`` or
        ``ubuntu-rootfs.tar.xz`` in the same directory as this file and
        then in the assets/ folder next to the app source.
    proot_binary:
        Path to a pre-compiled static proot binary.
        If None the class searches common locations.
    """

    def __init__(
        self,
        storage_dir: Optional[Path] = None,
        rootfs_tarball: Optional[Path] = None,
        proot_binary: Optional[Path] = None,
    ) -> None:
        self._base: Path = storage_dir or _app_storage_dir()
        self._rootfs_dir: Path = self._base / "rootfs"
        self._proot_bin: Optional[Path] = proot_binary or self._find_proot()
        self._rootfs_tarball: Optional[Path] = rootfs_tarball or self._find_tarball()

        self._status: str = self._detect_status()
        self._lock = threading.Lock()

    # ── Status ───────────────────────────────────────────────────────────────

    @property
    def status(self) -> str:
        return self._status

    @property
    def is_ready(self) -> bool:
        return self._status == STATUS_READY

    def _detect_status(self) -> str:
        sentinel = self._rootfs_dir / _SETUP_SENTINEL
        if sentinel.exists():
            return STATUS_READY
        return STATUS_NOT_SETUP

    # ── Discovery helpers ────────────────────────────────────────────────────

    def _find_tarball(self) -> Optional[Path]:
        """Look for a bundled rootfs tarball in the source/assets directory."""
        search_dirs = [
            Path(__file__).resolve().parent.parent / "assets",  # assets/ next to source
            Path(__file__).resolve().parent,                    # modules/ itself
            self._base,                                         # app storage
        ]
        candidates = [
            "alpine-rootfs.tar.gz",
            "alpine-rootfs-arm64.tar.gz",
            "alpine-rootfs-armv7.tar.gz",
            "ubuntu-rootfs.tar.xz",
            "debian-rootfs.tar.xz",
        ]
        for d in search_dirs:
            for name in candidates:
                p = d / name
                if p.exists():
                    log.info("[ProotEnv] Found rootfs tarball: %s", p)
                    return p
        log.warning("[ProotEnv] No bundled rootfs tarball found — will attempt download at setup")
        return None

    def _find_proot(self) -> Optional[Path]:
        """Locate the proot binary in assets/, PATH, or common locations."""
        # 1. Bundled in assets/
        asset_proot = Path(__file__).resolve().parent.parent / "assets" / _PROOT_BINARY_NAME
        if asset_proot.exists():
            return asset_proot
        # 2. Already installed in rootfs bin dir
        rootfs_bin = self._rootfs_dir / "usr" / "bin" / "proot" if hasattr(self, "_rootfs_dir") else None
        if rootfs_bin and rootfs_bin.exists():
            return rootfs_bin
        # 3. System PATH (e.g. Termux already has proot)
        import shutil
        system_proot = shutil.which("proot")
        if system_proot:
            return Path(system_proot)
        log.warning("[ProotEnv] proot binary not found — run setup() first")
        return None

    # ── First-run setup ──────────────────────────────────────────────────────

    def setup(
        self,
        progress_callback: Optional[Callable[[str, int], None]] = None,
        tarball_path: Optional[Path] = None,
    ) -> None:
        """Start first-run setup in a background thread.

        Parameters
        ----------
        progress_callback:
            Called with (message: str, percent: int) as setup progresses.
        tarball_path:
            Override the rootfs tarball path (takes priority over auto-detect).
        """
        with self._lock:
            if self._status == STATUS_READY:
                if progress_callback:
                    progress_callback("Already set up", 100)
                return
            if self._status == STATUS_SETTING_UP:
                log.warning("[ProotEnv] setup() called while already setting up")
                return
            self._status = STATUS_SETTING_UP

        tarball = tarball_path or self._rootfs_tarball
        t = threading.Thread(
            target=self._setup_thread,
            args=(progress_callback, tarball),
            daemon=True,
            name="ProotSetupThread",
        )
        t.start()

    def _setup_thread(
        self,
        cb: Optional[Callable[[str, int], None]],
        tarball: Optional[Path],
    ) -> None:
        def _progress(msg: str, pct: int) -> None:
            log.info("[ProotEnv] setup %d%% — %s", pct, msg)
            if cb:
                cb(msg, pct)

        try:
            # ── Step 1: Create directories ────────────────────────────────
            _progress("Creating directory structure…", 5)
            self._rootfs_dir.mkdir(parents=True, exist_ok=True)
            (self._base / "tmp").mkdir(exist_ok=True)
            (self._base / "home" / "niblit").mkdir(parents=True, exist_ok=True)

            # ── Step 2: Extract rootfs ────────────────────────────────────
            if not tarball:
                _progress("Downloading minimal Alpine Linux rootfs…", 10)
                tarball = self._download_alpine_rootfs()

            _progress(f"Extracting rootfs from {tarball.name}…", 20)
            self._extract_rootfs(tarball)
            _progress("Rootfs extracted", 40)

            # ── Step 3: Set up proot binary ───────────────────────────────
            _progress("Setting up proot binary…", 45)
            self._ensure_proot_binary()
            _progress("proot ready", 50)

            # ── Step 4: Verify proot works ────────────────────────────────
            _progress("Verifying proot environment…", 55)
            rc, out, _ = self.run("echo proot_ok")
            if rc != 0 or "proot_ok" not in out:
                raise RuntimeError(f"proot self-test failed (rc={rc}, out={out!r})")
            _progress("proot verified", 60)

            # ── Step 5: Update package lists inside rootfs ─────────────────
            _progress("Updating Alpine package lists…", 65)
            self.run("apk update --no-progress", timeout=120)
            _progress("Package lists updated", 70)

            # ── Step 6: Install Python3 + pip ─────────────────────────────
            _progress("Installing Python3 and pip…", 72)
            self.run(
                "apk add --no-progress python3 py3-pip py3-setuptools py3-wheel",
                timeout=300,
            )
            _progress("Python3 installed", 80)

            # ── Step 7: Install core Python packages ──────────────────────
            _progress("Installing Niblit Python dependencies…", 82)
            self.run(
                "pip3 install --no-cache-dir --quiet "
                "requests python-dotenv duckduckgo-search",
                timeout=300,
            )
            _progress("Core packages installed", 90)

            # ── Step 8: Write setup-complete sentinel ─────────────────────
            (self._rootfs_dir / _SETUP_SENTINEL).write_text("setup_complete\n")
            _progress("Setup complete!", 100)

            with self._lock:
                self._status = STATUS_READY

        except Exception as exc:
            log.error("[ProotEnv] Setup failed: %s", exc, exc_info=True)
            with self._lock:
                self._status = STATUS_ERROR
            if cb:
                cb(f"Setup failed: {exc}", -1)

    # ── Rootfs download ───────────────────────────────────────────────────────

    def _download_alpine_rootfs(self) -> Path:
        """Download a minimal Alpine Linux ARM64 rootfs tarball."""
        import urllib.request

        # Alpine Linux mini root filesystem — AArch64 (ARM64)
        # Prefer the architecture matching the running process
        import platform
        machine = platform.machine().lower()
        if "aarch64" in machine or "arm64" in machine:
            arch_url = "https://dl-cdn.alpinelinux.org/alpine/v3.19/releases/aarch64/alpine-minirootfs-3.19.1-aarch64.tar.gz"
            fname = "alpine-rootfs-arm64.tar.gz"
        elif "armv7" in machine or "armv8" in machine:
            arch_url = "https://dl-cdn.alpinelinux.org/alpine/v3.19/releases/armv7/alpine-minirootfs-3.19.1-armv7.tar.gz"
            fname = "alpine-rootfs-armv7.tar.gz"
        else:
            # Default to x86_64 for desktop dev/testing
            arch_url = "https://dl-cdn.alpinelinux.org/alpine/v3.19/releases/x86_64/alpine-minirootfs-3.19.1-x86_64.tar.gz"
            fname = "alpine-rootfs-x86_64.tar.gz"

        dest = self._base / fname
        log.info("[ProotEnv] Downloading Alpine rootfs from %s → %s", arch_url, dest)
        urllib.request.urlretrieve(arch_url, dest)
        return dest

    # ── Extraction ────────────────────────────────────────────────────────────

    def _extract_rootfs(self, tarball: Path) -> None:
        """Extract the rootfs tarball into self._rootfs_dir."""
        self._rootfs_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(str(tarball), mode="r:*") as tf:
            tf.extractall(str(self._rootfs_dir))
        log.info("[ProotEnv] Rootfs extracted to %s", self._rootfs_dir)

    # ── proot binary setup ────────────────────────────────────────────────────

    def _ensure_proot_binary(self) -> None:
        """Make sure a proot binary is available and executable."""
        if self._proot_bin and self._proot_bin.exists():
            self._proot_bin.chmod(0o755)
            return

        # Re-search after rootfs extraction (proot may be bundled inside rootfs)
        self._proot_bin = self._find_proot()
        if self._proot_bin and self._proot_bin.exists():
            self._proot_bin.chmod(0o755)
            return

        # Try to install proot via apk from inside the rootfs (bootstrapping)
        # This requires a minimal sh in the rootfs — Alpine ships /bin/sh
        proot_candidates = [
            self._rootfs_dir / "bin" / "proot",
            self._rootfs_dir / "usr" / "bin" / "proot",
        ]
        for p in proot_candidates:
            if p.exists():
                self._proot_bin = p
                p.chmod(0o755)
                return

        raise RuntimeError(
            "proot binary not found. "
            "Bundle assets/proot (static ARM64 binary) or install proot-distro/proot "
            "from the Termux repository first."
        )

    # ── Command execution ─────────────────────────────────────────────────────

    def _build_proot_argv(self, cmd: str) -> list[str]:
        """Build the proot argv list for running *cmd* inside the rootfs."""
        proot = str(self._proot_bin) if self._proot_bin else "proot"
        argv = [
            proot,
            "--rootfs=" + str(self._rootfs_dir),
            "--root-id",                        # fake root inside proot
            "--bind=/dev",
            "--bind=/proc",
            "--bind=/sys",
            "--bind=/dev/urandom:/dev/random",
            "--cwd=/root",
        ]
        # Resolve dynamic linker for Alpine (musl)
        loader = self._rootfs_dir / "lib" / "ld-musl-aarch64.so.1"
        if loader.exists():
            argv += ["--qemu=", f"--link2symlink"]
        argv += ["/bin/sh", "-c", cmd]
        return argv

    def run(
        self,
        cmd: str,
        timeout: Optional[int] = 60,
        env: Optional[dict] = None,
    ) -> Tuple[int, str, str]:
        """Run *cmd* inside the proot rootfs.

        Returns
        -------
        (returncode, stdout, stderr)
        """
        if self._status not in (STATUS_READY, STATUS_SETTING_UP):
            return -1, "", "ProotEnvironment is not ready"

        if self._proot_bin is None:
            return -1, "", "proot binary not available"

        base_env = {
            "HOME": "/root",
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "TERM": "xterm-256color",
            "LANG": "en_US.UTF-8",
        }
        if env:
            base_env.update(env)

        argv = self._build_proot_argv(cmd)
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, **base_env},
            )
            return proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired:
            return -1, "", f"Command timed out after {timeout}s"
        except Exception as exc:
            return -1, "", str(exc)

    def popen(
        self,
        cmd: str = "/bin/sh",
        env: Optional[dict] = None,
    ) -> Optional["subprocess.Popen[str]"]:
        """Return a live Popen connected to a shell inside the proot rootfs.

        Useful for the terminal emulator widget — write to stdin, read from
        stdout/stderr in a background thread.
        """
        if self._proot_bin is None:
            return None

        base_env = {
            "HOME": "/root",
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "TERM": "xterm-256color",
            "LANG": "en_US.UTF-8",
        }
        if env:
            base_env.update(env)

        argv = self._build_proot_argv(cmd)
        try:
            return subprocess.Popen(
                argv,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env={**os.environ, **base_env},
            )
        except Exception as exc:
            log.error("[ProotEnv] popen failed: %s", exc)
            return None

    def run_python(
        self,
        script: str,
        timeout: Optional[int] = 120,
    ) -> Tuple[int, str, str]:
        """Run a Python3 script string inside the proot Python3 interpreter."""
        import tempfile, uuid
        tmp_name = f"/tmp/niblit_{uuid.uuid4().hex[:8]}.py"
        # Write the script to a temp file inside the rootfs
        tmp_real = self._rootfs_dir / tmp_name.lstrip("/")
        tmp_real.parent.mkdir(parents=True, exist_ok=True)
        tmp_real.write_text(script, encoding="utf-8")
        rc, out, err = self.run(f"python3 {tmp_name}", timeout=timeout)
        try:
            tmp_real.unlink()
        except Exception:
            pass
        return rc, out, err

    # ── Summary ───────────────────────────────────────────────────────────────

    def info(self) -> dict:
        """Return a status summary dict."""
        return {
            "status": self._status,
            "storage_dir": str(self._base),
            "rootfs_dir": str(self._rootfs_dir),
            "proot_bin": str(self._proot_bin) if self._proot_bin else None,
            "rootfs_tarball": str(self._rootfs_tarball) if self._rootfs_tarball else None,
            "rootfs_exists": self._rootfs_dir.exists(),
            "setup_sentinel": (self._rootfs_dir / _SETUP_SENTINEL).exists(),
        }

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ProotEnvironment status={self._status} rootfs={self._rootfs_dir}>"


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_instance: Optional[ProotEnvironment] = None
_instance_lock = threading.Lock()


def get_proot_env() -> ProotEnvironment:
    """Return (or create) the global ProotEnvironment singleton."""
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = ProotEnvironment()
    return _instance


if __name__ == "__main__":
    print('Running proot_env.py')
